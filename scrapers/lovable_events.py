from html import escape
from typing import Any, Dict, List, Optional, Set

import requests
from supabase import Client, create_client

from scrapers.envutil import optional, require

REQUEST_TIMEOUT = 30


def _cfg() -> Dict[str, Any]:
    return {
        "events_url": optional(
            "LOVABLE_EVENTS_URL",
            "https://uvlyxzmstjpgekpwgctj.lovable.cloud/functions/v1/get-public-events",
        ),
        "telegram_token": require("LOVABLE_EVENTS_TELEGRAM_BOT_TOKEN"),
        "telegram_chat": require("LOVABLE_EVENTS_TELEGRAM_CHAT_ID"),
        "supabase": create_client(require("SUPABASE_URL"), require("SUPABASE_KEY")),
    }


def load_sent_event_ids(supabase: Client) -> Set[str]:
    try:
        response = supabase.table("sent_events").select("event_id").execute()
        rows = response.data or []
        return {row["event_id"] for row in rows if row.get("event_id")}
    except Exception as e:
        print(f"[ERROR] Could not load sent event IDs from Supabase: {e}")
        return set()


def safe_text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def save_sent_event(supabase: Client, event_id: str, event: Dict[str, Any]) -> None:
    try:
        supabase.table("sent_events").upsert({
            "event_id": event_id,
            "event_name": safe_text(event.get("event_name")),
            "start_date": safe_text(event.get("start_date")),
            "end_date": safe_text(event.get("end_date")),
            "city": safe_text(event.get("city")),
            "country": safe_text(event.get("country")),
        }).execute()
    except Exception as e:
        print(f"[ERROR] Could not save event to Supabase: {e}")


def fetch_events(events_url: str) -> List[Dict[str, Any]]:
    response = requests.get(
        events_url,
        headers={"Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("events"), list):
            return data["events"]
        if isinstance(data.get("data"), list):
            return data["data"]
    raise ValueError("Unexpected API response format")


def get_event_unique_id(event: Dict[str, Any]) -> str:
    if event.get("id"):
        return str(event["id"])
    if event.get("slug"):
        return str(event["slug"])
    return "|".join([
        str(event.get("event_name", "")),
        str(event.get("start_date", "")),
        str(event.get("end_date", "")),
        str(event.get("city", "")),
        str(event.get("country", "")),
    ])


def normalize_event_link(link: str) -> str:
    link = safe_text(link)
    if link.lower() in {"n/a", "na", "none", "null", "-"}:
        return "N/A"
    return link


def build_telegram_message(event: Dict[str, Any]) -> str:
    event_name = escape(safe_text(event.get("event_name")))
    description = escape(safe_text(event.get("description")))
    event_type = escape(safe_text(event.get("event_type")))
    organizer_name = escape(safe_text(event.get("organizer_name")))
    organizer_linkedin = normalize_event_link(safe_text(event.get("organizer_linkedin")))
    start_date = escape(safe_text(event.get("start_date")))
    end_date = escape(safe_text(event.get("end_date")))
    event_link = normalize_event_link(safe_text(event.get("event_link")))
    linkedin_line = (
        f'<a href="{escape(organizer_linkedin)}">View LinkedIn</a>'
        if organizer_linkedin != "N/A" and organizer_linkedin.startswith(("http://", "https://"))
        else "N/A"
    )
    event_link_line = (
        f'<a href="{escape(event_link)}">Open Event</a>'
        if event_link != "N/A" and event_link.startswith(("http://", "https://"))
        else "N/A"
    )
    return f"""
<b>✨ New Event Added</b>

<b>📌 Event Name</b>
{event_name}

<b>🗂 Event Type</b>
{event_type}

<b>👤 Organizer</b>
{organizer_name}

<b>🔗 LinkedIn</b>
{linkedin_line}

<b>🌐 Event Link</b>
{event_link_line}

<b>📅 Start Date</b>
{start_date}

<b>📅 End Date</b>
{end_date}

<b>📝 Description</b>
{description}
""".strip()


def build_inline_keyboard(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    buttons = []
    event_link = normalize_event_link(safe_text(event.get("event_link")))
    linkedin = normalize_event_link(safe_text(event.get("organizer_linkedin")))
    if event_link != "N/A" and event_link.startswith(("http://", "https://")):
        buttons.append({"text": "🌐 Open Event", "url": event_link})
    if linkedin != "N/A" and linkedin.startswith(("http://", "https://")):
        buttons.append({"text": "💼 Organizer LinkedIn", "url": linkedin})
    if not buttons:
        return None
    return {"inline_keyboard": [buttons]}


def send_to_telegram(cfg: Dict[str, Any], message: str, reply_markup=None) -> None:
    import time
    time.sleep(1)
    url = f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage"
    payload = {
        "chat_id": cfg["telegram_chat"],
        "text": message[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    try:
        data = response.json()
    except Exception:
        print("[ERROR] Non-JSON Telegram response:", response.status_code, response.text)
        response.raise_for_status()
        return
    if not response.ok or not data.get("ok"):
        raise RuntimeError(data.get("description", "Unknown Telegram API error"))


def check_and_send_new_events() -> None:
    cfg = _cfg()
    print("[INFO] Checking for new events...")
    sent_ids = load_sent_event_ids(cfg["supabase"])
    events = fetch_events(cfg["events_url"])
    if not events:
        print("[INFO] No events returned")
        return
    new_events = []
    for event in events:
        unique_id = get_event_unique_id(event)
        if unique_id not in sent_ids:
            new_events.append((unique_id, event))
    if not new_events:
        print("[INFO] No new events found")
        return
    new_events.sort(key=lambda x: str(x[1].get("start_date", "")))
    for unique_id, event in new_events:
        try:
            send_to_telegram(cfg, build_telegram_message(event), build_inline_keyboard(event))
            save_sent_event(cfg["supabase"], unique_id, event)
            sent_ids.add(unique_id)
            print(f"[INFO] Sent: {event.get('event_name', unique_id)}")
        except Exception as e:
            print(f"[ERROR] Failed to send {unique_id}: {e}")
    print(f"[INFO] Sent {len(new_events)} new events")


if __name__ == "__main__":
    check_and_send_new_events()
