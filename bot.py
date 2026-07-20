"""
╔══════════════════════════════════════════════════════════════════╗
║   🛡  БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ РФ  v3.0  🛡                 ║
║   Автопарсинг + антидубли + статистика + умный детектор         ║
╠══════════════════════════════════════════════════════════════════╣
║  pip install telethon python-telegram-bot==20.7                  ║
║                                                                  ║
║  Переменные окружения (или вписать прямо сюда):                  ║
║    BOT_TOKEN   — токен от @BotFather                             ║
║    API_ID      — с my.telegram.org                               ║
║    API_HASH    — с my.telegram.org                               ║
║    PHONE       — ваш номер (+7...)                               ║
║                                                                  ║
║  Запуск:  python bot.py                                          ║
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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from telethon import TelegramClient, events

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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
API_ID    = int(os.environ.get("API_ID", "0"))
API_HASH  = os.environ.get("API_HASH",  "ВАШ_API_HASH")
PHONE     = os.environ.get("PHONE",     "+7XXXXXXXXXX")

SUBS_FILE   = "subscriptions.json"
STATS_FILE  = "stats.json"

# Каналы-источники (без @)
SOURCE_CHANNELS = [
    "radar_rvk",
    "MonitorRostov",
    "TaganCHP",
]

# Привязка канала к региону по умолчанию (если авторазбор не нашёл)
CHANNEL_DEFAULT_REGION: Dict[str, str] = {
    "radar_rvk":    "ROS",
    "monitorrostov":"ROS",
    "taganchp":     "ROS",
}

# Кулдаун антидубля: одно и то же событие в одном регионе не шлём повторно (секунды)
DEDUP_TTL    = 300   # 5 минут
COOLDOWN_TTL = 120   # между однотипными алертами по одному региону — 2 минуты

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
#  ДЕТЕКТОР УГРОЗ — ключевые слова с весами
# ══════════════════════════════════════════════════════════════════
# Формат: (паттерн, вес)  — побеждает тип с наибольшей суммой весов
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
        ("мина упала", 9), ("взрыв", 5), ("взрывы", 5),
        ("канонада", 8), ("кассетный", 8),
    ],
}

REGION_KEYWORDS: Dict[str, List[str]] = {
    "ROS": ["ростов", "таганрог", "новочеркасск", "шахты", "волгодонск",
            "азов", "батайск", "донецк", "ростовск"],
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
    "KEM": ["кемерово", "кузбасс", "кемеровская"],
    "KRA": ["красноярск", "красноярский"],
    "IRK": ["иркутск", "иркутская"],
    "PRI": ["владивосток", "приморский", "приморье"],
    "KHA": ["хабаровск", "хабаровский"],
    "SAK": ["сахалин", "южно-сахалинск"],
    "SA":  ["якутск", "якутия", "саха"],
}

# ══════════════════════════════════════════════════════════════════
#  ШАБЛОНЫ ОПОВЕЩЕНИЙ
# ══════════════════════════════════════════════════════════════════
# Разделитель-линия
LINE = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

ALERT_TEMPLATES: Dict[str, Dict] = {
    "drone": {
        "header": "🚨 ВОЗДУШНАЯ ТРЕВОГА 🚨",
        "subhead": "🚁 УГРОЗА АТАКИ БПЛА",
        "color_bar": "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
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
        "header": "🚨 РАКЕТНАЯ ОПАСНОСТЬ 🚨",
        "subhead": "🚀 УГРОЗА РАКЕТНОГО УДАРА",
        "color_bar": "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
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
        "header": "💥 УГРОЗА ОБСТРЕЛА 💥",
        "subhead": "🔫 АРТИЛЛЕРИЙСКИЙ/МИНОМЁТНЫЙ ОГОНЬ",
        "color_bar": "🟠🟠🟠🟠🟠🟠🟠🟠🟠🟠",
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
        "header": "✅ ОТБОЙ ТРЕВОГИ ✅",
        "subhead": "🟢 УГРОЗА МИНОВАЛА",
        "color_bar": "🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢",
        "actions": [
            "✔️ Воздушная тревога отменена",
            "✔️ Можно вернуться к обычной деятельности",
            "⚠️ Сохраняйте бдительность",
            "📡 Следите за следующими оповещениями",
        ],
    },
}


def build_alert_message(
    alert_type: str,
    region_name: str,
    source: str,
    original_text: str = "",
    alert_id: str = "",
) -> str:
    t = ALERT_TEMPLATES[alert_type]
    ts = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
    actions = "\n".join(f"  {a}" for a in t["actions"])
    snippet = ""
    if original_text and alert_type != "all_clear":
        clean = original_text.strip()[:280].replace("*", "").replace("_", "")
        snippet = f"\n\n💬 *Из источника:*\n_{clean}…_\n"
    id_str = f"`#{alert_id}`  " if alert_id else ""

    return (
        f"{t['color_bar']}\n"
        f"*{t['header']}*\n"
        f"{t['color_bar']}\n\n"
        f"*{t['subhead']}*\n"
        f"📍 *{region_name}*\n\n"
        f"{LINE}\n"
        f"⚡️ *ДЕЙСТВИЯ:*\n\n"
        f"{actions}"
        f"{snippet}\n"
        f"{LINE}\n"
        f"📞 *ЭКСТРЕННАЯ СЛУЖБА: 112*\n"
        f"📡 Источник: {source}\n"
        f"⏰ {ts}   {id_str}"
    )


# ══════════════════════════════════════════════════════════════════
#  ХРАНИЛИЩЕ
# ══════════════════════════════════════════════════════════════════
subscriptions: Dict[int, Set[str]] = {}   # uid → {region_code, …}
user_district:  Dict[int, str]     = {}   # uid → текущий округ в меню

# Статистика
stats: Dict = {
    "total_alerts": 0,
    "by_type": defaultdict(int),
    "by_region": defaultdict(int),
    "total_sent": 0,
    "subscribers": 0,
}

# Антидубли: (region, type) → timestamp последней отправки
_dedup_cache:    Dict[str, float] = {}
_cooldown_cache: Dict[str, float] = {}

ptb_app: Optional[Application] = None


# ── persistence ────────────────────────────────────────────────
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


def save_subscriptions():
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): list(v) for k, v in subscriptions.items()}, f, ensure_ascii=False)


def save_stats():
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            **stats,
            "by_type":   dict(stats["by_type"]),
            "by_region": dict(stats["by_region"]),
        }, f, ensure_ascii=False)


def get_user_subs(uid: int) -> Set[str]:
    return subscriptions.setdefault(uid, set())


# ══════════════════════════════════════════════════════════════════
#  АНАЛИЗАТОР ТЕКСТА
# ══════════════════════════════════════════════════════════════════
def detect_alert_type(text: str) -> Optional[str]:
    lower = text.lower()
    scores: Dict[str, int] = defaultdict(int)
    for atype, patterns in THREAT_PATTERNS.items():
        for kw, weight in patterns:
            if kw in lower:
                scores[atype] += weight
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 8 else None


def detect_regions(text: str) -> Set[str]:
    lower = text.lower()
    found: Set[str] = set()
    for code, kws in REGION_KEYWORDS.items():
        for kw in kws:
            if kw in lower:
                found.add(code)
    return found


def make_dedup_key(regions: Set[str], alert_type: str) -> str:
    return hashlib.md5(f"{sorted(regions)}{alert_type}".encode()).hexdigest()[:12]


def is_duplicate(regions: Set[str], alert_type: str) -> bool:
    key = f"{sorted(regions)}:{alert_type}"
    now = time.time()
    last = _dedup_cache.get(key, 0)
    if now - last < DEDUP_TTL:
        return True
    _dedup_cache[key] = now
    return False


def is_on_cooldown(region: str, alert_type: str) -> bool:
    key = f"{region}:{alert_type}"
    now = time.time()
    last = _cooldown_cache.get(key, 0)
    if now - last < COOLDOWN_TTL:
        return True
    _cooldown_cache[key] = now
    return False


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ══════════════════════════════════════════════════════════════════
#  РАССЫЛКА
# ══════════════════════════════════════════════════════════════════
async def broadcast(
    region_codes: Set[str],
    alert_type: str,
    source: str,
    original_text: str = "",
):
    if ptb_app is None:
        return

    # Антидубль на весь пакет
    if is_duplicate(region_codes, alert_type):
        log.info(f"⏭ Дубль пропущен: {alert_type} / {region_codes}")
        return

    alert_id = make_dedup_key(region_codes, alert_type)
    sent_total = 0

    # Группируем пользователей по первому совпавшему региону
    region_to_users: Dict[str, List[int]] = defaultdict(list)
    for uid, subs in list(subscriptions.items()):
        matched = subs & region_codes
        if not matched:
            continue
        # кулдаун по каждому региону отдельно
        for rc in matched:
            if not is_on_cooldown(rc, alert_type):
                region_to_users[rc].append(uid)
                break  # одно оповещение на пользователя

    for region_code, uids in region_to_users.items():
        region_name = REGION_BY_CODE.get(region_code, region_code)
        message = build_alert_message(
            alert_type, region_name, source, original_text, alert_id
        )
        for uid in uids:
            try:
                await ptb_app.bot.send_message(
                    chat_id=uid,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                )
                sent_total += 1
                await asyncio.sleep(0.04)
            except Exception as e:
                log.warning(f"Ошибка отправки uid={uid}: {e}")

    if sent_total:
        stats["total_alerts"] += 1
        stats["by_type"][alert_type] += 1
        for rc in region_codes:
            stats["by_region"][rc] += 1
        stats["total_sent"] += sent_total
        save_stats()
        log.info(
            f"📨 [{ts()}] Разослано: {sent_total} чел. | "
            f"Тип: {alert_type} | Регионы: {region_codes} | #{alert_id}"
        )


# ══════════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════
def kb_main() -> InlineKeyboardMarkup:
    n = sum(len(v) for v in subscriptions.values())
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺  Выбрать регионы",        callback_data="select_district")],
        [InlineKeyboardButton("📋  Мои подписки",           callback_data="my_subs")],
        [InlineKeyboardButton("📊  Статистика оповещений",  callback_data="stats")],
        [InlineKeyboardButton("📡  Каналы мониторинга",     callback_data="sources")],
        [InlineKeyboardButton("🧹  Сбросить подписки",      callback_data="clear_confirm")],
        [InlineKeyboardButton("ℹ️  Помощь",                 callback_data="help")],
    ])


def kb_districts() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(d, callback_data=f"d:{d}")] for d in REGIONS]
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def kb_regions(uid: int, district: str) -> InlineKeyboardMarkup:
    subs = get_user_subs(uid)
    rows = []
    items = list(REGIONS[district].items())
    # по 2 кнопки в ряд
    for i in range(0, len(items), 2):
        row = []
        for code, name in items[i:i+2]:
            mark = "✅ " if code in subs else ""
            row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"t:{code}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ К округам",   callback_data="select_district"),
        InlineKeyboardButton("🏠 Меню",        callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])


# ══════════════════════════════════════════════════════════════════
#  ТЕКСТ ГЛАВНОГО МЕНЮ
# ══════════════════════════════════════════════════════════════════
def main_menu_text(uid: int) -> str:
    subs = get_user_subs(uid)
    sub_line = (
        f"📌 Вы следите за *{len(subs)}* регионами"
        if subs else
        "📌 Вы пока не выбрали ни одного региона"
    )
    return (
        "🛡 *БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ* 🛡\n"
        f"{LINE}\n"
        f"{sub_line}\n\n"
        "Выберите действие:"
    )


# ══════════════════════════════════════════════════════════════════
#  ОБРАБОТЧИКИ КОМАНД
# ══════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        main_menu_text(uid),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(),
    )


async def cmd_regions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Выберите федеральный округ:",
        reply_markup=kb_districts(),
    )


async def cmd_mysubs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    subs = get_user_subs(uid)
    if not subs:
        text = "У вас нет активных подписок.\n\n/regions — выбрать регионы"
    else:
        lines = "\n".join(f"  • {REGION_BY_CODE.get(c, c)}" for c in sorted(subs))
        text = f"📋 *Ваши регионы ({len(subs)}):*\n\n{lines}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    total_subs = len(subscriptions)
    total_regions = sum(len(v) for v in subscriptions.values())
    await update.message.reply_text(
        f"📊 *Статус бота*\n\n"
        f"👥 Пользователей: *{total_subs}*\n"
        f"📌 Всего подписок: *{total_regions}*\n"
        f"📨 Оповещений отправлено: *{stats['total_sent']}*\n"
        f"🔔 Тревог обработано: *{stats['total_alerts']}*\n\n"
        f"📡 Каналы: {', '.join('@'+c for c in SOURCE_CHANNELS)}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════════════════════════
#  ОБРАБОТЧИК КНОПОК
# ══════════════════════════════════════════════════════════════════
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    # ── Главное меню ──
    if data == "main_menu":
        await q.edit_message_text(
            main_menu_text(uid),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(),
        )

    # ── Список округов ──
    elif data == "select_district":
        await q.edit_message_text(
            "🗺 *Выберите федеральный округ:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_districts(),
        )

    # ── Войти в округ ──
    elif data.startswith("d:"):
        district = data[2:]
        user_district[uid] = district
        subs = get_user_subs(uid)
        selected = sum(1 for c in REGIONS[district] if c in subs)
        total    = len(REGIONS[district])
        await q.edit_message_text(
            f"*{district}*\n\n"
            f"Выбрано: {selected} / {total}\n"
            "Нажмите регион чтобы подписаться / отписаться (✅ — активно):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_regions(uid, district),
        )

    # ── Переключить регион ──
    elif data.startswith("t:"):
        code = data[2:]
        subs = get_user_subs(uid)
        name = REGION_BY_CODE.get(code, code)
        if code in subs:
            subs.remove(code)
            action = f"❌ Отписались от *{name}*"
        else:
            subs.add(code)
            action = f"✅ Подписались на *{name}*"
        save_subscriptions()
        district = user_district.get(uid, list(REGIONS.keys())[0])
        selected = sum(1 for c in REGIONS[district] if c in subs)
        total    = len(REGIONS[district])
        await q.edit_message_text(
            f"{action}\n\n*{district}*\nВыбрано: {selected} / {total}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_regions(uid, district),
        )

    # ── Мои подписки ──
    elif data == "my_subs":
        subs = get_user_subs(uid)
        if not subs:
            text = "У вас нет активных подписок.\n\nНажмите «Выбрать регионы» чтобы добавить."
        else:
            lines = "\n".join(f"  • {REGION_BY_CODE.get(c, c)}" for c in sorted(subs))
            text  = f"📋 *Ваши регионы ({len(subs)}):*\n\n{lines}"
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    # ── Статистика ──
    elif data == "stats":
        top_regions = sorted(
            stats["by_region"].items(), key=lambda x: x[1], reverse=True
        )[:5]
        top_str = "\n".join(
            f"  {i+1}. {REGION_BY_CODE.get(r, r)} — {n} раз"
            for i, (r, n) in enumerate(top_regions)
        ) or "  —"
        type_map = {"drone": "🚁 БПЛА", "missile": "🚀 Ракеты",
                    "artillery": "💥 Обстрелы", "all_clear": "✅ Отбой"}
        by_type_str = "\n".join(
            f"  {type_map.get(k, k)}: {v}"
            for k, v in stats["by_type"].items()
        ) or "  —"
        await q.edit_message_text(
            f"📊 *Статистика оповещений*\n\n"
            f"🔔 Всего тревог: *{stats['total_alerts']}*\n"
            f"📨 Сообщений отправлено: *{stats['total_sent']}*\n"
            f"👥 Пользователей: *{len(subscriptions)}*\n\n"
            f"*По типам:*\n{by_type_str}\n\n"
            f"*Топ-5 регионов:*\n{top_str}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back(),
        )

    # ── Источники ──
    elif data == "sources":
        ch_lines = "\n".join(f"  • @{c}" for c in SOURCE_CHANNELS)
        await q.edit_message_text(
            f"📡 *Каналы мониторинга:*\n\n{ch_lines}\n\n"
            "Бот отслеживает новые сообщения в реальном времени.\n"
            "При обнаружении угрозы автоматически рассылает\n"
            "оповещение подписчикам затронутого региона.\n\n"
            f"⏱ Антидубль: {DEDUP_TTL // 60} мин  •  "
            f"Кулдаун: {COOLDOWN_TTL // 60} мин",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back(),
        )

    # ── Подтверждение сброса ──
    elif data == "clear_confirm":
        subs = get_user_subs(uid)
        if not subs:
            await q.edit_message_text("У вас нет подписок.", reply_markup=kb_back())
            return
        await q.edit_message_text(
            f"⚠️ Вы уверены что хотите сбросить все *{len(subs)}* подписок?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, сбросить", callback_data="clear_subs")],
                [InlineKeyboardButton("❌ Отмена",       callback_data="main_menu")],
            ]),
        )

    elif data == "clear_subs":
        subscriptions[uid] = set()
        save_subscriptions()
        await q.edit_message_text("🧹 Все подписки сброшены.", reply_markup=kb_back())

    # ── Помощь ──
    elif data == "help":
        await q.edit_message_text(
            "ℹ️ *Справка*\n\n"
            f"{LINE}\n"
            "*/start* — главное меню\n"
            "*/regions* — выбрать регионы\n"
            "*/mysubs* — мои подписки\n"
            "*/status* — статус бота\n\n"
            f"{LINE}\n"
            "*Типы оповещений:*\n"
            "🚁 *БПЛА* — угроза беспилотников\n"
            "🚀 *Ракета* — ракетная опасность\n"
            "💥 *Обстрел* — артиллерийский/миномётный огонь\n"
            "✅ *Отбой* — угроза миновала\n\n"
            f"{LINE}\n"
            "📞 *Экстренная служба: 112*\n"
            "🚒 *МЧС: 101*\n"
            "👮 *Полиция: 102*\n"
            "🚑 *Скорая: 103*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back(),
        )


# ══════════════════════════════════════════════════════════════════
#  TELETHON — МОНИТОРИНГ КАНАЛОВ
# ══════════════════════════════════════════════════════════════════
async def run_telethon():
    client = TelegramClient("monitor_session", API_ID, API_HASH)
    await client.start(phone=PHONE)
    log.info("✅ Telethon подключён")

    channel_entities = []
    for username in SOURCE_CHANNELS:
        try:
            entity = await client.get_entity(username)
            channel_entities.append(entity)
            log.info(f"📡 Канал подключён: @{username}")
        except Exception as e:
            log.warning(f"Не удалось подключиться к @{username}: {e}")

    if not channel_entities:
        log.error("❌ Ни один канал не доступен. Проверьте SOURCE_CHANNELS.")
        return

    @client.on(events.NewMessage(chats=channel_entities))
    async def on_message(event):
        text = (event.message.message or "").strip()
        if len(text) < 10:
            return

        alert_type = detect_alert_type(text)
        if not alert_type:
            return

        regions = detect_regions(text)
        if not regions:
            ch_user = (getattr(event.chat, "username", "") or "").lower()
            fallback = CHANNEL_DEFAULT_REGION.get(ch_user)
            if fallback:
                regions = {fallback}
            else:
                log.info(f"⏭ Регион не определён, пропуск: {text[:80]}")
                return

        source = f"@{getattr(event.chat, 'username', 'unknown')}"
        log.info(f"🔔 [{ts()}] {alert_type.upper()} | {regions} | {source}")

        await broadcast(regions, alert_type, source, text)

    log.info("👁 Мониторинг запущен. Жду сообщения…")
    await client.run_until_disconnected()


# ══════════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
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
    log.info("✅ Бот запущен и ждёт сообщений")

    await run_telethon()

    await ptb_app.updater.stop()
    await ptb_app.stop()
    await ptb_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
