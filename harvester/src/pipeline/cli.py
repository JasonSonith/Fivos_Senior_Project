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

from pipeline.runner import (
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    _parse_urls,
    process_batch,
    scrape_urls,
    write_records_to_db,
    run_gudid_validation,
)

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

BAR_WIDTH = 40


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

class ProgressBar:
    """Animated progress bar that runs in a background thread.

    While running: white bar with a cycling animation.
    On complete:   green filled bar with a checkmark.
    """

    def __init__(self, label: str):
        self.label = label
        self._stop = threading.Event()
        self._thread = None
        self._success = True

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def finish(self, success: bool = True):
        self._success = success
        self._stop.set()
        if self._thread:
            self._thread.join()
        self._draw_complete()

    def _animate(self):
        frames = ["\u2591", "\u2592", "\u2593", "\u2588"]
        i = 0
        while not self._stop.is_set():
            filled = i % (BAR_WIDTH + 1)
            bar = ""
            for j in range(BAR_WIDTH):
                if j < filled:
                    bar += "\u2588"
                elif j == filled:
                    bar += frames[i % len(frames)]
                else:
                    bar += "\u2591"
            pct = int((filled / BAR_WIDTH) * 100)
            sys.stdout.write(f"\r  {WHITE}{self.label}  [{bar}] {pct:>3}%{RESET}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)

    def _draw_complete(self):
        if self._success:
            bar = "\u2588" * BAR_WIDTH
            sys.stdout.write(f"\r  {GREEN}{self.label}  [{bar}] 100% \u2714{RESET}\n")
        else:
            bar = "\u2591" * BAR_WIDTH
            sys.stdout.write(f"\r  {WHITE}{self.label}  [{bar}]  \u2718 Failed{RESET}\n")
        sys.stdout.flush()


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

def run_mode(mode: dict, options: dict):
    # Suppress noisy logs during progress bars unless verbose
    if options["verbose"]:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s %(name)s: %(message)s",
            force=True,
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(levelname)s %(name)s: %(message)s",
            force=True,
        )

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
    bar = ProgressBar("Scraping")
    bar.start()
    try:
        scrape_urls(urls, str(DEFAULT_INPUT_DIR))
        bar.finish(success=True)
    except Exception as e:
        bar.finish(success=False)
        print(f"  Scrape error: {e}")
        return

    # Step 2: Extract
    bar = ProgressBar("Extracting")
    bar.start()
    try:
        summary = process_batch(
            input_dir=str(DEFAULT_INPUT_DIR),
            output_dir=output_dir,
            harvest_run_id=run_id,
        )
        output_files = summary.get("files", [])
        bar.finish(success=summary["succeeded"] > 0 or summary["processed"] == 0)
    except Exception as e:
        bar.finish(success=False)
        print(f"  Extraction error: {e}")
        return

    # Step 3: DB write
    if mode["db"] and output_files:
        bar = ProgressBar("Saving to DB")
        bar.start()
        try:
            write_records_to_db(output_files, overwrite=options["overwrite"])
            bar.finish(success=True)
        except Exception as e:
            bar.finish(success=False)
            print(f"  DB error: {e}")

    # Step 4: Validation
    val = None
    if mode["validate"]:
        bar = ProgressBar("Validating")
        bar.start()
        try:
            val = run_gudid_validation(run_id=run_id, overwrite=options["overwrite"])
            bar.finish(success=val.get("success", False))
        except Exception as e:
            bar.finish(success=False)
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
    print(f"  Ollama-extracted: {summary['ollama_extracted']}")
    print(f"  Output:           {summary['output_dir']}")

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
