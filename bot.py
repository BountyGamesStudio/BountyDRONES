"""
╔══════════════════════════════════════════════════════════════════╗
║   🛡  БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ РФ  v5.0  🛡                 ║
║   Парсинг через t.me/s/ — БЕЗ авторизации                      ║
╠══════════════════════════════════════════════════════════════════╣
║  pip install python-telegram-bot==20.7 aiohttp beautifulsoup4   ║
║  Запуск: BOT_TOKEN=xxx python bot.py                            ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import hashlib
import json
import logging
import os
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8303616493:AAFyXfNfF0aIC1fG8aaB1PwsMu3CygvGb7k")

SUBS_FILE  = "subscriptions.json"
STATS_FILE = "stats.json"

# Публичные каналы для парсинга (без @)
SOURCE_CHANNELS = [
    "radar_rvk",
    "MonitorRostov",
    "TaganCHP",
    "bointygamesr",   # ← новый канал
]

# Регион по умолчанию для канала (если авторазбор не нашёл регион)
CHANNEL_DEFAULT_REGION: Dict[str, str] = {
    "radar_rvk":     "ROS",
    "monitorrostov": "ROS",
    "taganchp":      "ROS",
    "bointygamesr":  "ROS",
}

# Минимальная длина текста для анализа
MIN_TEXT_LEN = 15

# Интервал опроса каждого канала (секунды)
POLL_INTERVAL = 25

# Антидубль — одно и то же событие не шлём повторно N секунд
DEDUP_TTL = 240

# Кулдаун между однотипными алертами по региону
COOLDOWN_TTL = 90

# Максимальный размер кэша seen_ids на канал
MAX_SEEN = 500

# Заголовки для HTTP-запросов (имитируем браузер)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

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
#  ДЕТЕКТОР УГРОЗ — веса
#  all_clear проверяется ПЕРВЫМ чтобы не спутать "отбой" с угрозой
# ══════════════════════════════════════════════════════════════════
THREAT_PATTERNS: Dict[str, List[Tuple[str, int]]] = {
    "all_clear": [
        ("отбой тревог",       15), ("отбой воздушн",     15),
        ("тревога отменена",   15), ("угроза миновала",   15),
        ("опасность миновала", 15), ("можно выходить",    12),
        ("угроза прошла",      12), ("всё спокойно",      10),
        ("отбой",              10), ("тревога снята",      12),
        ("отменяется тревога", 12), ("воздух чист",        10),
    ],
    "drone": [
        ("воздушная тревога",   15), ("воздушная опасность", 15),
        ("угроза бпла",         15), ("атака бпла",          15),
        ("бпла",                12), ("беспилотник",         12),
        ("дрон",                10), ("дроны",               10),
        ("uav",                 10), ("шахед",               14),
        ("shahed",              14), ("герань-2",            14),
        ("герань",              12), ("гербера",             10),
        ("мопед",               10), ("налёт",                8),
        ("кружит",               8), ("барражир",             9),
        ("воздушная угроза",    14), ("ракетная опасность",   5),
    ],
    "missile": [
        ("ракетная опасность",  15), ("ракетная угроза",     15),
        ("ракетный удар",       15), ("угроза ракетного",    15),
        ("ракета",              10), ("ракеты",              10),
        ("крылатая ракета",     14), ("баллистическ",        13),
        ("кинжал",              12), ("искандер",            12),
        ("калибр",              12), ("х-101",               12),
        ("х-22",                12), ("х-55",                12),
        ("х-47",                12), ("зур",                 10),
        ("мбр",                 12),
    ],
    "artillery": [
        ("обстрел",             12), ("под обстрелом",       15),
        ("артиллерия",          12), ("артиллерийский",      14),
        ("миномёт",             12), ("миномётный",          13),
        ("снаряд",              10), ("снаряды",             10),
        ("прилёт",              11), ("прилёты",             12),
        ("выстрел",              8), ("канонада",            12),
        ("кассетный",           12), ("осколки",              8),
        ("взрывы слышны",       12), ("взрыв слышен",        12),
        ("стрельба",             8), ("открыли огонь",       14),
    ],
}

# ══════════════════════════════════════════════════════════════════
#  ОПРЕДЕЛЕНИЕ РЕГИОНА ПО ТЕКСТУ
# ══════════════════════════════════════════════════════════════════
REGION_KEYWORDS: Dict[str, List[str]] = {
    "ROS": [
        "ростов-на-дону", "ростовской", "ростовская", "ростов",
        "таганрог", "новочеркасск", "шахты", "волгодонск",
        "азов", "батайск", "новошахтинск", "каменск-шахтинск",
        "донецк ростов", "зверево", "гуково", "белая калитва",
    ],
    "KDA": [
        "краснодарского", "краснодарская", "краснодарский", "краснодар",
        "сочи", "новороссийск", "армавир", "кубань",
        "анапа", "геленджик", "туапсе", "тихорецк",
    ],
    "BEL": [
        "белгородской", "белгородская", "белгородский", "белгород",
        "старый оскол", "губкин", "шебекино", "валуйки",
    ],
    "KRS": ["курской", "курская", "курский", "курск", "железногорск"],
    "BRY": ["брянской", "брянская", "брянский", "брянск", "клинцы", "новозыбков"],
    "VOR": ["воронежской", "воронежская", "воронежский", "воронеж"],
    "LIP": ["липецкой", "липецкая", "липецкий", "липецк"],
    "TUL": ["тульской", "тульская", "тульский", "тула"],
    "ORL": ["орловской", "орловская", "орловский", "орёл", "орел"],
    "SMO": ["смоленской", "смоленская", "смоленский", "смоленск"],
    "TVE": ["тверской", "тверская", "тверской", "тверь"],
    "RYA": ["рязанской", "рязанская", "рязанский", "рязань"],
    "TAM": ["тамбовской", "тамбовская", "тамбовский", "тамбов"],
    "MOW": ["москвы", "московск", "москва", "москве"],
    "MOS": ["подмосковье", "московской области", "московская область"],
    "SPE": ["санкт-петербург", "петербург", "петербурге", "питер", "ленинград"],
    "LEN": ["ленинградской", "ленинградская"],
    "KLG": ["калининграда", "калининградской", "калининград"],
    "PSK": ["псковской", "псковская", "псков"],
    "NGR": ["новгородской", "новгородская", "новгород"],
    "MUR": ["мурманской", "мурманская", "мурманск"],
    "ARK": ["архангельской", "архангельская", "архангельск"],
    "VGG": ["волгоградской", "волгоградская", "волгоград"],
    "AST": ["астраханской", "астраханская", "астрахань"],
    "CR":  ["крыма", "крымской", "крымский", "крым", "симферополь", "керчь", "феодосия", "ялта", "евпатория"],
    "SEV": ["севастополь", "севастополя", "севастополе"],
    "STA": ["ставропольского", "ставропольская", "ставропольский", "ставрополь"],
    "DA":  ["дагестан", "дагестана", "махачкала", "дербент", "хасавюрт"],
    "CE":  ["чечня", "чечни", "чеченской", "грозный", "грозного"],
    "IN":  ["ингушетия", "ингушетии", "магас", "назрань"],
    "KB":  ["кабардино", "нальчик"],
    "NO":  ["северной осетии", "осетия", "владикавказ"],
    "SVE": ["свердловской", "свердловская", "екатеринбург"],
    "CHE": ["челябинской", "челябинская", "челябинск"],
    "PER": ["пермского", "пермский", "пермь"],
    "SAM": ["самарской", "самарская", "самара", "тольятти"],
    "SAR": ["саратовской", "саратовская", "саратов"],
    "ORE": ["оренбургской", "оренбургская", "оренбург"],
    "NIZ": ["нижегородской", "нижегородская", "нижний новгород"],
    "TA":  ["татарстан", "татарстана", "казань"],
    "BA":  ["башкортостан", "башкортостана", "уфа"],
    "NVS": ["новосибирской", "новосибирская", "новосибирск"],
    "OMS": ["омской", "омская", "омск"],
    "TOM": ["томской", "томская", "томск"],
    "KEM": ["кемеровской", "кемеровская", "кемерово", "кузбасс"],
    "KRA": ["красноярского", "красноярская", "красноярский", "красноярск"],
    "IRK": ["иркутской", "иркутская", "иркутск"],
    "PRI": ["приморского", "приморский", "владивосток", "приморье"],
    "KHA": ["хабаровского", "хабаровский", "хабаровск"],
    "SAK": ["сахалинской", "сахалинская", "сахалин", "южно-сахалинск"],
    "SA":  ["якутии", "якутия", "якутск", "саха"],
    "KAM": ["камчатского", "камчатский", "камчатка", "петропавловск-камчатский"],
}

# ══════════════════════════════════════════════════════════════════
#  ШАБЛОНЫ ОПОВЕЩЕНИЙ
# ══════════════════════════════════════════════════════════════════
LINE = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

ALERT_TEMPLATES: Dict[str, Dict] = {
    "drone": {
        "bar":     "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
        "header":  "🚨 ВОЗДУШНАЯ ТРЕВОГА 🚨",
        "subhead": "🚁 УГРОЗА АТАКИ БПЛА",
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
        "bar":     "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
        "header":  "🚨 РАКЕТНАЯ ОПАСНОСТЬ 🚨",
        "subhead": "🚀 УГРОЗА РАКЕТНОГО УДАРА",
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
        "bar":     "🟠🟠🟠🟠🟠🟠🟠🟠🟠🟠",
        "header":  "💥 УГРОЗА ОБСТРЕЛА 💥",
        "subhead": "🔫 АРТИЛЛЕРИЙСКИЙ / МИНОМЁТНЫЙ ОГОНЬ",
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
        "bar":     "🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢",
        "header":  "✅ ОТБОЙ ТРЕВОГИ ✅",
        "subhead": "🟢 УГРОЗА МИНОВАЛА",
        "actions": [
            "✔️ Воздушная тревога отменена",
            "✔️ Можно вернуться к обычной деятельности",
            "⚠️ Сохраняйте бдительность",
            "📡 Следите за следующими оповещениями",
        ],
    },
}


def build_alert(
    alert_type: str,
    region_name: str,
    source: str,
    original_text: str = "",
    alert_id: str = "",
) -> str:
    t   = ALERT_TEMPLATES[alert_type]
    ts  = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
    acts = "\n".join(f"  {a}" for a in t["actions"])

    snippet = ""
    if original_text and alert_type != "all_clear":
        clean = original_text.strip()[:300].replace("*", "").replace("_", "").replace("`", "")
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
        f"{acts}"
        f"{snippet}\n"
        f"{LINE}\n"
        f"📞 *ЭКСТРЕННАЯ СЛУЖБА: 112*\n"
        f"🚒 МЧС: 101  |  🚑 Скорая: 103\n"
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
    "by_type":      defaultdict(int),
    "by_region":    defaultdict(int),
    "total_sent":   0,
}

_dedup:    Dict[str, float]    = {}
_cooldown: Dict[str, float]    = {}
_seen_ids: Dict[str, Set[str]] = defaultdict(set)

ptb_app: Optional[Application] = None


def load_data():
    global subscriptions, stats
    if os.path.exists(SUBS_FILE):
        try:
            raw = json.load(open(SUBS_FILE, encoding="utf-8"))
            subscriptions = {int(k): set(v) for k, v in raw.items()}
            log.info(f"Подписки загружены: {len(subscriptions)} польз.")
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
        json.dump(
            {**stats, "by_type": dict(stats["by_type"]), "by_region": dict(stats["by_region"])},
            f, ensure_ascii=False,
        )


def get_subs(uid: int) -> Set[str]:
    return subscriptions.setdefault(uid, set())


# ══════════════════════════════════════════════════════════════════
#  АНАЛИЗАТОР ТЕКСТА
# ══════════════════════════════════════════════════════════════════
def detect_type(text: str) -> Optional[str]:
    """
    Определяет тип угрозы по весовым коэффициентам.
    all_clear всегда проверяется первым — если набрал ≥12, сразу возвращаем.
    """
    lower = text.lower()
    scores: Dict[str, int] = defaultdict(int)

    for atype, patterns in THREAT_PATTERNS.items():
        for kw, weight in patterns:
            if kw in lower:
                scores[atype] += weight

    # all_clear приоритетен
    if scores.get("all_clear", 0) >= 12:
        return "all_clear"

    # остальные типы
    candidates = {k: v for k, v in scores.items() if k != "all_clear" and v >= 10}
    if not candidates:
        return None
    return max(candidates, key=lambda k: candidates[k])


def detect_regions(text: str) -> Set[str]:
    lower = text.lower()
    found: Set[str] = set()
    for code, kws in REGION_KEYWORDS.items():
        for kw in kws:
            if kw in lower:
                found.add(code)
                break  # первый совпавший — достаточно для этого кода
    return found


def make_id(regions: Set[str], atype: str) -> str:
    return hashlib.md5(f"{sorted(regions)}{atype}".encode()).hexdigest()[:8]


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


def trim_seen(channel: str):
    """Ограничиваем размер кэша seen_ids."""
    ids = _seen_ids[channel]
    if len(ids) > MAX_SEEN:
        # оставляем последние MAX_SEEN/2
        _seen_ids[channel] = set(list(ids)[-(MAX_SEEN // 2):])


# ══════════════════════════════════════════════════════════════════
#  ПАРСЕР t.me/s/
# ══════════════════════════════════════════════════════════════════
async def fetch_channel(
    session: aiohttp.ClientSession, channel: str
) -> List[Dict]:
    url = f"https://t.me/s/{channel}"
    try:
        async with session.get(
            url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)
        ) as r:
            if r.status != 200:
                log.warning(f"[@{channel}] HTTP {r.status}")
                return []
            html = await r.text(encoding="utf-8", errors="replace")
    except asyncio.TimeoutError:
        log.warning(f"[@{channel}] Таймаут запроса")
        return []
    except Exception as e:
        log.warning(f"[@{channel}] Ошибка: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    messages = []
    for msg in soup.select(".tgme_widget_message"):
        msg_id   = msg.get("data-post", "")
        text_el  = msg.select_one(".tgme_widget_message_text")
        if not text_el or not msg_id:
            continue
        text = text_el.get_text("\n", strip=True)
        if len(text) >= MIN_TEXT_LEN:
            messages.append({"id": msg_id, "text": text})
    return messages


async def poll_channels():
    log.info(f"🔍 Поллинг запущен | интервал: {POLL_INTERVAL}с | каналов: {len(SOURCE_CHANNELS)}")

    conn = aiohttp.TCPConnector(ssl=False, limit=10)
    async with aiohttp.ClientSession(connector=conn) as session:

        # Первый прогон — заполняем seen_ids, ничего не шлём
        log.info("⏳ Первичная загрузка — инициализация seen_ids...")
        for ch in SOURCE_CHANNELS:
            msgs = await fetch_channel(session, ch)
            for m in msgs:
                _seen_ids[ch].add(m["id"])
            log.info(f"  ✓ @{ch}: {len(msgs)} сообщений в кэше")
            await asyncio.sleep(1.5)
        log.info("✅ Инициализация завершена. Слежу за новыми сообщениями.")

        while True:
            await asyncio.sleep(POLL_INTERVAL)
            for ch in SOURCE_CHANNELS:
                try:
                    msgs     = await fetch_channel(session, ch)
                    new_msgs = [m for m in msgs if m["id"] not in _seen_ids[ch]]

                    for m in new_msgs:
                        _seen_ids[ch].add(m["id"])
                        log.info(f"📩 @{ch} | новое сообщение: {m['text'][:80].strip()!r}")
                        await process_message(ch, m["text"])

                    trim_seen(ch)

                except Exception as e:
                    log.warning(f"[@{ch}] Ошибка цикла: {e}")

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
            log.info(f"⚠️  Регион не определён — пропуск")
            return

    source = f"@{channel}"
    log.info(f"🔔 {atype.upper()} | {regions} | {source}")
    await broadcast(regions, atype, source, text)


# ══════════════════════════════════════════════════════════════════
#  РАССЫЛКА
# ══════════════════════════════════════════════════════════════════
async def broadcast(
    regions: Set[str], atype: str, source: str, original: str = ""
):
    if ptb_app is None:
        return
    if is_dup(regions, atype):
        log.info(f"⏭  Дубль пропущен: {atype} / {regions}")
        return

    aid  = make_id(regions, atype)
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
                    chat_id=uid,
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                log.warning(f"  uid={uid}: {e}")

    if sent:
        stats["total_alerts"]    += 1
        stats["by_type"][atype]  += 1
        for rc in regions:
            stats["by_region"][rc] += 1
        stats["total_sent"] += sent
        save_stats()
        log.info(f"✅ Отправлено {sent} польз. | тип={atype} | #{aid}")


# ══════════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺  Выбрать регионы",      callback_data="select_district")],
        [InlineKeyboardButton("📋  Мои подписки",         callback_data="my_subs")],
        [InlineKeyboardButton("📊  Статистика",           callback_data="stats")],
        [InlineKeyboardButton("📡  Каналы мониторинга",   callback_data="sources")],
        [InlineKeyboardButton("🧹  Сбросить подписки",    callback_data="clear_confirm")],
        [InlineKeyboardButton("ℹ️  Помощь",               callback_data="help")],
    ])


def kb_districts() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(d, callback_data=f"d:{d}")] for d in REGIONS]
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def kb_regions(uid: int, district: str) -> InlineKeyboardMarkup:
    subs  = get_subs(uid)
    items = list(REGIONS[district].items())
    rows  = []
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


def menu_text(uid: int) -> str:
    subs = get_subs(uid)
    line = (
        f"📌 Вы следите за *{len(subs)}* регион(ами)"
        if subs else "📌 Вы пока не выбрали ни одного региона"
    )
    return f"🛡 *БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ* 🛡\n{LINE}\n{line}\n\nВыберите действие:"


# ══════════════════════════════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        menu_text(uid), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
    )


async def cmd_regions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выберите федеральный округ:", reply_markup=kb_districts())


async def cmd_mysubs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    subs = get_subs(uid)
    text = (
        "У вас нет активных подписок.\n\n/regions — выбрать регионы"
        if not subs else
        f"📋 *Ваши регионы ({len(subs)}):*\n\n" +
        "\n".join(f"  • {REGION_BY_CODE.get(c, c)}" for c in sorted(subs))
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chs = ", ".join(f"@{c}" for c in SOURCE_CHANNELS)
    await update.message.reply_text(
        f"📊 *Статус бота*\n\n"
        f"👥 Пользователей: *{len(subscriptions)}*\n"
        f"📨 Отправлено: *{stats['total_sent']}*\n"
        f"🔔 Тревог обработано: *{stats['total_alerts']}*\n\n"
        f"📡 Каналы: {chs}\n"
        f"⏱ Интервал опроса: *{POLL_INTERVAL}с*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════════════════════════
#  ОБРАБОТЧИК КНОПОК
# ══════════════════════════════════════════════════════════════════
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    if data == "main_menu":
        await q.edit_message_text(
            menu_text(uid), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )

    elif data == "select_district":
        await q.edit_message_text(
            "🗺 *Выберите федеральный округ:*",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_districts()
        )

    elif data.startswith("d:"):
        district = data[2:]
        user_district[uid] = district
        subs  = get_subs(uid)
        sel   = sum(1 for c in REGIONS[district] if c in subs)
        total = len(REGIONS[district])
        await q.edit_message_text(
            f"*{district}*\n\nВыбрано: {sel} / {total}\n"
            "Нажмите регион чтобы подписаться/отписаться (✅ — активно):",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_regions(uid, district)
        )

    elif data.startswith("t:"):
        code = data[2:]
        subs = get_subs(uid)
        name = REGION_BY_CODE.get(code, code)
        if code in subs:
            subs.remove(code); action = f"❌ Отписались от *{name}*"
        else:
            subs.add(code);    action = f"✅ Подписались на *{name}*"
        save_subs()
        district = user_district.get(uid, list(REGIONS.keys())[0])
        sel   = sum(1 for c in REGIONS[district] if c in subs)
        total = len(REGIONS[district])
        await q.edit_message_text(
            f"{action}\n\n*{district}*\nВыбрано: {sel} / {total}",
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
        top_str  = "\n".join(
            f"  {i+1}. {REGION_BY_CODE.get(r, r)} — {n} раз"
            for i, (r, n) in enumerate(top)
        ) or "  —"
        tmap = {
            "drone": "🚁 БПЛА", "missile": "🚀 Ракеты",
            "artillery": "💥 Обстрелы", "all_clear": "✅ Отбой",
        }
        btype = "\n".join(
            f"  {tmap.get(k, k)}: {v}" for k, v in stats["by_type"].items()
        ) or "  —"
        await q.edit_message_text(
            f"📊 *Статистика*\n\n"
            f"🔔 Тревог: *{stats['total_alerts']}*\n"
            f"📨 Отправлено: *{stats['total_sent']}*\n"
            f"👥 Пользователей: *{len(subscriptions)}*\n\n"
            f"*По типам:*\n{btype}\n\n"
            f"*Топ-5 регионов:*\n{top_str}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
        )

    elif data == "sources":
        ch_lines = "\n".join(f"  • @{c}" for c in SOURCE_CHANNELS)
        await q.edit_message_text(
            f"📡 *Каналы мониторинга ({len(SOURCE_CHANNELS)}):*\n\n{ch_lines}\n\n"
            f"Опрос каждые *{POLL_INTERVAL} секунд*\n"
            f"Антидубль: *{DEDUP_TTL // 60} мин*  |  "
            f"Кулдаун: *{COOLDOWN_TTL // 60} мин*\n\n"
            "Парсинг идёт через публичный t.me — без авторизации.",
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
            ]),
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
            "*Типы оповещений:*\n"
            "🚁 *БПЛА* — угроза беспилотников\n"
            "🚀 *Ракета* — ракетная опасность\n"
            "💥 *Обстрел* — артиллерийский/миномётный огонь\n"
            f"✅ *Отбой* — угроза миновала\n\n{LINE}\n"
            "📞 *112* — экстренная служба\n"
            "🚒 *101* — МЧС\n"
            "🚑 *103* — скорая\n"
            "👮 *102* — полиция",
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

    await poll_channels()   # блокирующий бесконечный цикл

    await ptb_app.updater.stop()
    await ptb_app.stop()
    await ptb_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
