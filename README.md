# SportBot

Automatisiert MySports-Kursbuchungen mit Playwright auf einem Debian/Ubuntu VPS.

## Einrichtung auf dem VPS

### 1) Projekt bereitstellen

```bash
cd /home/dennis
git clone https://github.com/DeMeyFo/SportBot.git
cd SportBot
```

Wenn das Repo bereits vorhanden ist:

```bash
cd /home/dennis/SportBot
git pull --ff-only origin main
```

### 2) Systempakete installieren

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip xvfb
```

### 3) Virtuelle Umgebung + Python-Abhaengigkeiten

```bash
cd /home/dennis/SportBot
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install playwright python-dotenv
python -m playwright install --with-deps chromium
```

### 4) Optional: `.env` anlegen

```bash
cd /home/dennis/SportBot
cat > .env <<'ENV'
MYSPORTS_GYM=EASYFITNESS Verden
MYSPORTS_LOCALE=de-DE
MYSPORTS_TIMEZONE=Europe/Berlin
ENV
```

`MYSPORTS_EMAIL` und `MYSPORTS_PASSWORD` koennen in `.env` stehen, werden aber hier meist direkt per CLI uebergeben.

## Manueller Start auf dem VPS

### 1) Testlauf ueber Kursname

```bash
cd /home/dennis/SportBot
xvfb-run -a --server-args="-screen 0 1920x1080x24" /home/dennis/SportBot/.venv/bin/python run_booking.py --course "Rücken-Workout" --days-ahead 6 --email "deine.mail@example.com" --password "dein-passwort" --attempts 1
```

### 2) Testlauf ueber exakten Slot

```bash
cd /home/dennis/SportBot
xvfb-run -a --server-args="-screen 0 1920x1080x24" /home/dennis/SportBot/.venv/bin/python run_booking.py --slot "INDOOR CYCLING, 16:45 - 17:45" --days-ahead 6 --email "deine.mail@example.com" --password "dein-passwort" --attempts 1
```

## Wichtige CLI-Parameter

- `--course` Kursname
- `--slot` exakter Slot-Text
- `--days-ahead` Zieltermin relativ zu heute (z. B. `6`)
- `--email` Login-E-Mail
- `--password` Login-Passwort
- `--attempts` Anzahl kompletter Wiederholungen

Hilfe anzeigen:

```bash
cd /home/dennis/SportBot
/home/dennis/SportBot/.venv/bin/python run_booking.py --help
```
