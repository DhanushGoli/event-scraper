import hashlib
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from scrapers.envutil import optional, require

REQUEST_TIMEOUT = 30
SUPABASE_TABLE = "hackathon_events"


def _cfg():
    return {
        "api_url": optional("MLH_EVENTS_URL", "https://www.mlh.com/seasons/2026/events"),
        "supabase_url": require("SUPABASE_URL"),
        "supabase_key": require("SUPABASE_KEY"),
        "telegram_token": require("MLH_TELEGRAM_BOT_TOKEN"),
        "telegram_chat": require("MLH_TELEGRAM_CHAT_ID"),
    }


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def generate_event_slug(name: str, date_text: str, location: str) -> str:
    base = f"{name}|{date_text}|{location}"
    short_hash = hashlib.md5(base.encode("utf-8")).hexdigest()[:10]
    return f"{slugify(name)}-{short_hash}"


def safe_text(value: Optional[str]) -> str:
    return value.strip() if value else ""


def fetch_html(url: str) -> str:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def parse_event_cards(html: str, source_url: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    events = []
    cards = soup.select("div.rounded-card.relative.overflow-hidden.bg-white.border-2.border-navy-100")
    for card in cards:
        try:
            title_el = card.select_one("h4")
            event_name = safe_text(title_el.get_text()) if title_el else ""
            imgs = card.select("img")
            background_image = imgs[0].get("src", "") if len(imgs) >= 1 else ""
            logo_image = imgs[1].get("src", "") if len(imgs) >= 2 else ""
            spans = card.select("span.text-sm.truncate")
            date_text = safe_text(spans[0].get_text()) if len(spans) > 0 else ""
            location_text = safe_text(spans[1].get_text()) if len(spans) > 1 else ""
            mode_el = card.select_one("span.rounded-full")
            event_mode = safe_text(mode_el.get_text()) if mode_el else ""
            city = state = country = ""
            if location_text:
                parts = [p.strip() for p in location_text.split(",")]
                if len(parts) >= 1:
                    city = parts[0]
                if len(parts) >= 2:
                    state = parts[1]
                if len(parts) >= 3:
                    country = parts[2]
            slug = generate_event_slug(event_name, date_text, location_text)
            event = {
                "slug": slug,
                "event_name": event_name,
                "date_text": date_text,
                "location_text": location_text,
                "city": city,
                "state": state,
                "country": country,
                "event_mode": event_mode,
                "background_image": background_image,
                "logo_image": logo_image,
                "source_url": source_url,
                "created_at": datetime.utcnow().isoformat(),
            }
            if event_name:
                events.append(event)
        except Exception as e:
            print(f"[WARN] Failed to parse one card: {e}")
    return events


def supabase_headers(cfg: Dict[str, str]) -> Dict[str, str]:
    return {
        "apikey": cfg["supabase_key"],
        "Authorization": f"Bearer {cfg['supabase_key']}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def event_exists(cfg: Dict[str, str], slug: str) -> bool:
    url = f"{cfg['supabase_url']}/rest/v1/{SUPABASE_TABLE}"
    params = {"select": "id,slug", "slug": f"eq.{slug}", "limit": 1}
    resp = requests.get(url, headers=supabase_headers(cfg), params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return len(resp.json()) > 0


def insert_event(cfg: Dict[str, str], event: Dict) -> Optional[Dict]:
    url = f"{cfg['supabase_url']}/rest/v1/{SUPABASE_TABLE}"
    payload = {k: event[k] for k in (
        "slug", "event_name", "date_text", "location_text", "city", "state",
        "country", "event_mode", "background_image", "logo_image", "source_url",
    )}
    resp = requests.post(url, headers=supabase_headers(cfg), json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None


def build_telegram_message(event: Dict) -> str:
    msg = (
        f"🎉 <b>New Hackathon Found</b>\n\n"
        f"🏷 <b>Name:</b> {event['event_name']}\n"
        f"📅 <b>Date:</b> {event['date_text'] or 'N/A'}\n"
        f"📍 <b>Location:</b> {event['location_text'] or 'N/A'}\n"
        f"🧭 <b>Mode:</b> {event['event_mode'] or 'N/A'}\n"
        f"🔗 <b>Slug:</b> {event['slug']}"
    )
    if event.get("background_image"):
        msg += f"\n🖼 <a href=\"{event['background_image']}\">Background Image</a>"
    if event.get("logo_image"):
        msg += f"\n🧩 <a href=\"{event['logo_image']}\">Logo Image</a>"
    return msg


def send_telegram(cfg: Dict[str, str], event: Dict) -> None:
    url = f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage"
    payload = {
        "chat_id": cfg["telegram_chat"],
        "text": build_telegram_message(event),
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    time.sleep(1)
    resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def main() -> None:
    cfg = _cfg()
    print("[INFO] Fetching HTML...")
    html = fetch_html(cfg["api_url"])
    print("[INFO] Parsing cards...")
    events = parse_event_cards(html, cfg["api_url"])
    print(f"[INFO] Found {len(events)} event cards")
    if not events:
        return
    new_count = 0
    for event in events:
        try:
            if event_exists(cfg, event["slug"]):
                print(f"[SKIP] Already exists: {event['event_name']}")
                continue
            insert_event(cfg, event)
            send_telegram(cfg, event)
            print(f"[INSERTED] {event['event_name']}")
            new_count += 1
        except Exception as e:
            print(f"[ERROR] Failed for event '{event.get('event_name', 'unknown')}': {e}")
    print(f"[DONE] New events inserted and notified: {new_count}")


if __name__ == "__main__":
    main()
