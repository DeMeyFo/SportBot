import os
import re
import sys
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

# --- AI-Fitness / Magicline Member-Plattform ---------------------------------
# Umzug von www.mysports.com auf eine gebrandete Magicline-Instanz.
# Basis-URL und Studio-ID kommen aus der .env (siehe save_session.py).
BASE_URL = os.getenv("AIFITNESS_BASE_URL", "https://dein.ai-fitness.de").rstrip("/")
STUDIO_ID = os.getenv("AIFITNESS_STUDIO_ID", "")
BASE_HOST = re.sub(r"^https?://", "", BASE_URL).split("/")[0]


def _studio_path(suffix: str) -> str:
    suffix = suffix.lstrip("/")
    if STUDIO_ID:
        return f"{BASE_URL}/studio/{STUDIO_ID}/{suffix}"
    return f"{BASE_URL}/{suffix}"


STATE_FILE = Path("aifitness_state.json")
PROFILE_DIR = Path(".aifitness_profile")
# Direkter Einstieg in den Kursplan - der alte Umweg ueber die Business-Seite
# entfaellt, weil die Studio-ID direkt in der URL steckt.
LOGIN_URL = _studio_path("login-register")
HOME_URL = _studio_path("course")
COURSE_URL = _studio_path("course")

GYM_NAME = os.getenv("MYSPORTS_GYM", "all inclusive Fitness")
COURSE_NAME = os.getenv("MYSPORTS_COURSE", "Kraft-Ausdauer Training")
EMAIL = os.getenv("MYSPORTS_EMAIL")
PASSWORD = os.getenv("MYSPORTS_PASSWORD")
VIEWPORT_WIDTH = int(os.getenv("MYSPORTS_VIEWPORT_WIDTH", "1920"))
VIEWPORT_HEIGHT = int(os.getenv("MYSPORTS_VIEWPORT_HEIGHT", "1080"))
HEADLESS = os.getenv("MYSPORTS_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"}
LOCALE = os.getenv("MYSPORTS_LOCALE", "de-DE")
TIMEZONE_ID = os.getenv("MYSPORTS_TIMEZONE", "Europe/Berlin")
TARGET_DAYS_AHEAD = int(os.getenv("MYSPORTS_TARGET_DAYS_AHEAD", "6"))

DAY_ALIASES = {
    "mon": ["montag", "monday", "mo"],
    "tue": ["dienstag", "tuesday", "di", "tu"],
    "wed": ["mittwoch", "wednesday", "mi", "we"],
    "thu": ["donnerstag", "thursday", "do", "th"],
    "fri": ["freitag", "friday", "fr", "fri"],
    "sat": ["samstag", "saturday", "sa", "sat"],
    "sun": ["sonntag", "sunday", "so", "sun"],
}

WEEKDAY_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
WEEKDAY_BY_INDEX = {v: k for k, v in WEEKDAY_INDEX.items()}

# Für UI-Selektoren keine 2-Zeichen-Aliase verwenden, damit keine False-Positives entstehen.
WEEKDAY_UI_LABELS = {
    "mon": ["Montag", "Monday", "Mon"],
    "tue": ["Dienstag", "Tuesday", "Tue"],
    "wed": ["Mittwoch", "Wednesday", "Wed"],
    "thu": ["Donnerstag", "Thursday", "Thu"],
    "fri": ["Freitag", "Friday", "Fri"],
    "sat": ["Samstag", "Saturday", "Sat"],
    "sun": ["Sonntag", "Sunday", "Sun"],
}

def safe_click(locator, timeout=15000, label="", allow_force=True):
    try:
        locator.wait_for(state="visible", timeout=timeout)
        locator.click(timeout=timeout)
    except PlaywrightTimeoutError as e:
        if not allow_force:
            raise PlaywrightTimeoutError(f"Timeout clicking {label or 'locator'} after {timeout}ms") from e
        # Fallback für überlagerte/abgefangene Klicks
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        locator.click(timeout=3000, force=True)

def normalize_weekday(weekday):
    if not weekday:
        return None
    raw = weekday.strip().lower()

    # Direkter Treffer auf Key wie mon/tue/...
    if raw in DAY_ALIASES:
        return raw

    # Treffer über bekannte Alias-Namen (de/en) inkl. Prefix-Varianten.
    for key, aliases in DAY_ALIASES.items():
        for alias in aliases:
            if raw == alias or raw.startswith(alias) or alias.startswith(raw):
                return key

    # Fallback auf 3-Zeichen-Kürzel (z. B. "don" -> Donnerstag)
    short = raw[:3]
    for key, aliases in DAY_ALIASES.items():
        if key.startswith(short):
            return key
        if any(a.startswith(short) for a in aliases):
            return key

    raise ValueError(f"Ungültiger Wochentag: {weekday}")

def click_first_visible(locator, label):
    count = locator.count()
    if not count:
        return False
    for i in range(min(count, 30)):
        item = locator.nth(i)
        try:
            if item.is_visible():
                safe_click(item, label=label)
                return True
        except Exception:
            pass
    return False

def click_any_visible(page, patterns, label):
    for pattern in patterns:
        loc = page.get_by_role("button", name=pattern)
        if click_first_visible(loc, label=label):
            return True
    return False

def weekday_ui_pattern(key):
    labels = WEEKDAY_UI_LABELS.get(key, [])
    if not labels:
        return re.compile(r"$^")
    escaped = [re.escape(x) for x in labels]
    # Word-boundary verhindert Matches wie "we" in "News".
    return re.compile(rf"\b(?:{'|'.join(escaped)})\b", re.IGNORECASE)

def is_booking_success_view(page, weekday=None):
    success = (
        has_visible_text(page, re.compile(r"Du hast diesen Termin gebucht", re.IGNORECASE))
        or has_visible_text(page, re.compile(r"You have booked (this )?(appointment|event)", re.IGNORECASE))
        or has_visible_text(page, re.compile(r"Zu meinen Terminbuchungen|My bookings|My appointments", re.IGNORECASE))
        # Weitere Magicline/AI-Fitness-Bestaetigungstexte (defensiv).
        or has_visible_text(page, re.compile(r"Buchung (erfolgreich|best[äa]tigt)|erfolgreich gebucht", re.IGNORECASE))
        or has_visible_text(page, re.compile(r"Booking (successful|confirmed)|successfully booked", re.IGNORECASE))
        or has_visible_text(page, re.compile(r"Termin(buchung)? best[äa]tigt", re.IGNORECASE))
    )
    if not success:
        return False
    if not weekday:
        return True
    try:
        key = normalize_weekday(weekday)
        pattern = weekday_ui_pattern(key)
        # Auf der Bestätigungsseite steht der konkrete Tag (z. B. "Dienstag, 10.03.2026")
        return has_visible_text(page, pattern)
    except Exception:
        return False

def wait_until_not_busy(page, timeout_ms=20000):
    waited = 0
    step = 400
    spinner = page.locator("[role='progressbar'], .MuiCircularProgress-root, .spinner, [class*='Spinner']")
    while waited < timeout_ms:
        try:
            if spinner.count() == 0:
                return True
            visible = False
            for i in range(min(spinner.count(), 8)):
                try:
                    if spinner.nth(i).is_visible():
                        visible = True
                        break
                except Exception:
                    pass
            if not visible:
                return True
        except Exception:
            return True
        page.wait_for_timeout(step)
        waited += step
    return False

def close_blocking_overlays(page):
    # Schließt offene Menüs/Dropdowns, die Klicks auf Kurs-Slots blockieren können.
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(120)
        page.keyboard.press("Escape")
        page.wait_for_timeout(120)
    except Exception:
        pass

    # Falls ein Dropdown offen bleibt: in den oberen leeren Bereich klicken.
    try:
        page.mouse.click(20, 20)
        page.wait_for_timeout(120)
    except Exception:
        pass

    # Offene Listbox explizit wegklicken.
    try:
        listbox = page.locator("[role='listbox']")
        if listbox.count():
            for i in range(min(listbox.count(), 3)):
                if listbox.nth(i).is_visible():
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(120)
                    break
    except Exception:
        pass

def find_date_input(page):
    # In der Kurse-Ansicht gibt es oft mehrere Comboboxen (Studio + Datum).
    # Wir wählen gezielt das Datumsfeld anhand von Wert/Attributen.
    inputs = page.locator("input[role='combobox'], input[id*='mui' i], input[placeholder]")
    count = inputs.count()
    best = None
    best_score = -999

    for i in range(min(count, 20)):
        item = inputs.nth(i)
        try:
            if not item.is_visible():
                continue
            value = ""
            try:
                value = item.input_value() or ""
            except Exception:
                value = (item.get_attribute("value") or "")
            attrs = " ".join(
                [
                    value,
                    item.get_attribute("placeholder") or "",
                    item.get_attribute("aria-label") or "",
                    item.get_attribute("name") or "",
                    item.get_attribute("id") or "",
                    item.get_attribute("class") or "",
                ]
            ).lower()

            score = 0
            if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", value):
                score += 10
            if re.search(r"datum|date|calendar|kalender", attrs):
                score += 8
            if re.search(r"studio|gym|location|club|fitness", attrs):
                score -= 8

            if score > best_score:
                best = item
                best_score = score
        except Exception:
            pass

    if best is not None and best_score > -1:
        return best

    # Fallback: falls nichts eindeutig erkannt wurde, bei mehreren Feldern das zweite nehmen
    # (im aktuellen Layout: 1=Studio, 2=Datum).
    visible = []
    for i in range(min(count, 10)):
        item = inputs.nth(i)
        try:
            if item.is_visible():
                visible.append(item)
        except Exception:
            pass
    if len(visible) >= 2:
        return visible[1]
    return visible[0] if visible else None

def stabilize_kurse_view(page):
    # In manchen Sessions bleibt die Tabelle im Ladespinner hängen.
    # Dann den Filter/Datum-Combobox-Zustand bereinigen.
    box = find_date_input(page)
    if box is not None:
        try:
            if box.is_visible():
                is_invalid = (box.get_attribute("aria-invalid") or "").lower() == "true"
                # Nur bei ungültigem Datumsfeld korrigieren; keine Studio-/Filterwerte löschen.
                if is_invalid:
                    today = datetime.now().strftime("%d.%m.%Y")
                    box.fill(today)
                    box.press("Enter")
                    page.wait_for_timeout(500)
        except Exception:
            pass

    if wait_until_not_busy(page, timeout_ms=12000):
        return

    # Fallback: harter Refresh + einmalige Navigation auf Kurse
    page.reload(wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    click_any_visible(
        page,
        [
            re.compile(r"^Kurse$|Classes|Termine|Appointments", re.IGNORECASE),
        ],
        label="KurseAfterReload",
    )
    wait_until_not_busy(page, timeout_ms=12000)

def reset_kurse_date(page, days_ahead=0):
    # Erzwingt einen stabilen Startpunkt über das Datumsfeld.
    # days_ahead=0 -> heute, days_ahead=6 -> typischer Buchungszeitpunkt in Folgewoche.
    box = find_date_input(page)
    if box is None:
        return
    try:
        if not box.is_visible():
            return
        try:
            target = datetime.now(ZoneInfo(TIMEZONE_ID))
        except Exception:
            target = datetime.now()
        try:
            from datetime import timedelta
            target = target + timedelta(days=max(0, int(days_ahead)))
        except Exception:
            pass
        target_str = target.strftime("%d.%m.%Y")
        box.fill(target_str)
        box.press("Enter")
        page.wait_for_timeout(500)
        wait_until_not_busy(page, timeout_ms=10000)
    except Exception:
        pass

def set_exact_kurse_date(page, date_str):
    # Setzt ein konkretes Datum (TT.MM.JJJJ) in das Kursplan-Datumsfeld.
    # Unabhaengig von der Systemuhr - wird fuer --date genutzt.
    box = find_date_input(page)
    if box is None:
        return
    try:
        if not box.is_visible():
            return
        box.fill(date_str)
        box.press("Enter")
        page.wait_for_timeout(500)
        wait_until_not_busy(page, timeout_ms=10000)
    except Exception:
        pass

def wait_for_booking_actions(page, timeout_ms=20000):
    patterns = [
        re.compile(r"Kostenfrei|Free", re.IGNORECASE),
        re.compile(r"Weiter|Next", re.IGNORECASE),
        re.compile(r"Jetzt buchen|Book now", re.IGNORECASE),
        re.compile(r"^Buchen$|^Book$", re.IGNORECASE),
        re.compile(r"Warteliste|Waitlist", re.IGNORECASE),
        re.compile(r"Auf Warteliste|Join waitlist", re.IGNORECASE),
        re.compile(r"Übernehmen|Apply|Confirm", re.IGNORECASE),
    ]
    waited = 0
    step = 400
    while waited < timeout_ms:
        for pattern in patterns:
            loc = page.get_by_role("button", name=pattern)
            count = loc.count()
            for i in range(min(count, 8)):
                try:
                    if loc.nth(i).is_visible():
                        return True
                except Exception:
                    pass
        page.wait_for_timeout(step)
        waited += step
    return False

def has_visible_text(page, pattern):
    loc = page.get_by_text(pattern)
    count = loc.count()
    for i in range(min(count, 40)):
        try:
            if loc.nth(i).is_visible():
                return True
        except Exception:
            pass
    return False

def is_kurse_view(page):
    # Die Kursansicht ist je nach Sprache/Viewport nicht immer identisch.
    # Beim AI-Fitness/Magicline-Portal landen wir direkt auf .../course und
    # sehen die Kurs-Slots als Karten mit Uhrzeit. Die zuverlaessigste
    # Erkennung ist daher die URL bzw. sichtbare Slot-Karten.
    try:
        if re.search(r"/course\b", page.url, re.IGNORECASE):
            on_course_url = True
        else:
            on_course_url = False
    except Exception:
        on_course_url = False

    has_filter = has_visible_text(page, re.compile(r"^Filters?(\s*\(\d+\))?$", re.IGNORECASE))
    has_date_row = has_visible_text(
        page,
        re.compile(
            r"(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday).*(20\d{2})",
            re.IGNORECASE,
        ),
    )
    has_date_input = False
    has_classes_nav = False
    has_slot_cards = False
    try:
        has_date_input = page.locator("input[role='combobox'], input[id*='mui' i]").count() > 0
    except Exception:
        pass
    try:
        has_classes_nav = (
            page.locator("a, button, [role='tab'], [role='link']")
            .filter(has_text=re.compile(r"^Kurse$|^Classes$", re.IGNORECASE))
            .count()
            > 0
        )
    except Exception:
        pass
    try:
        # Slot-Karten enthalten im Grid fast immer Uhrzeiten.
        has_slot_cards = (
            page.locator("[role='button']")
            .filter(has_text=re.compile(r"\b\d{1,2}:\d{2}\b", re.IGNORECASE))
            .count()
            > 0
        )
    except Exception:
        pass
    # Sichtbare Slot-Karten sind das staerkste Signal; die /course-URL mit
    # Datumsfeld oder Kurse-Navigation genuegt ebenfalls.
    return (
        has_slot_cards
        or has_filter
        or (on_course_url and (has_date_input or has_classes_nav or has_date_row))
        or (has_date_row and has_date_input)
        or (has_classes_nav and has_date_row)
    )

def is_booking_options_view(page):
    if has_visible_text(page, re.compile(r"Buchungsoptionen|Booking options", re.IGNORECASE)):
        return True
    if has_visible_text(page, re.compile(r"Kostenfrei|Free", re.IGNORECASE)) and has_visible_text(page, re.compile(r"Weiter|Next", re.IGNORECASE)):
        return True
    return False

def is_kurse_loading_view(page):
    try:
        kurse_tab_visible = (
            page.locator("a, button, [role='tab'], [role='link']")
            .filter(has_text=re.compile(r"^Kurse$|^Classes$", re.IGNORECASE))
            .count()
            > 0
        )
    except Exception:
        kurse_tab_visible = False
    if not kurse_tab_visible:
        return False

    try:
        spinner = page.locator("[role='progressbar'], .MuiCircularProgress-root, .spinner, [class*='Spinner']")
        count = spinner.count()
        for i in range(min(count, 8)):
            try:
                if spinner.nth(i).is_visible():
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False

def ensure_kurse_page(page):
    if is_kurse_view(page):
        return
    nav_candidates = [
        page.locator("header a, nav a, [role='navigation'] a").filter(has_text=re.compile(r"^Kurse$|^Classes$", re.IGNORECASE)),
        page.get_by_role("link", name=re.compile(r"^Kurse$|^Classes$", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"^Kurse$|^Classes$", re.IGNORECASE)),
        page.get_by_text(re.compile(r"^Kurse$|^Classes$", re.IGNORECASE)),
    ]

    for _ in range(4):
        close_blocking_overlays(page)
        for loc in nav_candidates:
            count = loc.count()
            for i in range(min(count, 12)):
                item = loc.nth(i)
                try:
                    if not item.is_visible():
                        continue
                    safe_click(item, label="OpenKurse")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(500)
                    if is_kurse_view(page):
                        return
                except Exception:
                    try:
                        safe_click(item, label="OpenKurseForce", allow_force=True)
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(500)
                        if is_kurse_view(page):
                            return
                    except Exception:
                        pass
        page.wait_for_timeout(500)

    page.screenshot(path="aifitness_kurse_view_missing.png", full_page=True)
    raise RuntimeError(
        "❌ Kursansicht konnte nicht geöffnet werden. Screenshot: aifitness_kurse_view_missing.png"
    )

def open_kurse_view_recorded(page, email=None):
    # 1) Avatar-Menü öffnen (laut Codegen häufig nötig, damit Kurse-Link sichtbar wird)
    user_email = email or EMAIL
    avatar_candidates = [
        page.locator(".Avatar--szjdia.deiVEI"),
        page.locator("[class*='Avatar']"),
        page.get_by_text(user_email or "", exact=False) if user_email else page.locator("__never__"),
    ]
    for loc in avatar_candidates:
        try:
            if loc.count() and loc.first.is_visible():
                safe_click(loc.first, label="AvatarMenu")
                page.wait_for_timeout(300)
                break
        except Exception:
            pass

    # 2) Kurse exakt nach Recording öffnen
    kurse_opened = False
    kurse_candidates = [
        page.get_by_role("link", name=re.compile(r"^Kurse$|^Classes$", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"^Kurse$|^Classes$", re.IGNORECASE)),
        page.get_by_text(re.compile(r"^Kurse$|^Classes$", re.IGNORECASE)),
    ]
    for loc in kurse_candidates:
        try:
            count = loc.count()
            for i in range(min(count, 12)):
                item = loc.nth(i)
                if not item.is_visible():
                    continue
                safe_click(item, label="OpenKurseRecorded")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(400)
                if is_kurse_view(page) or is_kurse_loading_view(page):
                    kurse_opened = True
                    break
        except Exception:
            pass
        if kurse_opened:
            break

    if not kurse_opened:
        ensure_kurse_page(page)
    else:
        stabilize_kurse_view(page)
        if not is_kurse_view(page) and not is_kurse_loading_view(page):
            ensure_kurse_page(page)

    # 3) "Übernehmen" falls vor der Kursauswahl notwendig
    confirm_candidates = [
        page.get_by_role("button", name=re.compile(r"^Übernehmen$|Apply|Confirm", re.IGNORECASE)),
        page.get_by_text(re.compile(r"^Übernehmen$", re.IGNORECASE)),
    ]
    for loc in confirm_candidates:
        try:
            if loc.count() and loc.first.is_visible():
                safe_click(loc.first, label="ÜbernehmenPreSlot")
                page.wait_for_timeout(250)
                break
        except Exception:
            pass

def go_to_next_week(page):
    if not is_kurse_view(page):
        return False
    next_week_candidates = [
        page.get_by_role("button", name=re.compile(r"^Pfeil rechts$|^Right arrow$|^Next$", re.IGNORECASE)),
        page.locator("button[aria-label*='rechts' i], button[aria-label*='right' i], button[title*='rechts' i], button[title*='right' i]"),
        page.get_by_text(re.compile(r"^>$")),
    ]
    for loc in next_week_candidates:
        try:
            count = loc.count()
            for i in range(min(count, 8)):
                item = loc.nth(i)
                if not item.is_visible():
                    continue
                safe_click(item, label="NextWeek")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(600)
                stabilize_kurse_view(page)
                close_blocking_overlays(page)
                return True
        except Exception:
            pass
    return False

def maybe_go_to_next_week_for_weekday(page, weekday):
    # Datumssteuerung erfolgt über reset_kurse_date(...). Kein zusätzlicher Week-Jump,
    # damit die Ansicht nicht ungewollt zu weit in die Zukunft driftet.
    return False

def focus_weekday(page, weekday):
    key = normalize_weekday(weekday)
    if not key:
        return
    pattern = weekday_ui_pattern(key)
    selectors = [
        page.get_by_role("tab", name=pattern),
        page.get_by_role("button", name=pattern),
        page.get_by_role("link", name=pattern),
    ]
    for loc in selectors:
        count = loc.count()
        for i in range(min(count, 25)):
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box:
                    continue
                # Wochentag-Header sitzt im oberen Kalenderbereich.
                if not (80 <= box["y"] <= 520 and box["width"] >= 60):
                    continue
                safe_click(item, label=f"Weekday:{weekday}")
                page.wait_for_timeout(400)
                return
            except Exception:
                pass

    # Fallback: In manchen Layouts sind Wochentage nicht klickbar.
    # Wenn die Zielspalte eindeutig erkannt wird, reicht das für den weiteren Flow.
    if get_weekday_column_bounds(page, weekday):
        return

    page.screenshot(path="aifitness_weekday_not_found.png", full_page=True)
    raise RuntimeError(
        f"❌ Gewünschter Wochentag '{weekday}' nicht auswählbar. "
        "Screenshot: aifitness_weekday_not_found.png"
    )

def get_weekday_column_bounds(page, weekday):
    key = normalize_weekday(weekday)
    if not key:
        return None

    # Das AI-Fitness/Magicline-Portal zeigt ein Wochen-Grid mit sieben
    # Tagesspalten nebeneinander. Die Wochentag-Header (z. B. "Samstag") sind
    # nur so breit wie das Wort selbst, die Kurs-Karten fuellen aber die ganze
    # Spalte. Deshalb leiten wir die Spaltenbreite aus dem Abstand zum naechsten
    # Header ab (gleichmaessiges Raster), statt aus der schmalen Textbreite.
    headers = _collect_weekday_headers(page)
    if not headers:
        return None

    # Rasterbreite = typischer Abstand zwischen zwei benachbarten Headern.
    xs = sorted(h["x"] for h in headers.values())
    gaps = [b - a for a, b in zip(xs, xs[1:]) if b - a > 0]
    grid_w = min(gaps) if gaps else 260.0

    target = headers.get(key)
    if target is None:
        return None

    x_start = target["x"]
    # Rechte Grenze = Start der naechsten Spalte (naechster Header rechts),
    # sonst eine Rasterbreite weiter.
    next_xs = [x for x in xs if x > x_start + 5]
    x_end = min(next_xs) if next_xs else (x_start + grid_w)
    # Kleine Toleranz nach links, damit linksbuendige Karten sicher zaehlen.
    return (x_start - 8, x_end)


def _collect_weekday_headers(page):
    # Liefert {weekday_key: {"x":..., "y":..., "w":...}} der sichtbaren
    # Wochentag-Header in der oberen Kalenderzeile.
    found = {}
    full_pattern = re.compile(
        r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|"
        r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday",
        re.IGNORECASE,
    )
    loc = page.get_by_text(full_pattern)
    count = loc.count()
    for i in range(min(count, 60)):
        item = loc.nth(i)
        try:
            if not item.is_visible():
                continue
            text = (item.inner_text() or "").strip()
            box = item.bounding_box()
            if not box:
                continue
            # Header sitzen in der oberen Kalenderzeile.
            if not (80 <= box["y"] <= 520):
                continue
            try:
                key = normalize_weekday(text)
            except Exception:
                continue
            if key and key not in found:
                found[key] = {"x": box["x"], "y": box["y"], "w": box["width"]}
        except Exception:
            pass
    return found

def click_course_in_weekday_column(page, course_name, weekday):
    bounds = get_weekday_column_bounds(page, weekday)
    if not bounds:
        return False
    x_min, x_max = bounds
    slots = page.get_by_role("button", name=re.compile(rf"{re.escape(course_name)}", re.IGNORECASE))
    count = slots.count()
    for i in range(min(count, 80)):
        slot = slots.nth(i)
        try:
            if not slot.is_visible():
                continue
            box = slot.bounding_box()
            if not box:
                continue
            center_x = box["x"] + (box["width"] / 2.0)
            if (x_min - 12) <= center_x <= (x_max + 12):
                safe_click(slot, label=f"CourseColumn:{weekday}")
                return True
        except Exception:
            pass
    return False

def click_course_slot_by_name(page, slot_name, weekday=None):
    if not slot_name:
        return False
    if not is_kurse_view(page):
        return False

    def has_booking_actions():
        patterns = [
            re.compile(r"Kostenfrei|Free", re.IGNORECASE),
            re.compile(r"Weiter|Next", re.IGNORECASE),
            re.compile(r"Jetzt buchen|Book now", re.IGNORECASE),
            re.compile(r"^Buchen$|^Book$", re.IGNORECASE),
            re.compile(r"Warteliste|Waitlist", re.IGNORECASE),
            re.compile(r"Auf Warteliste|Join waitlist", re.IGNORECASE),
            re.compile(r"Übernehmen|Apply|Confirm", re.IGNORECASE),
        ]
        for pattern in patterns:
            loc = page.get_by_role("button", name=pattern)
            count = loc.count()
            for i in range(min(count, 8)):
                try:
                    if loc.nth(i).is_visible():
                        return True
                except Exception:
                    pass
        return False

    weekday_bounds = get_weekday_column_bounds(page, weekday) if weekday else None
    # Wenn keine Spaltengrenzen erkannt wurden, versuchen wir trotzdem den Slot zu finden.
    # Das ist ein Fallback für Layout-Varianten auf VPS/Xvfb.

    def try_click(locator, label, require_actions=True):
        count = locator.count()
        for i in range(min(count, 40)):
            item = locator.nth(i)
            try:
                if not item.is_visible():
                    continue
                if weekday_bounds:
                    box = item.bounding_box()
                    if not box:
                        continue
                    center_x = box["x"] + (box["width"] / 2.0)
                    x_min, x_max = weekday_bounds
                    if not ((x_min - 12) <= center_x <= (x_max + 12)):
                        continue
                raw_label = item.get_attribute("aria-label") or item.inner_text() or ""
                normalized_label = raw_label.lower()
                # Trial/Probetraining-Kacheln nie als Kurs-Slot interpretieren.
                if "probetraining" in normalized_label or "trial" in normalized_label:
                    continue
                safe_click(item, label=label)
                page.wait_for_timeout(250)
                if has_booking_actions() or wait_for_booking_actions(page, timeout_ms=10000):
                    return True
                if not require_actions:
                    # Klick gilt als erfolgreich; finale Validierung erfolgt später im Flow.
                    return True
                # Falscher Treffer: Dialog/Panel schließen und nächsten Kandidaten testen.
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(200)
                except Exception:
                    pass
            except Exception:
                pass
        return False

    # 1) Exakter/nahezu exakter Treffer im aria-label
    pattern = re.compile(rf"{re.escape(slot_name)}", re.IGNORECASE)
    if try_click(page.get_by_role("button", name=pattern), label="CourseSlotName", require_actions=True):
        return True

    # 2) Textsuche in Slot-Containern
    text_slots = page.locator("[role='button']").filter(has_text=re.compile(rf"{re.escape(slot_name)}", re.IGNORECASE))
    if try_click(text_slots, label="CourseSlotText", require_actions=True):
        return True

    # 3) Fuzzy-Fallback: toleriert Namensabweichungen (Interpunktion, Leerzeichen, Groß/Kleinschreibung)
    # sowie 24h/12h-Zeitformate.
    def norm_text(value):
        text = unicodedata.normalize("NFKD", value or "")
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        text = re.sub(r"[^a-z0-9: ]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def extract_minutes(value):
        raw = (value or "").lower()
        minutes = []
        seen = set()

        # 12h (e.g. 04:45 PM)
        for h, m, meridiem in re.findall(r"\b(1[0-2]|0?[1-9]):([0-5]\d)\s*([ap]\.?m\.?)\b", raw):
            hh = int(h)
            mm = int(m)
            is_pm = meridiem.startswith("p")
            if hh == 12:
                hh = 12 if is_pm else 0
            elif is_pm:
                hh += 12
            total = hh * 60 + mm
            if total not in seen:
                seen.add(total)
                minutes.append(total)

        # 24h (exclude tokens immediately followed by am/pm)
        for h, m in re.findall(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[ap]\.?m\.?)", raw):
            total = int(h) * 60 + int(m)
            if total not in seen:
                seen.add(total)
                minutes.append(total)
        return minutes

    wanted = norm_text(slot_name)
    if not wanted:
        return False

    wanted_parts = [p.strip() for p in wanted.split(",") if p.strip()]
    wanted_tokens = [t for t in wanted.split(" ") if t]
    wanted_times = re.findall(r"\b\d{1,2}:\d{2}\b", wanted)
    wanted_minutes = extract_minutes(slot_name)

    candidates = page.locator("[role='button']")
    count = candidates.count()
    scored = []

    for i in range(min(count, 200)):
        item = candidates.nth(i)
        try:
            if not item.is_visible():
                continue
            label = item.get_attribute("aria-label") or item.inner_text() or ""
            normalized = norm_text(label)
            if not normalized:
                continue

            # Trial/Probetraining generell ausschließen.
            if "probetraining" in normalized or "trial" in normalized:
                continue

            # Starker Treffer: ganzer normalisierter String enthalten.
            if wanted in normalized:
                scored.append((9999, i))
                continue

            # Score-basierter Treffer: Tokens + Zeiten (24h/12h tolerant).
            tokens_hit = sum(1 for token in wanted_tokens if token in normalized)
            label_minutes = extract_minutes(label)
            times_hit = len(set(wanted_minutes) & set(label_minutes)) if wanted_minutes else 0
            if times_hit == 0 and wanted_times:
                # Fallback auf einfachen Textvergleich, falls keine Minuten geparsed wurden.
                times_hit = sum(1 for tm in wanted_times if tm in normalized)
            parts_hit = sum(1 for part in wanted_parts if part and part in normalized)
            score = (tokens_hit * 2) + (times_hit * 4) + (parts_hit * 3)

            # Nur plausible Kandidaten berücksichtigen.
            min_needed = max(3, len(wanted_tokens) // 2)
            if times_hit == 0 and wanted_times:
                continue
            if tokens_hit < min_needed:
                continue

            scored.append((score, i))
        except Exception:
            pass

    scored.sort(key=lambda x: x[0], reverse=True)
    for _score, idx in scored[:12]:
        candidate = candidates.nth(idx)
        try:
            if not candidate.is_visible():
                continue
            if weekday_bounds:
                box = candidate.bounding_box()
                if not box:
                    continue
                center_x = box["x"] + (box["width"] / 2.0)
                x_min, x_max = weekday_bounds
                if not ((x_min - 12) <= center_x <= (x_max + 12)):
                    continue
            safe_click(candidate, label="CourseSlotFuzzyBest")
            page.wait_for_timeout(450)
            if has_booking_actions():
                return True
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
            except Exception:
                pass
        except Exception:
            pass
    return False

def dismiss_cookie_banner(page):
    cookie_buttons = [
        page.get_by_role("button", name=re.compile(r"alle akzeptieren|accept all|akzeptieren|zustimmen|übernehmen", re.IGNORECASE)),
        page.get_by_text(re.compile(r"alle akzeptieren|accept all|übernehmen", re.IGNORECASE)),
    ]
    for loc in cookie_buttons:
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=2500)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass

def first_visible(*locators):
    for loc in locators:
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            pass
    return None

def open_login_form(page):
    # Auf der AI-Fitness/Magicline-Plattform blendet /login-register zuerst nur
    # einen Link "Registrieren / Einloggen" ein. Erst ein Klick darauf zeigt das
    # eigentliche E-Mail-/Passwort-Formular.
    for _ in range(2):
        try:
            if page.locator("input[type='email'], input[type='password']").first.is_visible():
                return
        except Exception:
            pass
        link = first_visible(
            page.get_by_role("link", name=re.compile(r"Registrieren\s*/\s*Einloggen|Einloggen|Login|Sign in", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"Registrieren\s*/\s*Einloggen|Einloggen|Login|Sign in", re.IGNORECASE)),
        )
        if link is None:
            return
        try:
            link.click(timeout=4000)
            page.wait_for_timeout(600)
            dismiss_cookie_banner(page)
        except Exception:
            return

def login_if_needed(page, email=None, password=None):
    dismiss_cookie_banner(page)
    if "login-register" not in page.url:
        return
    login_email = email or EMAIL
    login_password = password or PASSWORD
    if not login_email or not login_password:
        raise RuntimeError("❌ Login-Credentials fehlen. Setze MYSPORTS_EMAIL/MYSPORTS_PASSWORD oder übergebe --email/--password.")

    # Formular aufklappen und auf E-Mail-Feld warten (SPA rendert asynchron).
    open_login_form(page)
    try:
        page.wait_for_selector(
            "input[type='email'], input[name*='mail' i], input[id*='mail' i]",
            timeout=12000,
        )
    except PlaywrightTimeoutError:
        pass

    email_input = first_visible(
        page.get_by_role("textbox", name=re.compile(r"E-?Mail", re.IGNORECASE)),
        page.locator("input[type='email']"),
        page.locator("input[name*='mail' i]"),
        page.locator("input[id*='mail' i]"),
    )
    password_input = first_visible(
        page.get_by_role("textbox", name=re.compile(r"Passwort|Password", re.IGNORECASE)),
        page.locator("input[type='password']"),
        page.locator("input[name*='pass' i]"),
        page.locator("input[id*='pass' i]"),
    )
    login_button = first_visible(
        page.get_by_role("button", name=re.compile(r"^Login$|Sign in|Anmelden", re.IGNORECASE)),
        page.locator("button:has-text('Login')"),
        page.locator("button[type='submit']"),
    )

    if not email_input or not password_input or not login_button:
        page.screenshot(path="aifitness_login_fields_missing.png", full_page=True)
        raise RuntimeError(
            "❌ Login-Felder/Button nicht gefunden. Screenshot: aifitness_login_fields_missing.png"
        )

    email_input.fill(login_email)
    password_input.fill(login_password)
    login_button.click()
    try:
        page.wait_for_url(re.compile(r"/(?!login-register)[^/]*$"), timeout=45000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_load_state("networkidle")
    dismiss_cookie_banner(page)

def open_member_course_page(page, email=None, password=None):
    # Direkter Einstieg in den Kursplan ueber die Studio-URL.
    # Falls keine gueltige Session vorliegt, leitet das Portal auf
    # .../login-register um; dort melden wir uns an und kehren zum Kursplan zurueck.
    page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    dismiss_cookie_banner(page)
    page.wait_for_timeout(400)

    if "login-register" in page.url:
        login_if_needed(page, email=email, password=password)
        # Nach dem Login sicher zuruck auf den Kursplan navigieren.
        if "course" not in page.url:
            page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            dismiss_cookie_banner(page)
    return page

def run_booking_flow(page, course_name=None, weekday=None, slot_name=None, days_ahead=None, target_date=None, email=None, password=None):
    has_visible_text_fn = globals().get("has_visible_text")
    if has_visible_text_fn is None:
        def has_visible_text_fn(local_page, pattern):
            loc = local_page.get_by_text(pattern)
            count = loc.count()
            for i in range(min(count, 40)):
                try:
                    if loc.nth(i).is_visible():
                        return True
                except Exception:
                    pass
            return False

    selected_course_name = course_name or COURSE_NAME
    # Direkter Einstieg in den Kursplan (inkl. Login bei Bedarf).
    page = open_member_course_page(page, email=email, password=password)
    page.wait_for_timeout(500)
    dismiss_cookie_banner(page)

    if "login-register" in page.url:
        login_if_needed(page, email=email, password=password)

    if "login-register" in page.url:
        page.screenshot(path="aifitness_auth_required.png", full_page=True)
        raise RuntimeError(
            "❌ Login in Schritt 2 weiterhin auf `login-register` (vermutlich Cookie/Captcha/zusätzliche Bestätigung). "
            "Bitte Screenshot prüfen und ggf. Login einmal manuell im offenen Fenster abschließen. "
            "(Screenshot: aifitness_auth_required.png)"
        )

    # Die Studio-ID steckt bereits in der URL - der Kursplan wird direkt
    # angesteuert, ein separater Studio-Auswahlschritt entfaellt.
    close_blocking_overlays(page)
    # Datum wird primär über das Datumsfeld gesteuert.
    # Priorität:
    # 1) explizit über CLI (--days-ahead)
    # 2) bei weekday: TARGET_DAYS_AHEAD (Default +6)
    # 3) sonst: heute
    target_weekday_key = None
    target_dt = None
    use_exact_date = False
    effective_days_ahead = 0

    if target_date:
        # Exaktes Datum hat Vorrang (robust gegen abweichende Systemuhr).
        try:
            target_dt = datetime.strptime(target_date.strip(), "%d.%m.%Y")
            target_date_str = target_dt.strftime("%d.%m.%Y")
            target_weekday_key = WEEKDAY_BY_INDEX.get(target_dt.weekday())
            use_exact_date = True
        except Exception:
            raise RuntimeError(f"❌ Ungültiges --date Format: '{target_date}'. Erwartet TT.MM.JJJJ.")
    else:
        if days_ahead is not None:
            effective_days_ahead = max(0, int(days_ahead))
        else:
            effective_days_ahead = TARGET_DAYS_AHEAD if weekday else 0
        try:
            from datetime import timedelta
            target_dt = datetime.now(ZoneInfo(TIMEZONE_ID)) + timedelta(days=effective_days_ahead)
            target_weekday_key = WEEKDAY_BY_INDEX.get(target_dt.weekday())
            target_date_str = target_dt.strftime("%d.%m.%Y")
        except Exception:
            target_date_str = "unbekannt"

    effective_weekday = weekday or target_weekday_key
    print(f"🎯 Zieldatum: {target_date_str}" + ("" if use_exact_date else f" (days_ahead={effective_days_ahead})"))
    if effective_weekday:
        print(f"🎯 Ziel-Wochentag: {effective_weekday}")
    ensure_kurse_page(page)
    if use_exact_date:
        set_exact_kurse_date(page, target_date_str)
    else:
        reset_kurse_date(page, days_ahead=effective_days_ahead)
    ensure_kurse_page(page)
    if effective_weekday:
        maybe_go_to_next_week_for_weekday(page, effective_weekday)
    # Bei expliziter Datumssteuerung nie zusätzlich per "nächste Woche" springen.
    allow_week_jump = days_ahead is None and not use_exact_date

    # 2) Wenn expliziter Slot-Name gesetzt ist: Wochentag fokussieren und dann den Slot klicken.
    course_btn = None
    if slot_name:
        if effective_weekday:
            try:
                focus_weekday(page, effective_weekday)
            except RuntimeError:
                # In manchen Layouts ist der Tageskopf nicht klickbar.
                # Der eigentliche Tagesfilter erfolgt dann über die Spalten-Grenzen im Slot-Klick.
                pass
            page.wait_for_timeout(300)
        if click_course_slot_by_name(page, slot_name, weekday=effective_weekday):
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(400)
            course_btn = True
        elif allow_week_jump and (not effective_weekday) and go_to_next_week(page) and click_course_slot_by_name(page, slot_name, weekday=effective_weekday):
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(400)
            course_btn = True

    # 3) Wenn kein expliziter Slot-Name gesetzt ist und kein Wochentag vorgegeben ist:
    # direkter Klick auf Kurs in der aktuellen/folgenden Woche.
    if course_btn is None and not effective_weekday and not slot_name and days_ahead is None:
        direct_course = page.get_by_role(
            "button",
            name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
        ).first
        try:
            if direct_course.is_visible():
                safe_click(direct_course, label="CourseDirect")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(500)
                course_btn = direct_course
        except Exception:
            course_btn = None
        if course_btn is None and allow_week_jump and go_to_next_week(page):
            direct_course = page.get_by_role(
                "button",
                name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
            ).first
            try:
                if direct_course.is_visible():
                    safe_click(direct_course, label="CourseDirectNextWeek")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(500)
                    course_btn = direct_course
            except Exception:
                course_btn = None

    # 4) Falls direkte Kurskarte nicht sichtbar: über "Kurse" navigieren
    def ensure_nav_open():
        kurse_link = page.get_by_role("link", name=re.compile(r"^Kurse$", re.IGNORECASE))
        kurse_btn = page.get_by_role("button", name=re.compile(r"^Kurse$", re.IGNORECASE))

        if (kurse_link.count() and kurse_link.first.is_visible()) or (kurse_btn.count() and kurse_btn.first.is_visible()):
            return

        # typische Menu-Buttons (DE/EN)
        candidates = [
            page.get_by_role("button", name=re.compile(r"menü|menu|navigation", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"open|öffnen", re.IGNORECASE)),
            page.locator("button[aria-label*='Menu'], button[aria-label*='Menü'], button[aria-label*='menu']"),
        ]

        for c in candidates:
            try:
                if c.count() and c.first.is_visible():
                    c.first.click(timeout=2000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                pass

    if course_btn is None:
        ensure_nav_open()

        kurse_candidates = [
            page.get_by_role("link", name=re.compile(r"^Kurse$", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"^Kurse$", re.IGNORECASE)),
            page.get_by_text(re.compile(r"^Kurse$", re.IGNORECASE)),
            page.get_by_role("link", name=re.compile(r"Kursplan|Classes|Class", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"Kursplan|Classes|Class", re.IGNORECASE)),
            page.locator("a[href*='kurs'],a[href*='class'],button:has-text('Kurse')"),
        ]

        clicked = False
        for loc in kurse_candidates:
            try:
                if loc.count() and loc.first.is_visible():
                    safe_click(loc.first, label="Kurse")
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            # Einmaliger Retry nach Reload
            page.reload(wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            dismiss_cookie_banner(page)
            for loc in kurse_candidates:
                try:
                    if loc.count() and loc.first.is_visible():
                        safe_click(loc.first, label="KurseRetry")
                        clicked = True
                        break
                except Exception:
                    pass

        if not clicked:
            page.screenshot(path="aifitness_error.png", full_page=True)
            raise RuntimeError(
                "❌ 'Kurse' nicht gefunden/unsichtbar. "
                f"Screenshot: aifitness_error.png | URL: {page.url}"
            )

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        stabilize_kurse_view(page)
        page.wait_for_timeout(400)

        close_blocking_overlays(page)
        if slot_name and click_course_slot_by_name(page, slot_name, weekday=effective_weekday):
            course_btn = True
        elif slot_name and allow_week_jump and (not effective_weekday) and go_to_next_week(page) and click_course_slot_by_name(page, slot_name, weekday=effective_weekday):
            course_btn = True
        else:
            try:
                if effective_weekday:
                    focus_weekday(page, effective_weekday)
            except RuntimeError:
                # Fallback: ohne klickbaren Tageskopf weiter, die Spaltenlogik entscheidet später.
                pass
            page.wait_for_timeout(300)

        # Wenn ein expliziter Slot-Name gesetzt ist, hier nicht auf Kursnamen zurückfallen.
        if course_btn is None and slot_name:
            page.screenshot(path="aifitness_slot_not_found.png", full_page=True)
            raise RuntimeError(
                f"❌ Slot nicht gefunden: '{slot_name}' am Zieldatum {target_date_str}. "
                "Screenshot: aifitness_slot_not_found.png"
            )

        # Wenn Wochentag gesetzt ist, versuche zuerst Kombination aus Tag+Kurs im Label.
        if course_btn is None and effective_weekday:
            day_key = normalize_weekday(effective_weekday)
            day_labels = WEEKDAY_UI_LABELS.get(day_key, [])
            day_pattern = "|".join(re.escape(x) for x in day_labels)
            combined = page.get_by_role(
                "button",
                name=re.compile(rf"({day_pattern}).*{re.escape(selected_course_name)}|{re.escape(selected_course_name)}.*({day_pattern})", re.IGNORECASE),
            )
            if click_first_visible(combined, label="CourseByWeekday"):
                course_btn = combined.first
            elif click_course_in_weekday_column(page, selected_course_name, effective_weekday):
                course_btn = page.get_by_role(
                    "button",
                    name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
                ).first
            else:
                # Fallback: alle Kandidaten testen und nur das Zieldatum akzeptieren.
                target_date_regexes = []
                if target_date_str and target_date_str != "unbekannt":
                    try:
                        day = target_dt.day
                        month = target_dt.month
                        year = target_dt.year
                        # Numeric de/en variants: 18.03.2026 / 18/03/2026 / 03/18/2026 / 3/18/2026
                        target_date_regexes.extend(
                            [
                                re.compile(rf"\b0?{day}[./-]0?{month}[./-]{year}\b", re.IGNORECASE),
                                re.compile(rf"\b0?{month}[./-]0?{day}[./-]{year}\b", re.IGNORECASE),
                            ]
                        )
                        # Long month variants (EN/DE), e.g. March 18, 2026 / 18. März 2026
                        month_names = [
                            target_dt.strftime("%B"),   # locale dependent, often EN
                            target_dt.strftime("%b"),
                        ]
                        de_months = {
                            1: ["Januar", "Jan"],
                            2: ["Februar", "Feb"],
                            3: ["März", "Maerz", "Mär", "Mrz"],
                            4: ["April", "Apr"],
                            5: ["Mai"],
                            6: ["Juni", "Jun"],
                            7: ["Juli", "Jul"],
                            8: ["August", "Aug"],
                            9: ["September", "Sep"],
                            10: ["Oktober", "Okt"],
                            11: ["November", "Nov"],
                            12: ["Dezember", "Dez"],
                        }
                        month_names.extend(de_months.get(month, []))
                        for mname in set(month_names):
                            if not mname:
                                continue
                            m = re.escape(mname)
                            target_date_regexes.append(re.compile(rf"\b{m}\s+0?{day},?\s+{year}\b", re.IGNORECASE))
                            target_date_regexes.append(re.compile(rf"\b0?{day}\.?\s+{m}\s+{year}\b", re.IGNORECASE))
                    except Exception:
                        target_date_regexes = [re.compile(re.escape(target_date_str), re.IGNORECASE)]

                def back_to_kurse_grid():
                    # In der Buchungsansicht zurück in die Grid-Ansicht.
                    if click_any_visible(
                        page,
                        [re.compile(r"^Zur[üu]ck$|^Back$", re.IGNORECASE)],
                        label="BackToGrid",
                    ):
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(300)
                        wait_until_not_busy(page, timeout_ms=8000)
                        stabilize_kurse_view(page)
                        close_blocking_overlays(page)
                        ensure_kurse_page(page)
                        return True
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(250)
                    except Exception:
                        pass
                    if not is_kurse_view(page):
                        try:
                            ensure_kurse_page(page)
                        except Exception:
                            return False
                    return is_kurse_view(page)

                # Scroll nach unten: Kurse können lazy geladen / außerhalb des Viewports sein.
                try:
                    page.evaluate("window.scrollBy(0, 400)")
                    page.wait_for_timeout(600)
                except Exception:
                    pass

                candidates = page.get_by_role(
                    "button",
                    name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE),
                )
                # Wenn das Grid leer wirkt: bis zu 3×1,5s warten (Seite lädt ggf. noch nach).
                for _wait_retry in range(3):
                    if candidates.count() > 0:
                        break
                    page.wait_for_timeout(1500)

                for i in range(min(candidates.count(), 40)):
                    item = candidates.nth(i)
                    try:
                        if not item.is_visible():
                            continue
                        safe_click(item, label="CourseByDateFallback")
                        page.wait_for_timeout(350)
                        if not wait_for_booking_actions(page, timeout_ms=12000):
                            back_to_kurse_grid()
                            continue
                        if target_date_regexes and not any(has_visible_text_fn(page, rx) for rx in target_date_regexes):
                            # Falscher Termin (anderer Tag) -> zurück und nächsten Kandidaten testen.
                            back_to_kurse_grid()
                            continue
                        course_btn = item
                        break
                    except Exception:
                        back_to_kurse_grid()
                        continue

                if course_btn is None:
                    candidate_count = candidates.count()
                    page.screenshot(path="aifitness_weekday_course_mismatch.png", full_page=True)
                    if candidate_count == 0:
                        raise RuntimeError(
                            f"❌ Kursgitter leer: Kurs '{selected_course_name}' für Zieldatum {target_date_str} "
                            "nicht gefunden. Schedule noch nicht veröffentlicht oder Filter aktiv? "
                            "Screenshot: aifitness_weekday_course_mismatch.png"
                        )
                    raise RuntimeError(
                        f"❌ Kurs '{selected_course_name}' am Wochentag '{effective_weekday}' "
                        f"(Zieldatum {target_date_str}) nicht eindeutig gefunden "
                        f"({candidate_count} Kandidat(en) geprüft, keiner am richtigen Datum). "
                        "Screenshot: aifitness_weekday_course_mismatch.png"
                    )
        elif course_btn is None:
            course_btn = page.get_by_role(
                "button",
                name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
            ).first
            try:
                safe_click(course_btn, label="Course")
            except Exception:
                if not allow_week_jump or not go_to_next_week(page):
                    raise
                course_btn = page.get_by_role(
                    "button",
                    name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
                ).first
                safe_click(course_btn, label="CourseNextWeek")

    if not is_kurse_view(page) and not is_booking_options_view(page):
        if is_kurse_loading_view(page):
            wait_until_not_busy(page, timeout_ms=20000)
            stabilize_kurse_view(page)

    if not is_kurse_view(page) and not is_booking_options_view(page):
        page.screenshot(path="aifitness_not_in_kurse_view.png", full_page=True)
        raise RuntimeError(
            "❌ Weder Kursansicht noch Buchungsoptionen aktiv. "
            "Screenshot: aifitness_not_in_kurse_view.png"
        )

    # Schutz: falscher Flow (Probetraining) statt Kursbuchung.
    # WICHTIG: Nicht auf das bloße Wort "Probetraining" prüfen, da es oft nur ein Menüpunkt ist.
    is_probetraining_flow = (
        has_visible_text_fn(page, re.compile(r"Which date would you like to choose\?", re.IGNORECASE))
        or has_visible_text_fn(page, re.compile(r"Welches Datum m[oö]chtest du ausw[aä]hlen\?", re.IGNORECASE))
    )
    if is_probetraining_flow:
        page.screenshot(path="aifitness_wrong_flow_probetraining.png", full_page=True)
        raise RuntimeError(
            "❌ Falscher Flow erkannt (Probetraining statt Kursbuchung). "
            "Screenshot: aifitness_wrong_flow_probetraining.png"
        )

    close_blocking_overlays(page)

    if is_booking_success_view(page, weekday=weekday):
        label = slot_name or selected_course_name
        weekday_info = f" ({weekday})" if weekday else ""
        print(f"✅ Buchung bestätigt: {label}{weekday_info}")
        return

    # Warten, bis der Buchungsdialog/die Aktions-Buttons wirklich da sind.
    if not wait_for_booking_actions(page, timeout_ms=20000):
        # Retry: Kursdialog ist manchmal nicht aufgegangen, obwohl Kursansicht sichtbar ist.
        close_blocking_overlays(page)
        wait_until_not_busy(page, timeout_ms=8000)
        stabilize_kurse_view(page)

        retried_click = False
        if weekday:
            if click_course_in_weekday_column(page, selected_course_name, weekday):
                retried_click = True
        if not retried_click:
            retry_course = page.get_by_role(
                "button",
                name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
            )
            if click_first_visible(retry_course, label="CourseRetryDialog"):
                retried_click = True

        if retried_click:
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(500)

        if wait_for_booking_actions(page, timeout_ms=25000):
            pass
        else:
            if is_booking_success_view(page, weekday=weekday):
                label = slot_name or selected_course_name
                weekday_info = f" ({weekday})" if weekday else ""
                print(f"✅ Buchung bestätigt: {label}{weekday_info}")
                return
            page.screenshot(path="aifitness_booking_actions_timeout.png", full_page=True)
            raise RuntimeError(
                "❌ Buchungsdialog nicht rechtzeitig geladen. "
                "Screenshot: aifitness_booking_actions_timeout.png"
            )

    # 5) Kostenfrei/Weiter/Jetzt buchen
    free_btn = page.get_by_role("button", name=re.compile(r"Kostenfrei|Free", re.IGNORECASE))
    if free_btn.count():
        safe_click(free_btn.first, label="Kostenfrei")

        # Gemäß aufgezeichnetem Flow: "Übernehmen" zwischen zwei "Kostenfrei"-Schritten.
        confirm_btn = page.get_by_role("button", name=re.compile(r"Übernehmen|Apply|Confirm", re.IGNORECASE))
        try:
            if confirm_btn.count() and confirm_btn.first.is_visible():
                safe_click(confirm_btn.first, label="Übernehmen")
        except Exception:
            pass

        try:
            if free_btn.count() and free_btn.first.is_visible():
                free_btn.first.click(timeout=1500)
        except Exception:
            pass

    # Recording-Flow für Slot-Buchung: zuerst "Weiter", dann "Jetzt buchen".
    if slot_name:
        click_any_visible(
            page,
            [re.compile(r"^Weiter$|Next", re.IGNORECASE)],
            label="WeiterRecorded",
        )
        page.wait_for_timeout(200)

    # "Weiter" ist nicht in jedem Dialogschritt vorhanden.
    click_any_visible(
        page,
        [re.compile(r"Weiter|Next", re.IGNORECASE)],
        label="WeiterOptional",
    )

    booked = click_any_visible(
        page,
        [
            re.compile(r"Jetzt buchen|Book now", re.IGNORECASE),
            re.compile(r"^Buchen$|^Book$", re.IGNORECASE),
        ],
        label="JetztBuchen",
    )
    if not booked:
        waitlisted = click_any_visible(
            page,
            [
                re.compile(r"Warteliste|Waitlist", re.IGNORECASE),
                re.compile(r"Auf Warteliste|Join waitlist", re.IGNORECASE),
            ],
            label="Warteliste",
        )
        if waitlisted:
            weekday_info = f" ({weekday})" if weekday else ""
            print(f"✅ Kurs auf Warteliste gesetzt: {selected_course_name}{weekday_info}")
            return
        in_booking_dialog = (
            has_visible_text_fn(page, re.compile(r"Buchungsoptionen|Booking options", re.IGNORECASE))
            or has_visible_text_fn(page, re.compile(r"Zusammenfassung|Summary", re.IGNORECASE))
            or has_visible_text_fn(page, re.compile(r"F[üu]r die Buchung wird kein Guthaben ben[öo]tigt|No credit is required", re.IGNORECASE))
        )
        already_booked = has_visible_text_fn(page, re.compile(r"\bGebucht\b|\bBooked\b", re.IGNORECASE))
        if in_booking_dialog and already_booked:
            label = slot_name or selected_course_name
            weekday_info = f" ({weekday})" if weekday else ""
            print(f"✅ Kurs bereits gebucht: {label}{weekday_info}")
            return
        sold_out = has_visible_text_fn(page, re.compile(r"Ausgebucht|Fully booked", re.IGNORECASE))
        if in_booking_dialog and sold_out:
            page.screenshot(path="aifitness_booking_sold_out.png", full_page=True)
            raise RuntimeError(
                "❌ Kurs ist ausgebucht und kein Wartelisten-Button verfügbar. "
                "Screenshot: aifitness_booking_sold_out.png"
            )
        if not in_booking_dialog:
            page.screenshot(path="aifitness_booking_dialog_missing.png", full_page=True)
            raise RuntimeError(
                "❌ Nicht im Buchungsdialog gelandet (keine Buchungsoptionen/Zusammenfassung erkannt). "
                "Screenshot: aifitness_booking_dialog_missing.png"
            )
        page.screenshot(path="aifitness_booking_submit_missing.png", full_page=True)
        raise RuntimeError(
            "❌ Abschluss-Button nicht gefunden (Jetzt buchen/Buchen). "
            "Screenshot: aifitness_booking_submit_missing.png"
        )

    # Nach Abschluss-Klick nur mit echter Bestätigung als Erfolg werten.
    page.wait_for_timeout(1800)
    if is_booking_success_view(page, weekday=weekday):
        label = slot_name or selected_course_name
        weekday_info = f" ({weekday})" if weekday else ""
        print(f"✅ Buchung bestätigt: {label}{weekday_info}")
        return

    # Buchungsfenster noch nicht offen: Portal nennt den frühesten Buchungszeitpunkt.
    too_early = has_visible_text_fn(
        page,
        re.compile(r"kannst diesen Kurs fr[üu]hestens am .* buchen", re.IGNORECASE),
    ) or has_visible_text_fn(
        page,
        re.compile(r"can only book this .* from|earliest.*book", re.IGNORECASE),
    )
    if too_early:
        page.screenshot(path="aifitness_booking_too_early.png", full_page=True)
        raise RuntimeError(
            "⏳ Buchungsfenster noch nicht geöffnet. Das Portal gibt diesen Kurs erst zu "
            "einem späteren Zeitpunkt frei (siehe Meldung auf der Seite, i. d. R. 6 Tage "
            "vorher auf die Minute). Bot zum Freischaltzeitpunkt erneut ausführen. "
            "Screenshot: aifitness_booking_too_early.png"
        )

    page.screenshot(path="aifitness_booking_unconfirmed.png", full_page=True)
    raise RuntimeError(
        "❌ Abschluss geklickt, aber keine Buchungsbestätigung erkannt. "
        "Screenshot: aifitness_booking_unconfirmed.png"
    )

    page.wait_for_timeout(1500)
    label = slot_name or selected_course_name
    weekday_info = f" ({weekday})" if weekday else ""
    print(f"✅ Buchung-Flow durchgelaufen: {label}{weekday_info}")

def main():
    if not PROFILE_DIR.exists():
        raise SystemExit("❌ Browser-Profil fehlt. Erst: python save_session.py")

    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=HEADLESS,
            locale=LOCALE,
            timezone_id=TIMEZONE_ID,
        )
        if HEADLESS:
            launch_kwargs["viewport"] = {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
        else:
            launch_kwargs["no_viewport"] = True
            launch_kwargs["args"] = [
                "--start-maximized",
                f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
            ]

        context = p.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()

        try:
            run_booking_flow(page)
        except Exception:
            try:
                page.screenshot(path="aifitness_error.png", full_page=True)
                print("📸 Screenshot gespeichert: aifitness_error.png", file=sys.stderr)
                print("Aktuelle URL:", page.url, file=sys.stderr)
            except Exception:
                pass
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
