# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPER_ADMIN_ID_RAW = os.getenv("SUPER_ADMIN_ID", "").strip()

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@FM_femboy").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/FM_femboy").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "fem_bot.db").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in .env")

try:
    SUPER_ADMIN_ID = int(SUPER_ADMIN_ID_RAW)
except ValueError as exc:
    raise RuntimeError("SUPER_ADMIN_ID must be an integer") from exc

if SUPER_ADMIN_ID <= 0:
    raise RuntimeError("SUPER_ADMIN_ID must be positive")

