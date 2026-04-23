"""ThreadPoolExecutor parallelization tests for run_validation. No live network."""
import os
import sys
import time

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest
import requests


class FakeCollection:
    def __init__(self, initial=None):
        self.docs = list(initial) if initial else []
    def drop(self):
        self.docs.clear()
    def find(self, query=None):
        return iter(self.docs)
    def insert_one(self, doc):
        self.docs.append(doc)
    def update_one(self, *a, **kw):
        pass


class FakeDb(dict):
    def __init__(self, devices):
        self["devices"] = FakeCollection(devices)
        self["validationResults"] = FakeCollection()
        self["verified_devices"] = FakeCollection()


def _make_devices(n):
    return [{"_id": f"d{i}", "catalogNumber": f"A{i}",
             "versionModelNumber": f"M{i}", "brandName": f"B{i}"}
            for i in range(n)]


def _full_match_summary():
    return ({}, {
        "unweighted_numerator": 1, "unweighted_denominator": 1,
        "numerator": 1, "denominator": 1,
    })


class TestRunValidationParallel:

    def test_workers_run_concurrently(self, monkeypatch):
        """With 4 devices and 0.2s per fetch, 8 workers should finish in well
        under 4 * 0.2 = 0.8s. Serial would be ~0.8s + overhead."""
        from orchestrator import run_validation

        devices = _make_devices(4)
        fake_db = FakeDb(devices)
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        def slow_fetch(catalog_number=None, version_model_number=None):
            time.sleep(0.2)
            return (f"DI-{catalog_number}",
                    {"brandName": f"B{catalog_number[-1]}",
                     "versionModelNumber": version_model_number,
                     "catalogNumber": catalog_number})

        monkeypatch.setattr("orchestrator.fetch_gudid_record", slow_fetch)
        monkeypatch.setattr("orchestrator.compare_records", lambda h, g: _full_match_summary())

        t0 = time.monotonic()
        result = run_validation(overwrite=True)
        elapsed = time.monotonic() - t0

        assert result["success"] is True
        assert result["total"] == 4
        assert result["full_matches"] == 4
        # 4 * 0.2 = 0.8s serial baseline. Parallel with 8 workers should land
        # comfortably under 0.6s even on a slow CI host.
        assert elapsed < 0.6, f"elapsed={elapsed:.2f}s — workers not running concurrently"

    def test_all_results_persisted(self, monkeypatch):
        from orchestrator import run_validation

        devices = _make_devices(5)
        fake_db = FakeDb(devices)
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        monkeypatch.setattr(
            "orchestrator.fetch_gudid_record",
            lambda catalog_number=None, version_model_number=None: (
                f"DI-{catalog_number}",
                {"brandName": f"B{catalog_number[-1]}",
                 "versionModelNumber": version_model_number,
                 "catalogNumber": catalog_number},
            ),
        )
        monkeypatch.setattr("orchestrator.compare_records", lambda h, g: _full_match_summary())

        result = run_validation(overwrite=True)

        assert len(fake_db["validationResults"].docs) == 5
        assert result["full_matches"] == 5
        assert result["errors"] == 0

    def test_worker_exception_isolation(self, monkeypatch):
        """A single worker raising Timeout must not affect the other 3."""
        from orchestrator import run_validation

        devices = _make_devices(4)
        fake_db = FakeDb(devices)
        monkeypatch.setattr("database.db_connection.get_db", lambda: fake_db)

        def fetch(catalog_number=None, version_model_number=None):
            if catalog_number == "A2":
                raise requests.Timeout("nope")
            return (f"DI-{catalog_number}",
                    {"brandName": f"B{catalog_number[-1]}",
                     "versionModelNumber": version_model_number,
                     "catalogNumber": catalog_number})

        monkeypatch.setattr("orchestrator.fetch_gudid_record", fetch)
        monkeypatch.setattr("orchestrator.compare_records", lambda h, g: _full_match_summary())

        result = run_validation(overwrite=True)

        assert result["success"] is True
        assert result["total"] == 4
        assert result["errors"] == 1
        assert result["full_matches"] == 3
        statuses = sorted(d["status"] for d in fake_db["validationResults"].docs)
        assert statuses.count("fetch_error") == 1
        assert statuses.count("matched") == 3
