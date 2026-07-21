"""
╔══════════════════════════════════════════════════════════════════╗
║   🛰  БОТ-АГРЕГАТОР УГРОЗ БПЛА  v1.0                              ║
╠══════════════════════════════════════════════════════════════════╣
║  Логика:                                                          ║
║  1. Мониторит список каналов-источников через t.me/s/ (парсинг,   ║
║     без авторизации, публичные каналы).                          ║
║  2. Ищет в постах признаки угрозы: БПЛА, сирены, воздушная       ║
║     тревога, ракетная / ракетно-бомбовая опасность, обстрел,     ║
║     а также отбои.                                                ║
║  3. Чистит текст от промо-подвалов источника ("Монитор в MAX",   ║
║     "Подписаться", счётчики просмотров и т.д.)                   ║
║  4. Публикует очищенное сообщение в целевой канал, где бот админ.║
║                                                                    ║
║  pip install -r requirements.txt                                  ║
║  BOT_TOKEN=xxx python uav_monitor_bot.py                          ║
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

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# ══════════════════════════════════════════════════════════════════
#  ⚙️  КОНФИГ
# ══════════════════════════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН")

# Каналы-источники (без @, только юзернейм из t.me/xxxxx). Можно
# менять на лету командами /addsource и /delsource (админ-команды).
SOURCE_CHANNELS: List[str] = [
    "MonitorRostov",
    "TaganCHP",
    "radar_rvk",
]

# Канал-приёмник — бот должен быть там админом с правом публикации.
# Можно указать @username или числовой chat_id (для приватных каналов).
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "@bointygamesr")

STATE_FILE = "monitor_state.json"
POLL_INTERVAL = 15          # секунд между опросами каждого источника
DEDUP_TTL = 600             # секунд — не публиковать повторно похожий текст
MIN_TEXT_LEN = 12           # минимум символов, чтобы пост рассматривался
MAX_DEDUP_CACHE = 2000

ADMIN_IDS: Set[int] = {123456789}  # ← впиши свой Telegram ID (@userinfobot)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("UavMonitor")


# ══════════════════════════════════════════════════════════════════
#  РЕГИОНЫ РФ — для тегирования / антидубля / статистики
#  (сама публикация всегда содержит оригинальный текст с городами —
#   этот словарь не подменяет текст, а только помогает боту понять
#   "к какому региону относится пост" для внутренней логики).
# ══════════════════════════════════════════════════════════════════
REGION_KEYWORDS: Dict[str, List[str]] = {
    "Ростовская область": [
        "ростовская область", "ростовской области", "ростовскую область",
        "ростовской обл", "ростовская обл", "ростов-на-дону", "ростове-на-дону",
        "ростова-на-дону", "ростов на дону", "таганрог", "шахты",
        "новочеркасск", "волгодонск", "новошахтинск", "батайск", "азов",
        "гуково", "зверево", "донецк", "каменск-шахтинский", "белая калитва",
        "миллерово", "морозовск", "сальск", "красный сулин", "константиновск",
        "семикаракорск", "аксай", "цимлянск", "пролетарск", "зерноград",
        "матвеев курган", "чертково", "чертковский", "тарасовский",
        "мясниковский", "орловский район", "дубовский", "ремонтное",
        "заветное", "зимовники", "кашары", "боковская", "вёшенская",
        "вешенская", "верхнедонской", "белокалитвенский", "красносулинский",
        "октябрьский район", "багаевка", "весёловск", "куйбышево",
        "усть-донецк", "целина", "покровское", "красносулинский район",
        "новобатайск", "егорлыкская", "кагальник", "кулешовка",
        "лакедемоновка", "красный десант", "новобессергеневка", "беглица",
        "золотая коса", "бессергеновка", "семибалки", "круглое",
        "таганрогский залив", "таганрогского залива",
    ],
    "Краснодарский край": [
        "краснодарский край", "краснодарского края", "краснодарском крае",
        "краснодар", "сочи", "новороссийск", "армавир", "кубань",
        "анапа", "геленджик", "туапсе", "тихорецк", "кропоткин",
        "белореченск", "абинск", "ейск", "щербиновский", "новощербиновская",
        "новоминская", "каневская",
    ],
    "Белгородская область": [
        "белгородская область", "белгородской области", "белгород",
        "старый оскол", "губкин", "шебекино", "валуйки", "алексеевка",
    ],
    "Курская область": [
        "курская область", "курской области", "курск", "железногорск",
        "льгов", "рыльск", "обоянь", "щигры",
    ],
    "Брянская область": [
        "брянская область", "брянской области", "брянск", "клинцы",
        "новозыбков", "унеча", "карачев", "дятьково",
    ],
    "Воронежская область": [
        "воронежская область", "воронежской области", "воронеж",
        "борисоглебск", "лиски", "россошь", "острогожск",
    ],
    "Волгоградская область": [
        "волгоградская область", "волгоградской области", "волгоград",
        "камышин", "волжский", "михайловка",
    ],
    "Республика Крым": [
        "республика крым", "крым", "крыма", "крыму", "симферополь",
        "керчь", "феодосия", "ялта", "евпатория", "бахчисарай",
        "джанкой", "саки", "судак", "алушта",
    ],
    "г. Севастополь": ["севастополь", "севастополя", "севастополе"],
    "г. Москва": ["москва", "москвы", "москве", "мкад"],
    "Московская область": [
        "московская область", "московской области", "подмосковье",
    ],
    "г. Санкт-Петербург": [
        "санкт-петербург", "санкт-петербурга", "петербург", "спб",
    ],
    "Ленинградская область": ["ленинградская область", "ленобласть"],
    "Калининградская область": [
        "калининград", "калининградская область",
    ],
    "Ставропольский край": [
        "ставропольский край", "ставрополь", "невинномысск", "пятигорск",
        "кисловодск", "ессентуки", "минеральные воды",
    ],
    "Республика Дагестан": [
        "дагестан", "махачкала", "дербент", "хасавюрт", "каспийск",
    ],
    "Чеченская Республика": ["чечня", "грозный", "гудермес", "аргун"],
    "Псковская область": ["псков", "псковская область"],
    "Смоленская область": ["смоленск", "смоленская область"],
    "Тверская область": ["тверь", "тверская область"],
    "Рязанская область": ["рязань", "рязанская область"],
    "Тульская область": ["тула", "тульская область"],
    "Орловская область": ["орёл", "орел", "орловская область"],
    "Липецкая область": ["липецк", "липецкая область"],
    "Тамбовская область": ["тамбов", "тамбовская область"],
    "Владимирская область": ["владимир", "владимирская область"],
    "Ивановская область": ["иваново", "ивановская область"],
    "Калужская область": ["калуга", "калужская область"],
    "Костромская область": ["кострома", "костромская область"],
    "Ярославская область": ["ярославль", "ярославская область"],
    "Мурманская область": ["мурманск", "мурманская область"],
    "Архангельская область": ["архангельск", "архангельская область"],
    "Новгородская область": ["великий новгород", "новгородская область"],
    "Вологодская область": ["вологда", "вологодская область"],
    "Астраханская область": ["астрахань", "астраханская область"],
    "Республика Адыгея": ["майкоп", "адыгея"],
    "Республика Калмыкия": ["элиста", "калмыкия"],
    "Республика Ингушетия": ["магас", "назрань", "ингушетия"],
    "Кабардино-Балкарская Респ.": ["нальчик", "кабардино-балкар"],
    "Карачаево-Черкесская Респ.": ["черкесск", "карачаево-черкес"],
    "Республика Сев. Осетия": ["владикавказ", "северная осетия"],
    "Свердловская область": ["екатеринбург", "свердловская область"],
    "Челябинская область": ["челябинск", "челябинская область", "магнитогорск"],
    "Тюменская область": ["тюмень", "тюменская область"],
    "Пермский край": ["пермь", "пермский край"],
    "Самарская область": ["самара", "самарская область", "тольятти"],
    "Саратовская область": ["саратов", "саратовская область", "энгельс"],
    "Оренбургская область": ["оренбург", "оренбургская область", "орск"],
    "Нижегородская область": ["нижний новгород", "нижегородская область"],
    "Республика Татарстан": ["казань", "татарстан", "набережные челны"],
    "Республика Башкортостан": ["уфа", "башкортостан"],
    "Кировская область": ["киров", "кировская область"],
    "Пензенская область": ["пенза", "пензенская область"],
    "Ульяновская область": ["ульяновск", "ульяновская область"],
    "Новосибирская область": ["новосибирск", "новосибирская область"],
    "Омская область": ["омск", "омская область"],
    "Красноярский край": ["красноярск", "красноярский край", "норильск"],
    "Иркутская область": ["иркутск", "иркутская область", "братск"],
    "Алтайский край": ["барнаул", "алтайский край", "бийск"],
    "Приморский край": ["владивосток", "приморский край", "находка"],
    "Хабаровский край": ["хабаровск", "хабаровский край"],
    "Республика Саха (Якутия)": ["якутск", "якутия"],
    "Камчатский край": ["петропавловск-камчатский", "камчатка"],
}

# Общий regex-фолбэк: если пост упоминает "... область/край/республика",
# но региона нет в словаре выше — вытащим название для тегов/статистики.
GENERIC_REGION_RE = re.compile(
    r"([А-ЯЁ][а-яё\-]+(?:\s+[а-яё\-]+)?)\s+"
    r"(область|обл\.|край|республика|автономный округ|АО)\b",
    re.UNICODE,
)


# ══════════════════════════════════════════════════════════════════
#  ДЕТЕКТОР ТИПА УГРОЗЫ (весовая система)
# ══════════════════════════════════════════════════════════════════
THREAT_PATTERNS: Dict[str, List[Tuple[str, int]]] = {
    "all_clear": [
        ("отбой тревог", 15), ("отбой воздушн", 15), ("отбой опасности", 15),
        ("отбой беспилотной опасности", 15), ("тревога отменена", 15),
        ("угроза миновала", 15), ("опасность миновала", 15),
        ("угроза прошла", 12), ("отбой", 10), ("тревога снята", 12),
        ("отменяется тревога", 12), ("опасности нет", 12), ("угрозы нет", 12),
    ],
    "drone": [
        ("опасность по бпла", 15), ("угроза бпла", 15), ("атака бпла", 15),
        ("бпла", 10), ("беспилот", 10), ("бпла со стороны", 15),
        ("квадрокоптер", 8), ("дрон", 6), ("пролёты бпла", 12),
        ("пролеты бпла", 12), ("работа пво по бпла", 15),
        ("работают силы пво", 15), ("работает пво", 14), ("силы пво", 10),
    ],
    "missile": [
        ("ракетная опасность", 15), ("ракетный удар", 15),
        ("угроза ракетного удара", 15), ("баллистическая ракета", 15),
        ("крылатая ракета", 15), ("ракетно-бомбовая опасность", 15),
        ("ракетнобомбовая опасность", 15), ("ракета", 8),
    ],
    "artillery": [
        ("обстрел", 14), ("артобстрел", 15), ("миномётный обстрел", 15),
        ("минометный обстрел", 15), ("артиллерийский огонь", 14),
    ],
    "air_alarm": [
        ("воздушная тревога", 15), ("воздушная опасность", 14),
        ("сирены", 12), ("сирена", 10), ("в укрытия", 10),
        ("объявлена воздушная тревога", 15),
    ],
}

TYPE_ICON: Dict[str, Tuple[str, str]] = {
    # (кружок, эмодзи-тип)
    "drone": ("🔴", "🚁"),
    "missile": ("🔴", "🚀"),
    "artillery": ("🟠", "💥"),
    "air_alarm": ("🔴", "🚨"),
    "all_clear": ("🟢", "✅"),
}

TYPE_LABEL: Dict[str, str] = {
    "drone": "Опасность БПЛА",
    "missile": "Ракетная опасность",
    "artillery": "Угроза обстрела",
    "air_alarm": "Воздушная тревога",
    "all_clear": "Отбой опасности",
}


def strip_emoji(text: str) -> str:
    pattern = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U00002700-\U000027BF"
        "\U00002600-\U000026FF"
        "\U0001F1E6-\U0001F1FF"
        "\U00002B00-\U00002BFF"
        "\U0000FE0F"
        "]+",
        flags=re.UNICODE,
    )
    return pattern.sub(" ", text)


def detect_type(text: str) -> Optional[str]:
    clean = strip_emoji(text).lower()

    ac_score = sum(w for kw, w in THREAT_PATTERNS["all_clear"] if kw in clean)
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
    for region, kws in REGION_KEYWORDS.items():
        for kw in kws:
            if kw in clean:
                found.add(region)
                break
    if not found:
        m = GENERIC_REGION_RE.search(text)
        if m:
            found.add(f"{m.group(1)} {m.group(2)}")
    return found


# ══════════════════════════════════════════════════════════════════
#  ЧИСТКА ТЕКСТА ОТ ПРОМО-ПОДВАЛОВ ИСТОЧНИКА
# ══════════════════════════════════════════════════════════════════
NOISE_LINE_PATTERNS: List[re.Pattern] = [
    re.compile(r"монитор\s+ростовской\s+области.*оповещен", re.I),
    re.compile(r"монитор\s+в\s+max", re.I),
    re.compile(r"подписат[ьи]ся\s+на", re.I),
    re.compile(r"прислать\s+новость", re.I),
    re.compile(r"об\s+этом\s+сообщают\s+мониторинговые\s+каналы", re.I),
    re.compile(r"будьте\s+внимательны\s+и\s+осторожны", re.I),
    re.compile(r"^t\.me/\S+$", re.I),
    re.compile(r"^@\w+$"),
    re.compile(r"переслано\s+от", re.I),
    re.compile(r"перейти\s+в\s+канал", re.I),
    re.compile(r"^\s*telegram\s*$", re.I),
]

# Символы-декорации в начале строки, которыми источники любят
# оформлять "СРОЧНО" / кружки — срезаем, чтобы навесить свой заголовок.
LEADING_DECOR_RE = re.compile(
    r"^[\s🔴🟠🟢⚪️⚫️🔵❗️❕‼️!🚨🚁🚀💥✅•●○◎▪️▫️]+", re.UNICODE
)


def clean_text(raw: str) -> str:
    lines = [ln.strip() for ln in raw.splitlines()]
    out = []
    for ln in lines:
        if not ln:
            continue
        if any(p.search(ln) for p in NOISE_LINE_PATTERNS):
            continue
        out.append(ln)
    text = "\n".join(out).strip()
    text = LEADING_DECOR_RE.sub("", text).strip()
    return text


# ══════════════════════════════════════════════════════════════════
#  СБОРКА ИТОГОВОГО ПОСТА
# ══════════════════════════════════════════════════════════════════
def build_post(threat_type: str, body: str) -> str:
    circle, icon = TYPE_ICON[threat_type]
    ts = datetime.now().strftime("%d.%m.%Y  %H:%M")
    return f"{circle} ❗️ {icon} {body}\n\n🕒 {ts}"


# ══════════════════════════════════════════════════════════════════
#  ХРАНИЛИЩЕ СОСТОЯНИЯ (last_seen id по каналу, антидубль)
# ══════════════════════════════════════════════════════════════════
last_seen: Dict[str, int] = {}
_dedup: Dict[str, float] = {}
stats: Dict = {"published": 0, "by_type": defaultdict(int), "by_region": defaultdict(int)}

ptb_app: Optional[Application] = None


def load_state():
    global last_seen, SOURCE_CHANNELS, TARGET_CHANNEL
    if os.path.exists(STATE_FILE):
        try:
            raw = json.load(open(STATE_FILE, encoding="utf-8"))
            last_seen.update(raw.get("last_seen", {}))
            if raw.get("sources"):
                SOURCE_CHANNELS[:] = raw["sources"]
            if raw.get("target"):
                globals()["TARGET_CHANNEL"] = raw["target"]
            log.info(f"✅ Состояние загружено: {len(last_seen)} источников")
        except Exception as e:
            log.warning(f"Ошибка загрузки состояния: {e}")


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "last_seen": last_seen,
                    "sources": SOURCE_CHANNELS,
                    "target": TARGET_CHANNEL,
                },
                f, ensure_ascii=False,
            )
    except Exception as e:
        log.warning(f"Ошибка сохранения состояния: {e}")


def is_dup(text: str) -> bool:
    norm = re.sub(r"\s+", " ", strip_emoji(text).lower()).strip()
    key = hashlib.md5(norm.encode()).hexdigest()
    now = time.time()
    if now - _dedup.get(key, 0) < DEDUP_TTL:
        return True
    _dedup[key] = now
    if len(_dedup) > MAX_DEDUP_CACHE:
        for k in list(_dedup)[: len(_dedup) // 2]:
            _dedup.pop(k, None)
    return False


# ══════════════════════════════════════════════════════════════════
#  ПАРСИНГ ИСТОЧНИКОВ ЧЕРЕЗ t.me/s/
# ══════════════════════════════════════════════════════════════════
async def fetch_channel_posts(
    session: aiohttp.ClientSession, channel: str
) -> List[Tuple[int, str]]:
    """Возвращает список (id_поста, текст) в порядке возрастания id."""
    url = f"https://t.me/s/{channel}"
    try:
        async with session.get(url, headers=HEADERS, timeout=15) as resp:
            if resp.status != 200:
                log.warning(f"[{channel}] HTTP {resp.status}")
                return []
            html = await resp.text()
    except Exception as e:
        log.warning(f"[{channel}] ошибка запроса: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    posts: List[Tuple[int, str]] = []

    for block in soup.select("div.tgme_widget_message"):
        data_post = block.get("data-post", "")
        if "/" not in data_post:
            continue
        try:
            msg_id = int(data_post.split("/")[-1])
        except ValueError:
            continue

        text_div = block.select_one("div.tgme_widget_message_text")
        if not text_div:
            continue
        text = text_div.get_text(separator="\n").strip()
        if len(text) < MIN_TEXT_LEN:
            continue
        posts.append((msg_id, text))

    posts.sort(key=lambda p: p[0])
    return posts


# ══════════════════════════════════════════════════════════════════
#  ОБРАБОТКА ОДНОГО ПОСТА
# ══════════════════════════════════════════════════════════════════
async def process_post(channel: str, raw_text: str):
    threat_type = detect_type(raw_text)
    if not threat_type:
        return  # не про угрозу/отбой — пропускаем

    body = clean_text(raw_text)
    if len(body) < MIN_TEXT_LEN:
        return

    if is_dup(body):
        log.info(f"[{channel}] дубликат — пропуск")
        return

    regions = detect_regions(raw_text)
    post_text = build_post(threat_type, body)

    if ptb_app is None:
        return

    try:
        await ptb_app.bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=post_text,
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Не удалось отправить пост в {TARGET_CHANNEL}: {e}")
        return

    stats["published"] += 1
    stats["by_type"][threat_type] += 1
    for r in regions:
        stats["by_region"][r] += 1

    log.info(
        f"📤 [{channel}] {TYPE_LABEL[threat_type]} "
        f"({', '.join(regions) if regions else 'регион не определён'})"
    )


# ══════════════════════════════════════════════════════════════════
#  ЦИКЛ ОПРОСА ИСТОЧНИКОВ
# ══════════════════════════════════════════════════════════════════
async def poll_loop():
    async with aiohttp.ClientSession() as session:
        # При первом запуске просто запоминаем текущие id, чтобы не
        # заспамить канал старыми постами при старте бота.
        for ch in list(SOURCE_CHANNELS):
            if ch not in last_seen:
                posts = await fetch_channel_posts(session, ch)
                last_seen[ch] = posts[-1][0] if posts else 0
                log.info(f"[{ch}] инициализация, last_id={last_seen[ch]}")
        save_state()

        while True:
            for ch in list(SOURCE_CHANNELS):
                try:
                    posts = await fetch_channel_posts(session, ch)
                except Exception as e:
                    log.warning(f"[{ch}] ошибка опроса: {e}")
                    continue

                new_posts = [p for p in posts if p[0] > last_seen.get(ch, 0)]
                for msg_id, text in new_posts:
                    await process_post(ch, text)
                    last_seen[ch] = msg_id

                if new_posts:
                    save_state()

                await asyncio.sleep(1)  # небольшая пауза между каналами

            await asyncio.sleep(POLL_INTERVAL)


# ══════════════════════════════════════════════════════════════════
#  АДМИН-КОМАНДЫ
# ══════════════════════════════════════════════════════════════════
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    lines = [
        "🛰 *Статус бота*",
        f"Источники: {', '.join(SOURCE_CHANNELS)}",
        f"Целевой канал: {TARGET_CHANNEL}",
        f"Опубликовано всего: {stats['published']}",
    ]
    if stats["by_type"]:
        lines.append("\nПо типам:")
        for t, c in stats["by_type"].items():
            lines.append(f"  {TYPE_LABEL.get(t, t)}: {c}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_addsource(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /addsource username")
        return
    ch = ctx.args[0].lstrip("@")
    if ch not in SOURCE_CHANNELS:
        SOURCE_CHANNELS.append(ch)
        save_state()
        await update.message.reply_text(f"✅ Добавлен источник: {ch}")
    else:
        await update.message.reply_text("Уже есть в списке.")


async def cmd_delsource(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /delsource username")
        return
    ch = ctx.args[0].lstrip("@")
    if ch in SOURCE_CHANNELS:
        SOURCE_CHANNELS.remove(ch)
        last_seen.pop(ch, None)
        save_state()
        await update.message.reply_text(f"🗑 Удалён источник: {ch}")
    else:
        await update.message.reply_text("Такого источника нет в списке.")


async def cmd_settarget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global TARGET_CHANNEL
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /settarget @channel")
        return
    TARGET_CHANNEL = ctx.args[0]
    save_state()
    await update.message.reply_text(f"✅ Целевой канал: {TARGET_CHANNEL}")


async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Прогоняет произвольный текст через детектор/чистку без отправки в канал."""
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.partition(" ")[2]
    if not text:
        await update.message.reply_text("Использование: /test <текст поста>")
        return
    ttype = detect_type(text)
    regions = detect_regions(text)
    body = clean_text(text)
    preview = build_post(ttype, body) if ttype else "— угроза не распознана —"
    await update.message.reply_text(
        f"Тип: {ttype}\nРегионы: {regions}\n\nПревью:\n{preview}"
    )


# ══════════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════════
async def main():
    global ptb_app
    load_state()

    ptb_app = Application.builder().token(BOT_TOKEN).build()
    ptb_app.add_handler(CommandHandler("status", cmd_status))
    ptb_app.add_handler(CommandHandler("addsource", cmd_addsource))
    ptb_app.add_handler(CommandHandler("delsource", cmd_delsource))
    ptb_app.add_handler(CommandHandler("settarget", cmd_settarget))
    ptb_app.add_handler(CommandHandler("test", cmd_test))

    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.updater.start_polling(
        allowed_updates=["message"], drop_pending_updates=True
    )
    log.info("✅ Бот запущен")
    log.info(f"🔍 Источники: {SOURCE_CHANNELS}")
    log.info(f"📡 Целевой канал: {TARGET_CHANNEL}")

    try:
        await poll_loop()
    finally:
        await ptb_app.updater.stop()
        await ptb_app.stop()
        await ptb_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
