"""Parallel HTML file extraction for harvester batch runs.

Shared by CLI batch (runner.process_batch) and UI batch
(orchestrator.run_harvest_batch). Each worker runs _process_single_ollama
on one file; per-provider concurrency caps live inside llm_extractor
(semaphores). Exceptions in workers are caught and returned as error
results so one bad file cannot crash the batch.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class FileExtractionResult:
    path: str
    source_url: str | None
    records: list[dict] = field(default_factory=list)
    error: str | None = None


def process_html_files_parallel(
    html_paths: list[str],
    harvest_run_id: str,
    source_urls: dict[str, str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[FileExtractionResult]:
    """Extract records from HTML files in parallel.

    Args:
        html_paths: Paths to HTML files to process.
        harvest_run_id: ID threaded through to each record for traceability.
        source_urls: Optional path -> source URL map (propagated to _process_single_ollama).
        progress_callback: Called as (completed, total) whenever any worker finishes.

    Returns:
        One FileExtractionResult per input path, regardless of success.
    """
    # Lazy imports: Task 6 will have runner.process_batch import from this
    # module, which would create a circular import at module load time.
    from pipeline.llm_extractor import EXTRACT_WORKERS
    from pipeline.runner import _process_single_ollama

    total = len(html_paths)
    if total == 0:
        return []

    source_urls = source_urls or {}
    completed = 0
    progress_lock = threading.Lock()

    def _work(path: str) -> FileExtractionResult:
        try:
            records = _process_single_ollama(
                path,
                source_url=source_urls.get(path),
                harvest_run_id=harvest_run_id,
            )
            return FileExtractionResult(
                path=path,
                source_url=source_urls.get(path),
                records=records,
                error=None,
            )
        except Exception as exc:
            logger.error(
                "parallel_batch: worker crashed on %s: %s",
                path, exc, exc_info=True,
            )
            return FileExtractionResult(
                path=path,
                source_url=source_urls.get(path),
                records=[],
                error=str(exc),
            )

    results: list[FileExtractionResult] = []
    with ThreadPoolExecutor(
        max_workers=EXTRACT_WORKERS,
        thread_name_prefix="extract",
    ) as pool:
        futures = {pool.submit(_work, p): p for p in html_paths}
        for future in as_completed(futures):
            results.append(future.result())
            with progress_lock:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

    return results
