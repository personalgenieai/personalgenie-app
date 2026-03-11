#!/usr/bin/env python3
"""
tools/imessage_export.py — Export iMessage conversations and send to the PersonalGenie backend.

Run this on your Mac:
    python3 tools/imessage_export.py --user-id <your-user-id>

What it does:
1. Opens ~/Library/Messages/chat.db (read-only)
2. Finds the top N contacts by message volume (default 30)
3. Resolves phone numbers / emails to real names via macOS Contacts.app (AppleScript)
4. Sends each conversation to the backend for Claude analysis
5. Claude enriches your People Graph with memories, closeness updates, and moments

Requirements:
- macOS with Messages.app set up
- Terminal must have Full Disk Access (System Preferences → Privacy & Security → Full Disk Access)
- pip install requests (standard, usually already installed)
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_BACKEND_URL = "https://precious-hope-production-f0e3.up.railway.app"
CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

# Apple epoch: seconds since 2001-01-01 00:00:00 UTC
# (chat.db stores timestamps as nanoseconds in this epoch on newer macOS)
APPLE_EPOCH_OFFSET = 978307200  # seconds between Unix epoch and Apple epoch

# How many top contacts to export (ranked by message count)
DEFAULT_TOP_N = 30

# Minimum messages in a conversation to bother sending
MIN_MESSAGES = 5

# Maximum messages per conversation to send (most recent)
MAX_MESSAGES_PER_CONV = 200


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def apple_ts_to_iso(ts: int) -> str:
    """
    Convert an Apple epoch timestamp (nanoseconds since 2001-01-01) to ISO-8601.
    Older macOS versions store seconds, newer store nanoseconds.
    We detect which by magnitude.
    """
    # Nanoseconds if larger than ~1e16, seconds otherwise
    if ts > 1_000_000_000_000:
        ts_seconds = ts / 1_000_000_000
    else:
        ts_seconds = ts
    unix_ts = ts_seconds + APPLE_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()


# ── Contact name resolution ───────────────────────────────────────────────────

# phone_digits → name  (built once, then O(1) lookup)
_phone_to_name: dict = {}
_email_to_name: dict = {}
_contacts_loaded = False


def _normalise_phone(phone: str) -> str:
    """Strip all non-digit characters for fuzzy matching."""
    return "".join(c for c in phone if c.isdigit())


def _load_all_contacts() -> None:
    """
    Fetch every contact from Contacts.app in a single AppleScript call.
    Builds phone→name and email→name lookup dicts.
    Falls back silently if Contacts access is denied.
    """
    global _contacts_loaded
    if _contacts_loaded:
        return

    # One AppleScript call that returns tab-separated lines: name\tphone_or_email
    script = """
tell application "Contacts"
    set output to ""
    repeat with p in every person
        set pname to name of p
        repeat with ph in every phone of p
            set output to output & pname & "\t" & (value of ph) & "\n"
        end repeat
        repeat with em in every email of p
            set output to output & pname & "\t" & (value of em) & "\n"
        end repeat
    end repeat
    return output
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            name, value = parts[0].strip(), parts[1].strip()
            if not name or not value:
                continue
            if "@" in value:
                _email_to_name[value.lower()] = name
            else:
                digits = _normalise_phone(value)
                if digits:
                    # Store last-7, last-10, full digits for flexible matching
                    for suffix_len in (7, 10, len(digits)):
                        key = digits[-suffix_len:] if len(digits) >= suffix_len else digits
                        _phone_to_name.setdefault(key, name)
    except Exception:
        pass  # Contacts access denied or app not running — use raw identifiers

    _contacts_loaded = True


def resolve_contact_name(identifier: str) -> str:
    """
    Look up a phone number or email in the contacts dicts.
    Falls back to the raw identifier if not found.
    """
    _load_all_contacts()

    if "@" in identifier:
        return _email_to_name.get(identifier.lower(), identifier)

    digits = _normalise_phone(identifier)
    # Try last-10 digits first (handles country code variations), then last-7
    for suffix_len in (10, 7):
        if len(digits) >= suffix_len:
            name = _phone_to_name.get(digits[-suffix_len:])
            if name:
                return name

    return identifier


# ── Read chat.db ──────────────────────────────────────────────────────────────

def read_conversations(top_n: int = DEFAULT_TOP_N) -> list:
    """
    Read the top N conversations from chat.db by message volume.
    Returns a list of conversation dicts ready to POST to the backend.
    """
    if not os.path.exists(CHAT_DB_PATH):
        print(f"ERROR: chat.db not found at {CHAT_DB_PATH}")
        print("Make sure Terminal has Full Disk Access in System Preferences.")
        sys.exit(1)

    # Copy chat.db to a temp file — it's locked by Messages.app
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(CHAT_DB_PATH, tmp.name)
        return _extract_from_db(tmp.name, top_n)
    finally:
        os.unlink(tmp.name)


def _extract_from_db(db_path: str, top_n: int) -> list:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Find top handles by message count
    cur.execute("""
        SELECT
            h.id AS identifier,
            COUNT(m.rowid) AS msg_count
        FROM handle h
        JOIN chat_handle_join chj ON chj.handle_id = h.rowid
        JOIN chat_message_join cmj ON cmj.chat_id = chj.chat_id
        JOIN message m ON m.rowid = cmj.message_id
        WHERE m.text IS NOT NULL AND m.text != ''
        GROUP BY h.id
        ORDER BY msg_count DESC
        LIMIT ?
    """, (top_n,))

    top_handles = cur.fetchall()

    conversations = []
    total = len(top_handles)

    print("  Loading contacts from Contacts.app...", end=" ", flush=True)
    _load_all_contacts()
    print(f"done ({len(_phone_to_name)} phone entries, {len(_email_to_name)} email entries)")

    for idx, row in enumerate(top_handles, 1):
        identifier = row["identifier"]
        msg_count = row["msg_count"]

        contact_name = resolve_contact_name(identifier)
        print(f"  [{idx}/{total}] {contact_name} ({msg_count} messages)")

        # Fetch up to MAX_MESSAGES_PER_CONV most recent messages for this handle
        cur.execute("""
            SELECT
                m.text,
                m.date,
                m.is_from_me
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.rowid
            JOIN chat_handle_join chj ON chj.chat_id = cmj.chat_id
            JOIN handle h ON h.rowid = chj.handle_id
            WHERE h.id = ?
              AND m.text IS NOT NULL
              AND m.text != ''
            ORDER BY m.date DESC
            LIMIT ?
        """, (identifier, MAX_MESSAGES_PER_CONV))

        raw_messages = cur.fetchall()

        if len(raw_messages) < MIN_MESSAGES:
            print(f"    → skipping (only {len(raw_messages)} messages)")
            continue

        # Reverse so chronological order
        messages = []
        for msg in reversed(raw_messages):
            messages.append({
                "timestamp": apple_ts_to_iso(msg["date"]),
                "text": msg["text"],
                "is_from_me": bool(msg["is_from_me"]),
            })

        conversations.append({
            "contact_name": contact_name,
            "contact_identifier": identifier,
            "messages": messages,
        })

    conn.close()
    return conversations


# ── Send to backend ───────────────────────────────────────────────────────────

def send_to_backend(user_id: str, conversations: list, backend_url: str) -> None:
    url = f"{backend_url}/messages/import/imessage"
    payload = {
        "user_id": user_id,
        "conversations": conversations,
    }

    print(f"\nSending {len(conversations)} conversations to {url} ...")
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        print(f"Queued: {data}")
    except requests.HTTPError as e:
        print(f"ERROR: HTTP {e.response.status_code} — {e.response.text[:300]}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Export iMessage conversations and send to PersonalGenie for analysis."
    )
    parser.add_argument("--user-id", required=True, help="Your PersonalGenie user ID")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL, help="Backend URL")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                        help=f"Number of top contacts to export (default {DEFAULT_TOP_N})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read and resolve contacts but don't send to backend")
    args = parser.parse_args()

    print(f"Reading iMessage database...")
    print(f"  Path: {CHAT_DB_PATH}")
    print(f"  Top {args.top_n} contacts\n")

    conversations = read_conversations(top_n=args.top_n)

    print(f"\nFound {len(conversations)} conversations with ≥{MIN_MESSAGES} messages.")

    if args.dry_run:
        print("\nDry run — not sending. Sample output:")
        for conv in conversations[:3]:
            print(f"  {conv['contact_name']} ({conv['contact_identifier']}): {len(conv['messages'])} messages")
        return

    if not conversations:
        print("Nothing to send.")
        return

    send_to_backend(args.user_id, conversations, args.backend_url)
    print("\nDone. Genie is analysing your conversations in the background.")
    print("Check WhatsApp in ~2-3 minutes for updated insights.")


if __name__ == "__main__":
    main()
