"""
chat_reader.py — reads ~/Library/Messages/chat.db and extracts
conversations for a given phone number.

Requires Full Disk Access for Terminal in System Settings → Privacy & Security.
"""
import sqlite3
import os
from datetime import datetime, timezone

CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc).timestamp()


def normalize_variants(phone: str) -> list[str]:
    """Return several normalizations of a phone number to match chat.db handle formats."""
    digits = "".join(c for c in phone if c.isdigit())
    variants = set()
    # Full E.164
    if phone.startswith("+"):
        variants.add(phone)
    if digits:
        variants.add(f"+{digits}")
        # US without country code
        if digits.startswith("1") and len(digits) == 11:
            variants.add(digits[1:])        # 10-digit
            variants.add(f"+1{digits[1:]}")
        elif len(digits) == 10:
            variants.add(digits)
            variants.add(f"+1{digits}")
    return list(variants)


def _decode_attributed_body(blob: bytes) -> str | None:
    """Decode NSKeyedArchiver BLOB to plain text (fallback for older messages)."""
    try:
        parts = blob.split(b"NSString")
        if len(parts) < 2:
            return None
        data = parts[1][5:]
        length = data[0]
        if length == 0x81:
            length = int.from_bytes(data[1:3], "big")
            tb = data[3:3 + length]
        elif length == 0x82:
            length = int.from_bytes(data[1:5], "big")
            tb = data[5:5 + length]
        else:
            tb = data[1:1 + length]
        result = tb.decode("utf-8", errors="replace").strip().lstrip("\ufffc").strip()
        return result or None
    except Exception:
        return None


def _apple_ts_to_unix(ts: int | float) -> float:
    """Convert Apple's Mac absolute time (ns since 2001-01-01) to Unix timestamp."""
    if ts > 1_000_000_000_000_000:   # nanoseconds
        return APPLE_EPOCH + ts / 1e9
    elif ts > 1_000_000_000:          # looks like Unix already
        return float(ts)
    else:
        return APPLE_EPOCH + float(ts)


def _count_for_phone_conn(c, contact_phone: str) -> int:
    """Count messages for one phone using an existing cursor."""
    variants = normalize_variants(contact_phone)
    if not variants:
        return 0
    placeholders = ",".join("?" * len(variants))
    c.execute(f"SELECT ROWID FROM handle WHERE id IN ({placeholders})", variants)
    handle_ids = [r[0] for r in c.fetchall()]
    if not handle_ids:
        return 0
    hph = ",".join("?" * len(handle_ids))
    c.execute(
        f"SELECT DISTINCT chat_id FROM chat_handle_join WHERE handle_id IN ({hph})",
        handle_ids,
    )
    chat_ids = [r[0] for r in c.fetchall()]
    if not chat_ids:
        return 0
    cph = ",".join("?" * len(chat_ids))
    c.execute(
        f"SELECT COUNT(*) FROM message m JOIN chat_message_join cmj "
        f"ON m.ROWID = cmj.message_id WHERE cmj.chat_id IN ({cph})",
        chat_ids,
    )
    row = c.fetchone()
    return row[0] if row else 0


def count_messages(contact_phone: str) -> int:
    """Quick count of messages with a contact — no text decoding."""
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        count = _count_for_phone_conn(conn.cursor(), contact_phone)
        conn.close()
        return count
    except Exception as e:
        print(f"[chat_reader] count error: {e}")
        return 0


def batch_count_messages(phones: list[str]) -> dict[str, int]:
    """
    Count messages for many phones in one DB connection.
    Returns {phone: count}. Fast enough for 50+ contacts.
    """
    results: dict[str, int] = {}
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        for phone in phones:
            results[phone] = _count_for_phone_conn(cur, phone)
        conn.close()
    except Exception as e:
        print(f"[chat_reader] batch_count error: {e}")
    return results


def get_messages(contact_phone: str, max_messages: int = 3000) -> tuple[list[dict], int]:
    """
    Return (messages, total_count).
    messages = [{ text, is_from_me, timestamp }] sorted oldest→newest.
    Limited to last max_messages to fit Claude context.
    """
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        variants = normalize_variants(contact_phone)
        placeholders = ",".join("?" * len(variants))
        c.execute(
            f"SELECT ROWID FROM handle WHERE id IN ({placeholders})", variants
        )
        handle_ids = [r[0] for r in c.fetchall()]

        if not handle_ids:
            conn.close()
            return [], 0

        hph = ",".join("?" * len(handle_ids))
        c.execute(
            f"SELECT DISTINCT chat_id FROM chat_handle_join WHERE handle_id IN ({hph})",
            handle_ids,
        )
        chat_ids = [r[0] for r in c.fetchall()]

        if not chat_ids:
            conn.close()
            return [], 0

        cph = ",".join("?" * len(chat_ids))

        # Total count first
        c.execute(
            f"SELECT COUNT(*) FROM message m JOIN chat_message_join cmj "
            f"ON m.ROWID = cmj.message_id WHERE cmj.chat_id IN ({cph})",
            chat_ids,
        )
        total = c.fetchone()[0]

        # Fetch messages (most recent max_messages only)
        c.execute(
            f"""
            SELECT m.text, m.is_from_me, m.date, m.attributedBody
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            WHERE cmj.chat_id IN ({cph})
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (*chat_ids, max_messages),
        )
        rows = c.fetchall()
        conn.close()

        messages = []
        for row in reversed(rows):   # back to chronological order
            text = row["text"]
            if not text and row["attributedBody"]:
                text = _decode_attributed_body(bytes(row["attributedBody"]))
            if not text:
                continue
            text = text.strip().lstrip("\ufffc").strip()
            if not text:
                continue
            messages.append({
                "text": text,
                "is_from_me": bool(row["is_from_me"]),
                "timestamp": _apple_ts_to_unix(row["date"]) if row["date"] else 0,
            })

        return messages, total

    except Exception as e:
        print(f"[chat_reader] get_messages error: {e}")
        return [], 0
