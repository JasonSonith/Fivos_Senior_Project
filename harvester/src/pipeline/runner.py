"""Pipeline runner — CLI-runnable orchestration for the harvesting pipeline.

Usage:
    python -m pipeline.runner --adapter path/to.yaml --input file.html
    python -m pipeline.runner --adapter path/to.yaml --input-dir html_dir/ [--output-dir out/] [--run-id HR-10011] [-v]
    python -m pipeline.runner --adapter-dir harvester/src/site_adapters/ --input-dir html_dir/ [-v]
"""

import argparse
import glob
import logging
import os
import sys
from urllib.parse import urlparse

# Ensure harvester/src is on sys.path so imports resolve the same way pytest does.
_SRC_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
if os.path.abspath(_SRC_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC_DIR))

import yaml

from security.sanitizer import sanitize_html
from pipeline.parser import parse_html
from pipeline.extractor import extract_fields
from normalizers.text import normalize_text, clean_brand_name
from normalizers.model_numbers import clean_model_number
from normalizers.unit_conversions import normalize_measurement, normalize_manufacturer
from normalizers.dates import normalize_date
from validators.record_validator import validate_record
from pipeline.emitter import package_gudid_record, write_record_json
from pipeline.dimension_parser import parse_dimensions_from_specs
from pipeline.regulatory_parser import parse_regulatory_from_text
from normalizers.booleans import normalize_boolean, normalize_mri_status

logger = logging.getLogger(__name__)

# Field-type classification for normalizer routing
TEXT_FIELDS = {"device_name", "description", "brand_name", "product_type", "specs_container", "warning_text"}
MODEL_FIELDS = {"model_number", "catalog_number", "sku"}
DATE_FIELDS = {"approval_date", "clearance_date", "expiration_date"}
MEASUREMENT_FIELDS = {"length", "width", "height", "diameter", "weight", "volume", "pressure"}
BOOLEAN_FIELDS = {"singleUse", "deviceSterile", "sterilizationPriorToUse", "rx", "otc"}
ENUM_FIELDS = {"MRISafetyStatus"}


def load_adapter(yaml_path: str) -> dict:
    """Load a YAML adapter config and validate it has an 'extraction' key.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the YAML lacks an 'extraction' key.
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        adapter = yaml.safe_load(f)

    if not isinstance(adapter, dict) or "extraction" not in adapter:
        raise ValueError(f"Adapter config at {yaml_path} is missing required 'extraction' key")

    return adapter


def _extract_domain(url: str) -> str:
    """Extract domain from a URL, strip ``www.`` prefix, lowercase."""
    netloc = urlparse(url).netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.lower()


def _extract_host_from_filename(filename: str) -> str:
    """Extract host from a scraper-generated filename.

    Filenames follow the pattern ``{host}__{path-segment}__{hash}.html``.
    Returns the host segment with ``www.`` stripped and lowercased.
    """
    basename = os.path.basename(filename)
    host = basename.split("__")[0]
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


def load_adapters(adapter_dir: str) -> dict:
    """Load all YAML adapter configs from *adapter_dir* (recursive).

    Returns a ``{domain: adapter_dict}`` mapping keyed on the domain
    extracted from each adapter's ``base_url``.  Invalid files are
    skipped with a warning.
    """
    adapter_map: dict[str, dict] = {}
    for root, _dirs, files in os.walk(adapter_dir):
        for fname in files:
            if not fname.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(root, fname)
            try:
                adapter = load_adapter(path)
                base_url = adapter.get("base_url", "")
                if not base_url:
                    logger.warning("load_adapters: no base_url in %s, skipping", path)
                    continue
                domain = _extract_domain(base_url)
                adapter_map[domain] = adapter
                logger.debug("load_adapters: %s -> %s", domain, path)
            except Exception as exc:
                logger.warning("load_adapters: skipping %s: %s", path, exc)
    return adapter_map


def resolve_adapter(filename: str, adapter_map: dict) -> dict | None:
    """Look up the correct adapter for *filename* based on its host segment."""
    host = _extract_host_from_filename(filename)
    return adapter_map.get(host)


def normalize_record(raw_fields: dict, adapter: dict) -> dict:
    """Apply the correct normalizer to each field based on its name.

    Returns a new dict with normalized values. On failure for any field,
    keeps the raw value and stores a copy in ``raw_{field}``.
    """
    normalized = {}

    for field, value in raw_fields.items():
        if value is None:
            normalized[field] = None
            continue

        try:
            if field == "manufacturer":
                result = normalize_manufacturer(value)
                if result is None:
                    # Alias not found — fall back to adapter config via normalize_manufacturer
                    fallback = adapter.get("manufacturer", "")
                    fallback_result = normalize_manufacturer(fallback) if fallback else None
                    normalized[field] = fallback_result if fallback_result else value
                else:
                    normalized[field] = result

            elif field in MODEL_FIELDS:
                normalized[field] = clean_model_number(value)

            elif field in DATE_FIELDS:
                normalized[field] = normalize_date(value)

            elif field in MEASUREMENT_FIELDS:
                normalized[field] = normalize_measurement(value)

            elif field == "device_name":
                normalized[field] = clean_brand_name(value)

            elif field in TEXT_FIELDS:
                normalized[field] = normalize_text(value)

            else:
                # Unknown field — safe default
                normalized[field] = normalize_text(value)

        except Exception as exc:
            logger.warning("normalize_record: failed on field '%s': %s", field, exc)
            normalized[field] = value
            normalized[f"raw_{field}"] = value

    return normalized


def process_single(
    html_path: str,
    adapter: dict,
    source_url: str | None = None,
    harvest_run_id: str | None = None,
) -> dict | None:
    """Run the full pipeline on one HTML file.

    Returns a packaged record dict, or None if the file cannot be processed
    or validation rejects the record. Never raises.
    """
    try:
        raw_html = open(html_path, "r", encoding="utf-8").read()
    except Exception as exc:
        logger.error("process_single: cannot read %s: %s", html_path, exc)
        return None

    try:
        # 1. Sanitize
        sanitized = sanitize_html(raw_html)

        # 2. Parse
        parsed = parse_html(sanitized)

        # 3. Extract
        raw_fields = extract_fields(parsed, adapter, "html")

        # 3.5 Parse dimensions from specs_container
        # Re-extract specs table with tab separators so cells are distinguishable
        specs_selector = adapter.get("extraction", {}).get("specs_container", "")
        specs_tabbed = None
        if specs_selector:
            element = parsed.select_one(specs_selector)
            if element:
                specs_tabbed = element.get_text(separator="\t")
        parsed_dims = parse_dimensions_from_specs(
            specs_tabbed or raw_fields.get("specs_container"),
            model_number=raw_fields.get("model_number"),
            adapter=adapter,
        )
        for field, value in parsed_dims.items():
            if field in MEASUREMENT_FIELDS and raw_fields.get(field) is None:
                raw_fields[field] = value

        # 3.6 Re-extract warning_text using select() to aggregate ALL matching elements
        warning_selector = adapter.get("extraction", {}).get("warning_text", "")
        if warning_selector:
            elements = parsed.select(warning_selector)
            if elements:
                raw_fields["warning_text"] = " ".join(el.get_text(strip=True) for el in elements)

        # 4. Normalize
        normalized = normalize_record(raw_fields, adapter)

        # 4.5 Parse regulatory fields from warning_text
        warning_text = normalized.get("warning_text")
        if warning_text:
            regulatory = parse_regulatory_from_text(warning_text)
            for field, value in regulatory.items():
                if field not in normalized:
                    normalized[field] = value

        # 4.6 Normalize MRI safety status if present
        mri_raw = normalized.get("MRISafetyStatus")
        if mri_raw and isinstance(mri_raw, str):
            normalized["MRISafetyStatus"] = normalize_mri_status(mri_raw)

        # Resolve source URL
        if source_url is None:
            seed_urls = adapter.get("seed_urls", [])
            if seed_urls:
                source_url = seed_urls[0]
            else:
                source_url = f"file://{os.path.abspath(html_path)}"

        # Inject source_url and manufacturer for validation
        normalized["source_url"] = source_url
        if "manufacturer" not in normalized or normalized.get("manufacturer") is None:
            fallback = adapter.get("manufacturer", "unknown")
            fallback_result = normalize_manufacturer(fallback) if fallback else None
            normalized["manufacturer"] = fallback_result if fallback_result else "unknown"

        # 5. Validate
        is_valid, issues = validate_record(normalized)
        if not is_valid:
            logger.warning("process_single: record rejected for %s: %s", html_path, issues)
            return None

        # 6. Package with GUDID-aligned field names
        adapter_version = f"{adapter.get('manufacturer', 'unknown')}-{adapter.get('product_type', 'unknown')}"
        record = package_gudid_record(
            normalized_record=normalized,
            raw_html=raw_html,
            source_url=source_url,
            adapter_version=adapter_version,
            harvest_run_id=harvest_run_id,
            validation_issues=issues,
        )
        return record

    except Exception as exc:
        logger.error("process_single: unexpected error for %s: %s", html_path, exc)
        return None


def process_batch(
    input_dir: str,
    adapter: dict | None = None,
    output_dir: str = "harvester/output",
    harvest_run_id: str | None = None,
    adapter_map: dict | None = None,
) -> dict:
    """Process all HTML files in a directory.

    If *adapter_map* is provided, each file is routed to the adapter whose
    domain matches the filename's host segment.  Files with no matching
    adapter are counted as ``skipped``.

    If *adapter* is provided instead, it is used for every file (original
    behavior).

    Returns a summary dict with keys: processed, succeeded, failed, skipped,
    output_dir, files.
    """
    html_files = sorted(
        glob.glob(os.path.join(input_dir, "*.html"))
        + glob.glob(os.path.join(input_dir, "*.htm"))
    )

    summary = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "output_dir": output_dir,
        "files": [],
    }

    for html_path in html_files:
        summary["processed"] += 1

        # Determine which adapter to use for this file
        if adapter_map is not None:
            file_adapter = resolve_adapter(html_path, adapter_map)
            if file_adapter is None:
                host = _extract_host_from_filename(html_path)
                logger.warning("process_batch: no adapter for domain '%s' (%s), skipping", host, os.path.basename(html_path))
                summary["skipped"] += 1
                continue
        else:
            file_adapter = adapter

        record = process_single(html_path, file_adapter, harvest_run_id=harvest_run_id)

        if record is not None:
            out_path = write_record_json(record, output_dir)
            summary["succeeded"] += 1
            summary["files"].append(out_path)
        else:
            summary["failed"] += 1

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Run the Fivos harvesting pipeline on HTML files."
    )

    # Adapter source: single file OR directory (mutually exclusive, required)
    adapter_group = parser.add_mutually_exclusive_group(required=True)
    adapter_group.add_argument("--adapter", help="Path to a single YAML adapter config")
    adapter_group.add_argument(
        "--adapter-dir", dest="adapter_dir",
        help="Directory of YAML adapter configs (auto-routes files by domain)"
    )

    # Input source: single file OR directory (mutually exclusive, required)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", dest="input_file", help="Single HTML file to process")
    input_group.add_argument("--input-dir", dest="input_dir", help="Directory of HTML files to process")

    parser.add_argument("--output-dir", default="harvester/output", help="Output directory for JSON records")
    parser.add_argument("--run-id", dest="run_id", help="Harvest run ID (e.g. HR-10011)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Load adapter(s)
    if args.adapter:
        adapter = load_adapter(args.adapter)
        adapter_map = None

    else:
        adapter = None
        adapter_map = load_adapters(args.adapter_dir)
        print(f"Loaded {len(adapter_map)} adapter(s): {', '.join(sorted(adapter_map))}")

    if args.input_file:
        # Single-file mode
        if adapter_map is not None:
            adapter = resolve_adapter(args.input_file, adapter_map)
            if adapter is None:
                host = _extract_host_from_filename(args.input_file)
                print(f"No adapter found for domain '{host}'.")
                sys.exit(1)

        record = process_single(args.input_file, adapter, harvest_run_id=args.run_id)
        if record is None:
            print("Pipeline rejected the record (see logs above).")
            sys.exit(1)
        out_path = write_record_json(record, args.output_dir)
        print(f"Record written to: {out_path}")
    else:
        # Batch mode
        summary = process_batch(
            args.input_dir,
            adapter=adapter,
            output_dir=args.output_dir,
            harvest_run_id=args.run_id,
            adapter_map=adapter_map,
        )
        print(f"\n{'='*40}")
        print(f"  Processed: {summary['processed']}")
        print(f"  Succeeded: {summary['succeeded']}")
        print(f"  Failed:    {summary['failed']}")
        print(f"  Skipped:   {summary['skipped']}")
        print(f"  Output:    {summary['output_dir']}")
        print(f"{'='*40}")


if __name__ == "__main__":
    main()
