"""Diagnose der Studio-Auswahlseite (.../studios/<tenant>).

Loggt ein, landet auf der Auswahlseite und dumpt die echte DOM-Struktur,
damit die Studio-Auswahl passgenau gebaut werden kann. Bucht NICHTS.

Aufruf auf dem VPS:
    xvfb-run -a --server-args="-screen 0 1920x1080x24" \
      /home/dennis/SportBot/.venv/bin/python diag_studios.py \
      --email "..." --password "..."

Ergebnis:
    - Konsolenausgabe mit Struktur
    - Datei aifitness_studios_dump.html (vollstaendiges HTML der Seite)
"""
import argparse
import re
from playwright.sync_api import sync_playwright

from save_session import open_logged_in_context, HEADLESS
from book_course import COURSE_URL, dismiss_cookie_banner


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--email")
    p.add_argument("--password")
    return p.parse_args()


def main():
    args = parse_args()
    with sync_playwright() as pw:
        context, page = open_logged_in_context(
            pw, headless=HEADLESS, email=args.email, password=args.password
        )
        try:
            page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_load_state("networkidle")
            dismiss_cookie_banner(page)
            page.wait_for_timeout(1500)

            print(f"URL: {page.url}")
            print(f"Title: {page.title()}")

            # 1) Vollstaendiges HTML in Datei schreiben.
            try:
                html = page.content()
                with open("aifitness_studios_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"\nHTML-Dump: aifitness_studios_dump.html ({len(html)} Zeichen)")
            except Exception as e:
                print(f"HTML-Dump fehlgeschlagen: {e}")

            # 2) Element-Zaehlung nach gaengigen Rollen/Tags.
            print("\n=== Elementzahlen ===")
            for role in ("option", "listitem", "link", "button", "menuitem", "row", "cell", "tab"):
                try:
                    print(f"  role={role}: {page.get_by_role(role).count()}")
                except Exception:
                    pass
            for sel in ("input", "a[href]", "li", "ul", "[role='option']",
                        "[class*='studio' i]", "[class*='card' i]", "[class*='item' i]",
                        "[class*='list' i]", "[data-testid]"):
                try:
                    print(f"  sel={sel}: {page.locator(sel).count()}")
                except Exception:
                    pass

            # 3) Das 'Verden'-Element gezielt untersuchen.
            print("\n=== Umgebung des Treffers 'Verden' ===")
            try:
                v = page.get_by_text(re.compile(r"Verden", re.IGNORECASE))
                cnt = v.count()
                print(f"  Treffer get_by_text('Verden'): {cnt}")
                for i in range(min(cnt, 5)):
                    el = v.nth(i)
                    try:
                        info = el.evaluate(
                            """e => {
                                function desc(n){ if(!n) return null; return {
                                    tag:n.tagName, role:n.getAttribute('role'),
                                    cls:(n.className||'').toString().slice(0,80),
                                    href:n.getAttribute('href'),
                                    testid:n.getAttribute('data-testid'),
                                    text:(n.innerText||'').replace(/\\s+/g,' ').slice(0,40)
                                };}
                                return {self:desc(e), parent:desc(e.parentElement),
                                        gp:desc(e.parentElement&&e.parentElement.parentElement)};
                            }"""
                        )
                        print(f"  [{i}] {info}")
                    except Exception as e:
                        print(f"  [{i}] eval-Fehler: {e}")
            except Exception as e:
                print(f"  Verden-Suche fehlgeschlagen: {e}")

            # 4) Input-Felder beschreiben.
            print("\n=== Input-Felder ===")
            inp = page.locator("input")
            for i in range(min(inp.count(), 10)):
                el = inp.nth(i)
                try:
                    attrs = el.evaluate(
                        """e => ({type:e.type, name:e.name, id:e.id,
                                 placeholder:e.placeholder, role:e.getAttribute('role'),
                                 aria:e.getAttribute('aria-label')})"""
                    )
                    print(f"  input[{i}]: {attrs} visible={el.is_visible()}")
                except Exception:
                    pass
        finally:
            context.close()


if __name__ == "__main__":
    main()
