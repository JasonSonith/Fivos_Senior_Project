import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from pipeline.runner import (
    load_adapter, normalize_record, process_single, process_batch,
    load_adapters, resolve_adapter, _extract_domain, _extract_host_from_filename,
)
from pipeline.tests.fixtures.mock_adapters import MEDTRONIC_INPACT_ADAPTER

FIXTURE_HTML = Path(__file__).parent / "fixtures" / "medtronic_sample.html"
ADAPTER_YAML = Path(__file__).resolve().parents[2] / "site_adapters" / "medtronic" / "table_wrapper_layout.yaml"


class TestLoadAdapter:
    def test_load_adapter_from_yaml(self):
        adapter = load_adapter(str(ADAPTER_YAML))
        assert "extraction" in adapter
        assert "device_name" in adapter["extraction"]

    def test_load_adapter_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_adapter("/nonexistent/path.yaml")

    def test_load_adapter_missing_extraction_key(self, tmp_path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("manufacturer: test\n")
        with pytest.raises(ValueError, match="missing required 'extraction' key"):
            load_adapter(str(bad_yaml))


class TestNormalizeRecord:
    def test_normalize_record_text_fields(self):
        raw = {"device_name": "  IN.PACT\u00ad Admiral  "}
        adapter = {"manufacturer": "medtronic"}
        result = normalize_record(raw, adapter)
        assert result["device_name"] == "IN.PACT Admiral"

    def test_normalize_record_model_field(self):
        raw = {"model_number": "Model: cs-2000x"}
        adapter = {"manufacturer": "medtronic"}
        result = normalize_record(raw, adapter)
        assert result["model_number"] == "CS-2000X"

    def test_normalize_record_manufacturer_fallback(self):
        raw = {"manufacturer": "totally_unknown_mfr_xyz"}
        adapter = {"manufacturer": "medtronic"}
        result = normalize_record(raw, adapter)
        # Falls back to adapter config via normalize_manufacturer → GUDID legal entity
        assert result["manufacturer"] == "MEDTRONIC, INC."


class TestProcessSingle:
    def test_process_single_with_medtronic_fixture(self):
        adapter = MEDTRONIC_INPACT_ADAPTER.copy()
        adapter["manufacturer"] = "medtronic"
        adapter["product_type"] = "table_wrapper_layout"
        adapter["seed_urls"] = [
            "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-drug-coated-balloons/inpact-admiral-drug-coated-balloon.html"
        ]

        record = process_single(str(FIXTURE_HTML), adapter)
        assert record is not None
        # GUDID-aligned field names
        assert "brandName" in record
        assert "IN.PACT" in record["brandName"]
        assert "_harvest" in record
        assert "harvest_run_id" in record["_harvest"]
        assert "raw_html_sha256" in record["_harvest"]

    def test_process_single_returns_none_for_empty_html(self, tmp_path):
        empty_file = tmp_path / "empty.html"
        empty_file.write_text("")
        adapter = MEDTRONIC_INPACT_ADAPTER.copy()
        adapter["manufacturer"] = "test"
        adapter["product_type"] = "test"

        result = process_single(str(empty_file), adapter)
        assert result is None

    def test_process_single_never_raises(self):
        adapter = MEDTRONIC_INPACT_ADAPTER.copy()
        adapter["manufacturer"] = "test"
        adapter["product_type"] = "test"

        result = process_single("/nonexistent/file.html", adapter)
        assert result is None


class TestProcessBatch:
    def test_process_batch_writes_output(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        html_src = FIXTURE_HTML.read_text(encoding="utf-8")
        (input_dir / "device1.html").write_text(html_src, encoding="utf-8")

        output_dir = tmp_path / "output"

        mock_record = {
            "brandName": "IN.PACT Admiral",
            "versionModelNumber": "ABC123",
            "companyName": "MEDTRONIC, INC.",
            "_harvest": {"extraction_method": "ollama"},
        }
        with patch("pipeline.runner._process_single_ollama", return_value=[mock_record]):
            summary = process_batch(str(input_dir), str(output_dir))
        assert summary["processed"] == 1
        assert summary["succeeded"] == 1
        assert summary["failed"] == 0
        assert len(summary["files"]) == 1
        assert os.path.exists(summary["files"][0])

    def test_process_batch_empty_dir(self, tmp_path):
        input_dir = tmp_path / "empty_input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        summary = process_batch(str(input_dir), str(output_dir))
        assert summary["processed"] == 0
        assert summary["succeeded"] == 0
        assert summary["failed"] == 0


SITE_ADAPTERS_DIR = Path(__file__).resolve().parents[2] / "site_adapters"


class TestLoadAdapters:
    def test_load_adapters_finds_all_yamls(self):
        adapter_map = load_adapters(str(SITE_ADAPTERS_DIR))
        assert len(adapter_map) >= 7
        # Spot-check a few known domains
        assert "medtronic.com" in adapter_map or any("medtronic" in k for k in adapter_map)
        assert "cordis.com" in adapter_map

    def test_load_adapters_skips_invalid(self, tmp_path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("manufacturer: test\n")
        adapter_map = load_adapters(str(tmp_path))
        assert adapter_map == {}

    def test_load_adapters_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert load_adapters(str(empty)) == {}


class TestResolveAdapter:
    def test_resolve_matches_domain(self):
        adapter = {"extraction": {"device_name": "h1"}, "base_url": "https://cordis.com"}
        adapter_map = {"cordis.com": adapter}
        result = resolve_adapter("cordis.com__product__hash.html", adapter_map)
        assert result is adapter

    def test_resolve_strips_www(self):
        adapter = {"extraction": {"device_name": "h1"}, "base_url": "https://www.medtronic.com"}
        adapter_map = {"medtronic.com": adapter}
        result = resolve_adapter("www.medtronic.com__product__hash.html", adapter_map)
        assert result is adapter

    def test_resolve_returns_none_for_unknown(self):
        adapter_map = {"medtronic.com": {"extraction": {}}}
        result = resolve_adapter("unknown.com__product__hash.html", adapter_map)
        assert result is None


class TestProcessBatchOllama:
    def test_batch_ollama_failure_counts_as_failed(self, tmp_path):
        """Ollama returning no records counts as failed."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        (input_dir / "unknown.com__product__hash.html").write_text("<html><body>Test</body></html>", encoding="utf-8")

        with patch("pipeline.runner._process_single_ollama", return_value=[]):
            summary = process_batch(str(input_dir), str(output_dir))
        assert summary["processed"] == 1
        assert summary["failed"] == 1

    def test_batch_ollama_success(self, tmp_path):
        """Ollama-extracted records are written and counted."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        (input_dir / "device.html").write_text("<html><body>Test</body></html>", encoding="utf-8")

        mock_record = {
            "brandName": "Test Device",
            "versionModelNumber": "TD-001",
            "companyName": "Test Corp",
            "_harvest": {"extraction_method": "ollama"},
        }
        with patch("pipeline.runner._process_single_ollama", return_value=[mock_record]):
            summary = process_batch(str(input_dir), str(output_dir))
        assert summary["processed"] == 1
        assert summary["succeeded"] == 1
        assert summary["ollama_extracted"] == 1
        assert len(summary["files"]) == 1

    def test_batch_multi_product_page(self, tmp_path):
        """Multi-product pages produce multiple records."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        (input_dir / "device.html").write_text("<html><body>Test</body></html>", encoding="utf-8")

        mock_records = [
            {"brandName": "Device", "versionModelNumber": f"SKU-{i}", "companyName": "Corp",
             "_harvest": {"extraction_method": "ollama"}}
            for i in range(3)
        ]
        with patch("pipeline.runner._process_single_ollama", return_value=mock_records):
            summary = process_batch(str(input_dir), str(output_dir))
        assert summary["processed"] == 1
        assert summary["succeeded"] == 3
        assert summary["ollama_extracted"] == 3
