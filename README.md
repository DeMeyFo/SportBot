# SportBot

Automatisiert MySports-Kursbuchungen mit Playwright.

## Voraussetzungen

- Python 3
- virtuelle Umgebung (`.venv`)
- Abhaengigkeiten installiert
- Playwright Chromium installiert

Typischer Setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install playwright python-dotenv
python -m playwright install chromium
```

Wenn du auf einem Raspberry Pi / Debian ohne Desktop arbeitest:

```bash
sudo apt update
sudo apt install -y xvfb
```

## Konfiguration

Lege eine `.env` im Projekt an:

```bash
MYSPORTS_EMAIL=deine-mail@example.com
MYSPORTS_PASSWORD=dein-passwort
MYSPORTS_GYM=EASYFITNESS Verden
MYSPORTS_COURSE=Kraft-Ausdauer Training
MYSPORTS_ATTEMPTS=3
```

`MYSPORTS_EMAIL` und `MYSPORTS_PASSWORD` koennen auch pro Aufruf per CLI uebergeben werden.

## Standardstart

Einzelner Lauf mit sichtbarem Browser:

```bash
python run_booking.py --attempts 1
```

## Bestimmten Kurs buchen

Wenn du einen Kurs ueber den allgemeinen Kursnamen buchen willst:

```bash
python run_booking.py --course "Kraft-Ausdauer Training" --attempts 3
```

Optional mit Wochentag:

```bash
python run_booking.py --course "Yoga" --weekday Montag --attempts 3
```

## Bestimmten Slot buchen

Der stabilere Weg ist die Buchung ueber den exakten Slot-Text (inklusive Uhrzeit).

Beispiel:

```bash
python run_booking.py --slot "Rücken-Workout 09:00 10:00" --attempts 3
```

Weitere Beispiele:

```bash
python run_booking.py --slot "Indoor Cycling, 18:00 - 19:00" --attempts 3
python run_booking.py --slot "BODYPUMP, 19:15 - 20:15" --attempts 3
```

## Benutzername und Passwort explizit angeben

Wenn du Credentials nicht aus `.env` lesen willst:

```bash
python run_booking.py \
  --slot "Indoor Cycling, 18:00 - 19:00" \
  --email "dennis.meyer@online.de" \
  --password "dein-passwort" \
  --attempts 3
```

Hinweis:
- Das Passwort ist so in deiner Shell-History sichtbar.
- Fuer dauerhafte Nutzung ist `.env` die bessere Option.

## Raspberry Pi / Server

Ohne Desktop starte im virtuellen Display:

```bash
xvfb-run -a .venv/bin/python run_booking.py --slot "Indoor Cycling, 18:00 - 19:00" --attempts 3
```

## macOS mit `launchd`

Auf dem Mac ist `launchd` der bevorzugte Scheduler fuer einmalige und wiederkehrende Jobs.

Beispiel-Datei:

```bash
~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
```

Wichtige `launchctl`-Befehle:

```bash
plutil -lint ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
launchctl kickstart -k gui/$(id -u)/com.dennis.sportbot.rueckenworkout
launchctl list | grep rueckenworkout
```

Wenn der Job nur einmal laufen soll, danach wieder entfernen:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
rm ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
```

## Cronjob-Beispiel

Taeglich um 18:01:

```cron
1 18 * * * cd /home/dennis/SportBot && xvfb-run -a /home/dennis/SportBot/.venv/bin/python run_booking.py --slot "Indoor Cycling, 18:00 - 19:00" --attempts 3 >> /home/dennis/SportBot/booking_indoor_1800.log 2>&1
```

Hinweis:
- Auf Linux/Raspberry Pi ist `cron` oder `at` sinnvoll.
- Auf macOS ist `launchd` in der Regel die bessere Wahl.

## Wichtige Parameter

- `--course`: Buchung ueber Kursnamen
- `--slot`: Buchung ueber exakten Slot-Text
- `--weekday`: optionaler Wochentag fuer Kursnamen
- `--email`: Login-Mail explizit setzen
- `--password`: Login-Passwort explizit setzen
- `--attempts`: Anzahl kompletter Wiederholungsversuche

CLI-Hilfe:

```bash
python run_booking.py --help
```
