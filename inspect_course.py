"""Read-only Inspektion des Kursplans.

Oeffnet den Kursplan mit gespeicherter Session, navigiert auf ein Zieldatum
und listet alle sichtbaren Kurs-Slots auf. Bucht NICHTS.

Aufruf:
    .venv/bin/python inspect_course.py --days-ahead 9
"""
import argparse
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from save_session import open_logged_in_context, HEADLESS, TIMEZONE_ID
from book_course import (
    COURSE_URL,
    dismiss_cookie_banner,
    close_blocking_overlays,
    ensure_kurse_page,
    reset_kurse_date,
    stabilize_kurse_view,
    wait_until_not_busy,
    find_date_input,
)


def set_exact_date(page, date_str):
    box = find_date_input(page)
    if box is None:
        print("WARN: Kein Datumsfeld gefunden.")
        return
    try:
        box.fill(date_str)
        box.press("Enter")
        page.wait_for_timeout(500)
        wait_until_not_busy(page, timeout_ms=10000)
    except Exception as e:
        print(f"WARN: Datum setzen fehlgeschlagen: {e}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--days-ahead", type=int, default=9)
    p.add_argument("--date", help="Exaktes Zieldatum TT.MM.JJJJ (ueberschreibt --days-ahead)")
    p.add_argument("--email")
    p.add_argument("--password")
    return p.parse_args()


def main():
    args = parse_args()
    if args.date:
        print(f"Zieldatum (exakt): {args.date}")
    else:
        target = datetime.now(ZoneInfo(TIMEZONE_ID)) + timedelta(days=max(0, args.days_ahead))
        print(f"Zieldatum: {target.strftime('%A, %d.%m.%Y')} (days_ahead={args.days_ahead})")

    with sync_playwright() as pw:
        context, page = open_logged_in_context(
            pw, headless=HEADLESS, email=args.email, password=args.password
        )
        try:
            page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_load_state("networkidle")
            dismiss_cookie_banner(page)
            close_blocking_overlays(page)
            ensure_kurse_page(page)
            if args.date:
                set_exact_date(page, args.date)
            else:
                reset_kurse_date(page, days_ahead=max(0, args.days_ahead))
            ensure_kurse_page(page)
            wait_until_not_busy(page, timeout_ms=12000)
            stabilize_kurse_view(page)
            page.wait_for_timeout(1000)

            # Alle sichtbaren button-Rollen mit Uhrzeit im Label sammeln.
            buttons = page.get_by_role("button")
            count = buttons.count()
            seen = []
            for i in range(min(count, 400)):
                b = buttons.nth(i)
                try:
                    if not b.is_visible():
                        continue
                    label = (b.get_attribute("aria-label") or b.inner_text() or "").strip()
                    label = re.sub(r"\s+", " ", label)
                    if not label:
                        continue
                    if re.search(r"\b\d{1,2}:\d{2}\b", label):
                        if label not in seen:
                            seen.append(label)
                except Exception:
                    pass

            print(f"\nGefundene Kurs-Slots mit Uhrzeit ({len(seen)}):")
            for s in seen:
                marker = "  <-- YOGA" if re.search(r"yoga", s, re.IGNORECASE) else ""
                print(f"  - {s}{marker}")

            page.screenshot(path="aifitness_inspect.png", full_page=True)
            print("\nScreenshot: aifitness_inspect.png")
        finally:
            context.close()


if __name__ == "__main__":
    main()
