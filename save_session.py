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
VIEWPORT_WIDTH = int(os.getenv("MYSPORTS_VIEWPORT_WIDTH", "1920"))
VIEWPORT_HEIGHT = int(os.getenv("MYSPORTS_VIEWPORT_HEIGHT", "1080"))

EMAIL = os.environ["MYSPORTS_EMAIL"]
PASSWORD = os.environ["MYSPORTS_PASSWORD"]

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

def login_and_validate(page):
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    dismiss_cookie_banner(page)

    if "login-register" in page.url:
        # Login (stabiler: per role + name)
        page.get_by_role("textbox", name="E-Mail *").fill(EMAIL)
        page.get_by_role("textbox", name="Passwort *").fill(PASSWORD)
        page.get_by_role("button", name="Login").click()

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

def open_logged_in_context(playwright, headless=False):
    launch_kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        no_viewport=True,
    )
    launch_kwargs["args"] = [
        "--start-maximized",
        f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
    ]

    context = playwright.chromium.launch_persistent_context(**launch_kwargs)
    page = context.pages[0] if context.pages else context.new_page()
    login_and_validate(page)
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
