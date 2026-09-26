from __future__ import annotations
import asyncio
import datetime as dt
import html
import logging
import os
import random
import re
import secrets
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType, ChatMemberStatus
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile,
    LabeledPrice, PreCheckoutQuery, BotCommand,
)
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

import db
from data import LOCATIONS, UNICORNS, UNICORN_BY_ID, RARITY_EMOJI, BAITS, ACHIEVEMENTS
import game

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "").strip()
ADMIN_USERNAMES = {x.strip().lstrip("@").lower() for x in os.getenv("ADMIN_USERNAMES", "edgeel").split(",") if x.strip()}
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
TESTER_USERNAMES = set(ADMIN_USERNAMES)
if not TOKEN:
    raise RuntimeError("Создай .env и добавь BOT_TOKEN=...")

BASE = Path(__file__).resolve().parent
IMG_DIR = BASE / "unicorn_images"
CARD_DIR = BASE / "generated_cards"
IMG_DIR.mkdir(exist_ok=True)
CARD_DIR.mkdir(exist_ok=True)

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def norm(t):
    return re.sub(r"[^\wё]+", "", (t or "").lower())


def dur(s):
    s = max(0, int(s))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h} ч {m} мин" if h else f"{m}:{s:02d}"


def is_admin_user(user) -> bool:
    if not user:
        return False
    return user.id in ADMIN_IDS or (user.username or "").lower() in ADMIN_USERNAMES


def ensure_actor(user, chat_id=None):
    if not user:
        return
    db.ensure_player(
        user.id, user.full_name, username=user.username, chat_id=chat_id, seen_at=int(time.time())
    )
    if is_admin_user(user):
        db.unlock_tester_account(user.id)


def ensure(msg):
    if not msg.from_user:
        return
    ensure_actor(msg.from_user, msg.chat.id if getattr(msg, "chat", None) else None)


def ensure_callback(q: CallbackQuery):
    chat_id = q.message.chat.id if q.message and q.message.chat else None
    ensure_actor(q.from_user, chat_id)


def image_path(sid):
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = IMG_DIR / f"{sid}{ext}"
        if p.exists():
            return p
    return None


def _font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def fallback_card(u):
    out = CARD_DIR / f"{u['id']}.png"
    if out.exists():
        return out
    img = Image.new("RGB", (1000, 1000), "#11151d")
    d = ImageDraw.Draw(img)
    rnd = random.Random(u["id"])
    for _ in range(95):
        x, y = rnd.randrange(1000), rnd.randrange(720)
        r = rnd.choice([1, 1, 2, 3])
        d.ellipse((x-r, y-r, x+r, y+r), fill=u["color"])
    d.ellipse((650, 90, 870, 310), fill=u["color"])
    d.ellipse((315, 385, 650, 710), fill="#e7e9ee")
    d.ellipse((515, 315, 735, 505), fill="#eff1f4")
    d.polygon([(390,470),(565,455),(660,815),(330,815)], fill="#e7e9ee")
    d.polygon([(565,345),(635,115),(603,356)], fill=u["color"])
    d.polygon([(520,335),(485,245),(555,330)], fill="#e7e9ee")
    d.ellipse((628,386,645,403), fill="#11151d")
    d.rounded_rectangle((55,760,945,945), radius=26, fill="#171b24")
    d.text((90,790), u["name"], font=_font(45, True), fill="white")
    d.text((90,855), f"{u['rarity']} · {LOCATIONS[u['location']]['name']}", font=_font(28), fill=u["color"])
    img.save(out)
    return out


def photo_for(u):
    return image_path(u["id"]) or fallback_card(u)


def research_pct(uid, loc):
    p = db.get_progress(uid, loc)
    return game.research_percent(p["research_xp"], loc)


def current_weather_for(uid: int, loc: str, now: int | None = None):
    p = db.get_player(uid)
    if p and p["is_admin"]:
        ts = db.get_test_settings(uid)
        if ts and ts["enabled"] and ts["forced_weather"]:
            return ts["forced_weather"], "🧪", 3600
    return game.current_weather(loc, now)


def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🦄 Охота", callback_data="menu:hunt"),
         InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile")],
        [InlineKeyboardButton(text="🎒 Коллекция", callback_data="menu:inventory"),
         InlineKeyboardButton(text="📖 Бестиарий", callback_data="menu:bestiary")],
        [InlineKeyboardButton(text="🗺 Локации", callback_data="menu:locations"),
         InlineKeyboardButton(text="🧺 Наживка", callback_data="menu:bait")],
        [InlineKeyboardButton(text="🎯 Задания", callback_data="menu:quests"),
         InlineKeyboardButton(text="🏆 Топ", callback_data="menu:top")],
        [InlineKeyboardButton(text="🌍 Мир", callback_data="menu:world"),
         InlineKeyboardButton(text="📅 Сезон", callback_data="menu:season")],
        [InlineKeyboardButton(text="🪤 Ловушка", callback_data="menu:trap"),
         InlineKeyboardButton(text="🏅 Достижения", callback_data="menu:achievements")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
    ])


def _period_bounds(period_type: str, now: int | None = None):
    now = int(now or time.time())
    d = dt.datetime.fromtimestamp(now, game.MOSCOW)
    if period_type == "daily":
        start = d.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=1)
        return game.day_key(now), int(start.timestamp()), int(end.timestamp())
    start = (d - dt.timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=7)
    return game.week_key(now), int(start.timestamp()), int(end.timestamp())


def quest_status(uid: int, period_type: str, now: int | None = None):
    key, start, end = _period_bounds(period_type, now)
    quests = game.daily_quests(now) if period_type == "daily" else game.weekly_quests(now)
    rows = []
    for q in quests:
        value = int(db.quest_metric(uid, start, end, q["metric"]))
        claimed = db.quest_claimed(uid, period_type, key, q["id"])
        rows.append((q, min(value, q["target"]), claimed))
    return key, start, end, rows


def quest_reward_text(q):
    bits = [f"{q['reward_xp']} XP"] if q.get("reward_xp") else []
    if q.get("reward_bait"):
        b = BAITS[q["reward_bait"]]
        bits.append(f"{b['emoji']} {b['name']}")
    return " + ".join(bits) or "награда"


async def process_quest_rewards(uid: int, now: int):
    awarded = []
    for period_type in ("daily", "weekly"):
        key, _, _, rows = quest_status(uid, period_type, now)
        for q, value, claimed in rows:
            if claimed or value < q["target"]:
                continue
            if db.claim_quest(uid, period_type, key, q["id"], now):
                if q.get("reward_xp"):
                    db.add_xp(uid, q["reward_xp"], game.MAX_LEVEL, game.xp_needed)
                if q.get("reward_bait"):
                    db.add_bait(uid, q["reward_bait"], 1)
                awarded.append((period_type, q))
    if not awarded:
        return ""
    lines = ["\n\n🎯 <b>Задание выполнено!</b>"]
    for period_type, q in awarded:
        tag = "день" if period_type == "daily" else "неделя"
        lines.append(f"✅ {q['name']} ({tag}) — {quest_reward_text(q)}")
    return "\n".join(lines)


def location_keyboard(uid):
    p = db.get_player(uid)
    rows = []
    for lid, l in LOCATIONS.items():
        unlocked = p["level"] >= l["unlock_level"]
        mark = " ✅" if p["current_location"] == lid else ""
        lock = "" if unlocked else f" 🔒 ур. {l['unlock_level']}"
        rows.append([InlineKeyboardButton(
            text=f"{l['emoji']} {l['name']}{mark}{lock}",
            callback_data=f"loc:{lid}" if unlocked else "noop"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bait_keyboard(uid):
    p = db.get_player(uid)
    owned = {r["bait_id"]: r["amount"] for r in db.get_baits(uid)}
    rows = []
    for bid, b in BAITS.items():
        if owned.get(bid, 0):
            mark = " ✅" if p["active_bait"] == bid else ""
            rows.append([InlineKeyboardButton(
                text=f"{b['emoji']} {b['name']} ×{owned[bid]}{mark}",
                callback_data=f"bait:{bid}"
            )])
    rows.append([InlineKeyboardButton(text="🚫 Не использовать наживку", callback_data="bait:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def star_hunt_offer_keyboard(uid: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⭐ Поохотиться сейчас — 1 ⭐",
            callback_data=f"starhunt:offer:{uid}",
        )
    ]])


def hunt_again_keyboard(uid: int):
    """Single compact retry button shown after a hunt without a unicorn catch."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🦄 Поохотиться снова",
            callback_data=f"hunt:again:{uid}",
        )
    ]])


def star_hunt_payment_keyboard(invoice_link: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⭐ Оплатить 1 Star", url=invoice_link)
    ]])


def star_hunt_payload(uid: int, chat_id: int | None = None, message_id: int | None = None) -> str:
    token = secrets.token_hex(8)
    if chat_id is None or message_id is None:
        return f"extra_hunt:{uid}:{token}"
    return f"extra_hunt:{uid}:{chat_id}:{message_id}:{token}"


def parse_star_hunt_payload(payload: str):
    parts = (payload or "").split(":")
    try:
        if len(parts) == 3 and parts[0] == "extra_hunt" and parts[2]:
            return int(parts[1]), None, None
        if len(parts) == 5 and parts[0] == "extra_hunt" and parts[4]:
            return int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        pass
    return None


def valid_star_hunt_payload(payload: str, uid: int) -> bool:
    parsed = parse_star_hunt_payload(payload)
    return bool(parsed and parsed[0] == uid)


def star_hunt_origin(payload: str):
    parsed = parse_star_hunt_payload(payload)
    return (parsed[1], parsed[2]) if parsed else (None, None)



def inventory_keyboard(uid):
    rows, cur = [], []
    for r in db.inventory(uid):
        u = UNICORN_BY_ID.get(r["unicorn_id"])
        if not u:
            continue
        cur.append(InlineKeyboardButton(
            text=f"{RARITY_EMOJI[u['tier']]} {u['name']} ×{r['amount']}",
            callback_data=f"uni:{u['id']}"
        ))
        if len(cur) == 2:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Коллекция пуста", callback_data="noop")]])


def bestiary_keyboard(uid, loc):
    rows, cur = [], []
    p = db.get_player(uid)
    rp = research_pct(uid, loc)
    for u in UNICORNS:
        if u["location"] != loc:
            continue
        caught = db.species_amount(uid, u["id"]) > 0
        reveal_all = bool(p["is_admin"])
        if u.get("secret") and not (caught or reveal_all):
            continue
        visible = reveal_all or (p["level"] >= u["level"] and rp >= max(0, u["min_research"] - 15)) or caught
        if caught:
            label = f"{RARITY_EMOJI[u['tier']]} {u['name']}"
        elif visible:
            label = "❔ " + u["name"]
        else:
            label = "❔ Неизвестный вид"
        cur.append(InlineKeyboardButton(text=label, callback_data=f"beast:{u['id']}" if visible else "noop"))
        if len(cur) == 2:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bestiary_location_keyboard(uid):
    """Choose which location's bestiary to browse without changing the active hunting location."""
    p = db.get_player(uid)
    rows = []
    for lid, loc in LOCATIONS.items():
        unlocked = bool(p["is_admin"]) or p["level"] >= loc["unlock_level"]
        lock = "" if unlocked else f" 🔒 ур. {loc['unlock_level']}"
        rows.append([InlineKeyboardButton(
            text=f"{loc['emoji']} {loc['name']}{lock}",
            callback_data=f"bestiary:loc:{lid}" if unlocked else "noop",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bestiary_species_keyboard(uid, loc):
    rows = list(bestiary_keyboard(uid, loc).inline_keyboard)
    rows.append([InlineKeyboardButton(text="⬅️ Выбрать другую локацию", callback_data="bestiary:choose")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def check_achievements(uid, context=None):
    p = db.get_player(uid)
    unlocked = []
    now = int(time.time())
    unique = db.unique_count(uid)
    prog = {r["location_id"]: r for r in db.all_progress(uid)}

    def award(aid, ok):
        if ok and db.unlock_achievement(uid, aid, now):
            unlocked.append(aid)

    award("first_catch", p["caught"] >= 1)
    award("collector_5", unique >= 5)
    award("collector_15", unique >= 15)
    award("hunter_50", p["hunts"] >= 50)
    award("hunter_250", p["hunts"] >= 250)
    for lid, aid in [("forest","forest_master"),("marsh","marsh_master"),("ridge","ridge_master")]:
        award(aid, game.research_percent(prog[lid]["research_xp"], lid) >= 100)
    award("all_locations", all(prog[x]["hunts"] > 0 for x in LOCATIONS))

    cur_streak, _ = db.streaks(uid)
    award("streak_3", cur_streak >= 3)
    award("streak_7", cur_streak >= 7)
    award("streak_30", cur_streak >= 30)
    award("unlucky_10", p["pity_misses"] >= 10)
    award("complete_bestiary", unique >= len(UNICORNS))

    if context:
        u = context.get("u")
        spec = context.get("spec")
        bait = context.get("bait")
        source = context.get("source", "hunt")
        when = int(context.get("when") or now)
        msk = dt.datetime.fromtimestamp(when, game.MOSCOW)
        award("night_owl", source == "hunt" and msk.hour == 0 and msk.minute < 10)
        if u:
            award("mythic", u["tier"] >= 5)
            award("legend_no_bait", source == "hunt" and u["tier"] >= 4 and not bait)
            award("secret_catch", bool(u.get("secret")))
        if spec:
            award("perfect", spec["score"] >= 99.5)
            award("flawless_no_bait", source == "hunt" and spec["score"] >= 99.5 and not bait)
            award("giant_horn", spec["horn_cm"] >= 55)
        last_two = db.last_instances(uid, 2)
        if len(last_two) >= 2:
            tiers = [UNICORN_BY_ID.get(x["unicorn_id"], {}).get("tier", -1) for x in last_two]
            award("double_legend", all(t >= 4 for t in tiers))
    return unlocked


def achievement_text(ids):
    if not ids:
        return ""
    lines = ["\n\n🏆 <b>Новое достижение!</b>"]
    for aid in ids:
        n, d, e, _ = ACHIEVEMENTS[aid]
        lines.append(f"{e} <b>{n}</b> — {d}")
    return "\n".join(lines)


START_TEXT = (
    "🦄 <b>Unicorn Hunt</b>\n\n"
    "Коллекционная игра про охоту на единорогов. Напиши <b>единорог</b> или открой /menu: "
    "бесплатная охота доступна раз в 10 минут.\n\n"
    "В мире есть <b>3 локации и 27 видов</b>, включая секретные. Погода и глобальные события общие для всех игроков. "
    "Исследуй местность, используй наживки, собирай экземпляры разного качества, выполняй ежедневные и недельные задания, "
    "поддерживай серию дней и соревнуйся в глобальном, локальном и сезонном рейтингах.\n\n"
    "Раз в сутки можно поставить <b>ловушку</b>: она автоматически сработает через случайное время от 30 минут до суток "
    "и гарантированно поймает одного единорога. /trap\n\n"
    "Каждый пойманный единорог уникален: рост, рог, возраст, окрас, характер и словесное качество. "
    "Редкие виды могут требовать особую погоду, наживку, время суток, серию неудач или мировое событие.\n\n"
    "🎮 <b>Главное</b>\n"
    "• /menu — игровое меню\n"
    "• /profile — профиль и статистика\n"
    "• /quests — задания\n"
    "• /trap — поставить или проверить ловушку\n"
    "• /season — текущий сезон\n"
    "• /world — погода и события мира\n"
    "• /top — глобальный и локальный топ-10\n\n"
    "📚 Все механики и команды: /help"
)

HELP_TEXT = (
    "📚 <b>Как играть в Unicorn Hunt</b>\n\n"
    "<b>1. Охота</b>\nНапиши <b>единорог</b> или нажми «Охота» в /menu. Бесплатная охота — раз в 10 минут. "
    "Неудачи постепенно повышают шанс новой встречи. Отдельный скрытый pity увеличивает шанс более редких видов после серии обычных поимок, "
    "а защита от дубликатов уменьшает вероятность получать один и тот же вид много раз подряд.\n\n"
    "<b>2. Локации и исследование</b>\nТри локации открываются по уровню. Каждая охота повышает исследование текущей локации. "
    "Чем выше исследование, тем больше редких видов и подсказок доступно. /locations\n\n"
    "<b>3. Погода и мировые события</b>\nПогода одинакова для всех игроков и меняется по времени. Дополнительно происходят мировые события: "
    "например Радужный час, Лунное цветение, Звездопад и редкий двухчасовой Древний зов. /world\n\n"
    "<b>4. Наживки</b>\nНа охоте можно найти наживку. Она не включается сама: выбери её через /bait. "
    "Наживка тратится только при успешной поимке.\n\n"
    "<b>5. Экземпляры и качество</b>\nКаждая поимка сохраняется отдельным экземпляром. Качество: "
    "Обычный → Хороший → Отличный → Превосходный → Великолепный → Выдающийся → Исключительный → Безупречный. "
    "Бот отдельно отмечает новый вид, новый личный рекорд и особо качественные экземпляры. /inventory\n\n"
    "<b>6. Бестиарий и секреты</b>\nВ обычном бестиарии часть информации открывается с уровнем и исследованием. "
    "Секретные виды не раскрываются до поимки и требуют комбинаций условий. /bestiary\n\n"
    "<b>7. Серии</b>\nОхоться хотя бы раз в день, чтобы поддерживать streak. Текущая и рекордная серия показаны в /profile.\n\n"
    "<b>8. Задания</b>\nКаждый день выбираются 3 задания, каждую неделю — 4. Награды выдаются автоматически: XP и иногда наживки. /quests\n\n"
    "<b>9. Сезоны</b>\nКаждый календарный месяц — новый сезон. Есть рейтинг по числу поимок и по престижу коллекции "
    "(редкость + качество). Прошлые сезоны доступны в архиве. Топ-10 получает сезонные отметки. /season\n\n"
    "<b>10. Достижения</b>\nЕсть обычные и скрытые достижения: необычное время охоты, длинная серия неудач, секретный вид, "
    "безупречный экземпляр без наживки и другие. /achievements\n\n"
    "<b>11. Рейтинги</b>\n/top показывает только топ-10. Глобальный — по всему боту, локальный — по участникам текущего Telegram-чата. "
    "Доступны всё время и последние 24 часа.\n\n"
    "<b>12. Ловушка</b>\nРаз в календарные сутки можно поставить ловушку в текущей локации. Она срабатывает автоматически "
    "через случайное время от 30 минут до 24 часов и со 100% шансом приносит одного доступного единорога. "
    "Локация фиксируется в момент установки. Ловушка не расходует выбранную наживку и не меняет 10-минутный таймер обычной охоты. "
    "Если предыдущая ловушка ещё не сработала, вторую поставить нельзя. /trap\n\n"
    "<b>13. Дополнительная охота</b>\nЕсли бесплатная охота на перезарядке, можно поохотиться сейчас за 1 ⭐. "
    "Покупка не гарантирует поимку и не сдвигает бесплатный таймер. /starhunt · восстановление: /claimstar\n\n"
    "<b>Команды</b>\n"
    "/start — введение\n/menu — игровое меню\n/help — инструкция\n/profile — профиль\n"
    "/inventory — коллекция\n/bestiary — бестиарий\n/locations — локации\n/bait — наживки\n"
    "/quests — задания\n/trap — ловушка\n/achievements — достижения\n/world — погода и события\n/top — рейтинги\n"
    "/season — сезонный рейтинг\n/starhunt — дополнительная охота\n/claimstar — восстановить оплату\n"
    "/terms — условия покупок\n/paysupport — поддержка по платежам\n\n"
    "Также работают текстовые команды: <b>единорог</b>, <b>профиль</b>, <b>инвентарь</b>, <b>бестиарий</b>, "
    "<b>локации</b>, <b>наживка</b>, <b>ловушка</b>, <b>топ</b>, <b>меню</b>."
)


@dp.message(CommandStart())
async def start(m: Message):
    ensure(m)
    await m.answer(START_TEXT, reply_markup=main_menu_keyboard())


@dp.message(Command("help"))
async def help_command(m: Message):
    ensure(m)
    await m.answer(HELP_TEXT, reply_markup=main_menu_keyboard())


@dp.message(Command("menu"))
async def menu_command(m: Message):
    ensure(m)
    await m.answer("🎮 <b>Игровое меню</b>\nВыбери раздел:", reply_markup=main_menu_keyboard())


def _with_back(markup: InlineKeyboardMarkup | None):
    rows = list(markup.inline_keyboard) if markup else []
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trap_keyboard(uid: int, can_place: bool):
    rows = []
    if can_place:
        rows.append([InlineKeyboardButton(text="🪤 Поставить ловушку", callback_data=f"trap:place:{uid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trap_status(uid: int, now: int | None = None):
    now = int(now or time.time())
    p = db.get_player(uid)
    active = db.active_trap(uid)
    if active:
        loc = LOCATIONS.get(active["location_id"], LOCATIONS[p["current_location"]])
        text = (
            "🪤 <b>Ловушка установлена</b>\n\n"
            f"📍 {loc['emoji']} <b>{loc['name']}</b>\n"
            "Когда ловушка сработает, бот сам пришлёт результат в чат, где она была поставлена. "
            "Пока эта ловушка активна, поставить ещё одну нельзя."
        )
        return text, False

    today = db.trap_for_day(uid, game.day_key(now))
    if today:
        caught = UNICORN_BY_ID.get(today["unicorn_id"]) if today["unicorn_id"] else None
        result = f" Сегодня она поймала <b>{caught['name']}</b>." if caught else ""
        return (
            "🪤 <b>Ловушка на сегодня уже использована.</b>\n\n"
            f"{result}\nСледующую можно поставить после наступления нового дня по московскому времени.",
            False,
        )

    loc = LOCATIONS[p["current_location"]]
    text = (
        "🪤 <b>Поставить ловушку</b>\n\n"
        f"Сейчас она будет установлена в: {loc['emoji']} <b>{loc['name']}</b>.\n\n"
        "• доступна <b>1 раз в сутки</b>\n"
        "• срабатывает через случайное время <b>от 30 минут до 24 часов</b>\n"
        "• шанс поимки — <b>100%</b>\n"
        "• ловит одного доступного единорога этой локации\n"
        "• не расходует наживку и не меняет таймер обычной охоты\n\n"
        "После установки смена текущей локации уже не повлияет на эту ловушку."
    )
    return text, True


@dp.message(Command("trap"))
async def trap_command(m: Message):
    ensure(m)
    text, can_place = trap_status(m.from_user.id)
    await m.answer(text, reply_markup=trap_keyboard(m.from_user.id, can_place))


async def _menu_profile_text(uid: int, chat_id: int):
    p = db.get_player(uid)
    loc = p["current_location"]
    bait = BAITS.get(p["active_bait"])
    need = game.xp_needed(p["level"]) if p["level"] < game.MAX_LEVEL else 0
    success = 100 * p["caught"] / p["hunts"] if p["hunts"] else 0
    cur, best_streak = db.streaks(uid)
    best = db.best_instance_overall(uid)
    best_txt = "—"
    if best and UNICORN_BY_ID.get(best["unicorn_id"]):
        u = UNICORN_BY_ID[best["unicorn_id"]]
        best_txt = f"{game.quality_emoji(best['score'])} {u['name']} · {game.specimen_quality(best['score'])}"
    return (
        f"👤 <b>{html.escape(p['name'])}</b>\n"
        f"Уровень <b>{p['level']}</b> · XP <b>{p['xp']}/{need if need else 'MAX'}</b>\n"
        f"{LOCATIONS[loc]['emoji']} {LOCATIONS[loc]['name']} · исследование <b>{research_pct(uid, loc):.0f}%</b>\n"
        f"Наживка: <b>{bait['name'] if bait else 'нет'}</b>\n\n"
        f"Охот: <b>{p['hunts']}</b> · поймано: <b>{p['caught']}</b> · успех {success:.1f}%\n"
        f"Видов: <b>{db.unique_count(uid)}/{len(UNICORNS)}</b> · серия <b>{cur}</b> · рекорд <b>{best_streak}</b>\n"
        f"Глобальный ранг: <b>{'#'+str(db.global_rank(uid)) if db.global_rank(uid) else '—'}</b>\n"
        f"Лучший экземпляр: <b>{best_txt}</b>\n\n"
        "Полная карточка: /profile"
    )


@dp.callback_query(F.data.startswith("menu:"))
async def menu_cb(q: CallbackQuery):
    ensure_callback(q)
    uid = q.from_user.id
    action = q.data.split(":", 1)[1]
    if action == "back":
        await q.message.edit_text("🎮 <b>Игровое меню</b>\nВыбери раздел:", reply_markup=main_menu_keyboard())
    elif action == "hunt":
        await q.answer("Отправляемся на охоту…")
        return await do_hunt(q.message, actor=q.from_user)
    elif action == "profile":
        await q.message.edit_text(await _menu_profile_text(uid, q.message.chat.id), reply_markup=main_menu_keyboard())
    elif action == "inventory":
        rows = db.inventory(uid)
        if not rows:
            text = "🎒 <b>Коллекция</b>\nПока пуста."
        else:
            lines = ["🎒 <b>Коллекция</b>"]
            for r in rows:
                u = UNICORN_BY_ID.get(r["unicorn_id"])
                if u:
                    lines.append(f"{RARITY_EMOJI[u['tier']]} <b>{u['name']}</b> ×{r['amount']}")
            lines.append("\nНажми на вид, чтобы открыть лучший экземпляр.")
            text = "\n".join(lines)
        await q.message.edit_text(text, reply_markup=_with_back(inventory_keyboard(uid)))
    elif action == "bestiary":
        await q.message.edit_text(
            "📖 <b>Бестиарий</b>\nВыбери локацию, единорогов которой хочешь посмотреть.",
            reply_markup=bestiary_location_keyboard(uid),
        )
    elif action == "locations":
        p = db.get_player(uid); lines = ["🗺 <b>Локации</b>"]
        for lid, l in LOCATIONS.items():
            lock = "" if p["level"] >= l["unlock_level"] else f" 🔒 ур. {l['unlock_level']}"
            w, e, left = current_weather_for(uid, lid)
            lines.append(f"\n{l['emoji']} <b>{l['name']}</b>{lock}\nИсследовано: {research_pct(uid,lid):.0f}% · {e} {w} · ещё {dur(left)}")
        await q.message.edit_text("\n".join(lines), reply_markup=_with_back(location_keyboard(uid)))
    elif action == "bait":
        rows = db.get_baits(uid); lines = ["🧺 <b>Наживки</b>"]
        if not rows:
            lines.append("\nПока ничего нет.")
        for r in rows:
            b = BAITS[r["bait_id"]]
            lines.append(f"\n{b['emoji']} <b>{b['name']}</b> ×{r['amount']}\n<i>{b['desc']}</i>")
        await q.message.edit_text("\n".join(lines), reply_markup=_with_back(bait_keyboard(uid)))
    elif action == "quests":
        now = int(time.time()); reward = await process_quest_rewards(uid, now)
        await q.message.edit_text(quests_text(uid, now)+reward, reply_markup=main_menu_keyboard())
    elif action == "top":
        await q.message.edit_text(await top_text(uid, q.message.chat.id, "global", "all"), reply_markup=_with_back(top_keyboard("global","all")))
    elif action == "world":
        now = int(time.time()); eid, ecfg, eleft = game.current_world_event(now)
        lines=["🌍 <b>Состояние мира</b>"]
        if ecfg:
            lines.append(f"\n{ecfg['emoji']} <b>{ecfg['name']}</b> · ещё {dur(eleft)}\n<i>{ecfg['desc']}</i>")
        else:
            lines.append("\n🌤 Глобальное событие сейчас не активно.")
        for lid,l in LOCATIONS.items():
            w,e,left=current_weather_for(uid,lid,now); lines.append(f"{l['emoji']} {l['name']}: {e} {w} · {dur(left)}")
        await q.message.edit_text("\n".join(lines), reply_markup=main_menu_keyboard())
    elif action == "trap":
        text, can_place = trap_status(uid)
        await q.message.edit_text(text, reply_markup=trap_keyboard(uid, can_place))
    elif action == "season":
        await q.message.edit_text(season_text(uid,0,"catches"), reply_markup=season_keyboard(0,"catches"))
    elif action == "achievements":
        got=db.achievements(uid); lines=["🏆 <b>Достижения</b>"]
        for aid,(n,d,e,hidden) in ACHIEVEMENTS.items():
            lines.append(f"{e} <b>{n}</b> — {d}" if aid in got else ("❔ <i>Скрытое достижение</i>" if hidden else f"▫️ <b>{n}</b> — {d}"))
        await q.message.edit_text("\n".join(lines), reply_markup=main_menu_keyboard())
    elif action == "help":
        await q.message.edit_text(HELP_TEXT, reply_markup=main_menu_keyboard())
    await q.answer()


@dp.callback_query(F.data.startswith("trap:place:"))
async def trap_place_cb(q: CallbackQuery):
    ensure_callback(q)
    try:
        owner_uid = int(q.data.rsplit(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        return await q.answer()
    if q.from_user.id != owner_uid:
        return await q.answer("Эта кнопка предназначена другому игроку.", show_alert=True)

    now = int(time.time())
    p = db.get_player(owner_uid)
    delay = random.randint(30 * 60, 24 * 60 * 60)
    status, _row = db.place_trap(
        owner_uid,
        q.message.chat.id,
        p["current_location"],
        game.day_key(now),
        now,
        now + delay,
    )
    text, can_place = trap_status(owner_uid, now)
    await q.message.edit_text(text, reply_markup=trap_keyboard(owner_uid, can_place))
    if status == "placed":
        await q.answer("Ловушка установлена. Теперь остаётся ждать.")
    elif status == "active":
        await q.answer("У тебя уже есть активная ловушка.", show_alert=True)
    else:
        await q.answer("Сегодня ловушка уже использована.", show_alert=True)


@dp.callback_query(F.data.startswith("hunt:again:"))
async def hunt_again_cb(q: CallbackQuery):
    """Retry from the result card without producing an extra cooldown message."""
    ensure_callback(q)
    try:
        owner_uid = int(q.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        return await q.answer()

    if q.from_user.id != owner_uid:
        return await q.answer("Эта кнопка относится к охоте другого игрока.", show_alert=True)

    p = db.get_player(owner_uid)
    now = int(time.time())
    test = db.get_test_settings(owner_uid) if p and p["is_admin"] else None
    test_mode = bool(test and test["enabled"])

    # A normal failed hunt has just started the free-hunt cooldown. Instead of
    # adding another message to the chat, turn the existing retry button into
    # the paid-hunt offer on the same result card.
    if (
        p
        and not test_mode
        and p["last_hunt"]
        and now - p["last_hunt"] < game.COOLDOWN
    ):
        left = game.COOLDOWN - (now - p["last_hunt"])
        await q.message.edit_reply_markup(reply_markup=star_hunt_offer_keyboard(owner_uid))
        return await q.answer(f"Бесплатная охота через {dur(left)}")

    # Cooldown is already over (or admin test mode is enabled): launch another
    # hunt normally. Remove the stale retry control first so it cannot be tapped
    # repeatedly while the next result is being generated.
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await q.answer("Отправляемся на охоту…")
    return await do_hunt(q.message, actor=q.from_user)


@dp.message(Command("profile"))
async def profile(m):
    ensure(m)
    uid = m.from_user.id
    p = db.get_player(uid)
    loc = p["current_location"]
    rp = research_pct(uid, loc)
    bait = BAITS.get(p["active_bait"])
    bait_txt = f"{bait['emoji']} {bait['name']}" if bait else "нет"
    need = game.xp_needed(p["level"]) if p["level"] < game.MAX_LEVEL else 0
    pity = game.pity_flavour(p["pity_misses"])
    success = (100 * p["caught"] / p["hunts"]) if p["hunts"] else 0
    current_streak, max_streak = db.streaks(uid)
    best = db.best_instance_overall(uid)
    rarest = db.rarest_instance(uid)
    fav = db.favorite_location(uid)
    rank = db.global_rank(uid)
    local_rank = None
    if m.chat.id < 0:
        local_rows = await _local_leaderboard_rows(m.chat.id, since=None, limit=100)
        for i, row in enumerate(local_rows, 1):
            if int(row["id"]) == uid:
                local_rank = i
                break
    prev_key, _, prev_start, prev_end = game.season_bounds(-1)
    db.finalize_season(prev_key, prev_start, prev_end)
    first_hunt = db.first_hunt_time(uid)
    first_hunt_txt = dt.datetime.fromtimestamp(first_hunt, game.MOSCOW).strftime("%d.%m.%Y") if first_hunt else "—"
    best_txt = "—"
    if best and UNICORN_BY_ID.get(best["unicorn_id"]):
        bu = UNICORN_BY_ID[best["unicorn_id"]]
        best_txt = f"{game.quality_emoji(best['score'])} {bu['name']} · {game.specimen_quality(best['score'])}"
    rare_txt = "—"
    if rarest and UNICORN_BY_ID.get(rarest["unicorn_id"]):
        ru = UNICORN_BY_ID[rarest["unicorn_id"]]
        rare_txt = f"{RARITY_EMOJI[ru['tier']]} {ru['name']} · {ru['rarity']}"
    fav_txt = LOCATIONS[fav["location_id"]]["name"] if fav and fav["hunts"] else "—"
    awards = db.season_awards(uid, 4)
    award_txt = ""
    if awards:
        badges=[]
        for a in awards:
            med = "🥇" if a["rank"]==1 else "🥈" if a["rank"]==2 else "🥉" if a["rank"]==3 else "🏅"
            metric = "поимки" if a["metric"]=="catches" else "престиж"
            badges.append(f"{med} {a['season_key']} · {metric} #{a['rank']}")
        award_txt = "\n\n📅 <b>Сезонные награды</b>\n" + "\n".join(badges)
    admin_mark = "\n🧪 <b>Тестовый доступ активен</b>" if p["is_admin"] else ""
    await m.answer(
        f"🦄 <b>{html.escape(p['name'])}</b>\n"
        f"Уровень: <b>{p['level']}</b> · XP: <b>{p['xp']}/{need if need else 'MAX'}</b>\n"
        f"Локация: <b>{LOCATIONS[loc]['name']}</b> · исследование <b>{rp:.0f}%</b>\n"
        f"Наживка: <b>{bait_txt}</b>\n\n"
        f"🎯 Охот: <b>{p['hunts']}</b> · поймано: <b>{p['caught']}</b> · успех: <b>{success:.1f}%</b>\n"
        f"📚 Уникальных видов: <b>{db.unique_count(uid)}/{len(UNICORNS)}</b>\n"
        f"🔥 Серия: <b>{current_streak}</b> дн. · рекорд: <b>{max_streak}</b> дн.\n"
        f"🌍 Место в глобальном топе: <b>{'#'+str(rank) if rank else '—'}</b>\n"
        + (f"👥 Место в локальном топе: <b>{'#'+str(local_rank) if local_rank else '—'}</b>\n" if m.chat.id < 0 else "")
        + f"📆 Первая зафиксированная охота: <b>{first_hunt_txt}</b>\n"
        f"⭐ Лучший экземпляр: <b>{best_txt}</b>\n"
        f"🏆 Самая редкая находка: <b>{rare_txt}</b>\n"
        f"🗺 Любимая локация: <b>{fav_txt}</b>"
        + (f"\n\n{pity}" if pity else "") + award_txt + admin_mark,
        reply_markup=main_menu_keyboard(),
    )


@dp.message(Command("locations"))
async def locations(m):
    ensure(m)
    uid = m.from_user.id
    p = db.get_player(uid)
    lines = ["🗺 <b>Локации</b>"]
    for lid, l in LOCATIONS.items():
        rp = research_pct(uid, lid)
        lock = "" if p["level"] >= l["unlock_level"] else f" 🔒 ур. {l['unlock_level']}"
        w, e, left = current_weather_for(uid, lid)
        lines.append(f"\n{l['emoji']} <b>{l['name']}</b>{lock}\nИсследовано: {rp:.0f}% · сейчас {e} {w} · ещё {dur(left)}")
    await m.answer("\n".join(lines), reply_markup=location_keyboard(uid))


@dp.message(Command("bait"))
async def bait(m):
    ensure(m)
    uid = m.from_user.id
    rows = db.get_baits(uid)
    lines = ["🧺 <b>Наживки</b>"]
    if not rows:
        lines.append("\nПока ничего нет. Наживка иногда находится на охоте.")
    for r in rows:
        b = BAITS[r["bait_id"]]
        lines.append(f"\n{b['emoji']} <b>{b['name']}</b> ×{r['amount']}\n<i>{b['desc']}</i>")
    lines.append("\nВыбор не обязателен. Наживка расходуется <b>только при успешной поимке</b>.")
    await m.answer("\n".join(lines), reply_markup=bait_keyboard(uid))


@dp.message(Command("inventory"))
async def inventory(m):
    ensure(m)
    uid = m.from_user.id
    rows = db.inventory(uid)
    if not rows:
        return await m.answer("🎒 Коллекция пока пуста.")
    lines = ["🎒 <b>Коллекция</b>"]
    for r in rows:
        u = UNICORN_BY_ID.get(r["unicorn_id"])
        if u:
            lines.append(f"{RARITY_EMOJI[u['tier']]} <b>{u['name']}</b> ×{r['amount']}")
    lines.append("\nНажми на вид, чтобы открыть карточку и лучший экземпляр.")
    await m.answer("\n".join(lines), reply_markup=inventory_keyboard(uid))


@dp.message(Command("bestiary"))
async def bestiary(m):
    ensure(m)
    uid = m.from_user.id
    await m.answer(
        "📖 <b>Бестиарий</b>\n"
        "Выбери локацию, единорогов которой хочешь посмотреть.",
        reply_markup=bestiary_location_keyboard(uid),
    )


@dp.message(Command("achievements"))
async def ach(m):
    ensure(m)
    uid = m.from_user.id
    got = db.achievements(uid)
    lines = ["🏆 <b>Достижения</b>"]
    for aid, (n, d, e, hidden) in ACHIEVEMENTS.items():
        if aid in got:
            lines.append(f"{e} <b>{n}</b> — {d}")
        elif hidden:
            lines.append("❔ <i>Скрытое достижение</i>")
        else:
            lines.append(f"▫️ <b>{n}</b> — {d}")
    await m.answer("\n".join(lines))


def _leaderboard_lines(rows, uid):
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for pos, r in enumerate(rows, start=1):
        mark = medals[pos - 1] if pos <= 3 else f"{pos}."
        me = " 👈" if r["id"] == uid else ""
        name = html.escape(r["name"] or (f"@{r['username']}" if r["username"] else f"Игрок {r['id']}"))
        lines.append(f"{mark} <b>{name}</b> — {r['caught_count']} 🦄{me}")
    return lines or ["За выбранный период поимок пока нет."]


def top_keyboard(scope="global", period="all", expanded=None):
    scope_label = "🌍 Глобальный" if scope == "global" else "👥 Локальный"
    period_label = "🏆 Всё время" if period == "all" else "🕐 Последние 24 часа"
    rows = []
    if expanded == "scope":
        rows.append([InlineKeyboardButton(
            text=("✓ " if scope == "global" else "") + "🌍 Глобальный",
            callback_data=f"top:set:global:{period}",
        )])
        rows.append([InlineKeyboardButton(
            text=("✓ " if scope == "local" else "") + "👥 Локальный",
            callback_data=f"top:set:local:{period}",
        )])
    else:
        rows.append([InlineKeyboardButton(
            text=f"{scope_label} ▼",
            callback_data=f"top:menu:scope:{scope}:{period}",
        )])

    if expanded == "period":
        rows.append([InlineKeyboardButton(
            text=("✓ " if period == "all" else "") + "🏆 Всё время",
            callback_data=f"top:set:{scope}:all",
        )])
        rows.append([InlineKeyboardButton(
            text=("✓ " if period == "day" else "") + "🕐 Последние 24 часа",
            callback_data=f"top:set:{scope}:day",
        )])
    else:
        rows.append([InlineKeyboardButton(
            text=f"{period_label} ▼",
            callback_data=f"top:menu:period:{scope}:{period}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _local_leaderboard_rows(chat_id, since=None, limit=10):
    """Build a local leaderboard from actual current chat membership.

    Older bot versions did not store chat membership, so relying only on
    player_chats makes an upgraded group's leaderboard contain only users who
    have interacted after the update.  We therefore check every known player
    with Telegram and use player_chats only as a fallback when Telegram cannot
    return membership information.
    """
    candidates = db.leaderboard_global(1000000, since=since)
    cached = db.leaderboard_chat(chat_id, 1000000, since=since)
    cached_ids = {int(r["id"]) for r in cached}

    active_statuses = {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }

    rows = []
    for r in candidates:
        uid = int(r["id"])
        is_member = uid in cached_ids
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=uid)
        except Exception:
            # getChatMember for other users is not guaranteed by Telegram
            # unless the bot is an administrator.  Keep previously observed
            # members as a safe fallback instead of dropping them.
            pass
        else:
            is_member = member.status in active_statuses

        if is_member:
            rows.append(r)
            if len(rows) >= limit:
                break

    return rows


async def top_text(uid, chat_id, scope="global", period="all"):
    since = int(time.time()) - 86400 if period == "day" else None
    if scope == "local":
        rows = await _local_leaderboard_rows(chat_id, since=since, limit=10)
        title = "👥 <b>Локальный топ · этот чат</b>"
    else:
        rows = db.leaderboard_global(10, since=since)
        title = "🌍 <b>Глобальный топ</b>"
    period_text = "за последние 24 часа" if period == "day" else "за всё время"
    lines = ["🏆 <b>Топ охотников</b>", f"{title} · <i>{period_text}</i>", ""]
    lines.extend(_leaderboard_lines(rows, uid))
    return "\n".join(lines)


@dp.message(Command("top"))
async def top_players(m: Message):
    ensure(m)
    uid = m.from_user.id
    await m.answer(
        await top_text(uid, m.chat.id, "global", "all"),
        reply_markup=top_keyboard("global", "all"),
    )


@dp.callback_query(F.data.startswith("top:"))
async def top_cb(q: CallbackQuery):
    ensure_callback(q)
    parts = (q.data or "").split(":")
    if len(parts) not in {4, 5}:
        return await q.answer()

    expanded = None
    if parts[1] == "set" and len(parts) == 4:
        scope, period = parts[2], parts[3]
    elif parts[1] == "menu" and len(parts) == 5:
        expanded, scope, period = parts[2], parts[3], parts[4]
    else:
        return await q.answer()

    if scope not in {"global", "local"} or period not in {"all", "day"}:
        return await q.answer()

    await q.message.edit_text(
        await top_text(q.from_user.id, q.message.chat.id, scope, period),
        reply_markup=top_keyboard(scope, period, expanded=expanded),
    )
    await q.answer()


def quests_text(uid: int, now: int | None = None):
    now = int(now or time.time())
    lines = ["🎯 <b>Задания</b>"]
    for period_type, title in (("daily", "Сегодня"), ("weekly", "На этой неделе")):
        _, _, end, rows = quest_status(uid, period_type, now)
        lines.append(f"\n<b>{title}</b> · осталось {dur(end-now)}")
        for q, value, claimed in rows:
            mark = "✅" if claimed else ("🎁" if value >= q["target"] else "▫️")
            desc = q.get("desc") or q["name"]
            lines.append(
                f"{mark} <b>{q['name']}</b>\n"
                f"{desc}\n"
                f"Прогресс: <b>{value}/{q['target']}</b> · Награда: <b>{quest_reward_text(q)}</b>"
            )
    lines.append("\nНаграды за выполненные задания начисляются автоматически.")
    return "\n".join(lines)


@dp.message(Command("quests"))
async def quests_command(m: Message):
    ensure(m)
    now = int(time.time())
    reward = await process_quest_rewards(m.from_user.id, now)
    await m.answer(quests_text(m.from_user.id, now) + reward, reply_markup=main_menu_keyboard())


def season_keyboard(offset=0, metric="catches"):
    rows = [[
        InlineKeyboardButton(text="⬅️ Раньше", callback_data=f"season:{offset-1}:{metric}"),
        InlineKeyboardButton(text="Текущий" if offset == 0 else "➡️ Ближе", callback_data=f"season:{min(0,offset+1)}:{metric}"),
    ]]
    rows.append([
        InlineKeyboardButton(text=("✓ " if metric=="catches" else "") + "🦄 Поимки", callback_data=f"season:{offset}:catches"),
        InlineKeyboardButton(text=("✓ " if metric=="prestige" else "") + "💎 Престиж", callback_data=f"season:{offset}:prestige"),
    ])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def season_text(uid: int, offset=0, metric="catches"):
    key, label, start, end = game.season_bounds(offset)
    if offset < 0:
        db.finalize_season(key, start, end)
    rows = db.season_leaderboard_catches(start, end, 10) if metric == "catches" else db.season_leaderboard_prestige(start, end, 10)
    title = "по числу поимок" if metric == "catches" else "по престижу коллекции"
    lines = [f"📅 <b>Сезон: {label}</b>", f"Топ-10 {title}", ""]
    medals = ["🥇", "🥈", "🥉"]
    for pos, r in enumerate(rows, 1):
        mark = medals[pos-1] if pos <= 3 else f"{pos}."
        me = " 👈" if int(r["id"]) == int(uid) else ""
        name = html.escape(r["name"] or (f"@{r['username']}" if r["username"] else f"Игрок {r['id']}"))
        value = f"{r['caught_count']} 🦄" if metric == "catches" else f"{r['prestige']} очк."
        lines.append(f"{mark} <b>{name}</b> — {value}{me}")
    if not rows:
        lines.append("В этом сезоне пока нет результатов.")
    if metric == "prestige":
        lines.append("\n<i>Престиж учитывает редкость и качество пойманных экземпляров.</i>")
    if offset < 0:
        lines.append("\n🏅 Топ-10 получает сезонную отметку и награду: #1 — 2 Рассветные росы, #2–3 — 1 Роса, #4–10 — 1 Лунный клевер.")
    return "\n".join(lines)


@dp.message(Command("season"))
async def season_command(m: Message):
    ensure(m)
    await m.answer(season_text(m.from_user.id, 0, "catches"), reply_markup=season_keyboard(0, "catches"))


@dp.callback_query(F.data.startswith("season:"))
async def season_cb(q: CallbackQuery):
    ensure_callback(q)
    try:
        _, off, metric = q.data.split(":", 2)
        offset = max(-12, min(0, int(off)))
    except Exception:
        return await q.answer()
    if metric not in {"catches", "prestige"}:
        return await q.answer()
    await q.message.edit_text(season_text(q.from_user.id, offset, metric), reply_markup=season_keyboard(offset, metric))
    await q.answer()


@dp.message(Command("world"))
async def world(m):
    ensure(m)
    uid = m.from_user.id
    now = int(time.time())
    event_id, event_cfg, event_left = game.current_world_event(now)
    lines = ["🌍 <b>Состояние мира</b>"]
    if event_cfg:
        lines.append(
            f"\n{event_cfg['emoji']} <b>{event_cfg['name']}</b> · ещё {dur(event_left)}\n"
            f"<i>{event_cfg['desc']}</i>"
        )
    else:
        lines.append("\n🌤 Сейчас глобальное событие не активно.")
    lines.append("\n<b>Погода</b>")
    for lid, l in LOCATIONS.items():
        w, e, left = current_weather_for(uid, lid, now)
        lines.append(f"{l['emoji']} <b>{l['name']}</b>: {e} {w} · ещё {dur(left)}")
    if event_id == "ancient_call":
        lines.append("\n⚠️ Во время Древнего зова могут появиться следы, которых нет в обычных полевых записях.")
    await m.answer("\n".join(lines), reply_markup=main_menu_keyboard())


async def send_starhunt_offer(m: Message):
    uid = m.from_user.id
    await m.answer(
        (
            "⭐ <b>Поохотиться сейчас — 1 Star</b>\n\n"
            "Можно провести одну дополнительную охоту прямо сейчас. "
            "Она использует текущую локацию, погоду и выбранную наживку и "
            "<b>не сдвигает таймер</b> бесплатной охоты.\n\n"
            "Результат охоты случайный: покупка не гарантирует поимку единорога."
        ),
        reply_markup=star_hunt_offer_keyboard(uid),
    )


@dp.message(Command("starhunt"))
async def starhunt(m: Message):
    ensure(m)
    await send_starhunt_offer(m)


@dp.message(Command("terms"))
async def terms(m: Message):
    ensure(m)
    await m.answer(
        "📜 <b>Условия покупок</b>\n\n"
        "• 1 Telegram Star оплачивает ровно одну дополнительную охоту.\n"
        "• Это цифровая игровая услуга; результат определяется теми же игровыми правилами и случайностью, что и обычная охота.\n"
        "• Оплата не гарантирует поимку единорога, редкий вид или конкретную награду.\n"
        "• Дополнительная охота не обнуляет и не продлевает 10-минутный таймер бесплатной охоты.\n"
        "• Услуга считается оказанной после запуска оплаченной охоты.\n"
        "• Если Telegram списал Star, а результат охоты не появился, используй /claimstar — бот сверит транзакцию и восстановит охоту.\n\n"
        "По вопросам платежей используй /paysupport."
    )


@dp.message(Command("paysupport"))
async def paysupport(m: Message):
    ensure(m)
    if SUPPORT_CONTACT:
        await m.answer(
            "💳 <b>Поддержка по платежам</b>\n\n"
            f"Связь с владельцем бота: <b>{html.escape(SUPPORT_CONTACT)}</b>\n"
            "При обращении укажи примерное время платежа и свой Telegram ID. "
            "Telegram Support не обрабатывает споры по покупкам внутри этого бота."
        )
    else:
        await m.answer(
            "💳 <b>Поддержка по платежам</b>\n\n"
            "Контакт владельца пока не настроен. Владельцу бота нужно добавить "
            "<code>SUPPORT_CONTACT=...</code> в файл .env.\n"
            "Telegram Support не обрабатывает споры по покупкам внутри этого бота."
        )


@dp.callback_query(F.data == "noop")
async def noop(q):
    await q.answer("Пока недоступно.")


@dp.callback_query(F.data.startswith("starhunt:offer:"))
async def starhunt_offer_cb(q: CallbackQuery):
    ensure_callback(q)
    uid = q.from_user.id

    try:
        owner_uid = int(q.data.rsplit(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        return await q.answer("Не удалось определить владельца покупки.", show_alert=True)

    if uid != owner_uid:
        return await q.answer("Эта покупка предназначена другому игроку.", show_alert=True)

    invoice_link = await bot.create_invoice_link(
        title="Поохотиться сейчас",
        description="Одна дополнительная охота на единорога без ожидания 10-минутного кулдауна.",
        payload=star_hunt_payload(uid, q.message.chat.id, q.message.message_id),
        currency="XTR",
        prices=[LabeledPrice(label="Дополнительная охота", amount=1)],
    )

    name = html.escape(q.from_user.full_name)
    text = (
        "⭐ <b>Поохотиться сейчас — 1 Star</b>\n\n"
        "Одна дополнительная охота прямо сейчас. Она использует текущую локацию, "
        "погоду и выбранную наживку и <b>не сдвигает таймер</b> бесплатной охоты.\n\n"
        "Результат случайный: оплата не гарантирует поимку единорога.\n\n"
        f"👤 Покупка подготовлена для <b>{name}</b>.\n"
        "Нажимая кнопку оплаты, ты подтверждаешь согласие с /terms."
    )

    await q.message.edit_text(
        text,
        reply_markup=star_hunt_payment_keyboard(invoice_link),
    )
    await q.answer()


@dp.pre_checkout_query()
async def starhunt_pre_checkout(q: PreCheckoutQuery):
    ok = (
        q.currency == "XTR"
        and q.total_amount == 1
        and valid_star_hunt_payload(q.invoice_payload, q.from_user.id)
    )
    await q.answer(
        ok=ok,
        error_message=None if ok else "Не удалось проверить заказ. Создай новый счёт через /starhunt.",
    )


@dp.callback_query(F.data.startswith("bestiary:"))
async def bestiary_nav_cb(q: CallbackQuery):
    ensure_callback(q)
    uid = q.from_user.id
    parts = q.data.split(":")

    if len(parts) == 2 and parts[1] == "choose":
        await q.message.edit_text(
            "📖 <b>Бестиарий</b>\nВыбери локацию, единорогов которой хочешь посмотреть.",
            reply_markup=bestiary_location_keyboard(uid),
        )
        return await q.answer()

    if len(parts) == 3 and parts[1] == "loc":
        lid = parts[2]
        loc = LOCATIONS.get(lid)
        if not loc:
            return await q.answer("Неизвестная локация.", show_alert=True)
        p = db.get_player(uid)
        if not (p["is_admin"] or p["level"] >= loc["unlock_level"]):
            return await q.answer(f"Локация откроется на {loc['unlock_level']} уровне.", show_alert=True)
        await q.message.edit_text(
            f"📖 <b>Бестиарий: {loc['name']}</b>\n"
            "Пойманные виды раскрыты полностью. Для ещё не пойманных по мере исследования появляются полевые подсказки.",
            reply_markup=bestiary_species_keyboard(uid, lid),
        )
        return await q.answer()

    await q.answer()


@dp.callback_query(F.data.startswith("loc:"))
async def loc_cb(q):
    ensure_callback(q)
    uid = q.from_user.id
    lid = q.data.split(":", 1)[1]
    p = db.get_player(uid)
    if p["level"] < LOCATIONS[lid]["unlock_level"]:
        return await q.answer("Локация ещё закрыта.", show_alert=True)
    db.set_location(uid, lid)
    await q.answer(f"Теперь ты в локации: {LOCATIONS[lid]['name']}")
    try:
        await q.message.edit_reply_markup(reply_markup=location_keyboard(uid))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("bait:"))
async def bait_cb(q):
    ensure_callback(q)
    uid = q.from_user.id
    bid = q.data.split(":", 1)[1]
    if bid == "none":
        db.clear_active_bait(uid)
        await q.answer("Наживка отключена.")
    elif db.set_active_bait(uid, bid):
        await q.answer(f"Выбрано: {BAITS[bid]['name']}")
    else:
        return await q.answer("Такой наживки нет.", show_alert=True)
    try:
        await q.message.edit_reply_markup(reply_markup=bait_keyboard(uid))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("uni:"))
async def uni_cb(q):
    ensure_callback(q)
    uid = q.from_user.id
    sid = q.data.split(":", 1)[1]
    u = UNICORN_BY_ID.get(sid)
    if not u or db.species_amount(uid, sid) <= 0:
        return await q.answer("Этого вида нет в коллекции.", show_alert=True)
    inst = db.best_instance(uid, sid)
    extra = ""
    if inst:
        legacy = " <i>(архивные характеристики)</i>" if inst["legacy"] else ""
        extra = (
            f"\n\n🏅 <b>Лучший экземпляр: {game.specimen_quality(inst['score'])}</b>{legacy}\n"
            f"Рост: {inst['height_cm']:.1f} см · рог: {inst['horn_cm']:.1f} см\n"
            f"Возраст: {inst['age_label']} · окрас: {inst['coat']}\n"
            f"Характер: {inst['temperament']}"
        )
    cap = (
        f"🦄 <b>{u['name']}</b>\n{RARITY_EMOJI[u['tier']]} {u['rarity']}\n\n{u['text']}\n\n"
        f"📍 {LOCATIONS[u['location']]['name']} · {u['habitat']}\n📦 Поймано: <b>{db.species_amount(uid, sid)}</b>{extra}"
    )
    await q.message.answer_photo(FSInputFile(photo_for(u)), caption=cap)
    await q.answer()


@dp.callback_query(F.data.startswith("beast:"))
async def beast_cb(q):
    ensure_callback(q)
    uid = q.from_user.id
    sid = q.data.split(":", 1)[1]
    u = UNICORN_BY_ID.get(sid)
    if not u:
        return await q.answer()
    caught = db.species_amount(uid, sid) > 0
    if caught:
        text = (
            f"{RARITY_EMOJI[u['tier']]} <b>{u['name']}</b>\n{u['rarity']}\n\n{u['text']}\n\n"
            f"📍 {u['habitat']}\n💡 {u['hint']}"
        )
    else:
        text = f"❔ <b>{u['name']}</b>\nВид пока не пойман.\n\n💡 Полевые записи: <i>{u['hint']}</i>"
    await q.message.answer(text)
    await q.answer()


async def do_hunt(
    m: Message, *, actor=None, bypass_cooldown: bool = False, update_cooldown: bool = True,
    paid: bool = False, star_charge_id: str | None = None, target_chat_id: int | None = None
):
    user = actor or m.from_user
    ensure_actor(user, m.chat.id if getattr(m, "chat", None) else None)
    uid = user.id

    async def hunt_reply(text: str, **kwargs):
        if target_chat_id is None or target_chat_id == m.chat.id:
            return await m.reply(text, **kwargs)
        return await bot.send_message(chat_id=target_chat_id, text=text, **kwargs)

    async def hunt_reply_photo(photo, *, caption: str):
        if target_chat_id is None or target_chat_id == m.chat.id:
            return await m.reply_photo(photo, caption=caption)
        return await bot.send_photo(chat_id=target_chat_id, photo=photo, caption=caption)

    p = db.get_player(uid)
    now = int(time.time())
    test = db.get_test_settings(uid) if p["is_admin"] else None
    test_mode = bool(test and test["enabled"] and not paid)

    if not (bypass_cooldown or test_mode) and p["last_hunt"] and now - p["last_hunt"] < game.COOLDOWN:
        left = game.COOLDOWN - (now - p["last_hunt"])
        return await hunt_reply(
            f"🌲 Следующая полноценная охота через <b>{dur(left)}</b>.",
            reply_markup=star_hunt_offer_keyboard(uid),
        )

    loc = (test["forced_location"] if test_mode and test["forced_location"] in LOCATIONS else None) or p["current_location"]
    rp = research_pct(uid, loc)
    weather, wemoji, _ = (current_weather_for(uid, loc, now) if test_mode else game.current_weather(loc, now))
    event_id, event_cfg, _ = game.current_world_event(now)
    kind, obj, bait_id = game.roll_hunt(p, loc, rp, weather, now=now, event_id=event_id)

    # Admin sandbox: force branches without modifying persistent game statistics.
    if test_mode:
        forced_kind = test["forced_kind"]
        if forced_kind in {"unicorn", "bait", "nothing"}:
            kind = forced_kind
        if kind == "unicorn":
            forced = UNICORN_BY_ID.get(test["forced_species"] or "")
            if forced:
                obj = forced
                loc = forced["location"]
                weather, wemoji, _ = current_weather_for(uid, loc, now)
            elif not isinstance(obj, dict):
                pool = [u for u in UNICORNS if u["location"] == loc]
                obj = random.choice(pool)
        elif kind == "bait":
            obj = "carrot"

    gain = game.research_gain(kind)
    narrative = game.hunt_scene(loc, weather, kind)
    event_note = f"\n{event_cfg['emoji']} <i>{event_cfg['name']}</i>" if event_cfg else ""

    if not test_mode:
        db.record_hunt(uid, kind, now, update_last_hunt=update_cooldown)
        db.add_research(uid, loc, gain, kind == "unicorn")

    if kind == "unicorn":
        u = obj
        if not u:
            # This can only happen when no species is eligible despite an encounter roll.
            if not test_mode:
                db.log_hunt_event(uid, now, "nothing", loc, research_gain=gain, paid=paid)
            return await hunt_reply(
                "🌫 След был свежим, но зверь сумел уйти в последний момент.",
                reply_markup=hunt_again_keyboard(uid),
            )

        old_amount = db.species_amount(uid, u["id"])
        old_best = db.best_instance(uid, u["id"])
        old_overall = db.best_instance_overall(uid)
        forced_score = test["forced_quality"] if test_mode else None
        spec = game.specimen(u, forced_score=forced_score)
        is_new_species = old_amount == 0
        is_new_record = old_best is None or spec["score"] > float(old_best["score"])
        is_overall_record = old_overall is None or spec["score"] > float(old_overall["score"])

        reached = []
        new_level = p["level"]
        achs = []
        quest_note = ""
        if not test_mode:
            db.add_instance(uid, u, spec, now, loc, weather)
            db.record_catch_meta(uid, u["id"], u["tier"])
            new_level, _, reached = db.add_xp(uid, u["xp"], game.MAX_LEVEL, game.xp_needed)
            if bait_id:
                db.consume_bait(uid, bait_id)
            db.log_hunt_event(
                uid, now, "unicorn", loc, unicorn_id=u["id"], tier=u["tier"], bait_used=bait_id,
                research_gain=gain, score=spec["score"], paid=paid,
            )
            achs = await check_achievements(uid, {"u": u, "spec": spec, "bait": bait_id, "when": now})
            quest_note = await process_quest_rewards(uid, now)
            if star_charge_id:
                db.mark_star_payment_fulfilled(star_charge_id, int(time.time()))

        labels = []
        if test_mode:
            labels.append("🧪 <b>ТЕСТОВЫЙ РЕЖИМ — результат не сохранён</b>")
        if is_new_species:
            labels.append("📖 <b>Новый вид в бестиарии!</b>")
        if is_new_record and not is_new_species:
            labels.append("👑 <b>Новый лучший экземпляр этого вида!</b>")
        if is_overall_record and not is_new_species:
            labels.append("🏆 <b>Новый личный рекорд качества!</b>")
        if spec["score"] >= 99.5:
            labels.append("✨ <b>Безупречный экземпляр!</b>")

        paid_note = "⭐ <b>Дополнительная охота</b>\n" if paid else ""
        status = ("\n".join(labels) + "\n\n") if labels else ""
        cap_core = (
            paid_note + status
            + f"🦄 <b>ПОЙМАН: {u['name']}</b>\n"
            f"{RARITY_EMOJI[u['tier']]} {u['rarity']} · <i>{game.qualitative_encounter(u)}</i>\n\n"
            f"<i>{narrative}</i>\n\n{u['text']}\n\n"
            f"🗺 {LOCATIONS[loc]['name']} · {wemoji} {weather}{event_note}\n"
            + (f"✨ +{u['xp']} XP · исследование +{gain}\n\n" if not test_mode else "\n")
            + f"{game.quality_emoji(spec['score'])} Качество: <b>{game.specimen_quality(spec['score'])}</b>\n"
            f"Рост {spec['height_cm']:.1f} см · рог {spec['horn_cm']:.1f} см\n"
            f"{spec['age_label']}, {spec['coat']}, характер: {spec['temperament']}"
            + (f"\n🎣 Использована: {BAITS[bait_id]['name']}" if bait_id else "")
            + (f"\n\n⬆️ <b>Новый уровень: {new_level}</b>" if reached else "")
        )
        extras = achievement_text(achs) + quest_note
        cap = cap_core + extras
        if len(cap) > 1000:
            summary = "\n\n🏆 Есть новые достижения и/или выполненные задания — подробности в /achievements и /quests."
            cap = cap_core + summary
        await hunt_reply_photo(FSInputFile(photo_for(u)), caption=cap)

    elif kind == "bait":
        bid = obj if obj in BAITS else "carrot"
        b = BAITS[bid]
        achs = []
        quest_note = ""
        if not test_mode:
            db.add_bait(uid, bid)
            db.log_hunt_event(uid, now, "bait", loc, research_gain=gain, paid=paid)
            achs = await check_achievements(uid, {"when": now})
            quest_note = await process_quest_rewards(uid, now)
            if star_charge_id:
                db.mark_star_payment_fulfilled(star_charge_id, int(time.time()))
        test_note = "🧪 <b>ТЕСТОВЫЙ РЕЖИМ — результат не сохранён</b>\n\n" if test_mode else ""
        paid_note = "⭐ <b>Дополнительная охота</b>\n" if paid else ""
        await hunt_reply(
            paid_note + test_note
            + f"{b['emoji']} <b>Найдена наживка: {b['name']}</b>\n\n"
            f"<i>{narrative}</i>\n\n{b['desc']}\n"
            + ("Она добавлена в инвентарь, но <b>сама не включается</b>. Выбрать: /bait\n\n" if not test_mode else "\n")
            + f"🗺 {LOCATIONS[loc]['name']} · {wemoji} {weather}{event_note}\n"
            + (f"Исследование +{gain}" if not test_mode else "")
            + achievement_text(achs) + quest_note,
            reply_markup=hunt_again_keyboard(uid),
        )

    else:
        achs = []
        quest_note = ""
        if not test_mode:
            db.log_hunt_event(uid, now, "nothing", loc, research_gain=gain, paid=paid)
            achs = await check_achievements(uid, {"when": now})
            quest_note = await process_quest_rewards(uid, now)
            if star_charge_id:
                db.mark_star_payment_fulfilled(star_charge_id, int(time.time()))
        p2 = db.get_player(uid)
        pity = game.pity_flavour(p2["pity_misses"]) if not test_mode else ""
        test_note = "🧪 <b>ТЕСТОВЫЙ РЕЖИМ — результат не сохранён</b>\n\n" if test_mode else ""
        paid_note = "⭐ <b>Дополнительная охота</b>\n" if paid else ""
        await hunt_reply(
            paid_note + test_note
            + f"🌫 <b>Охота без поимки.</b>\n<i>{narrative}</i>\n\n"
            f"🗺 {LOCATIONS[loc]['name']} · {wemoji} {weather}{event_note}\n"
            + (f"Исследование +{gain}" if not test_mode else "")
            + (f"\n\n{pity}" if pity else "")
            + achievement_text(achs) + quest_note,
            reply_markup=hunt_again_keyboard(uid),
        )


async def resolve_and_notify_trap(trap_row):
    """Resolve one due trap and deliver its catch exactly once."""
    trap = db.get_trap(trap_row["trap_id"])
    if not trap:
        return

    uid = int(trap["user_id"])
    loc = trap["location_id"]
    p = db.get_player(uid)
    if not p or loc not in LOCATIONS:
        logging.error("Trap %s has invalid player/location", trap["trap_id"])
        return

    resolution = None
    if int(trap["resolved_at"] or 0) == 0:
        when = max(int(time.time()), int(trap["trigger_at"]))
        weather, _wemoji, _left = game.current_weather(loc, when)
        event_id, _event_cfg, _event_left = game.current_world_event(when)
        research = research_pct(uid, loc)
        u = game.choose_trap_unicorn(
            int(p["level"]), loc, research, weather, now=when, event_id=event_id
        )
        if u is None:
            logging.error("Trap %s has no eligible unicorn pool", trap["trap_id"])
            return
        spec = game.specimen(u)
        resolution = db.resolve_trap_capture(
            trap["trap_id"], u, spec, when, weather,
            game.research_gain("unicorn"), game.MAX_LEVEL, game.xp_needed,
        )
        if resolution is None:
            return
        trap = db.get_trap(trap["trap_id"])

    u = UNICORN_BY_ID.get(trap["unicorn_id"])
    inst = db.get_instance(trap["instance_id"]) if trap["instance_id"] else None
    if not u or not inst:
        logging.error("Resolved trap %s is missing unicorn/instance", trap["trap_id"])
        return

    event_when = int(trap["resolved_at"] or time.time())
    spec = {
        "score": float(inst["score"]),
        "height_cm": float(inst["height_cm"]),
        "horn_cm": float(inst["horn_cm"]),
        "age_label": inst["age_label"],
        "coat": inst["coat"],
        "temperament": inst["temperament"],
    }
    achs = await check_achievements(
        uid, {"u": u, "spec": spec, "bait": None, "when": event_when, "source": "trap"}
    )
    quest_note = await process_quest_rewards(uid, event_when)

    labels = []
    if db.species_amount(uid, u["id"]) == 1:
        labels.append("📖 <b>Новый вид в бестиарии!</b>")
    best = db.best_instance(uid, u["id"])
    if best and int(best["instance_id"]) == int(inst["instance_id"]):
        labels.append("👑 <b>Лучший экземпляр этого вида!</b>")
    overall = db.best_instance_overall(uid)
    if overall and int(overall["instance_id"]) == int(inst["instance_id"]):
        labels.append("🏆 <b>Новый личный рекорд качества!</b>")
    if spec["score"] >= 99.5:
        labels.append("✨ <b>Безупречный экземпляр!</b>")

    player = db.get_player(uid)
    name = html.escape(player["name"] if player else str(uid))
    mention = f'<a href="tg://user?id={uid}">{name}</a>'
    status = ("\n".join(labels) + "\n\n") if labels else ""
    gain = game.research_gain("unicorn")
    caption_core = (
        f"🪤 <b>Ловушка сработала!</b>\n{mention}, добыча уже ждёт тебя.\n\n"
        + status
        + f"🦄 <b>ПОЙМАН: {u['name']}</b>\n"
        f"{RARITY_EMOJI[u['tier']]} {u['rarity']} · <i>{game.qualitative_encounter(u)}</i>\n\n"
        f"{u['text']}\n\n"
        f"🗺 {LOCATIONS[loc]['name']} · {inst['weather']}\n"
        f"✨ +{u['xp']} XP · исследование +{gain}\n\n"
        f"{game.quality_emoji(spec['score'])} Качество: <b>{game.specimen_quality(spec['score'])}</b>\n"
        f"Рост {spec['height_cm']:.1f} см · рог {spec['horn_cm']:.1f} см\n"
        f"{spec['age_label']}, {spec['coat']}, характер: {spec['temperament']}"
    )
    extras = achievement_text(achs) + quest_note
    caption = caption_core + extras
    if len(caption) > 1000:
        caption = caption_core + "\n\n🏆 Новые достижения/задания можно посмотреть в /achievements и /quests."

    try:
        await bot.send_photo(
            chat_id=int(trap["chat_id"]),
            photo=FSInputFile(photo_for(u)),
            caption=caption,
        )
    except Exception:
        logging.exception("Could not deliver trap %s to chat %s", trap["trap_id"], trap["chat_id"])
        return
    db.mark_trap_notified(trap["trap_id"], int(time.time()))


async def trap_worker():
    """Persistent scheduler for passive traps.

    SQLite stores the schedule, so restarting the bot does not lose timers.
    """
    while True:
        try:
            now = int(time.time())
            for row in db.traps_due_for_delivery(now, limit=50):
                try:
                    await resolve_and_notify_trap(row)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logging.exception("Trap worker failed for trap %s", row["trap_id"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Trap worker iteration failed")
        await asyncio.sleep(20)


@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def starhunt_success(m: Message):
    """Persist the payment first, then fulfill it. If fulfillment crashes, /claimstar can recover it."""
    ensure(m)
    pay = m.successful_payment
    uid = m.from_user.id
    if not (
        pay
        and pay.currency == "XTR"
        and pay.total_amount == 1
        and valid_star_hunt_payload(pay.invoice_payload, uid)
    ):
        return await m.answer("⚠️ Платёж получен, но его назначение не удалось проверить. Обратись в /paysupport.")

    origin_chat_id, origin_message_id = star_hunt_origin(pay.invoice_payload)

    async def update_purchase_message(text: str):
        if origin_chat_id is not None and origin_message_id is not None:
            try:
                await bot.edit_message_text(
                    chat_id=origin_chat_id,
                    message_id=origin_message_id,
                    text=text,
                )
                return
            except Exception:
                logging.exception("Could not edit purchase message %s/%s", origin_chat_id, origin_message_id)
                try:
                    await bot.send_message(chat_id=origin_chat_id, text=text)
                except Exception:
                    logging.exception("Could not send payment status to origin chat %s", origin_chat_id)
                return
        # Legacy invoices do not contain an origin. Keep the old behavior for them.
        await m.answer(text)

    db.record_star_payment(
        uid=uid,
        amount=pay.total_amount,
        currency=pay.currency,
        payload=pay.invoice_payload,
        telegram_charge_id=pay.telegram_payment_charge_id,
        provider_charge_id=pay.provider_payment_charge_id,
        paid_at=int(time.time()),
    )
    row = db.get_star_payment(pay.telegram_payment_charge_id)
    if row and row["fulfilled_at"]:
        return await update_purchase_message("✅ Этот платёж уже был обработан; повторная охота не начислена.")

    await update_purchase_message(
        "✅ <b>Оплата получена.</b> Дополнительная охота запущена — обычный таймер не изменился."
    )
    try:
        await do_hunt(
            m,
            bypass_cooldown=True,
            update_cooldown=False,
            paid=True,
            star_charge_id=pay.telegram_payment_charge_id,
            target_chat_id=origin_chat_id,
        )
    except Exception:
        logging.exception("Paid hunt fulfillment failed for charge %s", pay.telegram_payment_charge_id)
        await update_purchase_message(
            "⚠️ Star списана, но при запуске охоты произошла техническая ошибка. "
            "Платёж сохранён — отправь /claimstar, и охота будет восстановлена без повторной оплаты."
        )


async def _recover_star_transaction(uid: int):
    """Find the newest unrecorded 1-Star extra-hunt payment for this user in Telegram history."""
    txs = await bot.get_star_transactions(limit=100)
    candidates = []
    for tx in txs.transactions:
        src = getattr(tx, "source", None)
        user = getattr(src, "user", None) if src else None
        payload = getattr(src, "invoice_payload", None) if src else None
        if not user or user.id != uid:
            continue
        if tx.amount != 1 or not valid_star_hunt_payload(payload or "", uid):
            continue
        existing = db.get_star_payment(tx.id)
        if existing and existing["fulfilled_at"]:
            continue
        candidates.append((tx, payload))

    if not candidates:
        return None

    # getStarTransactions is chronological; use the newest eligible payment.
    tx, payload = candidates[-1]
    date = getattr(tx, "date", None)
    if hasattr(date, "timestamp"):
        paid_at = int(date.timestamp())
    else:
        try:
            paid_at = int(date)
        except (TypeError, ValueError):
            paid_at = int(time.time())

    db.record_star_payment(
        uid=uid,
        amount=1,
        currency="XTR",
        payload=payload,
        telegram_charge_id=tx.id,
        provider_charge_id="recovered_from_star_transactions",
        paid_at=paid_at,
    )
    return db.get_star_payment(tx.id)


def admin_allowed(user) -> bool:
    if is_admin_user(user):
        return True
    p = db.get_player(user.id) if user else None
    return bool(p and p["is_admin"])


def test_panel_keyboard(uid: int):
    ts = db.get_test_settings(uid)
    enabled = bool(ts["enabled"])
    kind = ts["forced_kind"] or "normal"
    q = ts["forced_quality"]
    loc = ts["forced_location"] or "current"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🟢 Тест ON" if enabled else "⚪ Тест OFF"), callback_data="test:toggle")],
        [InlineKeyboardButton(text=("✓ " if kind=="normal" else "")+"🎲 RNG", callback_data="test:kind:normal"),
         InlineKeyboardButton(text=("✓ " if kind=="unicorn" else "")+"🦄 Поимка", callback_data="test:kind:unicorn")],
        [InlineKeyboardButton(text=("✓ " if kind=="bait" else "")+"🧺 Наживка", callback_data="test:kind:bait"),
         InlineKeyboardButton(text=("✓ " if kind=="nothing" else "")+"🌫 Промах", callback_data="test:kind:nothing")],
        [InlineKeyboardButton(text=("✓ " if q is None else "")+"💠 Качество RNG", callback_data="test:quality:normal"),
         InlineKeyboardButton(text=("✓ " if q is not None else "")+"👑 Безупречный", callback_data="test:quality:perfect")],
        [InlineKeyboardButton(text=f"🗺 Локация: {loc}", callback_data="test:location:cycle")],
        [InlineKeyboardButton(text="♻️ Сбросить настройки", callback_data="test:reset")],
    ])


def test_panel_text(uid: int):
    ts = db.get_test_settings(uid)
    species = UNICORN_BY_ID.get(ts["forced_species"] or "")
    return (
        "🧪 <b>Тестовый режим</b>\n\n"
        f"Статус: <b>{'включён' if ts['enabled'] else 'выключен'}</b>\n"
        f"Исход: <b>{ts['forced_kind'] or 'обычный RNG'}</b>\n"
        f"Вид: <b>{species['name'] if species else 'автовыбор'}</b>\n"
        f"Качество: <b>{game.specimen_quality(ts['forced_quality']) if ts['forced_quality'] is not None else 'обычное'}</b>\n"
        f"Локация: <b>{ts['forced_location'] or 'текущая'}</b>\n"
        f"Погода: <b>{ts['forced_weather'] or 'обычная'}</b>\n\n"
        "В тестовом режиме охота не меняет статистику, коллекцию, XP, кулдаун или рейтинги.\n"
        "Точный вид: <code>/admin_spawn ID</code> · погода: <code>/admin_forceweather НАЗВАНИЕ</code>."
    )


@dp.message(Command("admin"))
async def admin_command(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return await m.answer("Команда доступна только администратору.")
    await m.answer(
        "🛠 <b>Админ-панель</b>\n\n"
        "/test — безопасный тестовый режим\n"
        "/admin_stats — статистика проекта\n"
        "/admin_user @user — данные игрока\n"
        "/admin_setlevel @user 30\n"
        "/admin_setresearch @user forest 100 · вместо forest можно all\n"
        "/admin_givebait @user dew 5\n"
        "/admin_resetcooldown @user\n"
        "/admin_spawn ID — принудительный вид в тестовом режиме\n"
        "/admin_species — IDs всех видов\n"
        "/admin_forceweather НАЗВАНИЕ — тестовая погода; off для сброса\n"
        "\nТвои реальные уровень 30 и 100% исследования сохраняются автоматически."
    )


@dp.message(Command("test"))
async def test_command(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return await m.answer("Команда доступна только администратору.")
    await m.answer(test_panel_text(m.from_user.id), reply_markup=test_panel_keyboard(m.from_user.id))


@dp.callback_query(F.data.startswith("test:"))
async def test_cb(q: CallbackQuery):
    ensure_callback(q)
    if not admin_allowed(q.from_user):
        return await q.answer("Нет доступа.", show_alert=True)
    uid = q.from_user.id
    parts = q.data.split(":")
    ts = db.get_test_settings(uid)
    if parts[1] == "toggle":
        db.set_test_setting(uid, enabled=0 if ts["enabled"] else 1)
    elif parts[1] == "kind" and len(parts) >= 3:
        db.set_test_setting(uid, forced_kind=None if parts[2] == "normal" else parts[2])
    elif parts[1] == "quality" and len(parts) >= 3:
        db.set_test_setting(uid, forced_quality=None if parts[2] == "normal" else 99.6)
    elif parts[1] == "location" and len(parts) >= 3:
        vals = [None, "forest", "marsh", "ridge"]
        cur = ts["forced_location"]
        try:
            nxt = vals[(vals.index(cur) + 1) % len(vals)]
        except ValueError:
            nxt = None
        db.set_test_setting(uid, forced_location=nxt)
    elif parts[1] == "reset":
        db.set_test_setting(uid, enabled=0, forced_kind=None, forced_species=None,
                            forced_quality=None, forced_weather=None, forced_location=None)
    await q.message.edit_text(test_panel_text(uid), reply_markup=test_panel_keyboard(uid))
    await q.answer()


@dp.message(Command("admin_species"))
async def admin_species(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    lines = ["🦄 <b>ID видов</b>"]
    for lid, loc in LOCATIONS.items():
        lines.append(f"\n{loc['emoji']} <b>{loc['name']}</b>")
        for u in UNICORNS:
            if u["location"] == lid:
                secret = " 🗝" if u.get("secret") else ""
                lines.append(f"<code>{u['id']}</code> — {u['name']}{secret}")
    await m.answer("\n".join(lines))


@dp.message(Command("admin_spawn"))
async def admin_spawn(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Формат: <code>/admin_spawn species_id</code> или <code>/admin_spawn off</code>.")
    sid = parts[1].strip().lower()
    if sid == "off":
        db.set_test_setting(m.from_user.id, forced_species=None)
        return await m.answer("Принудительный вид отключён.")
    u = UNICORN_BY_ID.get(sid)
    if not u:
        return await m.answer("Неизвестный ID. Список: /admin_species")
    db.set_test_setting(m.from_user.id, enabled=1, forced_kind="unicorn", forced_species=sid, forced_location=u["location"])
    await m.answer(f"🧪 Следующая тестовая охота принудительно покажет: <b>{u['name']}</b>.")


@dp.message(Command("admin_forceweather"))
async def admin_forceweather(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Формат: <code>/admin_forceweather Название погоды</code> или <code>off</code>.")
    val = parts[1].strip()
    if val.lower() == "off":
        db.set_test_setting(m.from_user.id, forced_weather=None)
        return await m.answer("Тестовая погода отключена.")
    names = {name.lower(): name for cfg in LOCATIONS.values() for name, _, _ in cfg["weather"]}
    if val.lower() not in names:
        return await m.answer("Не нашёл такую погоду. Используй точное название из /world.")
    db.set_test_setting(m.from_user.id, enabled=1, forced_weather=names[val.lower()])
    await m.answer(f"🧪 Тестовая погода: <b>{names[val.lower()]}</b>.")


def _admin_target(text: str, index=1):
    parts = text.split()
    return db.find_player(parts[index]) if len(parts) > index else None


@dp.message(Command("admin_user"))
async def admin_user(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    p = _admin_target(m.text)
    if not p:
        return await m.answer("Игрок не найден. Формат: /admin_user @username")
    await m.answer(
        f"👤 <b>{html.escape(p['name'] or str(p['id']))}</b>\n"
        f"ID: <code>{p['id']}</code> · @{html.escape(p['username'] or '—')}\n"
        f"Уровень {p['level']} · XP {p['xp']} · охот {p['hunts']} · поймано {p['caught']}\n"
        f"Локация: {p['current_location']} · pity {p['pity_misses']} · rarity pity {p['rarity_pity']}"
    )


@dp.message(Command("admin_setlevel"))
async def admin_setlevel(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    parts = m.text.split()
    if len(parts) != 3:
        return await m.answer("Формат: /admin_setlevel @user 30")
    p = db.find_player(parts[1])
    try:
        level = max(1, min(game.MAX_LEVEL, int(parts[2])))
    except ValueError:
        return await m.answer("Уровень должен быть числом.")
    if not p:
        return await m.answer("Игрок не найден.")
    db.set_level(p["id"], level, 0)
    await m.answer(f"Уровень {html.escape(p['name'])}: <b>{level}</b>.")


@dp.message(Command("admin_setresearch"))
async def admin_setresearch(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    parts = m.text.split()
    if len(parts) != 4:
        return await m.answer("Формат: /admin_setresearch @user forest 100")
    p = db.find_player(parts[1])
    if not p:
        return await m.answer("Игрок не найден.")
    loc = parts[2].lower()
    try:
        pct = max(0, min(100, float(parts[3])))
    except ValueError:
        return await m.answer("Процент должен быть числом.")
    locs = list(LOCATIONS) if loc == "all" else [loc]
    if any(x not in LOCATIONS for x in locs):
        return await m.answer("Локации: forest, marsh, ridge или all.")
    for lid in locs:
        db.set_research_percent(p["id"], lid, pct)
    await m.answer(f"Исследование выставлено на <b>{pct:g}%</b>.")


@dp.message(Command("admin_givebait"))
async def admin_givebait(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    parts = m.text.split()
    if len(parts) != 4:
        return await m.answer("Формат: /admin_givebait @user dew 5")
    p = db.find_player(parts[1])
    bid = parts[2]
    try:
        amount = max(1, min(999, int(parts[3])))
    except ValueError:
        return await m.answer("Количество должно быть числом.")
    if not p or bid not in BAITS:
        return await m.answer("Не найден игрок или наживка. IDs: carrot, apple, clover, dew.")
    db.add_bait(p["id"], bid, amount)
    await m.answer(f"Добавлено: {BAITS[bid]['emoji']} {BAITS[bid]['name']} ×{amount}.")


@dp.message(Command("admin_resetcooldown"))
async def admin_resetcooldown(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    p = _admin_target(m.text)
    if not p:
        return await m.answer("Формат: /admin_resetcooldown @user")
    db.reset_cooldown(p["id"])
    await m.answer("Кулдаун сброшен.")


@dp.message(Command("admin_stats"))
async def admin_stats(m: Message):
    ensure(m)
    if not admin_allowed(m.from_user):
        return
    st = db.owner_stats(int(time.time()))
    conversion = (100 * st["payers"] / st["total_players"]) if st["total_players"] else 0
    avg = (st["hunts24"] / st["active24"]) if st["active24"] else 0
    lines = [
        "📊 <b>Статистика проекта</b>",
        f"Игроков всего: <b>{st['total_players']}</b>",
        f"DAU: <b>{st['dau']}</b> · активных по event-log: <b>{st['active24']}</b>",
        f"Охот за 24 ч: <b>{st['hunts24']}</b> · в среднем {avg:.1f} на активного",
        f"Поимок за 24 ч: <b>{st['catches24']}</b>",
        f"Stars: <b>{st['stars24']} ⭐</b> за 24 ч · <b>{st['stars_total']} ⭐</b> всего",
        f"Плативших игроков: <b>{st['payers']}</b> · conversion {conversion:.1f}%",
        "\n<b>Текущие локации игроков</b>",
    ]
    for r in st["locations"]:
        lid = r["current_location"]
        lines.append(f"• {LOCATIONS.get(lid, {}).get('name', lid)} — {r['n']}")
    if st["hunt_locations24"]:
        lines.append("\n<b>Популярные локации за 24 ч</b>")
        for r in st["hunt_locations24"]:
            lines.append(f"• {LOCATIONS.get(r['location_id'], {}).get('name', r['location_id'])} — {r['n']} охот")
    lines.append("\n<b>Уровни</b>")
    for r in st["levels"]:
        lines.append(f"• {r['bucket']}: {r['n']}")
    if st["popular"]:
        lines.append("\n<b>Самые частые поимки за 24 ч</b>")
        for r in st["popular"]:
            u = UNICORN_BY_ID.get(r["unicorn_id"])
            if u:
                lines.append(f"• {u['name']} — {r['n']}")
    rare = []
    for r in st["species24"]:
        u = UNICORN_BY_ID.get(r["unicorn_id"])
        if u:
            rare.append((u["tier"], -int(r["n"]), u, int(r["n"])))
    rare.sort(reverse=True, key=lambda x: (x[0], x[1]))
    if rare:
        lines.append("\n<b>Самые редкие виды, пойманные за 24 ч</b>")
        for _, _, u, n in rare[:5]:
            lines.append(f"• {RARITY_EMOJI[u['tier']]} {u['name']} — {n}")
    lines.append("\n<i>Детальный event-log охот ведётся начиная с версии 4.0.</i>")
    await m.answer("\n".join(lines))


@dp.message(Command("claimstar"))
async def claimstar(m: Message):
    """Recover a paid hunt when the successful-payment update was missed or fulfillment failed."""
    ensure(m)
    uid = m.from_user.id

    row = db.oldest_unfulfilled_star_payment(uid)
    if row is None:
        try:
            row = await _recover_star_transaction(uid)
        except Exception:
            logging.exception("Could not query Telegram Star transactions for user %s", uid)
            return await m.answer(
                "⚠️ Не удалось сейчас проверить историю Stars. Попробуй /claimstar ещё раз через минуту "
                "или обратись в /paysupport."
            )

    if row is None:
        return await m.answer(
            "⭐ Не нашёл неоприходованную оплату дополнительной охоты среди последних транзакций бота. "
            "Если Star точно списалась, обратись в /paysupport."
        )

    await m.answer("⭐ Оплата найдена. Восстанавливаю твою дополнительную охоту без повторного списания.")
    try:
        await do_hunt(
            m,
            bypass_cooldown=True,
            update_cooldown=False,
            paid=True,
            star_charge_id=row["telegram_charge_id"],
        )
    except Exception:
        logging.exception("Recovered paid hunt failed for charge %s", row["telegram_charge_id"])
        await m.answer(
            "⚠️ Платёж найден, но охоту пока не удалось запустить из-за технической ошибки. "
            "Оплата не потеряна — попробуй /claimstar ещё раз позже."
        )


@dp.message(F.text)
async def text_router(m):
    t = norm(m.text)
    if t == "единорог":
        await do_hunt(m)
    elif t == "инвентарь":
        await inventory(m)
    elif t == "профиль":
        await profile(m)
    elif t in {"наживка","наживки","приманка","приманки"}:
        await bait(m)
    elif t in {"локация","локации"}:
        await locations(m)
    elif t in {"бестиарий","энциклопедия"}:
        await bestiary(m)
    elif t in {"топ", "рейтинг", "лидеры"}:
        await top_players(m)
    elif t in {"меню", "menu"}:
        await menu_command(m)
    elif t in {"задание", "задания", "квест", "квесты"}:
        await quests_command(m)
    elif t in {"ловушка", "поставитьловушку", "trap"}:
        await trap_command(m)
    elif t in {"сезон", "season"}:
        await season_command(m)
    elif t in {"мир", "погода"}:
        await world(m)


async def main():
    db.init_db()
    # Finalize the previous monthly season once on startup so badges appear without manual archive browsing.
    key, _, start_ts, end_ts = game.season_bounds(-1)
    db.finalize_season(key, start_ts, end_ts)
    await bot.set_my_commands([
        BotCommand(command="menu", description="Игровое меню"),
        BotCommand(command="profile", description="Профиль и статистика"),
        BotCommand(command="quests", description="Ежедневные и недельные задания"),
        BotCommand(command="world", description="Погода и события мира"),
        BotCommand(command="locations", description="Локации"),
        BotCommand(command="bestiary", description="Бестиарий"),
        BotCommand(command="inventory", description="Коллекция"),
        BotCommand(command="bait", description="Наживки"),
        BotCommand(command="trap", description="Поставить или проверить ловушку"),
        BotCommand(command="top", description="Глобальный и локальный топ"),
        BotCommand(command="season", description="Сезонный рейтинг"),
        BotCommand(command="achievements", description="Достижения"),
        BotCommand(command="help", description="Правила и все команды"),
    ])
    print("Unicorn Hunt v4.1 started")
    trap_task = asyncio.create_task(trap_worker())
    try:
        await dp.start_polling(bot)
    finally:
        trap_task.cancel()
        await asyncio.gather(trap_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
