# event-scraper

Event scrapers, split by task.

```
scrapers/
  devpost.py            Devpost hackathons → Supabase + Telegram
  mlh.py                MLH season events
  lovable_events.py     Lovable public events
  lovable_partners.py   Lovable partner list
  cursor_luma.py        Cursor Luma calendar
```

## Setup (local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill .env
```

## Run

```bash
python run.py devpost
python run.py mlh
python run.py lovable-events
python run.py lovable-partners
python run.py cursor
python run.py all
```

Secrets stay in `.env` or Railway variables. Do not commit them.

## Deploy on Railway

This is a **cron service**, not a website. Railway starts it on a schedule, it runs all five scrapers, then exits.

1. [Railway](https://railway.app) → New project → Deploy from GitHub → `DhanushGoli/event-scraper`.
2. Open the service → **Variables** → add every key from `.env.example`.
3. `railway.toml` already sets:
   - start command: `python run.py all`
   - cron: `0 */6 * * *` (every 6 hours, **UTC**)
   - restart policy: `NEVER` (required so the next cron is not skipped)
4. Deploy. Check **Deployments** after the first cron tick, or click Deploy now for a one-off run.

To run only one scraper, duplicate the service in Railway and set its start command to `python run.py mlh` (or another task).

Do not add a public domain or a healthcheck path.
