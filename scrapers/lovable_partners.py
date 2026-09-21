import time
from typing import Any, Dict, List, Set

import requests

from scrapers.envutil import require

REQUEST_TIMEOUT = 30
TRACKER_TABLE = "partner_alerts"


def _cfg() -> Dict[str, str]:
    supabase_url = require("SUPABASE_URL").rstrip("/")
    supabase_key = require("SUPABASE_KEY")
    source_url = require("LOVABLE_PARTNERS_SOURCE_URL")
    source_key = require("LOVABLE_PARTNERS_SOURCE_KEY")
    return {
        "source_rpc_url": source_url,
        "source_key": source_key,
        "tracker_url": f"{supabase_url}/rest/v1/{TRACKER_TABLE}",
        "tracker_key": supabase_key,
        "telegram_token": require("LOVABLE_PARTNERS_TELEGRAM_BOT_TOKEN"),
        "telegram_chat": require("LOVABLE_PARTNERS_TELEGRAM_CHAT_ID"),
    }


def _headers(key: str) -> Dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def fetch_public_partners(cfg: Dict[str, str]) -> List[Dict[str, Any]]:
    resp = requests.post(
        cfg["source_rpc_url"],
        headers=_headers(cfg["source_key"]),
        json={},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected response from RPC: {type(data).__name__}")
    return data


def fetch_existing_names(cfg: Dict[str, str]) -> Set[str]:
    resp = requests.get(
        cfg["tracker_url"],
        headers=_headers(cfg["tracker_key"]),
        params={"select": "name", "limit": 10000},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json()
    return {(row.get("name") or "").strip().lower() for row in rows if row.get("name")}


def insert_partner(cfg: Dict[str, str], partner: Dict[str, Any]) -> None:
    payload = {
        "source_partner_id": partner.get("id"),
        "name": partner.get("name"),
        "slug": partner.get("slug"),
        "logo_url": partner.get("logo_url"),
        "sent_to_telegram": True,
    }
    resp = requests.post(
        cfg["tracker_url"],
        headers={**_headers(cfg["tracker_key"]), "Prefer": "return=minimal"},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


def build_telegram_message(partner: Dict[str, Any]) -> str:
    name = partner.get("name", "Unknown")
    slug = partner.get("slug", "n/a")
    logo_url = partner.get("logo_url", "")
    pid = partner.get("id", "n/a")
    lines = [
        "🆕 <b>New Partner Found</b>",
        "",
        f"🏷️ <b>Name:</b> {name}",
        f"🔗 <b>Slug:</b> {slug}",
        f"🆔 <b>ID:</b> <code>{pid}</code>",
    ]
    if logo_url:
        lines.append(f"🖼️ <b>Logo:</b> {logo_url}")
    return "\n".join(lines)


def send_to_telegram(cfg: Dict[str, str], message: str) -> None:
    url = f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage"
    payload = {
        "chat_id": cfg["telegram_chat"],
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    time.sleep(1)
    resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")


def process_partners() -> None:
    cfg = _cfg()
    print("[INFO] Fetching source partners...")
    partners = fetch_public_partners(cfg)
    if not partners:
        print("[INFO] No partners found.")
        return
    existing_names = fetch_existing_names(cfg)
    print(f"[INFO] Existing names in tracker DB: {len(existing_names)}")
    new_count = 0
    for partner in partners:
        name = (partner.get("name") or "").strip()
        if not name:
            print(f"[WARN] Skipping invalid row: {partner}")
            continue
        name_key = name.lower()
        if name_key in existing_names:
            print(f"[INFO] Already exists, skipping: {name}")
            continue
        try:
            send_to_telegram(cfg, build_telegram_message(partner))
            insert_partner(cfg, partner)
            existing_names.add(name_key)
            new_count += 1
            print(f"[INFO] Sent and stored: {name}")
        except Exception as e:
            print(f"[ERROR] Failed for {name}: {e}")
    print(f"[INFO] Done. New partners sent: {new_count}")


if __name__ == "__main__":
    process_partners()
