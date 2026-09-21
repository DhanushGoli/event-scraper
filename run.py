#!/usr/bin/env python3
import argparse
import sys

from scrapers import envutil  # loads .env


TASKS = ("devpost", "mlh", "lovable-events", "lovable-partners", "cursor")


def run_task(task: str) -> None:
    if task == "devpost":
        from scrapers.devpost import process_hackathons
        process_hackathons()
    elif task == "mlh":
        from scrapers.mlh import main as mlh_main
        mlh_main()
    elif task == "lovable-events":
        from scrapers.lovable_events import check_and_send_new_events
        check_and_send_new_events()
    elif task == "lovable-partners":
        from scrapers.lovable_partners import process_partners
        process_partners()
    elif task == "cursor":
        from scrapers.cursor_luma import process_entries
        process_entries()
    else:
        raise ValueError(f"Unknown task: {task}")


def run_all() -> int:
    failed = []
    for task in TASKS:
        print(f"\n======== {task} ========")
        try:
            run_task(task)
        except Exception as e:
            print(f"[ERROR] {task} failed: {e}")
            failed.append(task)
    if failed:
        print(f"[DONE] failed: {', '.join(failed)}")
        return 1
    print("[DONE] all tasks ok")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one event scraper task, or all")
    parser.add_argument(
        "task",
        nargs="?",
        default="all",
        choices=[*TASKS, "all"],
        help="Task to run. Default: all (used by Railway cron)",
    )
    args = parser.parse_args()
    if args.task == "all":
        sys.exit(run_all())
    run_task(args.task)


if __name__ == "__main__":
    main()
