"""
╔══════════════════════════════════════════════════════════════════╗
║   🛡  БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ  v6.0                        ║
╠══════════════════════════════════════════════════════════════════╣
║  Два режима парсинга:                                            ║
║  1. t.me/s/ — для внешних каналов (без авторизации)             ║
║  2. Bot API — для СВОЕГО канала @bointygamesr (бот там админ)   ║
╠══════════════════════════════════════════════════════════════════╣
║  pip install python-telegram-bot==20.7 aiohttp beautifulsoup4   ║
║  BOT_TOKEN=xxx python bot.py                                     ║
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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ══════════════════════════════════════════════════════════════════
#  ⚙️  КОНФИГ — заполни перед запуском
# ══════════════════════════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8303616493:AAFyXfNfF0aIC1fG8aaB1PwsMu3CygvGb7k")

# Твой канал — бот там АДМИН, слушает через Bot API (без парсинга)
OWN_CHANNEL = "bointygamesr"

# Внешние каналы — парсятся через t.me/s/
EXTERNAL_CHANNELS = [
    "radar_rvk",
    "MonitorRostov",
    "TaganCHP",
]

# Регион по умолчанию если в тексте канала регион не найден
CHANNEL_DEFAULT_REGION: Dict[str, str] = {
    "radar_rvk":     "ROS",
    "monitorrostov": "ROS",
    "taganchp":      "ROS",
    "bointygamesr":  "ROS",
}

SUBS_FILE   = "subscriptions.json"
STATS_FILE  = "stats.json"
POLL_INTERVAL = 20    # секунд между опросами внешних каналов

# ← Вставь сюда свой Telegram ID (узнать: @userinfobot)
ADMIN_IDS: Set[int] = {7728468302}
DEDUP_TTL     = 240   # антидубль — секунды
COOLDOWN_TTL  = 90    # кулдаун между однотипными алертами по региону
MIN_TEXT_LEN  = 10    # минимум символов для анализа
MAX_SEEN      = 600   # макс записей в кэше seen_ids

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control":   "no-cache",
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
#  ВСЕ КЛЮЧЕВЫЕ СЛОВА ДЛЯ ОПРЕДЕЛЕНИЯ РЕГИОНА
#  Ростовская область: все города + сёла + районы + падежи
# ══════════════════════════════════════════════════════════════════
REGION_KEYWORDS: Dict[str, List[str]] = {

    # ── РОСТОВСКАЯ ОБЛАСТЬ — максимально полный список ──────────
    "ROS": [
        # регион целиком (все падежи)
        "ростовская область", "ростовской области", "ростовскую область",
        "ростовской обл", "ростовская обл", "ростовском", "ростовская",
        "ростовщина", "дон", "донской", "донщина", "подонье",
        # города
        "ростов-на-дону", "ростове-на-дону", "ростова-на-дону",
        "ростов на дону", "ростов",
        "таганрог", "таганрога", "таганроге",
        "шахты", "шахтах", "шахтинск",
        "новочеркасск", "новочеркасска", "новочеркасске",
        "волгодонск", "волгодонска", "волгодонске",
        "новошахтинск", "новошахтинска",
        "батайск", "батайска", "батайске",
        "азов", "азова", "азове",
        "гуково", "гукова", "гуково",
        "зверево", "зверева",
        "донецк", "донецка", "донецке",          # г. Донецк РО
        "каменск-шахтинский", "каменск-шахтинск", "каменске",
        "белая калитва", "белой калитве", "калитва",
        "миллерово", "миллерова", "миллерове",
        "морозовск", "морозовска",
        "сальск", "сальска", "сальске",
        "красный сулин", "красносулинск",
        "константиновск", "константиновска",
        "семикаракорск", "семикаракорска",
        "аксай", "аксая", "аксае",
        "новый орлёанс",   # Новый (Ростов)
        "цимлянск", "цимлянска",
        "пролетарск", "пролетарска",
        "красноармейск",
        "зерноград", "зернограда",
        "кагальник", "кагальницк",
        "матвеев курган", "матвеево-курганский",
        "чертково", "черткова",
        "тарасовка", "тарасовский",
        "мясниковский", "мясниково",
        "орловский", "орловского",
        "дубовский", "дубовском",
        "ремонтное", "ремонтненский",
        "заветное", "заветинский",
        "зимовники", "зимовниковский",
        "волошино", "кашары", "кашарский",
        "боковская", "боковской",
        "советская", "советский район",
        "шолоховский", "вёшенская", "вешенская",
        "верхнедонской", "верхний дон",
        "белокалитвенский", "красносулинский",
        "октябрьский район",
        "аграрный", "багаевский", "багаевка",
        "весёловский", "весёловск",
        "куйбышевский", "куйбышево",
        "родионово-несветайский",
        "усть-донецкий", "усть-донецк",
        "целинский", "целина",
        "ц. усть-донецкий",
        # сёла и посёлки
        "красный город", "синявское", "синявка",
        "sambek", "самбек",
        "недвиговка", "недвиговке",
        "хапры", "хапры",
        "большой лог",
        "новоалександровка",
        "родники донской",
        "покровское", "покровск",
    ],

    # ── КРАСНОДАРСКИЙ КРАЙ ──────────────────────────────────────
    "KDA": [
        "краснодарский край", "краснодарского края", "краснодарском крае",
        "краснодар", "краснодара", "краснодаре",
        "сочи", "новороссийск", "армавир", "кубань", "кубанский",
        "анапа", "геленджик", "туапсе", "тихорецк", "кропоткин",
        "белореченск", "абинск", "майкопский",
    ],

    # ── БЕЛГОРОДСКАЯ ────────────────────────────────────────────
    "BEL": [
        "белгородская область", "белгородской области",
        "белгород", "белгорода", "белгороде",
        "старый оскол", "старом осколе",
        "губкин", "шебекино", "валуйки", "алексеевка",
        "бирюч", "строитель", "короча",
    ],

    # ── КУРСКАЯ ─────────────────────────────────────────────────
    "KRS": [
        "курская область", "курской области",
        "курск", "курска", "курске",
        "железногорск", "льгов", "рыльск", "обоянь", "щигры",
    ],

    # ── БРЯНСКАЯ ────────────────────────────────────────────────
    "BRY": [
        "брянская область", "брянской области",
        "брянск", "брянска", "брянске",
        "клинцы", "новозыбков", "унеча", "карачев", "дятьково",
    ],

    # ── ВОРОНЕЖСКАЯ ─────────────────────────────────────────────
    "VOR": [
        "воронежская область", "воронежской области",
        "воронеж", "воронежа", "воронеже",
        "борисоглебск", "лиски", "россошь", "острогожск",
    ],

    # ── ВОЛГОГРАДСКАЯ ───────────────────────────────────────────
    "VGG": [
        "волгоградская область", "волгоградской области",
        "волгоград", "волгограда", "волгограде",
        "камышин", "волжский", "михайловка",
    ],

    # ── КРЫМ ────────────────────────────────────────────────────
    "CR": [
        "республика крым", "республики крым",
        "крым", "крыма", "крыму",
        "симферополь", "керчь", "феодосия", "ялта",
        "евпатория", "севастополь", "бахчисарай",
    ],

    # ── СЕВАСТОПОЛЬ ─────────────────────────────────────────────
    "SEV": ["севастополь", "севастополя", "севастополе", "севастопольский"],

    # ── МОСКВА ──────────────────────────────────────────────────
    "MOW": [
        "москва", "москвы", "москве", "московск",
        "столица", "мкад",
    ],

    # ── МОСКОВСКАЯ ОБЛ ──────────────────────────────────────────
    "MOS": [
        "московская область", "московской области",
        "подмосковье", "подмосковья",
    ],

    # ── САНКТ-ПЕТЕРБУРГ ─────────────────────────────────────────
    "SPE": [
        "санкт-петербург", "санкт-петербурга", "санкт-петербурге",
        "петербург", "питер", "спб", "ленинград",
    ],

    # ── ЛЕНИНГРАДСКАЯ ───────────────────────────────────────────
    "LEN": ["ленинградская область", "ленинградской области", "ленобласть"],

    # ── КАЛИНИНГРАД ─────────────────────────────────────────────
    "KLG": [
        "калининград", "калининграда", "калининграде",
        "калининградская область", "калининградской области",
        "кёнигсберг",
    ],

    # ── СТАВРОПОЛЬСКИЙ ──────────────────────────────────────────
    "STA": [
        "ставропольский край", "ставропольского края",
        "ставрополь", "невинномысск", "пятигорск",
        "кисловодск", "ессентуки", "минеральные воды",
    ],

    # ── ДАГЕСТАН ────────────────────────────────────────────────
    "DA": [
        "дагестан", "дагестана", "дагестане",
        "махачкала", "дербент", "хасавюрт", "каспийск", "избербаш",
    ],

    # ── ЧЕЧНЯ ───────────────────────────────────────────────────
    "CE": [
        "чечня", "чечни", "чечне", "чеченской республики",
        "грозный", "грозного", "грозном",
        "гудермес", "аргун",
    ],

    # ── ОСТАЛЬНЫЕ ───────────────────────────────────────────────
    "PSK": ["псков", "псковская область", "псковской области"],
    "SMO": ["смоленск", "смоленская область", "смоленской области"],
    "TVE": ["тверь", "тверская область", "тверской области"],
    "RYA": ["рязань", "рязанская область", "рязанской области"],
    "TUL": ["тула", "тульская область", "тульской области"],
    "ORL": ["орёл", "орел", "орловская область", "орловской области"],
    "LIP": ["липецк", "липецкая область", "липецкой области"],
    "TAM": ["тамбов", "тамбовская область", "тамбовской области"],
    "VLA": ["владимир", "владимирская область", "владимирской области"],
    "IVA": ["иваново", "ивановская область", "ивановской области"],
    "KLU": ["калуга", "калужская область", "калужской области"],
    "KOS": ["кострома", "костромская область", "костромской области"],
    "YAR": ["ярославль", "ярославская область", "ярославской области"],
    "MUR": ["мурманск", "мурманская область", "мурманской области"],
    "ARK": ["архангельск", "архангельская область", "архангельской области"],
    "NGR": ["великий новгород", "новгородская область", "новгородской области"],
    "VLG": ["вологда", "вологодская область", "вологодской области"],
    "KR":  ["петрозаводск", "карелия", "карелии"],
    "KO":  ["сыктывкар", "республика коми", "коми"],
    "NAO": ["нарьян-мар", "ненецкий", "нао"],
    "AST": ["астрахань", "астраханская область", "астраханской области"],
    "AD":  ["майкоп", "адыгея", "адыгеи"],
    "KL":  ["элиста", "калмыкия", "калмыкии"],
    "IN":  ["магас", "назрань", "ингушетия", "ингушетии"],
    "KB":  ["нальчик", "кабардино", "кбр"],
    "KCH": ["черкесск", "карачаево-черкесия", "карачаевск"],
    "NO":  ["владикавказ", "северная осетия", "осетия"],
    "SVE": ["екатеринбург", "свердловск", "свердловская область"],
    "CHE": ["челябинск", "челябинская область", "магнитогорск"],
    "TYU": ["тюмень", "тюменская область"],
    "KGN": ["курган", "курганская область"],
    "KHM": ["ханты-мансийск", "хмао", "югра", "сургут", "нижневартовск"],
    "YAN": ["салехард", "янао", "ноябрьск", "новый уренгой"],
    "PER": ["пермь", "пермский край", "пермского края"],
    "SAM": ["самара", "самарская область", "тольятти", "сызрань"],
    "SAR": ["саратов", "саратовская область", "энгельс"],
    "ORE": ["оренбург", "оренбургская область", "орск"],
    "NIZ": ["нижний новгород", "нижегородская область", "дзержинск"],
    "TA":  ["казань", "татарстан", "набережные челны", "нижнекамск"],
    "BA":  ["уфа", "башкортостан", "магнитогорск"],
    "MO":  ["саранск", "мордовия", "мордовии"],
    "UD":  ["ижевск", "удмуртия", "глазов"],
    "CU":  ["чебоксары", "чувашия", "новочебоксарск"],
    "KIR": ["киров", "кировская область", "вятка"],
    "PNZ": ["пенза", "пензенская область"],
    "ULY": ["ульяновск", "ульяновская область"],
    "NVS": ["новосибирск", "новосибирская область"],
    "OMS": ["омск", "омская область"],
    "TOM": ["томск", "томская область"],
    "KEM": ["кемерово", "кузбасс", "новокузнецк"],
    "KRA": ["красноярск", "красноярский край", "норильск"],
    "IRK": ["иркутск", "иркутская область", "братск"],
    "ALT": ["барнаул", "алтайский край", "бийск", "рубцовск"],
    "BU":  ["улан-удэ", "бурятия"],
    "ZAB": ["чита", "забайкальский край"],
    "KK":  ["абакан", "хакасия"],
    "PRI": ["владивосток", "приморский край", "находка", "уссурийск"],
    "KHA": ["хабаровск", "хабаровский край", "комсомольск-на-амуре"],
    "AMU": ["благовещенск", "амурская область"],
    "MAG": ["магадан", "магаданская область"],
    "SAK": ["южно-сахалинск", "сахалин", "сахалинская область"],
    "SA":  ["якутск", "якутия", "саха"],
    "KAM": ["петропавловск-камчатский", "камчатка", "камчатский край"],
}

# ══════════════════════════════════════════════════════════════════
#  ДЕТЕКТОР УГРОЗ (весовая система)
# ══════════════════════════════════════════════════════════════════
THREAT_PATTERNS: Dict[str, List[Tuple[str, int]]] = {
    "all_clear": [
        ("отбой тревог",        15), ("отбой воздушн",       15),
        ("тревога отменена",    15), ("угроза миновала",      15),
        ("опасность миновала",  15), ("можно выходить",       12),
        ("угроза прошла",       12), ("всё спокойно",         10),
        ("отбой",               10), ("тревога снята",        12),
        ("отменяется тревога",  12), ("воздух чист",          10),
        ("опасности нет",       12), ("угрозы нет",           12),
        ("ситуация спокойна",   10),
    ],
    "drone": [
        ("воздушная тревога",   15), ("воздушная опасность",  15),
        ("угроза бпла",         15), ("атака бпла",           15),
        ("опасность бпла",      15), ("тревога бпла",         15),
        ("бпла",                12), ("беспилотник",          12),
        ("беспилотники",        12), ("дрон",                 10),
        ("дроны",               11), ("uav",                  10),
        ("шахед",               14), ("shahed",               14),
        ("герань-2",            14), ("герань",               12),
        ("гербера",             10), ("мопед",                10),
        ("налёт",                8), ("кружит",                9),
        ("барражир",             9), ("беспилотная опасность",16),
        ("угроза беспилот",     15), ("атака беспилот",       15),
        ("дроны летят",         14), ("летит бпла",           14),
        ("замечен бпла",        13), ("замечены бпла",        13),
        ("замечен беспилот",    13), ("фпв",                  10),
        ("fpv",                 10),
    ],
    "missile": [
        ("ракетная опасность",  15), ("ракетная угроза",      15),
        ("ракетный удар",       15), ("угроза ракетного",     15),
        ("ракета",              10), ("ракеты",               10),
        ("крылатая ракета",     14), ("баллистическ",         13),
        ("кинжал",              12), ("искандер",             12),
        ("калибр",              12), ("х-101",                12),
        ("х-22",                12), ("х-55",                 12),
        ("х-47",                12), ("зур",                  10),
        ("мбр",                 12), ("зенитная",              6),
    ],
    "artillery": [
        ("обстрел",             12), ("под обстрелом",        15),
        ("артиллерия",          12), ("артиллерийский",       14),
        ("миномёт",             12), ("миномётный",           13),
        ("снаряд",              10), ("снаряды",              10),
        ("прилёт",              11), ("прилёты",              12),
        ("взрывы слышны",       13), ("взрыв слышен",         13),
        ("стрельба",             8), ("открыли огонь",        14),
        ("ведут огонь",         14), ("канонада",             12),
        ("кассетный",           12), ("осколки",               8),
        ("мины упали",          13), ("мина упала",           13),
    ],
}


def strip_emoji(text: str) -> str:
    """
    Убирает эмодзи (в т.ч. премиум кастомные) из текста перед анализом.
    Премиум эмодзи Telegram выглядят как Unicode surrogates или
    custom emoji entities — BeautifulSoup их уже убрал, но на всякий случай.
    """
    # Убираем стандартные эмодзи Unicode
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0000200d"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub(" ", text)


def detect_type(text: str) -> Optional[str]:
    clean = strip_emoji(text).lower()

    # Сначала all_clear — если ≥12, сразу возвращаем
    ac_score = sum(
        w for kw, w in THREAT_PATTERNS["all_clear"] if kw in clean
    )
    if ac_score >= 12:
        return "all_clear"

    scores: Dict[str, int] = defaultdict(int)
    for atype, patterns in THREAT_PATTERNS.items():
        if atype == "all_clear":
            continue
        for kw, weight in patterns:
            if kw in clean:
                scores[atype] += weight

    candidates = {k: v for k, v in scores.items() if v >= 10}
    if not candidates:
        return None
    return max(candidates, key=lambda k: candidates[k])


def detect_regions(text: str) -> Set[str]:
    clean = strip_emoji(text).lower()
    found: Set[str] = set()
    for code, kws in REGION_KEYWORDS.items():
        for kw in kws:
            if kw in clean:
                found.add(code)
                break
    return found


# ══════════════════════════════════════════════════════════════════
#  ШАБЛОНЫ ОПОВЕЩЕНИЙ — без упоминания источника
# ══════════════════════════════════════════════════════════════════
LINE = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

ALERT_TEMPLATES: Dict[str, Dict] = {
    "drone": {
        "bar":     "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
        "header":  "🚨 ВОЗДУШНАЯ ТРЕВОГА 🚨",
        "subhead": "🚁 УГРОЗА АТАКИ БПЛА",
        "actions": [
            "🏃 *НЕМЕДЛЕННО* спуститесь в подвал или укрытие",
            "🪟 *ОТОЙДИТЕ* от окон и стеклянных поверхностей",
            "🛋 *ЛЯГТЕ НА ПОЛ*, прикрыв голову руками",
            "🚫 *НЕ ПОЛЬЗУЙТЕСЬ ЛИФТОМ*",
            "🔌 Выключите газ и электричество",
            "📵 *НЕ СНИМАЙТЕ* и не публикуйте видео",
        ],
    },
    "missile": {
        "bar":     "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴",
        "header":  "🚨 РАКЕТНАЯ ОПАСНОСТЬ 🚨",
        "subhead": "🚀 УГРОЗА РАКЕТНОГО УДАРА",
        "actions": [
            "🏃 *ПОКИНЬТЕ УЛИЦУ* — зайдите в здание",
            "🏚 *СПУСТИТЕСЬ В ПОДВАЛ* или бомбоубежище",
            "🪟 *НЕ ПОДХОДИТЕ К ОКНАМ*",
            "🎒 Возьмите документы, воду, тёплые вещи",
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
            "🪟 *ОТОЙДИТЕ ОТ ОКОН*",
            "🌳 На открытой местности — лягте в канаву или овраг",
            "💣 *НЕ ТРОГАЙТЕ* незнакомые предметы",
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


def build_alert(alert_type: str, region_name: str) -> str:
    """Собирает карточку оповещения БЕЗ указания источника."""
    t    = ALERT_TEMPLATES[alert_type]
    ts   = datetime.now().strftime("%d.%m.%Y  %H:%M")
    acts = "\n".join(f"  {a}" for a in t["actions"])
    return (
        f"{t['bar']}\n"
        f"*{t['header']}*\n"
        f"{t['bar']}\n\n"
        f"*{t['subhead']}*\n"
        f"📍 *{region_name}*\n\n"
        f"{LINE}\n"
        f"⚡️ *ДЕЙСТВИЯ:*\n\n"
        f"{acts}\n\n"
        f"{LINE}\n"
        f"📞 *112*  🚒 *101*  🚑 *103*\n"
        f"⏰ {ts}"
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
            log.info(f"✅ Подписки: {len(subscriptions)} пользователей")
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
    try:
        with open(SUBS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {str(k): list(v) for k, v in subscriptions.items()},
                f, ensure_ascii=False,
            )
    except Exception as e:
        log.warning(f"Ошибка сохранения подписок: {e}")


def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {**stats,
                 "by_type":   dict(stats["by_type"]),
                 "by_region": dict(stats["by_region"])},
                f, ensure_ascii=False,
            )
    except Exception as e:
        log.warning(f"Ошибка сохранения статистики: {e}")


def get_subs(uid: int) -> Set[str]:
    return subscriptions.setdefault(uid, set())


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


def trim_seen(ch: str):
    ids = _seen_ids[ch]
    if len(ids) > MAX_SEEN:
        _seen_ids[ch] = set(list(ids)[-(MAX_SEEN // 2):])


# ══════════════════════════════════════════════════════════════════
#  РАССЫЛКА
# ══════════════════════════════════════════════════════════════════
async def broadcast(regions: Set[str], atype: str):
    if ptb_app is None:
        return
    if is_dup(regions, atype):
        log.info(f"⏭  Дубль: {atype} / {regions}")
        return

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
        msg   = build_alert(atype, rname)
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
                log.warning(f"uid={uid}: {e}")

    if sent:
        stats["total_alerts"]   += 1
        stats["by_type"][atype] += 1
        for rc in regions:
            stats["by_region"][rc] += 1
        stats["total_sent"] += sent
        save_stats()
        log.info(f"📨 Отправлено {sent} польз. | {atype} | {regions}")


async def process_text(channel: str, text: str):
    """Анализирует текст и запускает рассылку."""
    if len(text) < MIN_TEXT_LEN:
        return
    atype = detect_type(text)
    if not atype:
        return
    regions = detect_regions(text)
    if not regions:
        fb = CHANNEL_DEFAULT_REGION.get(channel.lower())
        if fb:
            regions = {fb}
        else:
            return
    log.info(f"🔔 [{channel}] {atype.upper()} | {regions}")
    await broadcast(regions, atype)


# ══════════════════════════════════════════════════════════════════
#  ПАРСИНГ ВНЕШНИХ КАНАЛОВ через t.me/s/
# ══════════════════════════════════════════════════════════════════
async def fetch_channel(session: aiohttp.ClientSession, ch: str) -> List[Dict]:
    url = f"https://t.me/s/{ch}"
    try:
        async with session.get(
            url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)
        ) as r:
            if r.status != 200:
                log.warning(f"[@{ch}] HTTP {r.status}")
                return []
            html = await r.text(encoding="utf-8", errors="replace")
    except asyncio.TimeoutError:
        log.warning(f"[@{ch}] Таймаут")
        return []
    except Exception as e:
        log.warning(f"[@{ch}] Ошибка: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    msgs = []
    for el in soup.select(".tgme_widget_message"):
        mid  = el.get("data-post", "")
        tel  = el.select_one(".tgme_widget_message_text")
        if not tel or not mid:
            continue
        text = tel.get_text("\n", strip=True)
        if len(text) >= MIN_TEXT_LEN:
            msgs.append({"id": mid, "text": text})
    return msgs


async def poll_external():
    """Фоновый поллинг внешних каналов."""
    log.info(f"🔍 Поллинг внешних каналов: {EXTERNAL_CHANNELS}")
    conn = aiohttp.TCPConnector(ssl=False, limit=5)
    async with aiohttp.ClientSession(connector=conn) as session:
        # Инициализация — заполняем seen_ids без рассылки
        for ch in EXTERNAL_CHANNELS:
            msgs = await fetch_channel(session, ch)
            for m in msgs:
                _seen_ids[ch].add(m["id"])
            log.info(f"  ✓ @{ch}: {len(msgs)} в кэше")
            await asyncio.sleep(1)
        log.info("✅ Инициализация внешних каналов завершена")

        while True:
            await asyncio.sleep(POLL_INTERVAL)
            for ch in EXTERNAL_CHANNELS:
                try:
                    msgs     = await fetch_channel(session, ch)
                    new_msgs = [m for m in msgs if m["id"] not in _seen_ids[ch]]
                    for m in new_msgs:
                        _seen_ids[ch].add(m["id"])
                        log.info(f"📩 @{ch}: {m['text'][:80]!r}")
                        await process_text(ch, m["text"])
                    trim_seen(ch)
                except Exception as e:
                    log.warning(f"[@{ch}] Цикл: {e}")
                await asyncio.sleep(2)


# ══════════════════════════════════════════════════════════════════
#  ОБРАБОТЧИК СВОЕГО КАНАЛА @bointygamesr через Bot API
#  Бот должен быть АДМИНИСТРАТОРОМ канала
# ══════════════════════════════════════════════════════════════════
async def handle_channel_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Получает посты из твоего канала напрямую через Bot API.
    Работает мгновенно — без задержки поллинга.
    Премиум эмодзи Telegram в entities — просто игнорируем их текстовое представление.
    """
    msg: Message = update.channel_post
    if not msg:
        return

    # Определяем username канала
    chat_username = (msg.chat.username or "").lower()
    if chat_username != OWN_CHANNEL.lower():
        return

    # Берём текст — caption для медиа, text для обычных
    text = msg.text or msg.caption or ""
    if not text:
        return

    log.info(f"📡 Свой канал @{OWN_CHANNEL}: {text[:80]!r}")
    await process_text(OWN_CHANNEL, text)


# ══════════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺  Выбрать регионы",    callback_data="select_district")],
        [InlineKeyboardButton("📋  Мои подписки",       callback_data="my_subs")],
        [InlineKeyboardButton("📊  Статистика",         callback_data="stats")],
        [InlineKeyboardButton("📡  Каналы мониторинга", callback_data="sources")],
        [InlineKeyboardButton("🧹  Сбросить подписки",  callback_data="clear_confirm")],
        [InlineKeyboardButton("ℹ️  Помощь",             callback_data="help")],
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
        if subs else "📌 Регионы не выбраны"
    )
    return (
        "🛡 *БОТ ГРАЖДАНСКОГО ОПОВЕЩЕНИЯ* 🛡\n"
        f"{LINE}\n{line}\n\nВыберите действие:"
    )


# ══════════════════════════════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        menu_text(uid), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
    )


async def cmd_regions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Выберите федеральный округ:", reply_markup=kb_districts()
    )


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
    chs = ", ".join(
        [f"@{OWN_CHANNEL} (прямой)"] +
        [f"@{c} (парсинг)" for c in EXTERNAL_CHANNELS]
    )
    await update.message.reply_text(
        f"📊 *Статус бота*\n\n"
        f"👥 Пользователей: *{len(subscriptions)}*\n"
        f"📨 Отправлено: *{stats['total_sent']}*\n"
        f"🔔 Тревог: *{stats['total_alerts']}*\n\n"
        f"📡 {chs}\n"
        f"⏱ Интервал поллинга: *{POLL_INTERVAL}с*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════════════════════════
#  АДМИН-КОМАНДЫ
# ══════════════════════════════════════════════════════════════════
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


# Состояние ожидания ручного сообщения: uid -> {"type": atype, "region": code}
admin_pending: Dict[int, Dict] = {}


def kb_admin_type() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚁 БПЛА",     callback_data="adm_type:drone")],
        [InlineKeyboardButton("🚀 Ракета",   callback_data="adm_type:missile")],
        [InlineKeyboardButton("💥 Обстрел",  callback_data="adm_type:artillery")],
        [InlineKeyboardButton("✅ Отбой",    callback_data="adm_type:all_clear")],
        [InlineKeyboardButton("❌ Отмена",   callback_data="adm_cancel")],
    ])


def kb_admin_region() -> InlineKeyboardMarkup:
    """Быстрый выбор популярных регионов + ввод вручную."""
    popular = [
        ("ROS", "Ростовская обл."), ("KDA", "Краснодарский край"),
        ("BEL", "Белгородская обл."), ("KRS", "Курская обл."),
        ("BRY", "Брянская обл."),    ("VOR", "Воронежская обл."),
        ("MOW", "г. Москва"),        ("SPE", "г. Санкт-Петербург"),
        ("CR",  "Республика Крым"),  ("SEV", "г. Севастополь"),
        ("VGG", "Волгоградская обл."),("STA","Ставропольский край"),
    ]
    rows = []
    for i in range(0, len(popular), 2):
        row = [
            InlineKeyboardButton(name, callback_data=f"adm_region:{code}")
            for code, name in popular[i:i+2]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("🗺 Все регионы...", callback_data="adm_region_all")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="adm_cancel")])
    return InlineKeyboardMarkup(rows)


def kb_admin_districts() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(d, callback_data=f"adm_district:{d}")] for d in REGIONS]
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="adm_back_to_region")])
    return InlineKeyboardMarkup(rows)


def kb_admin_regions_in(district: str) -> InlineKeyboardMarkup:
    items = list(REGIONS[district].items())
    rows  = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(name, callback_data=f"adm_region:{code}")
            for code, name in items[i:i+2]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="adm_back_to_region")])
    return InlineKeyboardMarkup(rows)


async def cmd_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /send — открывает меню ручной рассылки (только для админа).
    Шаги: тип угрозы → регион → подтверждение → рассылка всем подписчикам.
    """
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔️ У вас нет доступа к этой команде.")
        return
    admin_pending.pop(uid, None)
    await update.message.reply_text(
        "📢 *Ручная рассылка*\n\nВыберите тип оповещения:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_admin_type(),
    )


async def cmd_broadcast_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /sendall <текст> — отправляет произвольный текст всем пользователям бота.
    Только для админа.
    """
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔️ У вас нет доступа к этой команде.")
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text(
            "Использование: `/sendall <текст сообщения>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = (
        f"📢 *СООБЩЕНИЕ ОТ АДМИНИСТРАТОРА*\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"{text}\n\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"⏰ {datetime.now().strftime('%d.%m.%Y  %H:%M')}"
    )
    sent = 0
    for sub_uid in list(subscriptions.keys()):
        try:
            await ptb_app.bot.send_message(
                chat_id=sub_uid, text=msg, parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            log.warning(f"sendall uid={sub_uid}: {e}")

    await update.message.reply_text(
        f"✅ Отправлено *{sent}* пользователям.", parse_mode=ParseMode.MARKDOWN
    )
    log.info(f"📢 /sendall от uid={uid}: отправлено {sent} польз.")


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Панель администратора /admin."""
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return
    total_subs = sum(len(v) for v in subscriptions.values())
    await update.message.reply_text(
        f"🔧 *Панель администратора*\n\n"
        f"👥 Пользователей: *{len(subscriptions)}*\n"
        f"📌 Подписок: *{total_subs}*\n"
        f"📨 Отправлено всего: *{stats['total_sent']}*\n"
        f"🔔 Тревог обработано: *{stats['total_alerts']}*\n\n"
        f"*Команды:*\n"
        f"/send — рассылка оповещения по типу и региону\n"
        f"/sendall <текст> — произвольное сообщение всем\n"
        f"/status — полный статус бота",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Разослать оповещение", callback_data="adm_start")],
        ]),
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
            "Нажмите регион для подписки/отписки (✅ — активно):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_regions(uid, district),
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
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_regions(uid, district),
        )

    elif data == "my_subs":
        subs = get_subs(uid)
        text = (
            "У вас нет активных подписок.\nНажмите «Выбрать регионы»."
            if not subs else
            f"📋 *Ваши регионы ({len(subs)}):*\n\n" +
            "\n".join(f"  • {REGION_BY_CODE.get(c, c)}" for c in sorted(subs))
        )
        await q.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
        )

    elif data == "stats":
        top = sorted(stats["by_region"].items(), key=lambda x: x[1], reverse=True)[:5]
        top_str  = "\n".join(
            f"  {i+1}. {REGION_BY_CODE.get(r, r)} — {n} раз"
            for i, (r, n) in enumerate(top)
        ) or "  —"
        tmap = {
            "drone":     "🚁 БПЛА",
            "missile":   "🚀 Ракеты",
            "artillery": "💥 Обстрелы",
            "all_clear": "✅ Отбой",
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
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back(),
        )

    elif data == "sources":
        own = f"  • @{OWN_CHANNEL} — прямой (Bot API, мгновенно)"
        ext = "\n".join(f"  • @{c} — парсинг (каждые {POLL_INTERVAL}с)" for c in EXTERNAL_CHANNELS)
        await q.edit_message_text(
            f"📡 *Каналы мониторинга:*\n\n{own}\n{ext}\n\n"
            f"Антидубль: *{DEDUP_TTL // 60} мин*  |  "
            f"Кулдаун: *{COOLDOWN_TTL // 60} мин*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back(),
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
            "📞 *112*  🚒 *101*  🚑 *103*  👮 *102*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back(),
        )


# ══════════════════════════════════════════════════════════════════
#  ОБРАБОТЧИК КНОПОК АДМИНА
# ══════════════════════════════════════════════════════════════════
async def on_admin_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    if not is_admin(uid):
        await q.answer("⛔️ Нет доступа", show_alert=True)
        return

    # Открыть выбор типа из /admin кнопки
    if data == "adm_start":
        admin_pending.pop(uid, None)
        await q.edit_message_text(
            "📢 *Ручная рассылка*\n\nВыберите тип оповещения:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin_type(),
        )

    # Выбор типа угрозы
    elif data.startswith("adm_type:"):
        atype = data[9:]
        admin_pending[uid] = {"type": atype}
        tnames = {
            "drone": "🚁 БПЛА", "missile": "🚀 Ракета",
            "artillery": "💥 Обстрел", "all_clear": "✅ Отбой",
        }
        await q.edit_message_text(
            f"*Тип:* {tnames.get(atype, atype)}\n\nВыберите регион:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin_region(),
        )

    # Показать все округа
    elif data == "adm_region_all":
        await q.edit_message_text(
            "Выберите федеральный округ:",
            reply_markup=kb_admin_districts(),
        )

    # Выбор округа → список регионов
    elif data.startswith("adm_district:"):
        district = data[13:]
        ctx.user_data["adm_district"] = district
        await q.edit_message_text(
            f"*{district}*\n\nВыберите регион:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin_regions_in(district),
        )

    # Назад к быстрому выбору региона
    elif data == "adm_back_to_region":
        pending = admin_pending.get(uid, {})
        atype   = pending.get("type", "drone")
        tnames  = {
            "drone": "🚁 БПЛА", "missile": "🚀 Ракета",
            "artillery": "💥 Обстрел", "all_clear": "✅ Отбой",
        }
        await q.edit_message_text(
            f"*Тип:* {tnames.get(atype, atype)}\n\nВыберите регион:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin_region(),
        )

    # Выбор региона → подтверждение
    elif data.startswith("adm_region:"):
        code    = data[11:]
        pending = admin_pending.get(uid, {})
        atype   = pending.get("type", "drone")
        admin_pending[uid] = {"type": atype, "region": code}

        rname  = REGION_BY_CODE.get(code, code)
        tnames = {
            "drone": "🚁 БПЛА", "missile": "🚀 Ракета",
            "artillery": "💥 Обстрел", "all_clear": "✅ Отбой",
        }
        # Считаем сколько подписчиков получат
        count = sum(1 for subs in subscriptions.values() if code in subs)
        await q.edit_message_text(
            f"📋 *Подтверждение рассылки*\n\n"
            f"Тип: *{tnames.get(atype, atype)}*\n"
            f"Регион: *{rname}*\n"
            f"Получат: *{count}* польз.\n\n"
            f"Отправить?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Отправить", callback_data="adm_confirm")],
                [InlineKeyboardButton("✏️ Изменить тип",    callback_data="adm_start")],
                [InlineKeyboardButton("❌ Отмена",          callback_data="adm_cancel")],
            ]),
        )

    # Подтверждение → рассылка
    elif data == "adm_confirm":
        pending = admin_pending.pop(uid, {})
        atype   = pending.get("type")
        code    = pending.get("region")

        if not atype or not code:
            await q.edit_message_text("❌ Данные утеряны. Начните заново через /send.")
            return

        rname = REGION_BY_CODE.get(code, code)
        msg   = build_alert(atype, rname)

        sent = 0
        for sub_uid, subs in list(subscriptions.items()):
            if code not in subs:
                continue
            try:
                await ptb_app.bot.send_message(
                    chat_id=sub_uid, text=msg, parse_mode=ParseMode.MARKDOWN
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                log.warning(f"adm_confirm uid={sub_uid}: {e}")

        # Обновляем статистику
        stats["total_alerts"]    += 1
        stats["by_type"][atype]  += 1
        stats["by_region"][code] += 1
        stats["total_sent"]      += sent
        save_stats()

        tnames = {
            "drone": "🚁 БПЛА", "missile": "🚀 Ракета",
            "artillery": "💥 Обстрел", "all_clear": "✅ Отбой",
        }
        log.info(f"📢 Ручная рассылка: {atype} / {code} → {sent} польз.")
        await q.edit_message_text(
            f"✅ *Рассылка выполнена*\n\n"
            f"Тип: *{tnames.get(atype, atype)}*\n"
            f"Регион: *{rname}*\n"
            f"Отправлено: *{sent}* польз.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Ещё рассылка", callback_data="adm_start")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu_admin")],
            ]),
        )

    elif data == "adm_cancel":
        admin_pending.pop(uid, None)
        await q.edit_message_text(
            "❌ Рассылка отменена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔧 Панель админа", callback_data="adm_start")],
            ]),
        )

    elif data == "main_menu_admin":
        await q.edit_message_text(
            f"🔧 *Панель администратора*\n\n"
            f"👥 Пользователей: *{len(subscriptions)}*\n"
            f"📨 Отправлено: *{stats['total_sent']}*\n"
            f"🔔 Тревог: *{stats['total_alerts']}*\n\n"
            "/send — рассылка по типу и региону\n"
            "/sendall <текст> — всем произвольный текст",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Разослать оповещение", callback_data="adm_start")],
            ]),
        )


# ══════════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════════
async def main():
    global ptb_app
    load_data()

    ptb_app = Application.builder().token(BOT_TOKEN).build()

    # Команды пользователей
    ptb_app.add_handler(CommandHandler("start",   cmd_start))
    ptb_app.add_handler(CommandHandler("regions", cmd_regions))
    ptb_app.add_handler(CommandHandler("mysubs",  cmd_mysubs))
    ptb_app.add_handler(CommandHandler("status",  cmd_status))
    # Команды администратора
    ptb_app.add_handler(CommandHandler("admin",      cmd_admin))
    ptb_app.add_handler(CommandHandler("send",       cmd_send))
    ptb_app.add_handler(CommandHandler("sendall",    cmd_broadcast_all))
    # Кнопки: сначала админские (по префиксу adm_), потом обычные
    ptb_app.add_handler(CallbackQueryHandler(on_admin_button, pattern=r"^adm_|^main_menu_admin$"))
    ptb_app.add_handler(CallbackQueryHandler(on_button))

    # Прямой приём постов из своего канала (бот = админ канала)
    ptb_app.add_handler(
        MessageHandler(filters.ChatType.CHANNEL, handle_channel_post)
    )

    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.updater.start_polling(
        allowed_updates=["message", "callback_query", "channel_post"],
        drop_pending_updates=True,
    )
    log.info("✅ Бот запущен")
    log.info(f"📡 Свой канал: @{OWN_CHANNEL} (прямой Bot API)")
    log.info(f"🔍 Внешние каналы: {EXTERNAL_CHANNELS}")

    # Поллинг внешних каналов — параллельно
    await poll_external()

    await ptb_app.updater.stop()
    await ptb_app.stop()
    await ptb_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
