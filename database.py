import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pytz

NOVOSIBIRSK = pytz.timezone('Asia/Novosibirsk')

DB_NAME = "roulette_bot.db"

def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS roulettes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            status TEXT DEFAULT 'waiting_start',
            start_time TIMESTAMP,
            stop_time TIMESTAMP,
            duration INTEGER DEFAULT 5,
            winners_count INTEGER DEFAULT 0,
            trigger TEXT DEFAULT '+',
            prizes TEXT DEFAULT '[]',
            rules TEXT DEFAULT '',
            start_msg TEXT DEFAULT '',
            stop_msg TEXT DEFAULT '',
            result_msg TEXT DEFAULT '',
            participants_json TEXT DEFAULT '[]',
            winners_json TEXT DEFAULT '[]',
            seed_hash TEXT,
            seed TEXT,
            re_rolled_from INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER,
            username TEXT,
            banned_until TIMESTAMP,
            reason TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY
        );
        """)
        defaults = {
            "trigger": "+",
            "duration": "5",
            "rules": "Правила: отправь ${trigger} для участия. Запись ${duration} мин.",
            "start_msg": "🎲 Старт! Пиши ${trigger}",
            "stop_msg": "⏰ Стоп!",
            "result_msg": "Победители:\n{winners}",
            "chat_id": "",
            "max_participants": "0",
            "prizes": "[]"
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

def parse_datetime(date_str: str) -> datetime:
    """Преобразует строку в aware datetime с таймзоной Новосибирска."""
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = NOVOSIBIRSK.localize(dt)
        return dt
    except:
        return datetime.now(NOVOSIBIRSK)

def get_setting(key: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

def get_channels() -> List[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT channel_id FROM channels").fetchall()
        return [r["channel_id"] for r in rows]

def add_channel(channel_id: str):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", (channel_id,))

def remove_channel(channel_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM channels WHERE channel_id=?", (channel_id,))

def add_banned_user(user_id: Optional[int], username: Optional[str], days: int, reason: str = ""):
    banned_until = datetime.now() + timedelta(days=days)
    with get_conn() as conn:
        if user_id:
            conn.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
        if username and not user_id:
            conn.execute("DELETE FROM banned_users WHERE username=? AND user_id IS NULL", (username,))
        conn.execute("INSERT INTO banned_users (user_id, username, banned_until, reason) VALUES (?,?,?,?)",
                     (user_id, username, banned_until, reason))

def is_user_banned(user_id: int, username: Optional[str]) -> bool:
    with get_conn() as conn:
        now = datetime.now()
        row = conn.execute("SELECT 1 FROM banned_users WHERE (user_id=? OR (username=? AND user_id IS NULL)) AND banned_until > ?",
                           (user_id, username, now)).fetchone()
        return row is not None

def clean_expired_bans():
    with get_conn() as conn:
        conn.execute("DELETE FROM banned_users WHERE banned_until <= ?", (datetime.now(),))

def save_roulette(chat_id: int, status: str, duration: int, winners_count: int,
                  trigger: str, prizes: str, rules: str, start_msg: str, stop_msg: str,
                  result_msg: str, start_time: datetime, stop_time: datetime,
                  seed: str = None, seed_hash: str = None) -> int:
    with get_conn() as conn:
        cur = conn.execute("""INSERT INTO roulettes (chat_id, status, duration, winners_count, trigger, prizes, rules, start_msg, stop_msg, result_msg, start_time, stop_time, seed, seed_hash)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (chat_id, status, duration, winners_count, trigger, prizes, rules, start_msg, stop_msg, result_msg,
                       start_time, stop_time, seed, seed_hash))
        return cur.lastrowid

def update_roulette(roulette_id: int, **kwargs):
    with get_conn() as conn:
        fields = ', '.join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [roulette_id]
        conn.execute(f"UPDATE roulettes SET {fields} WHERE id=?", values)

def get_roulette(chat_id: int, status: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        if status:
            row = conn.execute("SELECT * FROM roulettes WHERE chat_id=? AND status=? ORDER BY id DESC LIMIT 1", (chat_id, status)).fetchone()
        else:
            row = conn.execute("SELECT * FROM roulettes WHERE chat_id=? ORDER BY id DESC LIMIT 1", (chat_id,)).fetchone()
        return dict(row) if row else None

def get_roulette_by_id(roulette_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM roulettes WHERE id=?", (roulette_id,)).fetchone()
        return dict(row) if row else None

def get_last_finished_roulette(chat_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM roulettes WHERE chat_id=? AND status='finished' AND start_time > ? ORDER BY id DESC LIMIT 1",
                           (chat_id, datetime.now() - timedelta(hours=48))).fetchone()
        return dict(row) if row else None

def delete_old_roulettes(hours: int = 48):
    with get_conn() as conn:
        conn.execute("DELETE FROM roulettes WHERE start_time < ?", (datetime.now() - timedelta(hours=hours),))
