import math
import time
from typing import Any, Dict, List, Optional

import requests
from curl_cffi import requests as devpost_requests

from scrapers.envutil import require

DEVPOST_API_URL = "https://devpost.com/api/hackathons"
REQUEST_TIMEOUT = 30
SUPABASE_TABLE = "hackathons"


def _cfg():
    return {
        "supabase_url": require("SUPABASE_URL"),
        "supabase_key": require("SUPABASE_KEY"),
        "telegram_token": require("DEVPOST_TELEGRAM_BOT_TOKEN"),
        "telegram_chat": require("DEVPOST_TELEGRAM_CHAT_ID"),
    }


def fetch_devpost_page(page: int = 1) -> Dict[str, Any]:
    params = [
        ("challenge_type[]", "online"),
        ("challenge_type[]", "in-person"),
        ("status[]", "upcoming"),
        ("status[]", "open"),
        ("page", str(page)),
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://devpost.com/hackathons",
    }
    resp = devpost_requests.get(
        DEVPOST_API_URL,
        params=params,
        headers=headers,
        impersonate="chrome120",
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_all_hackathons() -> List[Dict[str, Any]]:
    print("[INFO] Fetching page 1...")
    first_page = fetch_devpost_page(1)
    hackathons = first_page.get("hackathons", [])
    meta = first_page.get("meta", {})
    total_count = meta.get("total_count", len(hackathons))
    per_page = meta.get("per_page", len(hackathons) or 1)
    total_pages = math.ceil(total_count / per_page)
    print(f"[INFO] total_count={total_count}, per_page={per_page}, total_pages={total_pages}")
    all_items = list(hackathons)
    for page in range(2, total_pages + 1):
        print(f"[INFO] Fetching page {page}/{total_pages}...")
        data = fetch_devpost_page(page)
        all_items.extend(data.get("hackathons", []))
        time.sleep(1)
    print(f"[INFO] Total fetched hackathons: {len(all_items)}")
    return all_items


def supabase_headers(cfg: Dict[str, str]) -> Dict[str, str]:
    return {
        "apikey": cfg["supabase_key"],
        "Authorization": f"Bearer {cfg['supabase_key']}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def hackathon_exists(cfg: Dict[str, str], devpost_id: int) -> bool:
    url = f"{cfg['supabase_url']}/rest/v1/{SUPABASE_TABLE}"
    params = {"select": "id", "devpost_id": f"eq.{devpost_id}", "limit": "1"}
    resp = requests.get(url, headers=supabase_headers(cfg), params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return len(resp.json()) > 0


def insert_hackathon(cfg: Dict[str, str], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{cfg['supabase_url']}/rest/v1/{SUPABASE_TABLE}"
    resp = requests.post(url, headers=supabase_headers(cfg), json=row, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list) and data:
        return data[0]
    return None


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_themes(item: Dict[str, Any]) -> List[str]:
    themes = item.get("themes", []) or []
    return [t.get("name", "").strip() for t in themes if t.get("name")]


def map_hackathon(item: Dict[str, Any]) -> Dict[str, Any]:
    displayed_location = item.get("displayed_location") or {}
    prizes_counts = item.get("prizes_counts") or {}
    return {
        "devpost_id": item.get("id"),
        "title": clean_text(item.get("title")),
        "url": clean_text(item.get("url")),
        "organization_name": clean_text(item.get("organization_name")),
        "open_state": clean_text(item.get("open_state")),
        "location_type": clean_text(displayed_location.get("icon")),
        "location": clean_text(displayed_location.get("location")),
        "thumbnail_url": clean_text(item.get("thumbnail_url")),
        "time_left_to_submission": clean_text(item.get("time_left_to_submission")),
        "submission_period_dates": clean_text(item.get("submission_period_dates")),
        "prize_amount": clean_text(item.get("prize_amount")),
        "cash_prizes_count": prizes_counts.get("cash", 0),
        "other_prizes_count": prizes_counts.get("other", 0),
        "registrations_count": item.get("registrations_count", 0),
        "featured": bool(item.get("featured", False)),
        "winners_announced": bool(item.get("winners_announced", False)),
        "invite_only": bool(item.get("invite_only", False)),
        "submission_gallery_url": clean_text(item.get("submission_gallery_url")),
        "start_a_submission_url": clean_text(item.get("start_a_submission_url")),
        "themes": extract_themes(item),
        "raw_json": item,
    }


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_telegram_message(row: Dict[str, Any]) -> str:
    title = escape_html(row.get("title", "Untitled"))
    org = escape_html(row.get("organization_name", "Unknown"))
    location = escape_html(row.get("location", "N/A"))
    open_state = escape_html(row.get("open_state", "N/A"))
    submission_dates = escape_html(row.get("submission_period_dates", "N/A"))
    time_left = escape_html(row.get("time_left_to_submission", "N/A"))
    prize_amount = escape_html(row.get("prize_amount", "N/A"))
    url = row.get("url", "")
    themes = row.get("themes", [])
    themes_text = escape_html(", ".join(themes)) if themes else "N/A"
    msg = (
        f"🚀 <b>New Hackathon Found</b>\n\n"
        f"🏷 <b>{title}</b>\n"
        f"🏢 <b>Organizer:</b> {org}\n"
        f"📍 <b>Location:</b> {location}\n"
        f"📌 <b>Status:</b> {open_state}\n"
        f"📅 <b>Dates:</b> {submission_dates}\n"
        f"⏳ <b>Time Left:</b> {time_left}\n"
        f"💰 <b>Prize:</b> {prize_amount}\n"
        f"🎯 <b>Themes:</b> {themes_text}\n"
    )
    if url:
        msg += f'\n🔗 <a href="{escape_html(url)}">Open Hackathon</a>'
    return msg


def send_telegram_message(cfg: Dict[str, str], text: str) -> None:
    telegram_url = f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage"
    payload = {
        "chat_id": cfg["telegram_chat"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(telegram_url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def process_hackathons() -> None:
    cfg = _cfg()
    print("[INFO] Starting hackathon sync...")
    all_hackathons = fetch_all_hackathons()
    if not all_hackathons:
        print("[INFO] No hackathons returned from Devpost.")
        return
    inserted_count = skipped_count = notified_count = 0
    for item in all_hackathons:
        devpost_id = item.get("id")
        if not devpost_id:
            skipped_count += 1
            continue
        try:
            if hackathon_exists(cfg, devpost_id):
                print(f"[INFO] Already exists: {devpost_id}")
                skipped_count += 1
                continue
            row = map_hackathon(item)
            insert_hackathon(cfg, row)
            print(f"[INFO] Inserted new hackathon: {row['title']} ({devpost_id})")
            inserted_count += 1
            try:
                send_telegram_message(cfg, build_telegram_message(row))
                notified_count += 1
                time.sleep(1)
            except Exception as tg_err:
                print(f"[ERROR] Telegram failed for {devpost_id}: {tg_err}")
        except Exception as db_err:
            print(f"[ERROR] Failed for hackathon {devpost_id}: {db_err}")
    print(f"[INFO] Done. inserted={inserted_count}, skipped={skipped_count}, notified={notified_count}")


if __name__ == "__main__":
    process_hackathons()
