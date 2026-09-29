# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

# Загружаем .env из папки скрипта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

#  Chrome 
# CHROME_PATH = "google-chrome" #для локалки
CHROME_PATH = "chromium-browser" #для сервера
CHROME_PORT = 9222
CHROME_USER_DATA_DIR = "/tmp/chrome_debug"
HEADLESS = False

#  CDP 
CDP_URL = f"http://localhost:{CHROME_PORT}"

#  Файлы 
LOG_FILE = os.path.join(BASE_DIR, "parser_log.txt")
STATE_FILE = os.path.join(BASE_DIR, "parser_state.json")
VOSK_MODEL_PATH = os.path.join(BASE_DIR, "vosk_small")
FFMPEG_PATH = "ffmpeg"
TEMP_AUDIO_DIR = "/tmp/captcha_audio"

#  PostgreSQL 
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "zek_parser")
DB_USER = os.getenv("DB_USER", "zek_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

#  VPN 
WG_CONFIGS_DIR = os.path.join(BASE_DIR, "wg_configs")
WG_INTERFACE = "wg0"
VPN_SWITCH_DELAY = 5

#  Парсер 
YEAR = "26"
MONTH = "09"

# Приоритетные (крупные) тюрьмы — идём в первую очередь
FACILITIES_PRIORITY = ["34", "30", "37", "08", "44"]

# Остальные тюрьмы — добавите позже вручную
# (Barstow 4240, Big Bear 4260, Morongo 4320, Colorado River 4300 и т.д.)
FACILITIES_OTHER = []

# Итоговый список: сначала крупные, потом остальные
FACILITIES_ALL = FACILITIES_PRIORITY + FACILITIES_OTHER

SEQ_MIN = 1
SEQ_MAX = 9999

# Стоп: сколько seq подряд без находок для КОНКРЕТНОЙ тюрьмы, прежде чем перейти к следующей
MAX_CONSECUTIVE_MISSES = 5

#  Тайминги 
DELAY_BETWEEN_REQUESTS = (0.5, 1.5)
TYPING_SPEED = (0.03, 0.10)
WAIT_AFTER_SEARCH = 2.0
WAIT_AFTER_CONTINUE = 1.0
RESULT_TIMEOUT = 60
API_WAIT_TIMEOUT = 15

#  Excel больше не используется, оставлено для совместимости 
CSV_FIELDS = [
    "timestamp", "celBooking", "celName", "celAge",
    "celArrestDate", "celArrestTime", "celSex", "celDOB",
    "celHeight", "celWeight", "celEyeColor", "celHairColor",
    "celArrestAgency", "celHousingFacility", "celArrestLocation",
    "celReleaseDate", "celReleasedTo", "celBailable", "celJailType",
]