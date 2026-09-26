from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import random
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from data import BAITS, DAILY_QUESTS, LOCATIONS, UNICORNS, WEEKLY_QUESTS, WORLD_EVENTS

COOLDOWN = 600
BASE_CATCH = 0.18
BASE_BAIT = 0.24
MAX_LEVEL = 30
try:
    MOSCOW = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:
    # Windows may not ship the IANA time-zone database. Moscow has used UTC+3
    # year-round since 2014, which is sufficient for all current game logic.
    MOSCOW = dt.timezone(dt.timedelta(hours=3), name="MSK")
UTC = dt.timezone.utc


def xp_needed(level: int) -> int:
    return round(70 + 42 * (level ** 1.42))


def research_percent(raw: int, loc: str) -> float:
    return min(100.0, 100.0 * raw / LOCATIONS[loc]["research_cap"])


def current_weather(loc: str, now: int | None = None):
    """One shared deterministic weather state per location for each hour."""
    now = int(now or time.time())
    slot = now // 3600
    pool = LOCATIONS[loc]["weather"]
    total = sum(x[2] for x in pool)
    seed = int(hashlib.sha256(f"weather:{loc}:{slot}".encode()).hexdigest()[:16], 16)
    r = random.Random(seed).uniform(0, total)
    acc = 0
    for name, emoji, weight in pool:
        acc += weight
        if r <= acc:
            return name, emoji, (slot + 1) * 3600 - now
    name, emoji, _ = pool[-1]
    return name, emoji, (slot + 1) * 3600 - now


def _week_start_utc(now: int) -> int:
    d = dt.datetime.fromtimestamp(now, UTC)
    monday = (d - dt.timedelta(days=d.weekday(), hours=d.hour, minutes=d.minute,
                               seconds=d.second, microseconds=d.microsecond))
    return int(monday.timestamp())


def current_world_event(now: int | None = None):
    """Shared deterministic world event.

    Two 2-hour slots per UTC week are reserved for the rare Ancient Call.
    Outside those windows a regular event may occupy a 4-hour slot.
    Returns (event_id|None, config|None, seconds_left).
    """
    now = int(now or time.time())
    week_start = _week_start_utc(now)
    two_hour_slot = (now - week_start) // 7200
    week_key = dt.datetime.fromtimestamp(week_start, UTC).strftime("%G-W%V")
    rnd = random.Random(int(hashlib.sha256(f"rare-event:{week_key}".encode()).hexdigest()[:16], 16))
    rare_slots = set(rnd.sample(range(84), 2))
    if two_hour_slot in rare_slots:
        left = week_start + (two_hour_slot + 1) * 7200 - now
        return "ancient_call", WORLD_EVENTS["ancient_call"], left

    four_hour_slot = now // 14400
    seed = int(hashlib.sha256(f"world-event:{four_hour_slot}".encode()).hexdigest()[:16], 16)
    rr = random.Random(seed)
    keys = [None, "rainbow", "moon_bloom", "crystal_storm", "starfall"]
    weights = [48, 16, 14, 10, 12]
    key = rr.choices(keys, weights=weights, k=1)[0]
    left = (four_hour_slot + 1) * 14400 - now
    return key, WORLD_EVENTS.get(key) if key else None, left


def event_modifiers(event_id: str | None, loc: str):
    if not event_id:
        return 0.0, 0.0, 0.0
    cfg = WORLD_EVENTS.get(event_id) or {}
    if cfg.get("location") and cfg["location"] != loc:
        return 0.0, 0.0, 0.0
    return float(cfg.get("catch_bonus", 0)), float(cfg.get("rarity_luck", 0)), float(cfg.get("bait_bonus", 0))


def catch_chance(pity_misses: int, bait_id: str | None, event_id: str | None = None, loc: str | None = None) -> float:
    # Encounter pity: repeated misses gradually make the next encounter more likely.
    pity_bonus = min(0.15, max(0, pity_misses) * 0.015)
    bait_bonus = BAITS[bait_id]["catch"] if bait_id else 0.0
    event_bonus = event_modifiers(event_id, loc)[0] if loc else 0.0
    return min(0.68, BASE_CATCH + pity_bonus + bait_bonus + event_bonus)


def eligible(level: int, loc: str, research: float, weather: str, bait_id: str | None,
             *, now: int | None = None, event_id: str | None = None, pity_misses: int = 0):
    now = int(now or time.time())
    hour_msk = dt.datetime.fromtimestamp(now, MOSCOW).hour
    result = []
    for u in UNICORNS:
        if u["location"] != loc:
            continue
        if level < u["level"] or research < u["min_research"]:
            continue
        if u.get("required_weather") and weather not in u["required_weather"]:
            continue
        if u.get("required_bait") and bait_id not in u["required_bait"]:
            continue
        if u.get("required_event") and event_id != u["required_event"]:
            continue
        if u.get("required_hours") and hour_msk not in u["required_hours"]:
            continue
        if pity_misses < int(u.get("required_misses", 0)):
            continue
        result.append(u)
    return result


def choose_unicorn(level: int, loc: str, research: float, weather: str, bait_id: str | None,
                   *, now: int | None = None, event_id: str | None = None,
                   rarity_pity: int = 0, last_unicorn_id: str | None = None,
                   duplicate_streak: int = 0, pity_misses: int = 0):
    pool = eligible(level, loc, research, weather, bait_id, now=now, event_id=event_id, pity_misses=pity_misses)
    if not pool:
        return None
    luck = BAITS[bait_id]["luck"] if bait_id else 0.0
    _, event_luck, _ = event_modifiers(event_id, loc)
    # Rarity pity grows after catches below Epic and increasingly benefits high tiers.
    rarity_boost = min(1.6, max(0, rarity_pity) * 0.08)
    weights = []
    for u in pool:
        tier = u["tier"]
        w = u["weight"] * ((1 + luck + event_luck) ** tier)
        w *= (1 + rarity_boost * (tier / 6.0))
        w *= u.get("weather_boost", {}).get(weather, 1.0)
        # Duplicate protection: repeated catches of the same species become progressively less likely.
        if last_unicorn_id and u["id"] == last_unicorn_id and duplicate_streak > 0:
            w *= max(0.12, 1.0 / (1.0 + duplicate_streak * 0.9))
        weights.append(max(w, 0.000001))
    return random.choices(pool, weights=weights, k=1)[0]


def choose_trap_unicorn(level: int, loc: str, research: float, weather: str,
                        *, now: int | None = None, event_id: str | None = None):
    """Choose the guaranteed catch for a passive trap.

    A trap does not use bait or pity and therefore cannot bypass bait-gated or
    other special encounter requirements. Weather/event-only species may still
    appear if their real conditions happen to be active when the trap fires.
    There are ordinary species in every location, so this normally always has
    a pool; the fallback keeps the 100% guarantee even after future data edits.
    """
    u = choose_unicorn(
        level, loc, research, weather, None,
        now=now, event_id=event_id, rarity_pity=0,
        last_unicorn_id=None, duplicate_streak=0, pity_misses=0,
    )
    if u is not None:
        return u
    fallback = [
        x for x in UNICORNS
        if x["location"] == loc
        and level >= x["level"]
        and research >= x["min_research"]
        and not x.get("secret")
        and not x.get("required_bait")
        and not x.get("required_event")
        and not x.get("required_hours")
        and not x.get("required_misses")
    ]
    if not fallback:
        fallback = [x for x in UNICORNS if x["location"] == loc and not x.get("secret")]
    if not fallback:
        return None
    return random.choices(fallback, weights=[max(float(x.get("weight", 1)), 0.000001) for x in fallback], k=1)[0]


def roll_hunt(player, loc: str, research: float, weather: str, *, now: int | None = None,
              event_id: str | None = None):
    now = int(now or time.time())
    bait_id = player["active_bait"]
    c = catch_chance(player["pity_misses"], bait_id, event_id, loc)
    roll = random.random()
    if roll < c:
        u = choose_unicorn(
            player["level"], loc, research, weather, bait_id,
            now=now, event_id=event_id,
            rarity_pity=player["rarity_pity"] if "rarity_pity" in player.keys() else 0,
            last_unicorn_id=player["last_unicorn_id"] if "last_unicorn_id" in player.keys() else None,
            duplicate_streak=player["duplicate_streak"] if "duplicate_streak" in player.keys() else 0,
            pity_misses=player["pity_misses"],
        )
        if u is not None:
            return "unicorn", u, bait_id
    _, _, bait_event_bonus = event_modifiers(event_id, loc)
    if roll < c + min(0.55, BASE_BAIT + bait_event_bonus):
        ids = list(BAITS)
        b = random.choices(ids, weights=[BAITS[x]["find_weight"] for x in ids], k=1)[0]
        return "bait", b, bait_id
    return "nothing", None, bait_id


def specimen(u, forced_score: float | None = None):
    tier = u["tier"]
    x = random.random()
    score = round(max(35.0, min(100.0, 100.0 * (x ** 0.22))), 1)
    if forced_score is not None:
        score = round(max(35.0, min(100.0, float(forced_score))), 1)
    base_height = 148 + tier * 4
    return {
        "score": score,
        "height_cm": round(random.gauss(base_height, 7), 1),
        "horn_cm": round(max(15, random.gauss(28 + tier * 3.4, 5)), 1),
        "age_label": random.choices(["молодой", "взрослый", "зрелый"], [2, 6, 2])[0],
        "coat": random.choice(u["coats"]),
        "temperament": random.choice(["спокойный", "осторожный", "любопытный", "независимый", "пугливый"]),
    }


def specimen_quality(score: float) -> str:
    score = float(score)
    if score >= 99.5:
        return "Безупречный"
    if score >= 98.0:
        return "Исключительный"
    if score >= 95.0:
        return "Выдающийся"
    if score >= 90.0:
        return "Великолепный"
    if score >= 82.0:
        return "Превосходный"
    if score >= 72.0:
        return "Отличный"
    if score >= 60.0:
        return "Хороший"
    return "Обычный"


def quality_emoji(score: float) -> str:
    score = float(score)
    if score >= 99.5:
        return "👑"
    if score >= 98:
        return "💎"
    if score >= 95:
        return "🔴"
    if score >= 90:
        return "🟠"
    if score >= 82:
        return "🟣"
    if score >= 72:
        return "🔵"
    if score >= 60:
        return "🟢"
    return "⚪"


def qualitative_encounter(u) -> str:
    return {
        0: "обычная встреча",
        1: "нечастая встреча",
        2: "редкая встреча",
        3: "очень редкая встреча",
        4: "исключительно редкая встреча",
        5: "мифическая встреча",
        6: "архивная редкость",
    }[u["tier"]]


def research_gain(kind: str) -> int:
    return {"nothing": 7, "bait": 9, "unicorn": 14}[kind]


def pity_flavour(n: int) -> str:
    if n >= 10:
        return "🔥 Следы буквально окружают тебя. Долго так продолжаться не может."
    if n >= 8:
        return "🔥 Следы вокруг становятся совсем свежими."
    if n >= 5:
        return "👣 Кажется, в этой местности кто-то ходит совсем рядом."
    if n >= 3:
        return "🌿 Ты всё чаще замечаешь свежие признаки присутствия единорогов."
    return ""


def hunt_scene(loc: str, weather: str, kind: str) -> str:
    pools = {
        "forest": [
            "В чаще хрустнула ветка, и между деревьями мелькнул светлый силуэт.",
            "Ты находишь свежие следы у мокрого мха и идёшь по ним глубже в лес.",
            "На листьях дрожат капли, а впереди слышится короткое фырканье.",
        ],
        "marsh": [
            "Камыш расходится сам собой, а по чёрной воде проходит круговая рябь.",
            "В тумане на секунду вспыхивает холодный свет рога.",
            "Под ногами хлюпает трясина; впереди остаются свежие отпечатки копыт.",
        ],
        "ridge": [
            "На снегу видна цепочка свежих следов, ведущая к верхнему гребню.",
            "Порыв ветра приносит звон, будто где-то столкнулись кристаллы.",
            "Над перевалом мелькает грива, освещённая небом.",
        ],
    }
    ending = {
        "unicorn": "След оказывается свежим — встреча неизбежна.",
        "bait": "Зверь ускользнул, но в следах осталось кое-что полезное.",
        "nothing": "След постепенно растворяется, оставляя только новые полевые записи.",
    }[kind]
    return f"{random.choice(pools.get(loc, pools['forest']))} {ending}"


def _stable_sample(items, count: int, key: str):
    rnd = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    return rnd.sample(list(items), min(count, len(items)))


def day_key(now: int | None = None) -> str:
    return dt.datetime.fromtimestamp(int(now or time.time()), MOSCOW).strftime("%Y-%m-%d")


def week_key(now: int | None = None) -> str:
    d = dt.datetime.fromtimestamp(int(now or time.time()), MOSCOW)
    return f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"


def daily_quests(now: int | None = None):
    key = day_key(now)
    return _stable_sample(DAILY_QUESTS, 3, f"daily:{key}")


def weekly_quests(now: int | None = None):
    key = week_key(now)
    return _stable_sample(WEEKLY_QUESTS, 4, f"weekly:{key}")


def season_bounds(offset: int = 0, now: int | None = None):
    """Calendar-month seasons in UTC. offset=0 current, -1 previous."""
    d = dt.datetime.fromtimestamp(int(now or time.time()), UTC)
    y, m = d.year, d.month
    total = y * 12 + (m - 1) + offset
    y2, m0 = divmod(total, 12)
    m2 = m0 + 1
    start = dt.datetime(y2, m2, 1, tzinfo=UTC)
    if m2 == 12:
        end = dt.datetime(y2 + 1, 1, 1, tzinfo=UTC)
    else:
        end = dt.datetime(y2, m2 + 1, 1, tzinfo=UTC)
    key = f"{y2}-{m2:02d}"
    label = f"{calendar.month_name[m2]} {y2}"
    ru_months = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    label = f"{ru_months[m2]} {y2}"
    return key, label, int(start.timestamp()), int(end.timestamp())
