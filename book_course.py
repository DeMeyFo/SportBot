import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

STATE_FILE = Path("mysports_state.json")
PROFILE_DIR = Path(".mysports_profile")
BUSINESS_URL = "https://www.mysports.com/business/de"
LOGIN_URL = "https://www.mysports.com/login-register?utm_source=google&utm_medium=organic"
HOME_URL = "https://www.mysports.com/"

GYM_NAME = os.getenv("MYSPORTS_GYM", "EASYFITNESS Verden")
COURSE_NAME = os.getenv("MYSPORTS_COURSE", "Kraft-Ausdauer Training")
EMAIL = os.getenv("MYSPORTS_EMAIL")
PASSWORD = os.getenv("MYSPORTS_PASSWORD")
VIEWPORT_WIDTH = int(os.getenv("MYSPORTS_VIEWPORT_WIDTH", "1920"))
VIEWPORT_HEIGHT = int(os.getenv("MYSPORTS_VIEWPORT_HEIGHT", "1080"))
HEADLESS = os.getenv("MYSPORTS_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"}

DAY_ALIASES = {
    "mon": ["montag", "monday", "mo"],
    "tue": ["dienstag", "tuesday", "di", "tu"],
    "wed": ["mittwoch", "wednesday", "mi", "we"],
    "thu": ["donnerstag", "thursday", "do", "th"],
    "fri": ["freitag", "friday", "fr", "fri"],
    "sat": ["samstag", "saturday", "sa", "sat"],
    "sun": ["sonntag", "sunday", "so", "sun"],
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

def stabilize_kurse_view(page):
    # In manchen Sessions bleibt die Tabelle im Ladespinner hängen.
    # Dann den Filter/Datum-Combobox-Zustand bereinigen.
    comboboxes = page.locator("input[role='combobox'], input[id*='mui' i]")
    if comboboxes.count():
        box = comboboxes.first
        try:
            if box.is_visible():
                is_invalid = (box.get_attribute("aria-invalid") or "").lower() == "true"
                # Filter leeren
                box.fill("")
                box.press("Enter")
                page.wait_for_timeout(300)

                # Bei invalidem Datum explizit auf heute setzen (dd.mm.yyyy)
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
    # Auf dem VPS sehen wir z. B. "Classes" + "Filters (1)" in Englisch.
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
    return has_filter or (has_date_row and has_date_input) or (has_classes_nav and has_date_row)

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

    page.screenshot(path="mysports_kurse_view_missing.png", full_page=True)
    raise RuntimeError(
        "❌ Kursansicht konnte nicht geöffnet werden. Screenshot: mysports_kurse_view_missing.png"
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

def focus_weekday(page, weekday):
    key = normalize_weekday(weekday)
    if not key:
        return
    day_words = DAY_ALIASES[key]
    pattern = re.compile("|".join(re.escape(x) for x in day_words), re.IGNORECASE)
    selectors = [
        page.get_by_role("tab", name=pattern),
        page.get_by_role("button", name=pattern),
        page.get_by_role("link", name=pattern),
        page.get_by_text(pattern),
    ]
    for loc in selectors:
        if click_first_visible(loc, label=f"Weekday:{weekday}"):
            page.wait_for_timeout(400)
            return
    page.screenshot(path="mysports_weekday_not_found.png", full_page=True)
    raise RuntimeError(
        f"❌ Gewünschter Wochentag '{weekday}' nicht auswählbar. "
        "Screenshot: mysports_weekday_not_found.png"
    )

def get_weekday_column_bounds(page, weekday):
    key = normalize_weekday(weekday)
    if not key:
        return None
    day_words = DAY_ALIASES[key]
    pattern = re.compile("|".join(re.escape(x) for x in day_words), re.IGNORECASE)
    candidates = [
        page.get_by_role("tab", name=pattern),
        page.get_by_role("button", name=pattern),
        page.get_by_text(pattern),
    ]
    for loc in candidates:
        count = loc.count()
        for i in range(min(count, 25)):
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box:
                    continue
                # Kopfzeile befindet sich oben.
                if box["y"] < 220 and box["width"] > 40:
                    return (box["x"], box["x"] + box["width"])
            except Exception:
                pass
    return None

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

def click_course_slot_by_name(page, slot_name):
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

    def try_click(locator, label, require_actions=False):
        count = locator.count()
        for i in range(min(count, 40)):
            item = locator.nth(i)
            try:
                if not item.is_visible():
                    continue
                raw_label = item.get_attribute("aria-label") or item.inner_text() or ""
                normalized_label = raw_label.lower()
                # Trial/Probetraining-Kacheln nie als Kurs-Slot interpretieren.
                if "probetraining" in normalized_label or "trial" in normalized_label:
                    continue
                safe_click(item, label=label)
                page.wait_for_timeout(250)
                if has_booking_actions() or wait_for_booking_actions(page, timeout_ms=5000):
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
    if try_click(page.get_by_role("button", name=pattern), label="CourseSlotName", require_actions=False):
        return True

    # 2) Textsuche in Slot-Containern
    text_slots = page.locator("[role='button']").filter(has_text=re.compile(rf"{re.escape(slot_name)}", re.IGNORECASE))
    if try_click(text_slots, label="CourseSlotText", require_actions=False):
        return True

    # 3) Fuzzy-Fallback: toleriert Namensabweichungen (Interpunktion, Leerzeichen, Groß/Kleinschreibung).
    def norm_text(value):
        text = unicodedata.normalize("NFKD", value or "")
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        text = re.sub(r"[^a-z0-9: ]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    wanted = norm_text(slot_name)
    if not wanted:
        return False

    wanted_parts = [p.strip() for p in wanted.split(",") if p.strip()]
    wanted_tokens = [t for t in wanted.split(" ") if t]
    wanted_times = re.findall(r"\b\d{1,2}:\d{2}\b", wanted)

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

            # Score-basierter Treffer: Tokens + Zeiten.
            tokens_hit = sum(1 for token in wanted_tokens if token in normalized)
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

def login_if_needed(page, email=None, password=None):
    dismiss_cookie_banner(page)
    if "login-register" not in page.url:
        return
    login_email = email or EMAIL
    login_password = password or PASSWORD
    if not login_email or not login_password:
        raise RuntimeError("❌ Login-Credentials fehlen. Setze MYSPORTS_EMAIL/MYSPORTS_PASSWORD oder übergebe --email/--password.")
    page.get_by_role("textbox", name=re.compile(r"E-Mail", re.IGNORECASE)).fill(login_email)
    page.get_by_role("textbox", name=re.compile(r"Passwort", re.IGNORECASE)).fill(login_password)
    page.get_by_role("button", name=re.compile(r"^Login$", re.IGNORECASE)).click()
    try:
        page.wait_for_url(re.compile(r"mysports\\.com/(?!login-register)"), timeout=45000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_load_state("networkidle")
    dismiss_cookie_banner(page)

def open_member_page_from_business(page):
    page.goto(BUSINESS_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    dismiss_cookie_banner(page)

    login_btn = page.get_by_role("button", name=re.compile(r"^login$|log in|sign in", re.IGNORECASE))
    if not (login_btn.count() and login_btn.first.is_visible()):
        return page

    popup_page = None
    try:
        with page.expect_popup(timeout=5000) as popup_info:
            login_btn.first.click(timeout=3000)
        popup_page = popup_info.value
        popup_page.wait_for_load_state("domcontentloaded")
        popup_page.wait_for_load_state("networkidle")
        dismiss_cookie_banner(popup_page)
        return popup_page
    except Exception:
        return page

def ensure_member_area(page):
    # Wenn wir auf der Marketing-/Business-Seite landen, zuerst Login öffnen.
    if not re.search(r"/business/", page.url, re.IGNORECASE):
        return

    login_candidates = [
        page.get_by_role("button", name=re.compile(r"^login$|log in|sign in", re.IGNORECASE)),
        page.get_by_role("link", name=re.compile(r"^login$|log in|sign in", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"los geht|jetzt loslegen|member", re.IGNORECASE)),
        page.get_by_role("link", name=re.compile(r"los geht|jetzt loslegen|member", re.IGNORECASE)),
    ]
    for loc in login_candidates:
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=4000)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(700)
                break
        except Exception:
            pass

def run_booking_flow(page, course_name=None, weekday=None, slot_name=None, email=None, password=None):
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
    page = open_member_page_from_business(page)
    page.wait_for_timeout(500)
    ensure_member_area(page)
    dismiss_cookie_banner(page)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    if re.search(r"/business/", page.url, re.IGNORECASE):
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        dismiss_cookie_banner(page)
        login_if_needed(page, email=email, password=password)

    if "login-register" in page.url:
        login_if_needed(page, email=email, password=password)

    if "login-register" in page.url:
        page.screenshot(path="mysports_auth_required.png", full_page=True)
        raise RuntimeError(
            "❌ Login in Schritt 2 weiterhin auf `login-register` (vermutlich Cookie/Captcha/zusätzliche Bestätigung). "
            "Bitte Screenshot prüfen und ggf. Login einmal manuell im offenen Fenster abschließen. "
            "(Screenshot: mysports_auth_required.png)"
        )

    # 1) Studio auswählen (wenn Auswahl angezeigt wird)
    gym = page.get_by_text(GYM_NAME)
    try:
        gym.wait_for(state="visible", timeout=8000)
        gym.first.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(800)
    except Exception:
        pass  # schon ausgewählt oder keine Auswahlseite

    open_kurse_view_recorded(page, email=email)
    close_blocking_overlays(page)

    # 2) Wenn expliziter Slot-Name gesetzt ist: direkt diesen Tabellenslot klicken.
    course_btn = None
    if slot_name:
        if click_course_slot_by_name(page, slot_name):
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(400)
            course_btn = True
        elif go_to_next_week(page) and click_course_slot_by_name(page, slot_name):
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(400)
            course_btn = True

    # 3) Wenn kein expliziter Slot-Name gesetzt ist und kein Wochentag vorgegeben ist:
    # direkter Klick auf Kurs in der aktuellen/folgenden Woche.
    if course_btn is None and not weekday and not slot_name:
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
        if course_btn is None and go_to_next_week(page):
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
            page.screenshot(path="mysports_error.png", full_page=True)
            raise RuntimeError(
                "❌ 'Kurse' nicht gefunden/unsichtbar. "
                f"Screenshot: mysports_error.png | URL: {page.url}"
            )

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        stabilize_kurse_view(page)
        page.wait_for_timeout(400)

        close_blocking_overlays(page)
        if slot_name and click_course_slot_by_name(page, slot_name):
            course_btn = True
        elif slot_name and go_to_next_week(page) and click_course_slot_by_name(page, slot_name):
            course_btn = True
        else:
            focus_weekday(page, weekday)
            page.wait_for_timeout(300)

        # Wenn ein expliziter Slot-Name gesetzt ist, hier nicht auf Kursnamen zurückfallen.
        if course_btn is None and slot_name:
            page.screenshot(path="mysports_slot_not_found.png", full_page=True)
            raise RuntimeError(
                f"❌ Slot nicht gefunden: '{slot_name}'. Screenshot: mysports_slot_not_found.png"
            )

        # Wenn Wochentag gesetzt ist, versuche zuerst Kombination aus Tag+Kurs im Label.
        if course_btn is None and weekday:
            day_pattern = "|".join(re.escape(x) for x in DAY_ALIASES[normalize_weekday(weekday)])
            combined = page.get_by_role(
                "button",
                name=re.compile(rf"({day_pattern}).*{re.escape(selected_course_name)}|{re.escape(selected_course_name)}.*({day_pattern})", re.IGNORECASE),
            )
            if click_first_visible(combined, label="CourseByWeekday"):
                course_btn = combined.first
            elif click_course_in_weekday_column(page, selected_course_name, weekday):
                course_btn = page.get_by_role(
                    "button",
                    name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
                ).first
            else:
                course_btn = page.get_by_role(
                    "button",
                    name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
                ).first
                try:
                    safe_click(course_btn, label="Course")
                except Exception:
                    if not go_to_next_week(page):
                        raise
                    course_btn = page.get_by_role(
                        "button",
                        name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
                    ).first
                    safe_click(course_btn, label="CourseNextWeek")
        elif course_btn is None:
            course_btn = page.get_by_role(
                "button",
                name=re.compile(rf"{re.escape(selected_course_name)}", re.IGNORECASE)
            ).first
            try:
                safe_click(course_btn, label="Course")
            except Exception:
                if not go_to_next_week(page):
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
        page.screenshot(path="mysports_not_in_kurse_view.png", full_page=True)
        raise RuntimeError(
            "❌ Weder Kursansicht noch Buchungsoptionen aktiv. "
            "Screenshot: mysports_not_in_kurse_view.png"
        )

    # Schutz: falscher Flow (Probetraining) statt Kursbuchung.
    # WICHTIG: Nicht auf das bloße Wort "Probetraining" prüfen, da es oft nur ein Menüpunkt ist.
    is_probetraining_flow = (
        has_visible_text_fn(page, re.compile(r"Which date would you like to choose\?", re.IGNORECASE))
        or has_visible_text_fn(page, re.compile(r"Welches Datum m[oö]chtest du ausw[aä]hlen\?", re.IGNORECASE))
    )
    if is_probetraining_flow:
        page.screenshot(path="mysports_wrong_flow_probetraining.png", full_page=True)
        raise RuntimeError(
            "❌ Falscher Flow erkannt (Probetraining statt Kursbuchung). "
            "Screenshot: mysports_wrong_flow_probetraining.png"
        )

    close_blocking_overlays(page)

    # Warten, bis der Buchungsdialog/die Aktions-Buttons wirklich da sind.
    if not wait_for_booking_actions(page, timeout_ms=20000):
        page.screenshot(path="mysports_booking_actions_timeout.png", full_page=True)
        raise RuntimeError(
            "❌ Buchungsdialog nicht rechtzeitig geladen. "
            "Screenshot: mysports_booking_actions_timeout.png"
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
        page.screenshot(path="mysports_booking_submit_missing.png", full_page=True)
        raise RuntimeError(
            "❌ Abschluss-Button nicht gefunden (Jetzt buchen/Buchen). "
            "Screenshot: mysports_booking_submit_missing.png"
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
                page.screenshot(path="mysports_error.png", full_page=True)
                print("📸 Screenshot gespeichert: mysports_error.png", file=sys.stderr)
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
