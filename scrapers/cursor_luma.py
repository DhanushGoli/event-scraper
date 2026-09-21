import html
import time
from typing import Any, Dict, List, Optional

import requests
from supabase import Client, create_client

from scrapers.envutil import optional, require

REQUEST_TIMEOUT = 30
TABLE_NAME = "cursor_events"
DEFAULT_LUMA_URL = (
    "https://api2.luma.com/calendar/get-items"
    "?calendar_api_id=cal-61Cv6COs4g9GKw7&period=future"
)


def _cfg() -> Dict[str, Any]:
    return {
        "api_url": optional("CURSOR_LUMA_API_URL", DEFAULT_LUMA_URL),
        "telegram_token": require("CURSOR_TELEGRAM_BOT_TOKEN"),
        "telegram_chat": require("CURSOR_TELEGRAM_CHAT_ID"),
        "supabase": create_client(require("SUPABASE_URL"), require("SUPABASE_KEY")),
    }


def fetch_entries(api_url: str) -> List[Dict[str, Any]]:
    response = requests.get(
        api_url,
        headers={"Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return data["entries"]
    if isinstance(data, list):
        return data
    raise ValueError("Unexpected API response format. Expected {'entries': [...]} or list.")


def safe_text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def get_nested(data: Dict[str, Any], *keys: str, default=None):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def get_event_unique_id(entry: Dict[str, Any]) -> str:
    top_api_id = entry.get("api_id")
    if top_api_id:
        return str(top_api_id)
    nested_event_api_id = get_nested(entry, "event", "api_id")
    if nested_event_api_id:
        return str(nested_event_api_id)
    event_url = get_nested(entry, "event", "url")
    if event_url:
        return str(event_url)
    return "|".join([
        safe_text(get_nested(entry, "event", "name"), ""),
        safe_text(get_nested(entry, "event", "start_at"), ""),
        safe_text(get_nested(entry, "event", "timezone"), ""),
        safe_text(get_nested(entry, "event", "geo_address_info", "city"), ""),
    ])


def extract_event_data(entry: Dict[str, Any]) -> Dict[str, Any]:
    event = entry.get("event", {}) if isinstance(entry.get("event"), dict) else {}
    geo = event.get("geo_address_info", {}) if isinstance(event.get("geo_address_info"), dict) else {}
    ticket_info = entry.get("ticket_info", {}) if isinstance(entry.get("ticket_info"), dict) else {}
    hosts = entry.get("hosts", [])
    host_names = []
    if isinstance(hosts, list):
        host_names = [h.get("name") for h in hosts if isinstance(h, dict) and h.get("name")]
    tags = entry.get("tags", [])
    tag_names = []
    if isinstance(tags, list):
        tag_names = [t.get("name") for t in tags if isinstance(t, dict) and t.get("name")]
    event_url_slug = safe_text(event.get("url"), "")
    event_link = f"https://lu.ma/{event_url_slug}" if event_url_slug and event_url_slug != "N/A" else "N/A"
    return {
        "unique_id": get_event_unique_id(entry),
        "entry_api_id": safe_text(entry.get("api_id")),
        "event_api_id": safe_text(event.get("api_id")),
        "event_name": safe_text(event.get("name")),
        "start_at": safe_text(event.get("start_at")),
        "end_at": safe_text(event.get("end_at")),
        "timezone": safe_text(event.get("timezone")),
        "location_type": safe_text(event.get("location_type")),
        "city": safe_text(geo.get("city")),
        "country": safe_text(geo.get("country")),
        "full_address": safe_text(geo.get("full_address")),
        "short_address": safe_text(geo.get("short_address")),
        "event_link": event_link,
        "calendar_name": safe_text(get_nested(entry, "calendar", "name")),
        "guest_count": entry.get("guest_count", 0),
        "ticket_count": entry.get("ticket_count", 0),
        "is_free": bool(ticket_info.get("is_free", False)),
        "is_sold_out": bool(ticket_info.get("is_sold_out", False)),
        "spots_remaining": ticket_info.get("spots_remaining"),
        "host_names": host_names,
        "tag_names": tag_names,
        "raw_data": entry,
    }


def check_if_exists_in_db(supabase: Client, unique_id: str) -> bool:
    result = (
        supabase.table(TABLE_NAME)
        .select("unique_id")
        .eq("unique_id", unique_id)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def save_to_db(supabase: Client, event_data: Dict[str, Any]) -> None:
    payload = {k: event_data[k] for k in (
        "unique_id", "entry_api_id", "event_api_id", "event_name", "start_at", "end_at",
        "timezone", "location_type", "city", "country", "full_address", "short_address",
        "event_link", "calendar_name", "guest_count", "ticket_count", "is_free",
        "is_sold_out", "spots_remaining", "host_names", "tag_names", "raw_data",
    )}
    supabase.table(TABLE_NAME).insert(payload).execute()


def build_telegram_message(event_data: Dict[str, Any]) -> str:
    event_name = html.escape(event_data["event_name"])
    start_at = html.escape(event_data["start_at"])
    end_at = html.escape(event_data["end_at"])
    timezone = html.escape(event_data["timezone"])
    city = html.escape(event_data["city"])
    country = html.escape(event_data["country"])
    location_type = html.escape(event_data["location_type"])
    calendar_name = html.escape(event_data["calendar_name"])
    event_link = html.escape(event_data["event_link"])
    host_names = ", ".join(event_data["host_names"]) if event_data["host_names"] else "N/A"
    tags = ", ".join(event_data["tag_names"]) if event_data["tag_names"] else "N/A"
    price_text = "Free" if event_data["is_free"] else "Paid"
    sold_out_text = "Yes" if event_data["is_sold_out"] else "No"
    spots_remaining = event_data["spots_remaining"]
    spots_text = "N/A" if spots_remaining is None else str(spots_remaining)
    return (
        f"🚀 <b>{event_name}</b>\n\n"
        f"🗓 <b>Start:</b> {start_at}\n"
        f"🕒 <b>End:</b> {end_at}\n"
        f"🌍 <b>Timezone:</b> {timezone}\n"
        f"📍 <b>Location:</b> {city}, {country}\n"
        f"🏢 <b>Type:</b> {location_type}\n"
        f"📚 <b>Calendar:</b> {calendar_name}\n"
        f"👤 <b>Hosts:</b> {html.escape(host_names)}\n"
        f"🎫 <b>Price:</b> {price_text}\n"
        f"❌ <b>Sold Out:</b> {sold_out_text}\n"
        f"🪑 <b>Spots Remaining:</b> {spots_text}\n"
        f"🏷 <b>Tags:</b> {html.escape(tags)}\n"
        f'🔗 <a href="{event_link}">Open Event</a>'
    )


def send_to_telegram(cfg: Dict[str, Any], event_data: Dict[str, Any]) -> None:
    url = f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage"
    payload = {
        "chat_id": cfg["telegram_chat"],
        "text": build_telegram_message(event_data),
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    time.sleep(1)
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()


def process_entries() -> None:
    cfg = _cfg()
    print("[INFO] Fetching entries from API...")
    entries = fetch_entries(cfg["api_url"])
    if not entries:
        print("[INFO] No entries found")
        return
    print(f"[INFO] Total entries fetched: {len(entries)}")
    for entry in entries:
        try:
            event_data = extract_event_data(entry)
            unique_id = event_data["unique_id"]
            if check_if_exists_in_db(cfg["supabase"], unique_id):
                print(f"[SKIP] Already exists in DB: {unique_id}")
                continue
            send_to_telegram(cfg, event_data)
            save_to_db(cfg["supabase"], event_data)
            print(f"[SENT] New event sent and saved: {event_data['event_name']} ({unique_id})")
        except Exception as e:
            print(f"[ERROR] Failed processing entry: {e}")


if __name__ == "__main__":
    process_entries()
