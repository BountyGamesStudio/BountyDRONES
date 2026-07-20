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
    Application, CallbackQueryHandler, CommandHandler, 
    MessageHandler, filters, ContextTypes
)

# ══════════════════════════════════════════════════════════════════
# КОНФИГ
# ══════════════════════════════════════════════════════════════════
BOT_TOKEN = "8303616493:AAFyXfNfF0aIC1fG8aaB1PwsMu3CygvGb7k"  # <--- Вставьте токен сюда
SUBS_FILE = "subscriptions.json"
ADMIN_CHANNEL = "bointygamesr" # Ваш канал
SOURCE_CHANNELS = ["radar_rvk", "MonitorRostov", "TaganCHP"] # Сторонние каналы

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("AlertBot")

# ══════════════════════════════════════════════════════════════════
# БАЗА И СОСТОЯНИЕ
# ══════════════════════════════════════════════════════════════════
subscriptions: Dict[int, Set[str]] = {}
_dedup: Dict[str, float] = {}

def load_subs():
    global subscriptions
    if os.path.exists(SUBS_FILE):
        try:
            with open(SUBS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                subscriptions = {int(k): set(v) for k, v in raw.items()}
        except: subscriptions = {}

def save_subs():
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): list(v) for k, v in subscriptions.items()}, f, ensure_ascii=False)

# ══════════════════════════════════════════════════════════════════
# УМНЫЙ ПАРСИНГ ДЕТАЛЕЙ
# ══════════════════════════════════════════════════════════════════
def extract_details(text: str) -> str:
    """Извлекает ключевую информацию о БПЛА и угрозах."""
    keywords = ["шт", "штук", "лет", "направлен", "км", "мин", "скорост", "через", "откуда", "цель"]
    lines = text.split('\n')
    extracted = []
    for line in lines:
        l = line.lower()
        if any(kw in l for kw in keywords) and len(line) > 5 and "http" not in l and "@" not in l:
            extracted.append(f"  • {line.strip().replace('*', '').replace('_', '')}")
    return "\n".join(extracted[:5]) if extracted else "  • Информация уточняется."

# ══════════════════════════════════════════════════════════════════
# АНАЛИЗАТОР УГРОЗ
# ══════════════════════════════════════════════════════════════════
THREATS = {
    "all_clear": ["отбой", "угроза миновала", "опасность миновала", "воздух чист"],
    "drone": ["бпла", "беспилотник", "дрон", "шахед", "герань", "воздушная тревога"],
    "missile": ["ракет", "авиабомб", "каб", "фаб", "ракетно-бомбовая"],
}

def detect_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in THREATS["all_clear"]): return "all_clear"
    if any(k in t for k in THREATS["drone"]): return "drone"
    if any(k in t for k in THREATS["missile"]): return "missile"
    return ""

# ══════════════════════════════════════════════════════════════════
# БЛОК РАССЫЛКИ
# ══════════════════════════════════════════════════════════════════
async def broadcast(text: str, atype: str):
    # Глобальная рассылка всем пользователям
    msg = f"🔔 *ВНИМАНИЕ: {atype.upper()}*\n\n{text}\n\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n🔎 *ИНФОРМАЦИЯ О ЦЕЛЯХ:*\n{extract_details(text)}"
    for uid in list(subscriptions.keys()):
        try:
            await ptb_app.bot.send_message(chat_id=uid, text=msg, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(0.05)
        except: continue

# ══════════════════════════════════════════════════════════════════
# ОБРАБОТЧИКИ
# ══════════════════════════════════════════════════════════════════
async def handle_admin_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.chat.username == ADMIN_CHANNEL:
        text = update.channel_post.text or update.channel_post.caption or ""
        atype = detect_type(text)
        if atype: await broadcast(text, atype)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    subscriptions.setdefault(uid, set())
    save_subs()
    await update.message.reply_text("Добро пожаловать в систему оповещения!", reply_markup=kb_main())

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺  Выбрать регионы", callback_data="select_district")],
        [InlineKeyboardButton("📋  Мои подписки", callback_data="my_subs")],
        [InlineKeyboardButton("📊  Статистика", callback_data="stats")],
        [InlineKeyboardButton("🧹  Сбросить подписки", callback_data="clear_confirm")],
        [InlineKeyboardButton("ℹ️  Помощь", callback_data="help")],
        [InlineKeyboardButton("💬  Поддержка", url="https://t.me/Durove14")],
    ])

# ... (Логика callback_query осталась прежней) ...

async def main():
    global ptb_app
    load_subs()
    ptb_app = Application.builder().token(BOT_TOKEN).build()
    ptb_app.add_handler(CommandHandler("start", cmd_start))
    ptb_app.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_admin_post))
    # ... (добавьте другие хендлеры и запуск polling) ...
    await ptb_app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
