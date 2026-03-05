# SportBot

Automatisiert MySports-Kursbuchungen mit Playwright.

## Voraussetzungen

- Python 3
- virtuelle Umgebung (`.venv`)
- Playwright
- Chromium

Typischer lokaler Setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install playwright python-dotenv
python -m playwright install chromium
```

Typischer Debian-/VPS-Setup:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip xvfb
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install playwright python-dotenv
python -m playwright install --with-deps chromium
```

## Konfiguration

Optionale `.env`:

```bash
MYSPORTS_EMAIL=deine-mail@example.com
MYSPORTS_PASSWORD=dein-passwort
MYSPORTS_GYM=EASYFITNESS Verden
MYSPORTS_COURSE=Kraft-Ausdauer Training
MYSPORTS_LOCALE=de-DE
MYSPORTS_TIMEZONE=Europe/Berlin
```

`MYSPORTS_EMAIL` und `MYSPORTS_PASSWORD` koennen auch direkt per CLI uebergeben werden.
`MYSPORTS_LOCALE` und `MYSPORTS_TIMEZONE` sorgen fuer konsistente UI-Sprache/-Zeiten (empfohlen auf VPS).

## Standardstart

Ein einzelner lokaler Testlauf:

```bash
python run_booking.py --attempts 1
```

Auf Debian/VPS ohne Desktop:

```bash
xvfb-run -a --server-args="-screen 0 1920x1080x24" .venv/bin/python run_booking.py --attempts 1
```

## Bestimmten Kurs buchen

Wenn du ueber den allgemeinen Kursnamen buchst:

```bash
python run_booking.py --course "Kraft-Ausdauer Training" --attempts 1
```

Auf dem VPS mit expliziten Credentials:

```bash
xvfb-run -a --server-args="-screen 0 1920x1080x24" .venv/bin/python run_booking.py --course "Kraft-Ausdauer Training" --email "deine.mail@example.com" --password "dein-passwort" --attempts 1
```

Optional mit Wochentag:

```bash
python run_booking.py --course "Yoga" --weekday Montag --attempts 1
```

## Bestimmten Slot buchen

Der stabilere Weg ist die Buchung ueber den exakten Slot-Text inklusive Uhrzeit.

Beispiele:

```bash
python run_booking.py --slot "Rücken-Workout 09:00 10:00" --attempts 1
python run_booking.py --slot "Indoor Cycling, 18:00 - 19:00" --attempts 1
python run_booking.py --slot "BODYPUMP, 19:15 - 20:15" --attempts 1
```

Auf dem VPS:

```bash
xvfb-run -a --server-args="-screen 0 1920x1080x24" .venv/bin/python run_booking.py --slot "Indoor Cycling, 18:00 - 19:00" --email "deine.mail@example.com" --password "dein-passwort" --attempts 1
```

## Benutzername und Passwort explizit angeben

Wenn du Credentials nicht aus `.env` lesen willst:

```bash
python run_booking.py --slot "Indoor Cycling, 18:00 - 19:00" --email "deine.mail@example.com" --password "dein-passwort" --attempts 1
```

Hinweis:
- Das Passwort ist so in Shell-History, Prozessliste oder Crontab sichtbar.
- Fuer kurzfristige Tests ist das okay.
- Fuer dauerhafte Automatisierung ist `.env` sicherer.

## macOS mit `launchd`

Auf dem Mac ist `launchd` der bevorzugte Scheduler.

Wichtige Befehle:

```bash
plutil -lint ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
launchctl kickstart -k gui/$(id -u)/com.dennis.sportbot.rueckenworkout
launchctl list | grep rueckenworkout
```

Einmalige Jobs danach wieder entfernen:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
rm ~/Library/LaunchAgents/com.dennis.sportbot.rueckenworkout.plist
```

## Debian / VPS mit Cron

Auf Linux ist `cron` der richtige Scheduler.

Wichtig:
- Viele Server laufen in `UTC`.
- Plane die Uhrzeiten deshalb am stabilsten direkt in `UTC`.
- Beispiel im Winter: `18:01 Europe/Berlin` = `17:01 UTC`.

Crontab bearbeiten:

```bash
crontab -e
```

Aktuelle Crontab anzeigen:

```bash
crontab -l
```

### Beispiel: Jeden Dienstag um 18:01 Uhr Berlin `Indoor Cycling`

Wenn der Server auf `UTC` laeuft und Winterzeit gilt, entspricht das `17:01 UTC`:

```cron
1 17 * * 2 cd /home/dennis/SportBot && xvfb-run -a --server-args="-screen 0 1920x1080x24" /home/dennis/SportBot/.venv/bin/python run_booking.py --slot "Indoor Cycling, 18:00 - 19:00" --email "deine.mail@example.com" --password "dein-passwort" --attempts 2 >> /home/dennis/SportBot/booking_indoor_cycling.log 2>&1
```

### Beispiel: Testjob fuer `Rücken-Workout`

Wenn du testweise nur einen temporaeren Eintrag setzen willst:

```cron
55 12 * * * cd /home/dennis/SportBot && xvfb-run -a --server-args="-screen 0 1920x1080x24" /home/dennis/SportBot/.venv/bin/python run_booking.py --slot "Rücken-Workout 09:00 10:00" --email "deine.mail@example.com" --password "dein-passwort" --attempts 1 >> /home/dennis/SportBot/booking_rueckenworkout_test.log 2>&1
```

Das Beispiel oben entspricht im Winter `13:55 Uhr Berlin` = `12:55 UTC`.

Wenn der Test nur einmal laufen soll:
- nach dem Lauf die Zeile wieder aus `crontab -e` entfernen

### Cron pruefen

Cron-Dienststatus:

```bash
systemctl status cron --no-pager
```

Pruefen, ob Cron generell Jobs ausfuehrt:

```bash
* * * * * echo "cron probe $(date)" >> /home/dennis/cron_probe.log
```

Probe-Log ansehen:

```bash
tail -n 20 /home/dennis/cron_probe.log
```

### Logs ansehen

Job-Log:

```bash
tail -n 100 /home/dennis/SportBot/booking_indoor_cycling.log
tail -n 100 /home/dennis/SportBot/booking_rueckenworkout_test.log
```

Cron-Systemlog:

```bash
sudo grep CRON /var/log/syslog | tail -n 50
```

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
