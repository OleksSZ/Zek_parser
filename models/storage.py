# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import other.Zek_parser.models.config as config

# ============================================================
# STATE (per-facility)
# ============================================================

STATE = {
    "year": config.YEAR,
    "month": config.MONTH,
    "facilities": {},  # {"34": {"last_seq": 1574}, "30": {"last_seq": 0}, ...}
    "last_updated": datetime.now().isoformat(),
}


def _init_state_facilities():
    """Убедиться, что для всех известных тюрем есть запись."""
    for fac in config.FACILITIES_ALL:
        STATE["facilities"].setdefault(fac, {"last_seq": config.SEQ_MIN - 1})


# ============================================================
# ЛОГИ
# ============================================================

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(config.LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


# ============================================================
# POSTGRESQL
# ============================================================

_db_conn = None


def _get_conn():
    """Singleton-соединение с БД."""
    global _db_conn
    if _db_conn is None or _db_conn.closed:
        _db_conn = psycopg2.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            connect_timeout=10,
        )
        _db_conn.autocommit = True
    return _db_conn


def init_db():
    """Создаёт таблицу inmates, если её нет."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS inmates (
        id              SERIAL PRIMARY KEY,
        booking_no      VARCHAR(20) UNIQUE NOT NULL,
        name            VARCHAR(255),
        age             VARCHAR(10),
        arrest_date     VARCHAR(30),
        arrest_time     VARCHAR(20),
        sex             VARCHAR(20),
        dob             VARCHAR(30),
        height          VARCHAR(20),
        weight          VARCHAR(20),
        eye_color       VARCHAR(30),
        hair_color      VARCHAR(30),
        arrest_agency   VARCHAR(255),
        housing_facility VARCHAR(255),
        arrest_location VARCHAR(255),
        release_date    VARCHAR(30),
        released_to     VARCHAR(50),
        bailable        VARCHAR(50),
        jail_type       VARCHAR(20),
        raw_json        JSONB,
        created_at      TIMESTAMP DEFAULT NOW(),
        updated_at      TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_inmates_booking ON inmates(booking_no);
    CREATE INDEX IF NOT EXISTS idx_inmates_facility ON inmates(housing_facility);
    CREATE INDEX IF NOT EXISTS idx_inmates_arrest_date ON inmates(arrest_date);
    """
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(create_sql)
        log("[db] ✅ Таблица inmates готова")
        return True
    except Exception as e:
        log(f"[db] ❌ init_db: {e}")
        return False


def save_to_db(record):
    """
    INSERT ... ON CONFLICT (booking_no) DO UPDATE.
    Возвращает True при успехе.
    """
    insert_sql = """
    INSERT INTO inmates (
        booking_no, name, age, arrest_date, arrest_time, sex, dob,
        height, weight, eye_color, hair_color, arrest_agency,
        housing_facility, arrest_location, release_date, released_to,
        bailable, jail_type, raw_json
    ) VALUES (
        %(celBooking)s, %(celName)s, %(celAge)s, %(celArrestDate)s, %(celArrestTime)s,
        %(celSex)s, %(celDOB)s, %(celHeight)s, %(celWeight)s, %(celEyeColor)s,
        %(celHairColor)s, %(celArrestAgency)s, %(celHousingFacility)s,
        %(celArrestLocation)s, %(celReleaseDate)s, %(celReleasedTo)s,
        %(celBailable)s, %(celJailType)s, %(raw_json)s
    )
    ON CONFLICT (booking_no) DO UPDATE SET
        name = EXCLUDED.name,
        age = EXCLUDED.age,
        arrest_date = EXCLUDED.arrest_date,
        arrest_time = EXCLUDED.arrest_time,
        sex = EXCLUDED.sex,
        dob = EXCLUDED.dob,
        height = EXCLUDED.height,
        weight = EXCLUDED.weight,
        eye_color = EXCLUDED.eye_color,
        hair_color = EXCLUDED.hair_color,
        arrest_agency = EXCLUDED.arrest_agency,
        housing_facility = EXCLUDED.housing_facility,
        arrest_location = EXCLUDED.arrest_location,
        release_date = EXCLUDED.release_date,
        released_to = EXCLUDED.released_to,
        bailable = EXCLUDED.bailable,
        jail_type = EXCLUDED.jail_type,
        raw_json = EXCLUDED.raw_json,
        updated_at = NOW();
    """
    params = {
        "celBooking": record.get("celBooking") or None,
        "celName": record.get("celName"),
        "celAge": record.get("celAge"),
        "celArrestDate": record.get("celArrestDate"),
        "celArrestTime": record.get("celArrestTime"),
        "celSex": record.get("celSex"),
        "celDOB": record.get("celDOB"),
        "celHeight": record.get("celHeight"),
        "celWeight": record.get("celWeight"),
        "celEyeColor": record.get("celEyeColor"),
        "celHairColor": record.get("celHairColor"),
        "celArrestAgency": record.get("celArrestAgency"),
        "celHousingFacility": record.get("celHousingFacility"),
        "celArrestLocation": record.get("celArrestLocation"),
        "celReleaseDate": record.get("celReleaseDate"),
        "celReleasedTo": record.get("celReleasedTo"),
        "celBailable": record.get("celBailable"),
        "celJailType": record.get("celJailType"),
        "raw_json": json.dumps(record, ensure_ascii=False),
    }
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(insert_sql, params)
        return True
    except Exception as e:
        log(f"[db] ❌ save: {e}")
        # на случай обрыва соединения
        global _db_conn
        _db_conn = None
        return False


# ============================================================
# STATE — load/save
# ============================================================

def load_state():
    """Загружает state. Мигрирует старый формат при необходимости."""
    global STATE

    if not os.path.exists(config.STATE_FILE):
        _init_state_facilities()
        save_state()
        return STATE

    with open(config.STATE_FILE, 'r', encoding='utf-8') as f:
        loaded = json.load(f)

    # Смена периода
    if loaded.get("year") != config.YEAR or loaded.get("month") != config.MONTH:
        log(f"[*] Смена периода: {loaded.get('year')}-{loaded.get('month')} → {config.YEAR}-{config.MONTH}. Сброс.")
        STATE["year"] = config.YEAR
        STATE["month"] = config.MONTH
        STATE["facilities"] = {}
        _init_state_facilities()
        save_state()
        return STATE

    STATE["year"] = loaded.get("year", config.YEAR)
    STATE["month"] = loaded.get("month", config.MONTH)

    # Новый формат
    if "facilities" in loaded:
        STATE["facilities"] = loaded["facilities"]
    # Старый формат — миграция
    else:
        log("[*] Миграция state: старый формат → per-facility")
        STATE["facilities"] = {}
        old_last_seq = loaded.get("last_seq", config.SEQ_MIN - 1)
        old_last_hit = loaded.get("last_facility_hit")
        if old_last_hit:
            STATE["facilities"][old_last_hit] = {"last_seq": old_last_seq}
            log(f"[*]   {old_last_hit} → last_seq={old_last_seq}")

    _init_state_facilities()
    save_state()
    return STATE


def save_state():
    STATE["last_updated"] = datetime.now().isoformat()
    with open(config.STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(STATE, f, ensure_ascii=False, indent=2)


def get_facility_seq(facility):
    """Возвращает последний известный seq для тюрьмы."""
    return STATE["facilities"].get(facility, {}).get("last_seq", config.SEQ_MIN - 1)


def set_facility_seq(facility, seq_val):
    """Сохраняет прогресс по тюрьме."""
    STATE["facilities"].setdefault(facility, {})
    STATE["facilities"][facility]["last_seq"] = seq_val
    save_state()


# Алиас для совместимости со старым кодом
def advance_seq(seq_val, facility):
    set_facility_seq(facility, seq_val)