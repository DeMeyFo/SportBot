from playwright.sync_api import sync_playwright

import argparse
import os
from datetime import datetime

from save_session import open_logged_in_context, STATE_FILE, HEADLESS
from book_course import run_booking_flow, COURSE_NAME


def parse_args():
    parser = argparse.ArgumentParser(description="Run MySports booking for a single course.")
    parser.add_argument("--course", help="Course name for this run (one course per cronjob).")
    parser.add_argument("--slot", help="Optional exact slot label, e.g. 'BODYPUMP, 17:45 - 18:45'.")
    parser.add_argument("--weekday", help="Optional weekday filter, e.g. Mon/Tue or Montag/Dienstag.")
    parser.add_argument(
        "--days-ahead",
        type=int,
        help="Target date offset from today (e.g. 5 means today+5). Uses date field instead of weekday selection.",
    )
    parser.add_argument("--email", help="Login email (overrides MYSPORTS_EMAIL).")
    parser.add_argument("--password", help="Login password (overrides MYSPORTS_PASSWORD).")
    parser.add_argument(
        "--attempts",
        type=int,
        default=int(os.getenv("MYSPORTS_ATTEMPTS", "3")),
        help="How many full booking attempts should be made before failing (default: 3).",
    )
    return parser.parse_args()

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def main():
    args = parse_args()
    course = (args.course or COURSE_NAME or "").strip()
    if not course:
        raise SystemExit("❌ Kein Kurs gesetzt. Nutze --course \"...\" oder MYSPORTS_COURSE.")
    attempts = max(1, args.attempts)

    with sync_playwright() as p:
        target = args.slot or course
        last_error = None

        for attempt in range(1, attempts + 1):
            log(f"1/2 Login + Session ... (Versuch {attempt}/{attempts})")
            context, page = open_logged_in_context(
                p,
                headless=HEADLESS,
                email=args.email,
                password=args.password,
            )
            context.storage_state(path=str(STATE_FILE))
            log("✅ Session gespeichert.")

            log("2/2 Starte Buchung ...")
            try:
                log(f"➡️ Buche: {target}")
                run_booking_flow(
                    page,
                    course_name=course,
                    weekday=args.weekday,
                    slot_name=args.slot,
                    days_ahead=args.days_ahead,
                    email=args.email,
                    password=args.password,
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    log(f"⚠️ Versuch {attempt} fehlgeschlagen, starte erneut ...")
                else:
                    raise
            finally:
                context.close()

        if last_error:
            raise last_error


if __name__ == "__main__":
    main()
