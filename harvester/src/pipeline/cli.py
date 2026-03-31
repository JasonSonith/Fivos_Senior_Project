"""Interactive CLI menu for the Fivos harvesting pipeline.

Usage:
    python harvester/src/pipeline/cli.py
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone

# Ensure harvester/src is on sys.path
_SRC_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
if os.path.abspath(_SRC_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC_DIR))

from pathlib import Path

from pipeline.runner import (
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    _parse_urls,
    process_batch,
    scrape_urls,
    write_records_to_db,
    run_gudid_validation,
)
from pipeline.llm_extractor import get_first_available_model

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "log-files"

# ANSI color codes
WHITE = "\033[97m"
GREEN = "\033[92m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

HEADER_ART = rf"""
{WHITE}  _    _                           _
 | |  | |                         | |
 | |__| | __ _ _ ____   _____  ___| |_ ___ _ __
 |  __  |/ _` | '__\ \ / / _ \/ __| __/ _ \ '__|
 | |  | | (_| | |   \ V /  __/\__ \ ||  __/ |
 |_|  |_|\__,_|_|    \_/ \___||___/\__\___|_|
{RESET}
   {DIM}Fivos Medical Device Data Pipeline{RESET}
"""

MODES = [
    {"label": "Harvest Only",              "desc": "Scrape URLs + extract with Ollama \u2192 JSON files",              "scrape": True, "db": False, "validate": False},
    {"label": "Harvest + Save to DB",      "desc": "Scrape + extract + save records to MongoDB",                       "scrape": True, "db": True,  "validate": False},
    {"label": "Harvest + Save + Validate", "desc": "Full pipeline: scrape + extract + DB + GUDID validation",          "scrape": True, "db": True,  "validate": True},
]

DEFAULT_URLS_FILE = os.path.join(os.path.dirname(__file__), os.pardir, "urls.txt")

# ---------------------------------------------------------------------------
# Animated status line
# ---------------------------------------------------------------------------

class StatusLine:
    """Shows 'Label...' with animated dots, then checkmark or X when done."""

    def __init__(self, label: str):
        self.label = label
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def done(self, success: bool = True):
        self._stop.set()
        if self._thread:
            self._thread.join()
        if success:
            sys.stdout.write(f"\r  {GREEN}{self.label} \u2714{RESET}              \n")
        else:
            sys.stdout.write(f"\r  {WHITE}{self.label} \u2718 Failed{RESET}      \n")
        sys.stdout.flush()

    def _animate(self):
        dots = 0
        while not self._stop.is_set():
            dots = (dots % 3) + 1
            sys.stdout.write(f"\r  {WHITE}{self.label}{'.' * dots}{' ' * (3 - dots)}{RESET}")
            sys.stdout.flush()
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def print_header():
    print(HEADER_ART)


def print_menu():
    print("  Choose a pipeline mode:\n")
    for i, mode in enumerate(MODES, 1):
        print(f"    {BOLD}[{i}]{RESET}  {mode['label']}")
        print(f"         {DIM}{mode['desc']}{RESET}\n")
    print(f"    {BOLD}[0]{RESET}  Quit\n")


def prompt_choice() -> int:
    while True:
        raw = input("  Enter choice (0-3): ").strip()
        if raw.isdigit() and 0 <= int(raw) <= len(MODES):
            return int(raw)
        print("  Invalid choice. Try again.\n")


def prompt_yes_no(question: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"  {question} {suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def prompt_url_source() -> str:
    print(f"\n  URL source:")
    print(f"    - Press Enter to use default ({DIM}{DEFAULT_URLS_FILE}{RESET})")
    print(f"    - Enter a path to a .txt file")
    print(f"    - Enter a single URL\n")
    raw = input("  URL source: ").strip()
    if not raw:
        return DEFAULT_URLS_FILE
    return raw


def prompt_db_mode() -> bool:
    """Prompt for append vs overwrite. Returns True if overwrite."""
    print("\n  Database write mode:\n")
    print(f"    {BOLD}[1]{RESET}  Append (add to existing data)")
    print(f"    {BOLD}[2]{RESET}  Overwrite (wipe collection first)\n")
    while True:
        raw = input("  Enter choice (1-2): ").strip()
        if raw == "1":
            return False
        if raw == "2":
            return True
        print("  Invalid choice. Try again.\n")


def collect_options(mode: dict) -> dict:
    options = {}

    options["url_source"] = prompt_url_source()

    if mode["db"]:
        options["overwrite"] = prompt_db_mode()
    else:
        options["overwrite"] = False

    options["verbose"] = prompt_yes_no("Verbose logging?", default=False)

    return options


def print_confirmation(mode: dict, options: dict):
    print(f"\n  {'='*50}")
    print(f"  Mode:      {BOLD}{mode['label']}{RESET}")

    source = options["url_source"]
    if os.path.isfile(source):
        urls = _parse_urls(source)
        print(f"  URLs:      {source} ({len(urls)} URLs)")
    else:
        print(f"  URL:       {source}")

    if mode["db"]:
        db_mode = "Overwrite" if options["overwrite"] else "Append"
        print(f"  DB:        {db_mode}")
    else:
        print(f"  DB:        No")

    print(f"  Validate:  {'Yes' if mode['validate'] else 'No'}")
    print(f"  Verbose:   {'Yes' if options['verbose'] else 'No'}")
    print(f"  {'='*50}\n")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _setup_file_logging() -> tuple[logging.FileHandler, str]:
    """Redirect all logging to a file. Returns (handler, log_path)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"harvest_{ts}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove any console handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(fh)
    return fh, str(log_path)


def _teardown_file_logging(fh: logging.FileHandler):
    root = logging.getLogger()
    root.removeHandler(fh)
    fh.close()


def run_mode(mode: dict, options: dict):
    fh, log_path = _setup_file_logging()

    run_id = f"HR-LOCAL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    output_dir = str(DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)
    output_files = []

    # Step 1: Scrape
    source = options["url_source"]
    if os.path.isfile(source):
        urls = _parse_urls(source)
    elif source.startswith("http"):
        urls = [source]
    else:
        urls = _parse_urls(source)

    if not urls:
        print("\n  No URLs found. Aborting.")
        return

    print()
    status = StatusLine("Scraping")
    status.start()
    try:
        scrape_urls(urls, str(DEFAULT_INPUT_DIR))
        status.done(success=True)
    except Exception as e:
        status.done(success=False)
        print(f"  Scrape error: {e}")
        return

    # Step 2: Extract
    model = get_first_available_model()
    status = StatusLine(f"Extracting ({model})")
    status.start()
    try:
        summary = process_batch(
            input_dir=str(DEFAULT_INPUT_DIR),
            output_dir=output_dir,
            harvest_run_id=run_id,
        )
        output_files = summary.get("files", [])
        status.done(success=summary["succeeded"] > 0 or summary["processed"] == 0)
    except Exception as e:
        status.done(success=False)
        print(f"  Extraction error: {e}")
        return

    # Step 3: DB write
    if mode["db"] and output_files:
        status = StatusLine("Saving to DB")
        status.start()
        try:
            write_records_to_db(output_files, overwrite=options["overwrite"])
            status.done(success=True)
        except Exception as e:
            status.done(success=False)
            print(f"  DB error: {e}")

    # Step 4: Validation
    val = None
    if mode["validate"]:
        status = StatusLine("Validating")
        status.start()
        try:
            val = run_gudid_validation(run_id=run_id, overwrite=options["overwrite"])
            status.done(success=val.get("success", False))
        except Exception as e:
            status.done(success=False)
            print(f"  Validation error: {e}")

    # Results
    print(f"\n  {BOLD}{'='*50}{RESET}")
    print(f"  {BOLD}Results{RESET}")
    print(f"  {'='*50}")
    print(f"  Processed:        {summary['processed']}")
    print(f"  {GREEN}Succeeded:        {summary['succeeded']}{RESET}")
    if summary["failed"] > 0:
        print(f"  \033[91mFailed:           {summary['failed']}{RESET}")
    else:
        print(f"  Failed:           {summary['failed']}")
    print(f"  Records written:  {len(output_files)}")
    print(f"  Output:           {summary['output_dir']}")
    print(f"  Log file:         {log_path}")

    if mode["db"]:
        db_mode = "overwrite" if options["overwrite"] else "append"
        print(f"  DB mode:          {db_mode}")
        print(f"  Records saved:    {len(output_files)}")

    if val and val.get("success"):
        print(f"\n  {BOLD}Validation{RESET}")
        print(f"  Total:            {val['total']}")
        print(f"  {GREEN}Full matches:     {val['full_matches']}{RESET}")
        if val["partial_matches"] > 0:
            print(f"  \033[93mPartial matches:  {val['partial_matches']}{RESET}")
        else:
            print(f"  Partial matches:  {val['partial_matches']}")
        if val["mismatches"] > 0:
            print(f"  \033[91mMismatches:       {val['mismatches']}{RESET}")
        else:
            print(f"  Mismatches:       {val['mismatches']}")
        print(f"  Not found:        {val['not_found']}")
    elif val:
        print(f"\n  Validation error: {val.get('error')}")

    print(f"  {'='*50}")
    print(f"\n  {GREEN}\u2714 Done.{RESET}")

    _teardown_file_logging(fh)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def interactive_main():
    print_header()

    while True:
        print_menu()
        choice = prompt_choice()

        if choice == 0:
            print(f"\n  Goodbye.\n")
            break

        mode = MODES[choice - 1]
        print(f"\n  Selected: {BOLD}{mode['label']}{RESET}\n")

        options = collect_options(mode)
        print_confirmation(mode, options)

        if not prompt_yes_no("Proceed?", default=True):
            print("  Cancelled.\n")
            continue

        try:
            run_mode(mode, options)
        except KeyboardInterrupt:
            print(f"\n\n  Interrupted by user.")
        except Exception as e:
            print(f"\n  Error: {e}")

        print()
        if not prompt_yes_no("Run again?", default=False):
            print(f"\n  Goodbye.\n")
            break
        print()


if __name__ == "__main__":
    interactive_main()
