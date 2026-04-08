"""Pipeline runner — CLI-runnable orchestration for the harvesting pipeline.

Usage:
    # End-to-end: scrape → extract → DB (append) → validate
    python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt

    # End-to-end with DB overwrite
    python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite

    # Extract only (existing HTML, no DB)
    python harvester/src/pipeline/runner.py
    python harvester/src/pipeline/runner.py --input file.html

    # Extract + DB
    python harvester/src/pipeline/runner.py --db --overwrite --validate
"""

import argparse
import asyncio
import glob
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Ensure harvester/src is on sys.path so imports resolve the same way pytest does.
_SRC_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
if os.path.abspath(_SRC_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC_DIR))

# Default paths (relative to project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_DIR = _PROJECT_ROOT / "harvester" / "src" / "web-scraper" / "out_html"
DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "harvester" / "output"

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
from normalizers.booleans import normalize_mri_status

logger = logging.getLogger(__name__)

# Field-type classification for normalizer routing
TEXT_FIELDS = {"description", "brand_name", "product_type", "specs_container", "warning_text"}
MODEL_FIELDS = {"model_number", "catalog_number", "sku"}
DATE_FIELDS = {"approval_date", "clearance_date", "expiration_date"}
MEASUREMENT_FIELDS = {"length", "width", "height", "diameter", "weight", "volume", "pressure"}
PASSTHROUGH_FIELDS = {"deviceKit", "premarketSubmissions", "environmentalConditions", "_description_source", "MRISafetyStatus"}


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


def _resolve_manufacturer(raw: str, adapter: dict) -> str:
    """Normalize a manufacturer name, falling back to the adapter's manufacturer field."""
    result = normalize_manufacturer(raw)
    if result is not None:
        return result
    fallback = adapter.get("manufacturer", "")
    fallback_result = normalize_manufacturer(fallback) if fallback else None
    return fallback_result if fallback_result else raw


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
                normalized[field] = _resolve_manufacturer(value, adapter)

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

            elif field in PASSTHROUGH_FIELDS:
                normalized[field] = value

            else:
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
        with open(html_path, "r", encoding="utf-8") as f:
            raw_html = f.read()
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

        # 3.7 Ollama description extraction (only if CSS didn't get it)
        if raw_fields.get("description") is not None:
            raw_fields["_description_source"] = "css"
        else:
            try:
                from pipeline.llm_extractor import extract_description
                page_text = parsed.get_text(separator=" ", strip=True)[:4000]
                ollama_desc = extract_description(
                    page_text,
                    device_name=raw_fields.get("device_name", ""),
                    model_number=raw_fields.get("model_number", ""),
                    manufacturer=adapter.get("manufacturer", ""),
                )
                if ollama_desc:
                    raw_fields["description"] = ollama_desc
                    raw_fields["_description_source"] = "ollama"
            except Exception as exc:
                logger.warning("process_single: Ollama description extraction failed: %s", exc)

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
            normalized["manufacturer"] = _resolve_manufacturer(
                adapter.get("manufacturer", "unknown"), adapter
            ) or "unknown"

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


_PRODUCT_TABLE_KEYWORDS = [
    "catalog", "model", "ref", "sku", "part number",
    "diameter", "length", "width", "size", "mm", "french",
    "quantity", "description", "sterile",
]
_JUNK_TABLE_KEYWORDS = [
    "cookie", "consent", "privacy", "analytics",
    "tracking", "tapad", "visitor", "syncd",
]


def _score_table(table) -> int:
    text = table.get_text(" ", strip=True).lower()
    score = sum(1 for kw in _PRODUCT_TABLE_KEYWORDS if kw in text)
    score -= sum(2 for kw in _JUNK_TABLE_KEYWORDS if kw in text)
    return score


def _select_best_table(tables):
    scored = [(t, _score_table(t)) for t in tables]
    best_by_score = max(scored, key=lambda x: x[1])
    if best_by_score[1] > 0:
        return best_by_score[0]
    return max(tables, key=lambda t: len(t.find_all("tr")))


def _process_single_ollama(
    html_path: str,
    source_url: str | None = None,
    harvest_run_id: str | None = None,
) -> list[dict]:
    """Run Ollama-based extraction on one HTML file (no adapter needed).

    Returns a list of packaged GUDID record dicts (one per product/SKU found).
    Returns empty list if extraction fails. Never raises.
    """
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            raw_html = f.read()
    except Exception as exc:
        logger.error("_process_single_ollama: cannot read %s: %s", html_path, exc)
        return []

    try:
        from pipeline.llm_extractor import extract_all_fields, get_last_model

        sanitized = sanitize_html(raw_html)
        parsed = parse_html(sanitized)

        visible_text = parsed.get_text(separator=" ", strip=True)

        # Find the best product table for Pass 2
        tables = parsed.find_all("table")
        table_text = None
        if tables:
            best = _select_best_table(tables)
            table_text = best.get_text(separator="\t")

        raw_fields_list = extract_all_fields(visible_text, table_text)
        if not raw_fields_list:
            logger.warning("_process_single_ollama: Ollama returned no fields for %s", html_path)
            return []

        # Resolve source URL from filename
        if source_url is None:
            host = _extract_host_from_filename(html_path)
            source_url = f"https://{host}/"

        pseudo_adapter = {"manufacturer": "unknown", "product_type": "ollama_extracted"}
        records = []

        for raw_fields in raw_fields_list:
            normalized = normalize_record(raw_fields, pseudo_adapter)

            # Parse regulatory fields from warning_text
            warning_text = normalized.get("warning_text")
            if warning_text:
                regulatory = parse_regulatory_from_text(warning_text)
                for field, value in regulatory.items():
                    if field not in normalized:
                        normalized[field] = value

            # Normalize MRI safety status
            mri_raw = normalized.get("MRISafetyStatus")
            if mri_raw and isinstance(mri_raw, str):
                normalized["MRISafetyStatus"] = normalize_mri_status(mri_raw)

            normalized["source_url"] = source_url
            if not normalized.get("manufacturer") or normalized["manufacturer"] is None:
                normalized["manufacturer"] = "unknown"

            is_valid, issues = validate_record(normalized)
            if not is_valid:
                logger.warning("_process_single_ollama: record rejected: %s", issues)
                continue

            last_model = get_last_model() or "unknown"
            record = package_gudid_record(
                normalized_record=normalized,
                raw_html=raw_html,
                source_url=source_url,
                adapter_version=last_model,
                harvest_run_id=harvest_run_id,
                validation_issues=issues,
                extraction_method="llm",
                extraction_model=last_model,
            )
            records.append(record)

        return records

    except Exception as exc:
        logger.error("_process_single_ollama: unexpected error for %s: %s", html_path, exc)
        return []


def process_batch(
    input_dir: str,
    output_dir: str = "harvester/output",
    harvest_run_id: str | None = None,
) -> dict:
    """Process all HTML files in a directory using parallel LLM extraction.

    Returns a summary dict with keys: processed, succeeded, failed,
    ollama_extracted, output_dir, files.
    """
    from pipeline.parallel_batch import process_html_files_parallel

    html_files = sorted(
        glob.glob(os.path.join(input_dir, "*.html"))
        + glob.glob(os.path.join(input_dir, "*.htm"))
    )

    summary = {
        "processed": len(html_files),
        "succeeded": 0,
        "failed": 0,
        "ollama_extracted": 0,
        "output_dir": output_dir,
        "files": [],
    }

    if not html_files:
        return summary

    results = process_html_files_parallel(
        html_files,
        harvest_run_id=harvest_run_id or "",
    )

    for r in results:
        if r.records:
            for record in r.records:
                summary["files"].append(write_record_json(record, output_dir))
            summary["succeeded"] += len(r.records)
            summary["ollama_extracted"] += len(r.records)
        else:
            summary["failed"] += 1

    return summary


# ---------------------------------------------------------------------------
# End-to-end helpers: scrape, DB write, validation
# ---------------------------------------------------------------------------

def _parse_urls(urls_arg: str) -> list[str]:
    """Parse URLs from a file path (one per line) or comma-separated string."""
    if os.path.isfile(urls_arg):
        with open(urls_arg, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [line.strip() for line in lines
                if line.strip() and not line.strip().startswith("#")]
    return [u.strip() for u in urls_arg.split(",") if u.strip()]


def _scrape_urls_with_meta(urls: list[str], output_dir: str) -> list[dict]:
    """Scrape URLs, return per-URL metadata (preserves input order and failures).

    Each entry is a dict: {url, final_url, path, error}. For successful
    URLs, final_url and path are set and error is None. For failed URLs,
    final_url and path are None and error contains the failure reason.
    """
    from web_scraper.scraper import (
        BrowserEngine, safe_filename_from_url, is_pdf_url, dedupe_keep_order,
    )

    urls = dedupe_keep_order(urls)
    urls = [u for u in urls if not is_pdf_url(u)]
    os.makedirs(output_dir, exist_ok=True)

    logger.info("Scraping %d URL(s)...", len(urls))

    async def _run():
        async with BrowserEngine(
            max_concurrency=3,
            page_timeout_ms=30_000,
            retries=3,
            retry_delay_s=5.0,
            rate_limit_delay_s=2.0,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            headless=True,
        ) as engine:
            return await asyncio.gather(*(engine.fetch(u) for u in urls))

    results = asyncio.run(_run())
    meta: list[dict] = []
    saved_count = 0
    for url, r in zip(urls, results):
        if r.ok and r.html:
            fname = safe_filename_from_url(r.final_url or r.url)
            path = os.path.join(output_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(r.html)
            saved_count += 1
            logger.info("Scraped: %s", r.final_url or r.url)
            meta.append({
                "url": url,
                "final_url": r.final_url or r.url,
                "path": path,
                "error": None,
            })
        else:
            logger.warning("Scrape failed: %s — %s", r.url, r.error)
            meta.append({
                "url": url,
                "final_url": None,
                "path": None,
                "error": r.error,
            })
    logger.info("Scraped %d/%d pages.", saved_count, len(urls))
    return meta


def scrape_urls(urls: list[str], output_dir: str) -> list[str]:
    """Scrape URLs via Playwright and save HTML files. Returns list of saved paths.

    Backward-compatible wrapper around _scrape_urls_with_meta() for callers
    that only need successful paths.
    """
    meta = _scrape_urls_with_meta(urls, output_dir)
    return [m["path"] for m in meta if m["path"]]


def write_records_to_db(json_paths: list[str], overwrite: bool = False) -> int:
    """Load JSON files and insert into MongoDB devices collection."""
    from database.db_connection import get_db

    try:
        db = get_db()
    except Exception as e:
        logger.warning("MongoDB unavailable — skipping DB write: %s", e)
        logger.warning("Records saved as JSON only.")
        return 0

    if overwrite:
        db["devices"].drop()
        logger.info("Dropped devices collection (--overwrite)")

    count = 0
    for path in json_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
            db["devices"].insert_one(record)
            count += 1
        except Exception as e:
            logger.warning("DB insert failed for %s: %s", path, e)

    logger.info("Inserted %d/%d records into MongoDB (overwrite=%s).", count, len(json_paths), overwrite)
    return count


def run_gudid_validation(run_id: str | None = None, overwrite: bool = False) -> dict:
    """Run GUDID validation on devices in DB. Returns result dict."""
    from orchestrator import run_validation
    result = run_validation(run_id=run_id, overwrite=overwrite)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run the Fivos harvesting pipeline. Supports end-to-end: scrape → extract → DB → validate."
    )

    # Input / output
    parser.add_argument("--input", dest="input_file", help="Single HTML file to process")
    parser.add_argument("--input-dir", dest="input_dir", default=str(DEFAULT_INPUT_DIR),
                        help="Directory of HTML files to process (default: web-scraper/out_html)")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="Output directory for JSON records (default: harvester/output)")
    parser.add_argument("--adapter", help="Path to a YAML adapter config (CSS extraction override)")
    parser.add_argument("--run-id", dest="run_id", help="Harvest run ID (e.g. HR-10011)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    # End-to-end flags
    parser.add_argument("--urls", help="File with URLs (one per line) or comma-separated URLs to scrape")
    parser.add_argument("--db", action="store_true", help="Write records to MongoDB after extraction")
    parser.add_argument("--overwrite", action="store_true",
                        help="Drop DB collections before inserting (default: append)")
    parser.add_argument("--validate", action="store_true", help="Run GUDID validation after extraction")
    parser.add_argument("--no-validate", action="store_true", dest="no_validate",
                        help="Skip GUDID validation (only relevant with --urls)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Determine effective modes
    end_to_end = args.urls is not None
    do_db = args.db or end_to_end
    do_validate = (args.validate or end_to_end) and not args.no_validate

    run_id = args.run_id or f"HR-LOCAL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    output_files = []

    # Step 1: Scrape (if --urls provided)
    if args.urls:
        urls = _parse_urls(args.urls)
        if not urls:
            print("No URLs found in --urls argument.")
            sys.exit(1)
        scrape_urls(urls, args.input_dir)

    # Step 2: Extract
    if args.input_file:
        # Single-file mode
        if args.adapter:
            adapter = load_adapter(args.adapter)
            record = process_single(args.input_file, adapter, harvest_run_id=run_id)
            if record is None:
                print("Pipeline rejected the record (see logs above).")
                sys.exit(1)
            out_path = write_record_json(record, args.output_dir)
            output_files.append(out_path)
            print(f"Record written to: {out_path}")
        else:
            records = _process_single_ollama(args.input_file, harvest_run_id=run_id)
            if not records:
                print("Ollama extraction returned no records (see logs above).")
                sys.exit(1)
            for record in records:
                out_path = write_record_json(record, args.output_dir)
                output_files.append(out_path)
                print(f"Record written to: {out_path}")
    else:
        # Batch mode
        summary = process_batch(
            args.input_dir,
            output_dir=args.output_dir,
            harvest_run_id=run_id,
        )
        output_files = summary.get("files", [])
        print(f"\n{'='*40}")
        print(f"  Processed:        {summary['processed']}")
        print(f"  Succeeded:        {summary['succeeded']}")
        print(f"  Failed:           {summary['failed']}")
        print(f"  Ollama-extracted: {summary['ollama_extracted']}")
        print(f"  Output:           {summary['output_dir']}")
        print(f"{'='*40}")

    # Step 3: Write to DB
    if do_db and output_files:
        write_records_to_db(output_files, overwrite=args.overwrite)

    # Step 4: GUDID validation
    if do_validate:
        print("\nRunning GUDID validation...")
        val = run_gudid_validation(run_id=run_id, overwrite=args.overwrite)
        if val.get("success"):
            print(f"  Total:            {val['total']}")
            print(f"  Full matches:     {val['full_matches']}")
            print(f"  Partial matches:  {val['partial_matches']}")
            print(f"  Mismatches:       {val['mismatches']}")
            print(f"  Not found:        {val['not_found']}")
        else:
            print(f"  Validation error: {val.get('error')}")


if __name__ == "__main__":
    main()
