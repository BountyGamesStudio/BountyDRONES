"""
╔══════════════════════════════════════════════════════════════════╗
║   🛡  БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ РФ  v4.0  🛡                 ║
║   Парсинг через t.me/s/ — БЕЗ авторизации и без кода           ║
╠══════════════════════════════════════════════════════════════════╣
║  pip install python-telegram-bot==20.7 aiohttp beautifulsoup4   ║
║  Запуск: python bot.py                                           ║
║  Нужно заполнить только BOT_TOKEN                               ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import aiohttp
from bs4 import BeautifulSoup

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ══════════════════════════════════════════════════════════════════
#  ⚙️  КОНФИГ
# ══════════════════════════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")

SUBS_FILE  = "subscriptions.json"
STATS_FILE = "stats.json"

# Публичные каналы для парсинга (без @)
SOURCE_CHANNELS = [
    "radar_rvk",
    "MonitorRostov",
    "TaganCHP",
]

# Регион по умолчанию для канала (если авторазбор не нашёл)
CHANNEL_DEFAULT_REGION: Dict[str, str] = {
    "radar_rvk":    "ROS",
    "monitorrostov":"ROS",
    "taganchp":     "ROS",
}

POLL_INTERVAL = 30   # секунд между проверками каждого канала
DEDUP_TTL     = 300  # антидубль — 5 минут
COOLDOWN_TTL  = 120  # кулдаун между однотипными алертами по региону

# ══════════════════════════════════════════════════════════════════
#  ЛОГГЕР
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("AlertBot")

# ══════════════════════════════════════════════════════════════════
#  РЕГИОНЫ
# ══════════════════════════════════════════════════════════════════
REGIONS: Dict[str, Dict[str, str]] = {
    "🏛 Центральный ФО": {
        "MOW": "г. Москва",        "MOS": "Московская обл.",
        "BRY": "Брянская обл.",    "VLA": "Владимирская обл.",
        "IVA": "Ивановская обл.",  "KLU": "Калужская обл.",
        "KOS": "Костромская обл.", "KRS": "Курская обл.",
        "LIP": "Липецкая обл.",    "ORL": "Орловская обл.",
        "RYA": "Рязанская обл.",   "SMO": "Смоленская обл.",
        "TAM": "Тамбовская обл.",  "TVE": "Тверская обл.",
        "TUL": "Тульская обл.",    "YAR": "Ярославская обл.",
        "VOR": "Воронежская обл.", "BEL": "Белгородская обл.",
    },
    "🌊 Северо-Западный ФО": {
        "SPE": "г. Санкт-Петербург", "LEN": "Ленинградская обл.",
        "ARK": "Архангельская обл.",  "VLG": "Вологодская обл.",
        "KLG": "Калининградская обл.","KR":  "Республика Карелия",
        "KO":  "Республика Коми",     "MUR": "Мурманская обл.",
        "NAO": "Ненецкий АО",         "NGR": "Новгородская обл.",
        "PSK": "Псковская обл.",
    },
    "☀️ Южный ФО": {
        "ROS": "Ростовская обл.",    "KDA": "Краснодарский край",
        "AST": "Астраханская обл.",  "VGG": "Волгоградская обл.",
        "AD":  "Республика Адыгея",  "KL":  "Республика Калмыкия",
        "CR":  "Республика Крым",    "SEV": "г. Севастополь",
    },
    "🏔 Северо-Кавказский ФО": {
        "STA": "Ставропольский край",        "CE":  "Чеченская Республика",
        "DA":  "Республика Дагестан",        "IN":  "Республика Ингушетия",
        "KB":  "Кабардино-Балкарская Респ.", "KCH": "Карачаево-Черкесская Респ.",
        "NO":  "Республика С. Осетия",
    },
    "🌲 Приволжский ФО": {
        "NIZ": "Нижегородская обл.", "SAM": "Самарская обл.",
        "SAR": "Саратовская обл.",   "ULY": "Ульяновская обл.",
        "PNZ": "Пензенская обл.",    "ORE": "Оренбургская обл.",
        "PER": "Пермский край",      "KIR": "Кировская обл.",
        "BA":  "Башкортостан",       "MO":  "Мордовия",
        "TA":  "Татарстан",          "UD":  "Удмуртия",
        "CU":  "Чувашия",
    },
    "⛏ Уральский ФО": {
        "SVE": "Свердловская обл.", "CHE": "Челябинская обл.",
        "TYU": "Тюменская обл.",    "KGN": "Курганская обл.",
        "KHM": "ХМАО — Югра",      "YAN": "ЯНАО",
    },
    "🌏 Сибирский ФО": {
        "NVS": "Новосибирская обл.", "KEM": "Кузбасс",
        "KRA": "Красноярский край",  "IRK": "Иркутская обл.",
        "OMS": "Омская обл.",        "TOM": "Томская обл.",
        "BU":  "Бурятия",            "KK":  "Хакасия",
        "ALT": "Алтайский край",     "ZAB": "Забайкальский край",
    },
    "🌅 Дальневосточный ФО": {
        "PRI": "Приморский край",  "KHA": "Хабаровский край",
        "AMU": "Амурская обл.",    "MAG": "Магаданская обл.",
        "SAK": "Сахалинская обл.", "SA":  "Республика Саха (Якутия)",
        "KAM": "Камчатский край",
    },
}

REGION_BY_CODE: Dict[str, str] = {
    c: n for d in REGIONS.values() for c, n in d.items()
}

# ══════════════════════════════════════════════════════════════════
#  ДЕТЕКТОР УГРОЗ
# ══════════════════════════════════════════════════════════════════
THREAT_PATTERNS: Dict[str, List[Tuple[str, int]]] = {
    "all_clear": [
        ("отбой", 10), ("тревога отменена", 10), ("угроза миновала", 10),
        ("опасность миновала", 10), ("отбой тревог", 10), ("отбой воздушн", 10),
        ("всё спокойно", 8), ("можно выходить", 8), ("угроза прошла", 8),
    ],
    "drone": [
        ("бпла", 10), ("беспилотник", 10), ("дрон", 8), ("uav", 8),
        ("шахед", 10), ("shahed", 10), ("герань", 10), ("гербера", 8),
        ("мопед", 8), ("воздушная тревога", 10), ("воздушная опасность", 10),
        ("угроза бпла", 10), ("атака бпла", 10), ("налёт", 6),
        ("кружит", 5), ("барражир", 6),
    ],
    "missile": [
        ("ракета", 10), ("ракетный удар", 10), ("зур", 8),
        ("крылатая ракета", 10), ("баллистическ", 10),
        ("кинжал", 9), ("искандер", 9), ("калибр", 9),
        ("х-101", 9), ("х-22", 9), ("х-55", 9), ("х-47", 9),
        ("ракетная опасность", 10), ("ракетная угроза", 10),
    ],
    "artillery": [
        ("обстрел", 10), ("артиллерия", 10), ("миномёт", 9),
        ("снаряд", 8), ("прилёт", 8), ("выстрел", 6),
        ("взрыв", 5), ("взрывы", 5), ("канонада", 8), ("кассетный", 8),
    ],
}

REGION_KEYWORDS: Dict[str, List[str]] = {
    "ROS": ["ростов", "таганрог", "новочеркасск", "шахты", "волгодонск",
            "азов", "батайск", "ростовск"],
    "KDA": ["краснодар", "сочи", "новороссийск", "армавир", "кубань", "краснодарск"],
    "BEL": ["белгород", "старый оскол", "губкин", "белгородск"],
    "KRS": ["курск", "курская"],
    "BRY": ["брянск", "брянская"],
    "VOR": ["воронеж", "воронежская"],
    "MOW": ["москва", "московск"],
    "MOS": ["подмосковье", "московская обл"],
    "SPE": ["петербург", "санкт-петербург", "питер", "ленинград"],
    "LEN": ["ленинградская"],
    "KLG": ["калининград", "калининградск"],
    "SMO": ["смоленск", "смоленская"],
    "TVE": ["тверь", "тверская"],
    "PSK": ["псков", "псковская"],
    "NGR": ["новгород", "новгородская"],
    "MUR": ["мурманск", "мурманская"],
    "ARK": ["архангельск", "архангельская"],
    "VGG": ["волгоград", "волгоградская"],
    "AST": ["астрахань", "астраханская"],
    "CR":  ["крым", "симферополь", "керчь", "феодосия", "ялта"],
    "SEV": ["севастополь"],
    "STA": ["ставрополь", "ставропольский"],
    "DA":  ["дагестан", "махачкала", "дербент"],
    "CE":  ["чечня", "чеченская", "грозный"],
    "LIP": ["липецк", "липецкая"],
    "TUL": ["тула", "тульская"],
    "ORL": ["орёл", "орел", "орловская"],
    "RYA": ["рязань", "рязанская"],
    "TAM": ["тамбов", "тамбовская"],
    "PER": ["пермь", "пермский"],
    "SVE": ["екатеринбург", "свердловск"],
    "CHE": ["челябинск", "челябинская"],
    "SAM": ["самара", "самарская", "тольятти"],
    "SAR": ["саратов", "саратовская"],
    "ORE": ["оренбург", "оренбургская"],
    "NIZ": ["нижний новгород", "нижегородская"],
    "TA":  ["казань", "татарстан"],
    "NVS": ["новосибирск", "новосибирская"],
    "OMS": ["омск", "омская"],
    "TOM": ["томск", "томская"],
    "KEM": ["кемерово", "кузбасс"],
    "KRA": ["красноярск", "красноярский"],
    "IRK": ["иркутск", "иркутская"],
    "PRI": ["владивосток", "приморский"],
    "KHA": ["хабаровск", "хабаровский"],
    "SAK": ["сахалин", "южно-сахалинск"],
    "SA":  ["якутск", "якутия", "саха"],
}

# ══════════════════════════════════════════════════════════════════
#  ШАБЛОНЫ ОПОВЕЩЕНИЙ
# ══════════════════════════════════════════════════════════════════
LINE = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

ALERT_TEMPLATES: Dict[str, Dict] = {
    "drone": {
        "header":   "🚨 ВОЗДУШНАЯ ТРЕВОГА 🚨",
        "subhead":  "🚁 УГРОЗА АТАКИ БПЛА",
        "bar":      "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
        "actions": [
            "🏃 *НЕМЕДЛЕННО* спуститесь в подвал или укрытие",
            "🪟 *НЕ ПОДХОДИТЕ* к окнам — отойдите от стёкол",
            "🛋 *ЛЯГТЕ НА ПОЛ*, прикрыв голову руками",
            "🚫 *НЕ ПОЛЬЗУЙТЕСЬ ЛИФТОМ*",
            "🔌 Выключите газ и электричество если возможно",
            "📵 *НЕ СНИМАЙТЕ* видео — не публикуйте в соцсетях",
        ],
    },
    "missile": {
        "header":   "🚨 РАКЕТНАЯ ОПАСНОСТЬ 🚨",
        "subhead":  "🚀 УГРОЗА РАКЕТНОГО УДАРА",
        "bar":      "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
        "actions": [
            "🏃 *НЕМЕДЛЕННО* покиньте улицу — зайдите в здание",
            "🏚 *СПУСТИТЕСЬ В ПОДВАЛ* или бомбоубежище",
            "🪟 *НЕ ПОДХОДИТЕ К ОКНАМ*",
            "🎒 Возьмите документы, воду и тёплые вещи",
            "🚫 *НЕ ПОЛЬЗУЙТЕСЬ ЛИФТОМ*",
            "📡 Следите за официальными оповещениями",
        ],
    },
    "artillery": {
        "header":   "💥 УГРОЗА ОБСТРЕЛА 💥",
        "subhead":  "🔫 АРТИЛЛЕРИЙСКИЙ/МИНОМЁТНЫЙ ОГОНЬ",
        "bar":      "🟠🟠🟠🟠🟠🟠🟠🟠🟠🟠",
        "actions": [
            "🏚 *УКРОЙТЕСЬ В ПОДВАЛЕ* или бомбоубежище",
            "🚫 *НЕ ВЫХОДИТЕ НА УЛИЦУ*",
            "🪟 *НЕ ПОДХОДИТЕ К ОКНАМ*",
            "🌳 На открытой местности — лягте в канаву или овраг",
            "💣 *НЕ ТРОГАЙТЕ* незнакомые предметы после обстрела",
            "📵 Не публикуйте фото и видео",
        ],
    },
    "all_clear": {
        "header":   "✅ ОТБОЙ ТРЕВОГИ ✅",
        "subhead":  "🟢 УГРОЗА МИНОВАЛА",
        "bar":      "🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢",
        "actions": [
            "✔️ Воздушная тревога отменена",
            "✔️ Можно вернуться к обычной деятельности",
            "⚠️ Сохраняйте бдительность",
            "📡 Следите за следующими оповещениями",
        ],
    },
}


def build_alert(alert_type: str, region_name: str, source: str,
                original_text: str = "", alert_id: str = "") -> str:
    t = ALERT_TEMPLATES[alert_type]
    ts = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
    actions = "\n".join(f"  {a}" for a in t["actions"])
    snippet = ""
    if original_text and alert_type != "all_clear":
        clean = original_text.strip()[:280].replace("*", "").replace("_", "")
        snippet = f"\n\n💬 *Из источника:*\n_{clean}_\n"
    id_str = f"`#{alert_id}`" if alert_id else ""
    return (
        f"{t['bar']}\n"
        f"*{t['header']}*\n"
        f"{t['bar']}\n\n"
        f"*{t['subhead']}*\n"
        f"📍 *{region_name}*\n\n"
        f"{LINE}\n"
        f"⚡️ *ДЕЙСТВИЯ:*\n\n"
        f"{actions}"
        f"{snippet}\n"
        f"{LINE}\n"
        f"📞 *ЭКСТРЕННАЯ СЛУЖБА: 112*\n"
        f"📡 {source}\n"
        f"⏰ {ts}  {id_str}"
    )


# ══════════════════════════════════════════════════════════════════
#  ХРАНИЛИЩЕ
# ══════════════════════════════════════════════════════════════════
subscriptions: Dict[int, Set[str]] = {}
user_district:  Dict[int, str]     = {}
stats: Dict = {
    "total_alerts": 0,
    "by_type":   defaultdict(int),
    "by_region": defaultdict(int),
    "total_sent": 0,
}
_dedup:    Dict[str, float] = {}
_cooldown: Dict[str, float] = {}
# Последние обработанные ID сообщений каждого канала
_seen_ids: Dict[str, Set[str]] = defaultdict(set)

ptb_app: Optional[Application] = None


def load_data():
    global subscriptions, stats
    if os.path.exists(SUBS_FILE):
        try:
            raw = json.load(open(SUBS_FILE, encoding="utf-8"))
            subscriptions = {int(k): set(v) for k, v in raw.items()}
            log.info(f"Подписки загружены: {len(subscriptions)} пользователей")
        except Exception as e:
            log.warning(f"Ошибка загрузки подписок: {e}")
    if os.path.exists(STATS_FILE):
        try:
            raw = json.load(open(STATS_FILE, encoding="utf-8"))
            stats.update(raw)
            stats["by_type"]   = defaultdict(int, stats.get("by_type", {}))
            stats["by_region"] = defaultdict(int, stats.get("by_region", {}))
        except Exception:
            pass


def save_subs():
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): list(v) for k, v in subscriptions.items()}, f, ensure_ascii=False)


def save_stats():
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({**stats, "by_type": dict(stats["by_type"]),
                   "by_region": dict(stats["by_region"])}, f, ensure_ascii=False)


def get_subs(uid: int) -> Set[str]:
    return subscriptions.setdefault(uid, set())


# ══════════════════════════════════════════════════════════════════
#  АНАЛИЗ ТЕКСТА
# ══════════════════════════════════════════════════════════════════
def detect_type(text: str) -> Optional[str]:
    lower = text.lower()
    scores: Dict[str, int] = defaultdict(int)
    for atype, patterns in THREAT_PATTERNS.items():
        for kw, w in patterns:
            if kw in lower:
                scores[atype] += w
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 8 else None


def detect_regions(text: str) -> Set[str]:
    lower = text.lower()
    return {code for code, kws in REGION_KEYWORDS.items() if any(k in lower for k in kws)}


def dedup_key(regions: Set[str], atype: str) -> str:
    return hashlib.md5(f"{sorted(regions)}{atype}".encode()).hexdigest()[:10]


def is_dup(regions: Set[str], atype: str) -> bool:
    key = f"{sorted(regions)}:{atype}"
    now = time.time()
    if now - _dedup.get(key, 0) < DEDUP_TTL:
        return True
    _dedup[key] = now
    return False


def on_cooldown(region: str, atype: str) -> bool:
    key = f"{region}:{atype}"
    now = time.time()
    if now - _cooldown.get(key, 0) < COOLDOWN_TTL:
        return True
    _cooldown[key] = now
    return False


# ══════════════════════════════════════════════════════════════════
#  ПАРСЕР t.me/s/  (без авторизации)
# ══════════════════════════════════════════════════════════════════
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


async def fetch_channel(session: aiohttp.ClientSession, channel: str) -> List[Dict]:
    """
    Получает последние сообщения публичного канала через t.me/s/channel
    Возвращает список {"id": str, "text": str}
    """
    url = f"https://t.me/s/{channel}"
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                log.warning(f"[{channel}] HTTP {r.status}")
                return []
            html = await r.text()
    except Exception as e:
        log.warning(f"[{channel}] Ошибка запроса: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    messages = []
    for msg in soup.select(".tgme_widget_message"):
        msg_id = msg.get("data-post", "")
        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        text = text_el.get_text("\n", strip=True)
        if text:
            messages.append({"id": msg_id, "text": text})
    return messages


async def poll_channels():
    """Фоновая задача — опрашивает каналы каждые POLL_INTERVAL секунд."""
    log.info(f"🔍 Поллинг запущен (интервал: {POLL_INTERVAL}с)")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Первый прогон — просто заполняем _seen_ids, не рассылаем
        for ch in SOURCE_CHANNELS:
            msgs = await fetch_channel(session, ch)
            for m in msgs:
                _seen_ids[ch].add(m["id"])
            log.info(f"📡 @{ch}: загружено {len(msgs)} начальных сообщений")
            await asyncio.sleep(1)

        while True:
            await asyncio.sleep(POLL_INTERVAL)
            for ch in SOURCE_CHANNELS:
                try:
                    msgs = await fetch_channel(session, ch)
                    new_msgs = [m for m in msgs if m["id"] not in _seen_ids[ch]]
                    for m in new_msgs:
                        _seen_ids[ch].add(m["id"])
                        await process_message(ch, m["text"])
                    if new_msgs:
                        log.info(f"📨 @{ch}: {len(new_msgs)} новых сообщений")
                except Exception as e:
                    log.warning(f"[{ch}] Ошибка обработки: {e}")
                await asyncio.sleep(2)


async def process_message(channel: str, text: str):
    atype = detect_type(text)
    if not atype:
        return

    regions = detect_regions(text)
    if not regions:
        fallback = CHANNEL_DEFAULT_REGION.get(channel.lower())
        if fallback:
            regions = {fallback}
        else:
            return

    source = f"@{channel}"
    log.info(f"🔔 {atype.upper()} | {regions} | {source}")
    await broadcast(regions, atype, source, text)


# ══════════════════════════════════════════════════════════════════
#  РАССЫЛКА
# ══════════════════════════════════════════════════════════════════
async def broadcast(regions: Set[str], atype: str, source: str, original: str = ""):
    if ptb_app is None:
        return
    if is_dup(regions, atype):
        log.info(f"⏭ Дубль пропущен: {atype} / {regions}")
        return

    aid = dedup_key(regions, atype)
    sent = 0
    region_to_users: Dict[str, List[int]] = defaultdict(list)

    for uid, subs in list(subscriptions.items()):
        matched = subs & regions
        if not matched:
            continue
        for rc in matched:
            if not on_cooldown(rc, atype):
                region_to_users[rc].append(uid)
                break

    for rc, uids in region_to_users.items():
        rname = REGION_BY_CODE.get(rc, rc)
        msg   = build_alert(atype, rname, source, original, aid)
        for uid in uids:
            try:
                await ptb_app.bot.send_message(
                    chat_id=uid, text=msg, parse_mode=ParseMode.MARKDOWN
                )
                sent += 1
                await asyncio.sleep(0.04)
            except Exception as e:
                log.warning(f"uid={uid}: {e}")

    if sent:
        stats["total_alerts"] += 1
        stats["by_type"][atype] += 1
        for rc in regions:
            stats["by_region"][rc] += 1
        stats["total_sent"] += sent
        save_stats()
        log.info(f"✅ Отправлено {sent} чел. | #{aid}")


# ══════════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺  Выбрать регионы",       callback_data="select_district")],
        [InlineKeyboardButton("📋  Мои подписки",          callback_data="my_subs")],
        [InlineKeyboardButton("📊  Статистика",            callback_data="stats")],
        [InlineKeyboardButton("📡  Каналы мониторинга",    callback_data="sources")],
        [InlineKeyboardButton("🧹  Сбросить подписки",     callback_data="clear_confirm")],
        [InlineKeyboardButton("ℹ️  Помощь",                callback_data="help")],
    ])


def kb_districts() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(d, callback_data=f"d:{d}")] for d in REGIONS]
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def kb_regions(uid: int, district: str) -> InlineKeyboardMarkup:
    subs = get_subs(uid)
    rows = []
    items = list(REGIONS[district].items())
    for i in range(0, len(items), 2):
        row = []
        for code, name in items[i:i+2]:
            mark = "✅ " if code in subs else ""
            row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"t:{code}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ К округам", callback_data="select_district"),
        InlineKeyboardButton("🏠 Меню",      callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])


def main_menu_text(uid: int) -> str:
    subs = get_subs(uid)
    sub_line = (
        f"📌 Вы следите за *{len(subs)}* регионами"
        if subs else "📌 Вы пока не выбрали ни одного региона"
    )
    return (
        "🛡 *БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ* 🛡\n"
        f"{LINE}\n"
        f"{sub_line}\n\n"
        "Выберите действие:"
    )


# ══════════════════════════════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        main_menu_text(uid), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
    )


async def cmd_regions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выберите федеральный округ:", reply_markup=kb_districts())


async def cmd_mysubs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    subs = get_subs(uid)
    if not subs:
        text = "У вас нет активных подписок.\n\n/regions — выбрать регионы"
    else:
        lines = "\n".join(f"  • {REGION_BY_CODE.get(c, c)}" for c in sorted(subs))
        text = f"📋 *Ваши регионы ({len(subs)}):*\n\n{lines}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 *Статус бота*\n\n"
        f"👥 Пользователей: *{len(subscriptions)}*\n"
        f"📨 Отправлено оповещений: *{stats['total_sent']}*\n"
        f"🔔 Тревог обработано: *{stats['total_alerts']}*\n\n"
        f"📡 Каналы: {', '.join('@'+c for c in SOURCE_CHANNELS)}\n"
        f"⏱ Интервал опроса: *{POLL_INTERVAL}с*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════════════════════════
#  КНОПКИ
# ══════════════════════════════════════════════════════════════════
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    if data == "main_menu":
        await q.edit_message_text(
            main_menu_text(uid), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )
    elif data == "select_district":
        await q.edit_message_text(
            "🗺 *Выберите федеральный округ:*",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_districts()
        )
    elif data.startswith("d:"):
        district = data[2:]
        user_district[uid] = district
        subs     = get_subs(uid)
        selected = sum(1 for c in REGIONS[district] if c in subs)
        total    = len(REGIONS[district])
        await q.edit_message_text(
            f"*{district}*\n\nВыбрано: {selected} / {total}\n"
            "Нажмите регион чтобы подписаться / отписаться (✅ — активно):",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_regions(uid, district)
        )
    elif data.startswith("t:"):
        code = data[2:]
        subs = get_subs(uid)
        name = REGION_BY_CODE.get(code, code)
        if code in subs:
            subs.remove(code);  action = f"❌ Отписались от *{name}*"
        else:
            subs.add(code);     action = f"✅ Подписались на *{name}*"
        save_subs()
        district = user_district.get(uid, list(REGIONS.keys())[0])
        selected = sum(1 for c in REGIONS[district] if c in subs)
        await q.edit_message_text(
            f"{action}\n\n*{district}*\nВыбрано: {selected} / {len(REGIONS[district])}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_regions(uid, district)
        )
    elif data == "my_subs":
        subs = get_subs(uid)
        text = (
            "У вас нет активных подписок." if not subs
            else f"📋 *Ваши регионы ({len(subs)}):*\n\n" +
                 "\n".join(f"  • {REGION_BY_CODE.get(c, c)}" for c in sorted(subs))
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())
    elif data == "stats":
        top = sorted(stats["by_region"].items(), key=lambda x: x[1], reverse=True)[:5]
        top_str = "\n".join(
            f"  {i+1}. {REGION_BY_CODE.get(r,r)} — {n} раз"
            for i,(r,n) in enumerate(top)
        ) or "  —"
        tmap = {"drone":"🚁 БПЛА","missile":"🚀 Ракеты","artillery":"💥 Обстрелы","all_clear":"✅ Отбой"}
        btype = "\n".join(f"  {tmap.get(k,k)}: {v}" for k,v in stats["by_type"].items()) or "  —"
        await q.edit_message_text(
            f"📊 *Статистика*\n\n"
            f"🔔 Тревог: *{stats['total_alerts']}*\n"
            f"📨 Отправлено: *{stats['total_sent']}*\n"
            f"👥 Пользователей: *{len(subscriptions)}*\n\n"
            f"*По типам:*\n{btype}\n\n*Топ-5 регионов:*\n{top_str}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
        )
    elif data == "sources":
        ch_lines = "\n".join(f"  • @{c}" for c in SOURCE_CHANNELS)
        await q.edit_message_text(
            f"📡 *Каналы мониторинга:*\n\n{ch_lines}\n\n"
            f"Опрос каждые *{POLL_INTERVAL} секунд*\n"
            f"Антидубль: *{DEDUP_TTL//60} мин* | Кулдаун: *{COOLDOWN_TTL//60} мин*\n\n"
            "Парсинг идёт через публичный веб-интерфейс t.me — без авторизации.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
        )
    elif data == "clear_confirm":
        subs = get_subs(uid)
        if not subs:
            await q.edit_message_text("У вас нет подписок.", reply_markup=kb_back())
            return
        await q.edit_message_text(
            f"⚠️ Сбросить все *{len(subs)}* подписки?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, сбросить", callback_data="clear_subs")],
                [InlineKeyboardButton("❌ Отмена",       callback_data="main_menu")],
            ])
        )
    elif data == "clear_subs":
        subscriptions[uid] = set()
        save_subs()
        await q.edit_message_text("🧹 Все подписки сброшены.", reply_markup=kb_back())
    elif data == "help":
        await q.edit_message_text(
            f"ℹ️ *Справка*\n\n{LINE}\n"
            "*/start* — главное меню\n"
            "*/regions* — выбрать регионы\n"
            "*/mysubs* — мои подписки\n"
            "*/status* — статус бота\n\n"
            f"{LINE}\n"
            "🚁 *БПЛА* — угроза беспилотников\n"
            "🚀 *Ракета* — ракетная опасность\n"
            "💥 *Обстрел* — артиллерийский/миномётный огонь\n"
            f"✅ *Отбой* — угроза миновала\n\n{LINE}\n"
            "📞 *112* — экстренная служба\n"
            "🚒 *101* — МЧС\n"
            "🚑 *103* — скорая",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
        )


# ══════════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════════
async def main():
    global ptb_app
    load_data()

    ptb_app = Application.builder().token(BOT_TOKEN).build()
    ptb_app.add_handler(CommandHandler("start",   cmd_start))
    ptb_app.add_handler(CommandHandler("regions", cmd_regions))
    ptb_app.add_handler(CommandHandler("mysubs",  cmd_mysubs))
    ptb_app.add_handler(CommandHandler("status",  cmd_status))
    ptb_app.add_handler(CallbackQueryHandler(on_button))

    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.updater.start_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )
    log.info("✅ Бот запущен")

    # Запускаем поллинг каналов параллельно
    await poll_channels()

    await ptb_app.updater.stop()
    await ptb_app.stop()
    await ptb_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
