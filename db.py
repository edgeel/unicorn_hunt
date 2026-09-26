from __future__ import annotations

import datetime as dt
import os
import random
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from data import LOCATIONS, UNICORNS, UNICORN_BY_ID

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "unicorns.db"))
BACKUP_DIR = BASE_DIR / "backups"
try:
    MOSCOW = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:
    # Windows may not ship the IANA time-zone database. Moscow has used UTC+3
    # year-round since 2014, which is sufficient for all current game logic.
    MOSCOW = dt.timezone(dt.timedelta(hours=3), name="MSK")


@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def backup_once_per_day():
    if not DB_PATH.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"unicorns_{dt.datetime.now():%Y-%m-%d}.db"
    if not target.exists():
        shutil.copy2(DB_PATH, target)


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def ensure_column(conn, table, name, definition):
    if name not in columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db():
    backup_once_per_day()
    with connection() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS players(
            id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            last_hunt INTEGER DEFAULT 0,
            hunts INTEGER DEFAULT 0,
            caught INTEGER DEFAULT 0,
            empty INTEGER DEFAULT 0,
            bait_found INTEGER DEFAULT 0,
            active_bait TEXT,
            current_location TEXT DEFAULT 'forest',
            pity_misses INTEGER DEFAULT 0,
            rarity_pity INTEGER DEFAULT 0,
            last_unicorn_id TEXT,
            duplicate_streak INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS unicorn_inventory(
            user_id INTEGER,
            unicorn_id TEXT,
            amount INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, unicorn_id)
        );
        CREATE TABLE IF NOT EXISTS bait_inventory(
            user_id INTEGER,
            bait_id TEXT,
            amount INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, bait_id)
        );
        CREATE TABLE IF NOT EXISTS location_progress(
            user_id INTEGER,
            location_id TEXT,
            research_xp INTEGER DEFAULT 0,
            hunts INTEGER DEFAULT 0,
            catches INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, location_id)
        );
        CREATE TABLE IF NOT EXISTS unicorn_instances(
            instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            unicorn_id TEXT,
            caught_at INTEGER,
            location_id TEXT,
            weather TEXT,
            score REAL,
            height_cm REAL,
            horn_cm REAL,
            age_label TEXT,
            coat TEXT,
            temperament TEXT,
            legacy INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS achievements(
            user_id INTEGER,
            achievement_id TEXT,
            unlocked_at INTEGER,
            PRIMARY KEY(user_id, achievement_id)
        );
        CREATE TABLE IF NOT EXISTS star_payments(
            telegram_charge_id TEXT PRIMARY KEY,
            provider_charge_id TEXT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL,
            payload TEXT NOT NULL,
            paid_at INTEGER NOT NULL,
            fulfilled_at INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS player_chats(
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            last_seen INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, chat_id)
        );
        CREATE TABLE IF NOT EXISTS hunt_events(
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            happened_at INTEGER NOT NULL,
            kind TEXT NOT NULL,
            location_id TEXT,
            unicorn_id TEXT,
            tier INTEGER,
            bait_used TEXT,
            research_gain INTEGER DEFAULT 0,
            score REAL,
            paid INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_hunt_events_user_time ON hunt_events(user_id, happened_at);
        CREATE INDEX IF NOT EXISTS idx_hunt_events_time ON hunt_events(happened_at);
        CREATE TABLE IF NOT EXISTS hunt_days(
            user_id INTEGER NOT NULL,
            day_key TEXT NOT NULL,
            PRIMARY KEY(user_id, day_key)
        );
        CREATE TABLE IF NOT EXISTS quest_claims(
            user_id INTEGER NOT NULL,
            period_type TEXT NOT NULL,
            period_key TEXT NOT NULL,
            quest_id TEXT NOT NULL,
            claimed_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, period_type, period_key, quest_id)
        );
        CREATE TABLE IF NOT EXISTS season_awards(
            season_key TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            metric TEXT NOT NULL,
            rank INTEGER NOT NULL,
            awarded_at INTEGER NOT NULL,
            PRIMARY KEY(season_key, user_id, metric)
        );
        CREATE TABLE IF NOT EXISTS test_settings(
            user_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            forced_kind TEXT,
            forced_species TEXT,
            forced_quality REAL,
            forced_weather TEXT,
            forced_location TEXT
        );
        CREATE TABLE IF NOT EXISTS traps(
            trap_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            location_id TEXT NOT NULL,
            day_key TEXT NOT NULL,
            set_at INTEGER NOT NULL,
            trigger_at INTEGER NOT NULL,
            resolved_at INTEGER DEFAULT 0,
            notified_at INTEGER DEFAULT 0,
            unicorn_id TEXT,
            instance_id INTEGER,
            UNIQUE(user_id, day_key)
        );
        CREATE INDEX IF NOT EXISTS idx_traps_due ON traps(trigger_at, resolved_at, notified_at);
        """)
        # Upgrade old installations in place.
        ensure_column(c, "players", "active_bait", "TEXT")
        ensure_column(c, "players", "current_location", "TEXT DEFAULT 'forest'")
        ensure_column(c, "players", "pity_misses", "INTEGER DEFAULT 0")
        ensure_column(c, "players", "username", "TEXT")
        ensure_column(c, "players", "rarity_pity", "INTEGER DEFAULT 0")
        ensure_column(c, "players", "last_unicorn_id", "TEXT")
        ensure_column(c, "players", "duplicate_streak", "INTEGER DEFAULT 0")
        ensure_column(c, "players", "is_admin", "INTEGER DEFAULT 0")
        ensure_column(c, "star_payments", "fulfilled_at", "INTEGER DEFAULT 0")
        ensure_column(c, "test_settings", "forced_location", "TEXT")
        ensure_column(c, "traps", "notified_at", "INTEGER DEFAULT 0")
        ensure_column(c, "traps", "unicorn_id", "TEXT")
        ensure_column(c, "traps", "instance_id", "INTEGER")

        users = [r["id"] for r in c.execute("SELECT id FROM players")]
        for uid in users:
            for loc in LOCATIONS:
                c.execute("INSERT OR IGNORE INTO location_progress(user_id, location_id) VALUES(?, ?)", (uid, loc))

        # Migration of old aggregate inventory: preserve quantity and create archive specimens.
        old_rows = c.execute("SELECT user_id, unicorn_id, amount FROM unicorn_inventory").fetchall()
        for r in old_rows:
            u = UNICORN_BY_ID.get(r["unicorn_id"])
            if not u:
                continue
            existing = c.execute(
                "SELECT COUNT(*) AS n FROM unicorn_instances WHERE user_id=? AND unicorn_id=?",
                (r["user_id"], r["unicorn_id"]),
            ).fetchone()["n"]
            for i in range(max(0, r["amount"] - existing)):
                rnd = random.Random(f'{r["user_id"]}-{r["unicorn_id"]}-{i}')
                c.execute("""INSERT INTO unicorn_instances
                    (user_id, unicorn_id, caught_at, location_id, weather, score, height_cm, horn_cm,
                     age_label, coat, temperament, legacy)
                    VALUES(?, ?, 0, ?, 'архивная запись', ?, ?, ?, ?, ?, ?, 1)""",
                    (r["user_id"], u["id"], u["location"], round(rnd.uniform(52, 88), 1),
                     round(rnd.uniform(140, 180), 1), round(rnd.uniform(24, 46), 1),
                     rnd.choice(["молодой", "взрослый", "зрелый"]), rnd.choice(u["coats"]),
                     rnd.choice(["спокойный", "осторожный", "любопытный"])))


def ensure_player(uid, name, username=None, chat_id=None, seen_at=None):
    with connection() as c:
        c.execute("""INSERT INTO players(id, name, username, current_location) VALUES(?, ?, ?, 'forest')
                     ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name,
                         username=COALESCE(excluded.username, players.username)""",
                  (uid, name, username))
        for loc in LOCATIONS:
            c.execute("INSERT OR IGNORE INTO location_progress(user_id, location_id) VALUES(?, ?)", (uid, loc))
        if chat_id is not None:
            c.execute("""INSERT INTO player_chats(user_id, chat_id, last_seen) VALUES(?, ?, ?)
                         ON CONFLICT(user_id, chat_id) DO UPDATE SET last_seen=excluded.last_seen""",
                      (uid, int(chat_id), int(seen_at or dt.datetime.now().timestamp())))


def set_admin(uid, value=True):
    with connection() as c:
        c.execute("UPDATE players SET is_admin=? WHERE id=?", (1 if value else 0, uid))


def unlock_tester_account(uid):
    """Grant testing access without touching catches or collection."""
    with connection() as c:
        c.execute("UPDATE players SET level=30, xp=0, is_admin=1 WHERE id=?", (uid,))
        for loc, cfg in LOCATIONS.items():
            c.execute("INSERT OR IGNORE INTO location_progress(user_id, location_id) VALUES(?, ?)", (uid, loc))
            c.execute(
                "UPDATE location_progress SET research_xp=MAX(research_xp, ?) WHERE user_id=? AND location_id=?",
                (int(cfg["research_cap"]), uid, loc),
            )
        c.execute("INSERT OR IGNORE INTO test_settings(user_id) VALUES(?)", (uid,))


def get_player(uid):
    with connection() as c:
        return c.execute("SELECT * FROM players WHERE id=?", (uid,)).fetchone()


def find_player(ref: str):
    ref = (ref or "").strip()
    with connection() as c:
        if ref.startswith("@"):
            return c.execute("SELECT * FROM players WHERE lower(username)=lower(?)", (ref[1:],)).fetchone()
        try:
            return c.execute("SELECT * FROM players WHERE id=?", (int(ref),)).fetchone()
        except ValueError:
            return c.execute("SELECT * FROM players WHERE lower(username)=lower(?)", (ref,)).fetchone()


def set_location(uid, loc):
    with connection() as c:
        c.execute("UPDATE players SET current_location=? WHERE id=?", (loc, uid))


def set_level(uid, level, xp=0):
    with connection() as c:
        c.execute("UPDATE players SET level=?, xp=? WHERE id=?", (int(level), int(xp), uid))


def reset_cooldown(uid):
    with connection() as c:
        c.execute("UPDATE players SET last_hunt=0 WHERE id=?", (uid,))


def get_progress(uid, loc):
    with connection() as c:
        return c.execute("SELECT * FROM location_progress WHERE user_id=? AND location_id=?", (uid, loc)).fetchone()


def all_progress(uid):
    with connection() as c:
        return c.execute("SELECT * FROM location_progress WHERE user_id=?", (uid,)).fetchall()


def set_research_percent(uid, loc, percent):
    cap = int(LOCATIONS[loc]["research_cap"])
    xp = round(cap * max(0, min(100, float(percent))) / 100)
    with connection() as c:
        c.execute("INSERT OR IGNORE INTO location_progress(user_id, location_id) VALUES(?, ?)", (uid, loc))
        c.execute("UPDATE location_progress SET research_xp=? WHERE user_id=? AND location_id=?", (xp, uid, loc))


def add_research(uid, loc, xp, caught=False):
    with connection() as c:
        c.execute("""UPDATE location_progress
                     SET research_xp=MIN(research_xp+?, ?), hunts=hunts+1, catches=catches+?
                     WHERE user_id=? AND location_id=?""",
                  (xp, int(LOCATIONS[loc]["research_cap"]), 1 if caught else 0, uid, loc))


def record_hunt(uid, kind, when, update_last_hunt=True):
    with connection() as c:
        fields = ["hunts=hunts+1"]
        args = []
        if update_last_hunt:
            fields.insert(0, "last_hunt=?")
            args.append(when)
        if kind == "unicorn":
            fields += ["caught=caught+1", "pity_misses=0"]
        elif kind == "bait":
            fields += ["bait_found=bait_found+1", "pity_misses=pity_misses+1"]
        else:
            fields += ["empty=empty+1", "pity_misses=pity_misses+1"]
        args.append(uid)
        c.execute(f"UPDATE players SET {','.join(fields)} WHERE id=?", args)


def record_catch_meta(uid, unicorn_id, tier):
    with connection() as c:
        p = c.execute("SELECT last_unicorn_id, duplicate_streak, rarity_pity FROM players WHERE id=?", (uid,)).fetchone()
        same = p and p["last_unicorn_id"] == unicorn_id
        dup = (p["duplicate_streak"] + 1) if same else 1
        rarity_pity = 0 if int(tier) >= 3 else int((p["rarity_pity"] if p else 0) or 0) + 1
        c.execute("UPDATE players SET last_unicorn_id=?, duplicate_streak=?, rarity_pity=? WHERE id=?",
                  (unicorn_id, dup, rarity_pity, uid))


def log_hunt_event(uid, when, kind, loc, *, unicorn_id=None, tier=None, bait_used=None,
                   research_gain=0, score=None, paid=False):
    day = dt.datetime.fromtimestamp(int(when), MOSCOW).strftime("%Y-%m-%d")
    with connection() as c:
        c.execute("""INSERT INTO hunt_events
            (user_id, happened_at, kind, location_id, unicorn_id, tier, bait_used, research_gain, score, paid)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, int(when), kind, loc, unicorn_id, tier, bait_used, int(research_gain), score, 1 if paid else 0))
        c.execute("INSERT OR IGNORE INTO hunt_days(user_id, day_key) VALUES(?, ?)", (uid, day))


def record_star_payment(uid, amount, currency, payload, telegram_charge_id, provider_charge_id, paid_at):
    with connection() as c:
        cur = c.execute(
            """INSERT OR IGNORE INTO star_payments
               (telegram_charge_id, provider_charge_id, user_id, amount, currency, payload, paid_at, fulfilled_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, 0)""",
            (telegram_charge_id, provider_charge_id, uid, amount, currency, payload, paid_at),
        )
        return cur.rowcount > 0


def get_star_payment(telegram_charge_id):
    with connection() as c:
        return c.execute("SELECT * FROM star_payments WHERE telegram_charge_id=?", (telegram_charge_id,)).fetchone()


def oldest_unfulfilled_star_payment(uid):
    with connection() as c:
        return c.execute("""SELECT * FROM star_payments
               WHERE user_id=? AND COALESCE(fulfilled_at, 0)=0
               ORDER BY paid_at ASC LIMIT 1""", (uid,)).fetchone()


def mark_star_payment_fulfilled(telegram_charge_id, fulfilled_at):
    with connection() as c:
        cur = c.execute("""UPDATE star_payments SET fulfilled_at=?
               WHERE telegram_charge_id=? AND COALESCE(fulfilled_at, 0)=0""",
            (fulfilled_at, telegram_charge_id))
        return cur.rowcount > 0


def add_xp(uid, amount, max_level, xp_needed):
    with connection() as c:
        p = c.execute("SELECT level, xp FROM players WHERE id=?", (uid,)).fetchone()
        level, xp = p["level"], p["xp"] + amount
        reached = []
        while level < max_level and xp >= xp_needed(level):
            xp -= xp_needed(level)
            level += 1
            reached.append(level)
        c.execute("UPDATE players SET level=?, xp=? WHERE id=?", (level, xp, uid))
        return level, xp, reached


def add_bait(uid, bait_id, amount=1):
    with connection() as c:
        c.execute("""INSERT INTO bait_inventory(user_id, bait_id, amount) VALUES(?, ?, ?)
                     ON CONFLICT(user_id, bait_id) DO UPDATE SET amount=amount+excluded.amount""",
                  (uid, bait_id, amount))


def get_baits(uid):
    with connection() as c:
        return c.execute("SELECT * FROM bait_inventory WHERE user_id=? ORDER BY amount DESC", (uid,)).fetchall()


def set_active_bait(uid, bait_id):
    with connection() as c:
        r = c.execute("SELECT amount FROM bait_inventory WHERE user_id=? AND bait_id=?", (uid, bait_id)).fetchone()
        if not r or r["amount"] <= 0:
            return False
        c.execute("UPDATE players SET active_bait=? WHERE id=?", (bait_id, uid))
        return True


def clear_active_bait(uid):
    with connection() as c:
        c.execute("UPDATE players SET active_bait=NULL WHERE id=?", (uid,))


def consume_bait(uid, bait_id):
    if not bait_id:
        return
    with connection() as c:
        r = c.execute("SELECT amount FROM bait_inventory WHERE user_id=? AND bait_id=?", (uid, bait_id)).fetchone()
        if not r:
            return
        if r["amount"] <= 1:
            c.execute("DELETE FROM bait_inventory WHERE user_id=? AND bait_id=?", (uid, bait_id))
            c.execute("UPDATE players SET active_bait=NULL WHERE id=?", (uid,))
        else:
            c.execute("UPDATE bait_inventory SET amount=amount-1 WHERE user_id=? AND bait_id=?", (uid, bait_id))


def add_instance(uid, u, spec, when, loc, weather):
    with connection() as c:
        c.execute("""INSERT INTO unicorn_inventory(user_id, unicorn_id, amount) VALUES(?, ?, 1)
                     ON CONFLICT(user_id, unicorn_id) DO UPDATE SET amount=amount+1""", (uid, u["id"]))
        cur = c.execute("""INSERT INTO unicorn_instances
        (user_id, unicorn_id, caught_at, location_id, weather, score, height_cm, horn_cm,
         age_label, coat, temperament, legacy)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (uid, u["id"], when, loc, weather, spec["score"], spec["height_cm"], spec["horn_cm"],
         spec["age_label"], spec["coat"], spec["temperament"]))
        return cur.lastrowid


def active_trap(uid):
    with connection() as c:
        return c.execute(
            """SELECT * FROM traps
               WHERE user_id=? AND COALESCE(resolved_at,0)=0
               ORDER BY set_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()


def trap_for_day(uid, day_key):
    with connection() as c:
        return c.execute(
            "SELECT * FROM traps WHERE user_id=? AND day_key=? LIMIT 1",
            (uid, str(day_key)),
        ).fetchone()


def place_trap(uid, chat_id, loc, day_key, set_at, trigger_at):
    """Create today's trap.

    Returns (status, row), where status is one of: placed, active, used.
    Only one unresolved trap may exist for a player, and only one trap may be
    placed per Moscow calendar day.
    """
    with connection() as c:
        active = c.execute(
            """SELECT * FROM traps WHERE user_id=? AND COALESCE(resolved_at,0)=0
               ORDER BY set_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if active:
            return "active", active
        used = c.execute(
            "SELECT * FROM traps WHERE user_id=? AND day_key=? LIMIT 1",
            (uid, str(day_key)),
        ).fetchone()
        if used:
            return "used", used
        cur = c.execute(
            """INSERT INTO traps(user_id,chat_id,location_id,day_key,set_at,trigger_at)
               VALUES(?,?,?,?,?,?)""",
            (uid, int(chat_id), loc, str(day_key), int(set_at), int(trigger_at)),
        )
        return "placed", c.execute("SELECT * FROM traps WHERE trap_id=?", (cur.lastrowid,)).fetchone()


def traps_due_for_delivery(now, limit=50):
    """Due traps that have not yet been successfully announced.

    Resolved-but-unannounced rows are intentionally included so a restart or
    temporary Telegram error cannot make a catch notification disappear.
    """
    with connection() as c:
        return c.execute(
            """SELECT * FROM traps
               WHERE trigger_at<=? AND COALESCE(notified_at,0)=0
               ORDER BY trigger_at ASC LIMIT ?""",
            (int(now), int(limit)),
        ).fetchall()


def get_trap(trap_id):
    with connection() as c:
        return c.execute("SELECT * FROM traps WHERE trap_id=?", (int(trap_id),)).fetchone()


def get_instance(instance_id):
    with connection() as c:
        return c.execute("SELECT * FROM unicorn_instances WHERE instance_id=?", (int(instance_id),)).fetchone()


def resolve_trap_capture(trap_id, u, spec, when, weather, research_gain, max_level, xp_needed):
    """Atomically turn a due trap into a caught specimen.

    All durable game-state changes happen in one SQLite transaction. If the
    process dies before commit, the trap remains pending; after commit, the
    notification can safely be retried without creating a duplicate specimen.
    """
    with connection() as c:
        trap = c.execute("SELECT * FROM traps WHERE trap_id=?", (int(trap_id),)).fetchone()
        if not trap:
            return None
        if int(trap["resolved_at"] or 0) > 0:
            return {
                "trap": trap,
                "instance_id": trap["instance_id"],
                "new_level": None,
                "reached": [],
                "already_resolved": True,
            }
        if int(trap["trigger_at"]) > int(when):
            return None

        uid = int(trap["user_id"])
        loc = trap["location_id"]
        c.execute(
            """INSERT INTO unicorn_inventory(user_id, unicorn_id, amount) VALUES(?, ?, 1)
               ON CONFLICT(user_id, unicorn_id) DO UPDATE SET amount=amount+1""",
            (uid, u["id"]),
        )
        cur = c.execute(
            """INSERT INTO unicorn_instances
               (user_id, unicorn_id, caught_at, location_id, weather, score, height_cm, horn_cm,
                age_label, coat, temperament, legacy)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                uid, u["id"], int(when), loc, weather, spec["score"], spec["height_cm"],
                spec["horn_cm"], spec["age_label"], spec["coat"], spec["temperament"],
            ),
        )
        instance_id = cur.lastrowid

        # A trap catch counts as a successful expedition for aggregate stats,
        # but deliberately does not touch last_hunt or the active-hunt pity.
        c.execute("UPDATE players SET hunts=hunts+1, caught=caught+1 WHERE id=?", (uid,))
        cap = int(LOCATIONS[loc]["research_cap"])
        c.execute(
            """UPDATE location_progress
               SET research_xp=MIN(research_xp+?, ?), hunts=hunts+1, catches=catches+1
               WHERE user_id=? AND location_id=?""",
            (int(research_gain), cap, uid, loc),
        )

        p = c.execute("SELECT level,xp FROM players WHERE id=?", (uid,)).fetchone()
        level = int(p["level"])
        xp = int(p["xp"]) + int(u["xp"])
        reached = []
        while level < int(max_level) and xp >= xp_needed(level):
            xp -= xp_needed(level)
            level += 1
            reached.append(level)
        c.execute("UPDATE players SET level=?,xp=? WHERE id=?", (level, xp, uid))

        day = dt.datetime.fromtimestamp(int(when), MOSCOW).strftime("%Y-%m-%d")
        c.execute(
            """INSERT INTO hunt_events
               (user_id,happened_at,kind,location_id,unicorn_id,tier,bait_used,research_gain,score,paid)
               VALUES(?,?,?,?,?,?,?,?,?,0)""",
            (uid, int(when), "unicorn", loc, u["id"], int(u["tier"]), None, int(research_gain), spec["score"]),
        )
        c.execute("INSERT OR IGNORE INTO hunt_days(user_id,day_key) VALUES(?,?)", (uid, day))
        c.execute(
            """UPDATE traps SET resolved_at=?, unicorn_id=?, instance_id=?
               WHERE trap_id=? AND COALESCE(resolved_at,0)=0""",
            (int(when), u["id"], int(instance_id), int(trap_id)),
        )
        trap2 = c.execute("SELECT * FROM traps WHERE trap_id=?", (int(trap_id),)).fetchone()
        return {
            "trap": trap2,
            "instance_id": instance_id,
            "new_level": level,
            "reached": reached,
            "already_resolved": False,
        }


def mark_trap_notified(trap_id, when):
    with connection() as c:
        c.execute(
            "UPDATE traps SET notified_at=? WHERE trap_id=? AND COALESCE(notified_at,0)=0",
            (int(when), int(trap_id)),
        )


def inventory(uid):
    with connection() as c:
        return c.execute("SELECT * FROM unicorn_inventory WHERE user_id=? AND amount>0 ORDER BY amount DESC", (uid,)).fetchall()


def species_amount(uid, sid):
    with connection() as c:
        r = c.execute("SELECT amount FROM unicorn_inventory WHERE user_id=? AND unicorn_id=?", (uid, sid)).fetchone()
        return r["amount"] if r else 0


def unique_count(uid):
    with connection() as c:
        return c.execute("SELECT COUNT(*) AS n FROM unicorn_inventory WHERE user_id=? AND amount>0", (uid,)).fetchone()["n"]


def best_instance(uid, sid):
    with connection() as c:
        return c.execute("""SELECT * FROM unicorn_instances WHERE user_id=? AND unicorn_id=?
                            ORDER BY score DESC, caught_at DESC LIMIT 1""", (uid, sid)).fetchone()


def best_instance_overall(uid):
    with connection() as c:
        return c.execute("""SELECT * FROM unicorn_instances WHERE user_id=?
                            ORDER BY score DESC, caught_at DESC LIMIT 1""", (uid,)).fetchone()


def recent_instances(uid, sid, limit=8):
    with connection() as c:
        return c.execute("""SELECT * FROM unicorn_instances WHERE user_id=? AND unicorn_id=?
                            ORDER BY score DESC, caught_at DESC LIMIT ?""", (uid, sid, limit)).fetchall()


def last_instances(uid, limit=2):
    with connection() as c:
        return c.execute("""SELECT * FROM unicorn_instances WHERE user_id=? AND caught_at>0
                            ORDER BY caught_at DESC, instance_id DESC LIMIT ?""", (uid, limit)).fetchall()


def unlock_achievement(uid, aid, when):
    with connection() as c:
        cur = c.execute("INSERT OR IGNORE INTO achievements(user_id, achievement_id, unlocked_at) VALUES(?, ?, ?)",
                        (uid, aid, when))
        return cur.rowcount > 0


def achievements(uid):
    with connection() as c:
        return {r["achievement_id"] for r in c.execute("SELECT achievement_id FROM achievements WHERE user_id=?", (uid,))}


def leaderboard_global(limit=10, since=None):
    with connection() as c:
        where = "WHERE i.caught_at >= ?" if since is not None else ""
        args = [int(since)] if since is not None else []
        args.append(int(limit))
        return c.execute(
            f"""SELECT p.id, p.name, p.username, COUNT(i.instance_id) AS caught_count
                FROM players p JOIN unicorn_instances i ON i.user_id=p.id
                {where}
                GROUP BY p.id, p.name, p.username
                HAVING COUNT(i.instance_id) > 0
                ORDER BY caught_count DESC, p.id ASC LIMIT ?""", args).fetchall()


def leaderboard_chat(chat_id, limit=10, since=None):
    with connection() as c:
        where = "AND i.caught_at >= ?" if since is not None else ""
        args = [int(chat_id)]
        if since is not None:
            args.append(int(since))
        args.append(int(limit))
        return c.execute(
            f"""SELECT p.id, p.name, p.username, COUNT(i.instance_id) AS caught_count
                FROM players p JOIN player_chats pc ON pc.user_id=p.id AND pc.chat_id=?
                JOIN unicorn_instances i ON i.user_id=p.id
                WHERE 1=1 {where}
                GROUP BY p.id, p.name, p.username
                HAVING COUNT(i.instance_id) > 0
                ORDER BY caught_count DESC, p.id ASC LIMIT ?""", args).fetchall()


def global_rank(uid, since=None):
    rows = leaderboard_global(1_000_000, since=since)
    for idx, r in enumerate(rows, 1):
        if int(r["id"]) == int(uid):
            return idx
    return None


def season_leaderboard_catches(start, end, limit=10):
    with connection() as c:
        return c.execute("""SELECT p.id, p.name, p.username, COUNT(i.instance_id) AS caught_count
            FROM unicorn_instances i JOIN players p ON p.id=i.user_id
            WHERE i.caught_at>=? AND i.caught_at<?
            GROUP BY p.id, p.name, p.username
            ORDER BY caught_count DESC, p.id ASC LIMIT ?""", (int(start), int(end), int(limit))).fetchall()


def season_leaderboard_prestige(start, end, limit=10):
    with connection() as c:
        rows = c.execute("""SELECT i.user_id, i.unicorn_id, i.score, p.name, p.username
                            FROM unicorn_instances i JOIN players p ON p.id=i.user_id
                            WHERE i.caught_at>=? AND i.caught_at<?""", (int(start), int(end))).fetchall()
    agg = {}
    meta = {}
    for r in rows:
        u = UNICORN_BY_ID.get(r["unicorn_id"])
        if not u:
            continue
        uid = int(r["user_id"])
        # Tier matters much more than tiny quality differences, while quality still breaks close totals.
        points = (u["tier"] + 1) * 100 + float(r["score"] or 0)
        agg[uid] = agg.get(uid, 0.0) + points
        meta[uid] = (r["name"], r["username"])
    out = []
    for uid, score in sorted(agg.items(), key=lambda x: (-x[1], x[0]))[:limit]:
        out.append({"id": uid, "name": meta[uid][0], "username": meta[uid][1], "prestige": round(score)})
    return out


def finalize_season(season_key, start, end, now=None):
    now = int(now or dt.datetime.now().timestamp())
    catches = season_leaderboard_catches(start, end, 10)
    prestige = season_leaderboard_prestige(start, end, 10)
    with connection() as c:
        for metric, rows in (("catches", catches), ("prestige", prestige)):
            for rank, r in enumerate(rows, 1):
                cur = c.execute("""INSERT OR IGNORE INTO season_awards(season_key,user_id,metric,rank,awarded_at)
                             VALUES(?,?,?,?,?)""", (season_key, int(r["id"]), metric, rank, now))
                if cur.rowcount > 0:
                    # Tangible but modest season reward; idempotent because it is tied to the award insert.
                    if rank == 1:
                        bait_id, amount = "dew", 2
                    elif rank <= 3:
                        bait_id, amount = "dew", 1
                    else:
                        bait_id, amount = "clover", 1
                    c.execute("""INSERT INTO bait_inventory(user_id,bait_id,amount) VALUES(?,?,?)
                                 ON CONFLICT(user_id,bait_id) DO UPDATE SET amount=amount+excluded.amount""",
                              (int(r["id"]), bait_id, amount))


def season_awards(uid, limit=8):
    with connection() as c:
        return c.execute("""SELECT * FROM season_awards WHERE user_id=? ORDER BY season_key DESC, metric, rank LIMIT ?""",
                         (uid, int(limit))).fetchall()


def quest_metric(uid, start, end, metric):
    with connection() as c:
        args = (uid, int(start), int(end))
        if metric == "hunts":
            return c.execute("SELECT COUNT(*) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<?", args).fetchone()["n"]
        if metric == "catches":
            return c.execute("SELECT COUNT(*) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<? AND kind='unicorn'", args).fetchone()["n"]
        if metric == "research":
            return c.execute("SELECT COALESCE(SUM(research_gain),0) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<?", args).fetchone()["n"]
        if metric == "bait_found":
            return c.execute("SELECT COUNT(*) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<? AND kind='bait'", args).fetchone()["n"]
        if metric == "unique_species":
            return c.execute("SELECT COUNT(DISTINCT unicorn_id) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<? AND kind='unicorn'", args).fetchone()["n"]
        if metric == "rare_catches":
            return c.execute("SELECT COUNT(*) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<? AND kind='unicorn' AND tier>=2", args).fetchone()["n"]
        if metric == "locations":
            return c.execute("SELECT COUNT(DISTINCT location_id) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<?", args).fetchone()["n"]
        if metric == "high_quality":
            return c.execute("SELECT COUNT(*) n FROM hunt_events WHERE user_id=? AND happened_at>=? AND happened_at<? AND kind='unicorn' AND score>=90", args).fetchone()["n"]
    return 0


def quest_claimed(uid, period_type, period_key, quest_id):
    with connection() as c:
        return c.execute("""SELECT 1 FROM quest_claims WHERE user_id=? AND period_type=? AND period_key=? AND quest_id=?""",
                         (uid, period_type, period_key, quest_id)).fetchone() is not None


def claim_quest(uid, period_type, period_key, quest_id, when):
    with connection() as c:
        cur = c.execute("""INSERT OR IGNORE INTO quest_claims(user_id,period_type,period_key,quest_id,claimed_at)
                           VALUES(?,?,?,?,?)""", (uid, period_type, period_key, quest_id, int(when)))
        return cur.rowcount > 0


def streaks(uid, today=None):
    if today is None:
        today = dt.datetime.now(MOSCOW).date()
    elif isinstance(today, str):
        today = dt.date.fromisoformat(today)
    with connection() as c:
        vals = [dt.date.fromisoformat(r["day_key"]) for r in c.execute(
            "SELECT day_key FROM hunt_days WHERE user_id=? ORDER BY day_key", (uid,)).fetchall()]
    if not vals:
        return 0, 0
    unique = sorted(set(vals))
    max_streak = cur = 1
    for a, b in zip(unique, unique[1:]):
        if (b - a).days == 1:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 1
    last = unique[-1]
    if last not in {today, today - dt.timedelta(days=1)}:
        current = 0
    else:
        current = 1
        i = len(unique) - 1
        while i > 0 and (unique[i] - unique[i-1]).days == 1:
            current += 1
            i -= 1
    return current, max_streak


def favorite_location(uid):
    with connection() as c:
        return c.execute("""SELECT location_id, hunts, catches FROM location_progress WHERE user_id=?
                            ORDER BY hunts DESC, catches DESC LIMIT 1""", (uid,)).fetchone()


def rarest_instance(uid):
    with connection() as c:
        rows = c.execute("""SELECT * FROM unicorn_instances WHERE user_id=? ORDER BY caught_at DESC""", (uid,)).fetchall()
    best = None
    best_key = (-1, -1)
    for r in rows:
        u = UNICORN_BY_ID.get(r["unicorn_id"])
        if not u:
            continue
        key = (u["tier"], float(r["score"] or 0))
        if key > best_key:
            best, best_key = r, key
    return best


def first_hunt_time(uid):
    with connection() as c:
        r = c.execute("SELECT MIN(happened_at) t FROM hunt_events WHERE user_id=?", (uid,)).fetchone()
        return r["t"] if r and r["t"] is not None else None


def get_test_settings(uid):
    with connection() as c:
        c.execute("INSERT OR IGNORE INTO test_settings(user_id) VALUES(?)", (uid,))
        return c.execute("SELECT * FROM test_settings WHERE user_id=?", (uid,)).fetchone()


def set_test_setting(uid, **kwargs):
    allowed = {"enabled", "forced_kind", "forced_species", "forced_quality", "forced_weather", "forced_location"}
    items = [(k, v) for k, v in kwargs.items() if k in allowed]
    if not items:
        return
    with connection() as c:
        c.execute("INSERT OR IGNORE INTO test_settings(user_id) VALUES(?)", (uid,))
        sql = ", ".join(f"{k}=?" for k, _ in items)
        c.execute(f"UPDATE test_settings SET {sql} WHERE user_id=?", [v for _, v in items] + [uid])


def owner_stats(now):
    since = int(now) - 86400
    with connection() as c:
        total_players = c.execute("SELECT COUNT(*) n FROM players").fetchone()["n"]
        dau = c.execute("SELECT COUNT(*) n FROM players WHERE last_hunt>=?", (since,)).fetchone()["n"]
        hunts24 = c.execute("SELECT COUNT(*) n FROM hunt_events WHERE happened_at>=?", (since,)).fetchone()["n"]
        active24 = c.execute("SELECT COUNT(DISTINCT user_id) n FROM hunt_events WHERE happened_at>=?", (since,)).fetchone()["n"]
        catches24 = c.execute("SELECT COUNT(*) n FROM unicorn_instances WHERE caught_at>=?", (since,)).fetchone()["n"]
        stars_total = c.execute("SELECT COALESCE(SUM(amount),0) n FROM star_payments WHERE currency='XTR'").fetchone()["n"]
        stars24 = c.execute("SELECT COALESCE(SUM(amount),0) n FROM star_payments WHERE currency='XTR' AND paid_at>=?", (since,)).fetchone()["n"]
        payers = c.execute("SELECT COUNT(DISTINCT user_id) n FROM star_payments WHERE currency='XTR'").fetchone()["n"]
        locs = c.execute("SELECT current_location, COUNT(*) n FROM players GROUP BY current_location ORDER BY n DESC").fetchall()
        hunt_locs24 = c.execute("""SELECT location_id, COUNT(*) n FROM hunt_events WHERE happened_at>=?
                                  GROUP BY location_id ORDER BY n DESC""", (since,)).fetchall()
        levels = c.execute("""SELECT CASE WHEN level<5 THEN '1–4' WHEN level<10 THEN '5–9'
                                   WHEN level<20 THEN '10–19' WHEN level<30 THEN '20–29' ELSE '30' END bucket,
                                   COUNT(*) n FROM players GROUP BY bucket ORDER BY MIN(level)""").fetchall()
        popular = c.execute("""SELECT unicorn_id, COUNT(*) n FROM unicorn_instances WHERE caught_at>=?
                               GROUP BY unicorn_id ORDER BY n DESC LIMIT 5""", (since,)).fetchall()
        species24 = c.execute("""SELECT unicorn_id, COUNT(*) n FROM unicorn_instances WHERE caught_at>=?
                                 GROUP BY unicorn_id""", (since,)).fetchall()
    return dict(total_players=total_players, dau=dau, hunts24=hunts24, active24=active24,
                catches24=catches24, stars_total=stars_total, stars24=stars24, payers=payers,
                locations=locs, hunt_locations24=hunt_locs24, levels=levels, popular=popular, species24=species24)
