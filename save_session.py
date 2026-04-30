import os
import re
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

LOGIN_URL = "https://www.mysports.com/login-register?utm_source=google&utm_medium=organic"
HOME_URL = "https://www.mysports.com/"
STATE_FILE = Path("mysports_state.json")
PROFILE_DIR = Path(".mysports_profile")

def _profile_dir_for_email(email: str) -> Path:
    local = email.strip().lower().split("@")[0]
    safe = re.sub(r"[^a-z0-9]", "_", local)
    return Path(f".mysports_profile_{safe}")

def _state_file_for_email(email: str) -> Path:
    local = email.strip().lower().split("@")[0]
    safe = re.sub(r"[^a-z0-9]", "_", local)
    return Path(f"mysports_state_{safe}.json")

VIEWPORT_WIDTH = int(os.getenv("MYSPORTS_VIEWPORT_WIDTH", "1920"))
VIEWPORT_HEIGHT = int(os.getenv("MYSPORTS_VIEWPORT_HEIGHT", "1080"))
HEADLESS = os.getenv("MYSPORTS_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"}
LOCALE = os.getenv("MYSPORTS_LOCALE", "de-DE")
TIMEZONE_ID = os.getenv("MYSPORTS_TIMEZONE", "Europe/Berlin")

EMAIL = os.getenv("MYSPORTS_EMAIL")
PASSWORD = os.getenv("MYSPORTS_PASSWORD")


def first_visible(*locators):
    for loc in locators:
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            pass
    return None

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

def login_and_validate(page, email=None, password=None):
    login_email = email or EMAIL
    login_password = password or PASSWORD

    if not login_email or not login_password:
        raise RuntimeError("❌ Login-Credentials fehlen. Setze MYSPORTS_EMAIL/MYSPORTS_PASSWORD oder übergebe --email/--password.")

    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(500)
    dismiss_cookie_banner(page)

    if "login-register" in page.url:
        # SPA rendert Login-Felder asynchron — warten bis Email-Input sichtbar ist.
        try:
            page.wait_for_selector(
                "input[type='email'], input[name*='mail' i], input[id*='mail' i]",
                timeout=12000,
            )
        except PlaywrightTimeoutError:
            pass

        # Login (Fallback-Selektoren für Headless/Layout-Varianten)
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
            page.screenshot(path="mysports_login_fields_missing.png", full_page=True)
            raise RuntimeError(
                "❌ Login-Felder/Button nicht gefunden. Screenshot: mysports_login_fields_missing.png"
            )

        email_input.fill(login_email)
        password_input.fill(login_password)
        login_button.click()

    # Login abschliessen lassen (inkl. eventueller Redirects/Captcha)
    try:
        page.wait_for_url(re.compile(r"mysports\.com/(?!login-register)"), timeout=60000)
    except PlaywrightTimeoutError:
        pass

    page.wait_for_load_state("networkidle")
    dismiss_cookie_banner(page)
    page.wait_for_timeout(800)

    # Falls weiterhin Login-Seite, Login war nicht erfolgreich
    if "login-register" in page.url:
        page.screenshot(path="mysports_login_failed.png", full_page=True)
        raise RuntimeError(
            "❌ Login nicht abgeschlossen. Bitte Login/Captcha im Browser fertigstellen und erneut ausführen. "
            "Screenshot: mysports_login_failed.png"
        )

    # Verifizieren, dass Session auf Home weiterhin gültig ist
    page.goto(HOME_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    if "login-register" in page.url:
        page.screenshot(path="mysports_login_invalid.png", full_page=True)
        raise RuntimeError(
            "❌ Session ist nicht gültig (zur Login-Seite zurückgeleitet). "
            "Screenshot: mysports_login_invalid.png"
        )

def open_logged_in_context(playwright, headless=None, email=None, password=None):
    if headless is None:
        headless = HEADLESS

    login_email = email or EMAIL
    profile_dir = _profile_dir_for_email(login_email) if login_email else PROFILE_DIR

    launch_kwargs = dict(
        user_data_dir=str(profile_dir),
        headless=headless,
        locale=LOCALE,
        timezone_id=TIMEZONE_ID,
    )
    if headless:
        launch_kwargs["viewport"] = {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
    else:
        launch_kwargs["no_viewport"] = True
        launch_kwargs["args"] = [
            "--start-maximized",
            f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
        ]

    context = playwright.chromium.launch_persistent_context(**launch_kwargs)
    page = context.pages[0] if context.pages else context.new_page()
    login_and_validate(page, email=email, password=password)
    return context, page

def main():
    with sync_playwright() as p:
        context, _page = open_logged_in_context(p)

        # Session speichern
        context.storage_state(path=str(STATE_FILE))
        print(f"✅ Session gespeichert: {STATE_FILE.resolve()} | Profil: {PROFILE_DIR.resolve()}")

        context.close()

if __name__ == "__main__":
    main()
