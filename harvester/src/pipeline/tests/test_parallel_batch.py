"""Unit tests for the parallel batch executor.

All tests mock _process_single_ollama to avoid real HTTP and disk I/O.
"""
import threading
import time
from unittest.mock import patch

from pipeline.parallel_batch import (
    FileExtractionResult,
    process_html_files_parallel,
)


def test_empty_input_returns_empty():
    result = process_html_files_parallel([], harvest_run_id="hr-test")
    assert result == []


def test_all_files_succeed():
    def fake_worker(path, source_url=None, harvest_run_id=None):
        return [{"device_name": f"D-{path}"}]

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        results = process_html_files_parallel(
            ["a.html", "b.html", "c.html", "d.html", "e.html"],
            harvest_run_id="hr-test",
        )

    assert len(results) == 5
    for r in results:
        assert isinstance(r, FileExtractionResult)
        assert r.error is None
        assert len(r.records) == 1


def test_one_file_raises_others_succeed():
    """A worker exception must not kill the batch — 'never crash the run'."""
    def fake_worker(path, source_url=None, harvest_run_id=None):
        if path == "bad.html":
            raise ValueError("simulated worker crash")
        return [{"device_name": f"D-{path}"}]

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        results = process_html_files_parallel(
            ["good1.html", "bad.html", "good2.html"],
            harvest_run_id="hr-test",
        )

    assert len(results) == 3
    by_path = {r.path: r for r in results}
    assert by_path["bad.html"].records == []
    assert "simulated worker crash" in by_path["bad.html"].error
    assert by_path["good1.html"].error is None
    assert len(by_path["good1.html"].records) == 1
    assert by_path["good2.html"].error is None
    assert len(by_path["good2.html"].records) == 1


def test_progress_callback_fires_per_completion():
    def fake_worker(path, source_url=None, harvest_run_id=None):
        return [{"device_name": "X"}]

    progress_events = []
    lock = threading.Lock()

    def on_progress(completed, total):
        with lock:
            progress_events.append((completed, total))

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        process_html_files_parallel(
            ["a.html", "b.html", "c.html", "d.html"],
            harvest_run_id="hr-test",
            progress_callback=on_progress,
        )

    assert len(progress_events) == 4
    # Totals are always 4
    assert all(total == 4 for _, total in progress_events)
    # Completed counts cover 1..4
    assert sorted(completed for completed, _ in progress_events) == [1, 2, 3, 4]


def test_source_urls_passed_through():
    received = {}

    def fake_worker(path, source_url=None, harvest_run_id=None):
        received[path] = source_url
        return [{"device_name": "X"}]

    source_urls = {
        "a.html": "https://example.com/a",
        "b.html": "https://example.com/b",
    }

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        results = process_html_files_parallel(
            ["a.html", "b.html"],
            harvest_run_id="hr-test",
            source_urls=source_urls,
        )

    assert received == source_urls
    for r in results:
        assert r.source_url == source_urls[r.path]


def test_progress_callback_thread_safe():
    """20 files × 4 workers — the callback must see exactly 20 events."""
    def fake_worker(path, source_url=None, harvest_run_id=None):
        time.sleep(0.01)  # force interleaving
        return [{"device_name": "X"}]

    events = []
    lock = threading.Lock()

    def on_progress(completed, total):
        with lock:
            events.append((completed, total))

    paths = [f"f{i}.html" for i in range(20)]
    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        process_html_files_parallel(
            paths,
            harvest_run_id="hr-test",
            progress_callback=on_progress,
        )

    assert len(events) == 20
    completed_values = sorted(c for c, _ in events)
    assert completed_values == list(range(1, 21))


def test_worker_receives_harvest_run_id():
    received_ids = []
    lock = threading.Lock()

    def fake_worker(path, source_url=None, harvest_run_id=None):
        with lock:
            received_ids.append(harvest_run_id)
        return [{"device_name": "X"}]

    with patch("pipeline.runner._process_single_ollama", side_effect=fake_worker):
        process_html_files_parallel(
            ["a.html", "b.html", "c.html"],
            harvest_run_id="HR-EXPECTED",
        )

    assert received_ids == ["HR-EXPECTED"] * 3
