

import asyncio
from playwright.async_api import async_playwright
import json
import random
from datetime import datetime
import os
import sys
import subprocess
from openpyxl import Workbook, load_workbook

# Vosk
from vosk import Model, KaldiRecognizer, SetLogLevel

# 
# НАСТРОЙКИ
# 

CDP_URL = "http://localhost:9222"
OUTPUT_FILE = "inmates_san_bernardino.xlsx"
LOG_FILE = "parser_log.txt"
STATE_FILE = "parser_state.json"

YEAR = "26"
MONTH = "09"
FACILITIES = ["34", "30", "37", "08", "44"]
SEQ_MIN = 1
SEQ_MAX = 9999
MAX_CONSECUTIVE_MISSES = 5

DELAY_BETWEEN_REQUESTS = (2, 4)
TYPING_SPEED = (0.05, 0.15)
WAIT_AFTER_SEARCH = 3        # после Search by Booking перед проверкой
WAIT_AFTER_CONTINUE = 2      # после клика Continue

# --- Vosk / Captcha ---
VOSK_MODEL_PATH = "vosk_small"  # Папка с моделью в корне проекта
FFMPEG_PATH = "ffmpeg"
TEMP_AUDIO_DIR = "/tmp/captcha_audio"

# Отключаем спам от Vosk
SetLogLevel(-1)

# Загружаем модель один раз
VOSK_MODEL = None
try:
    VOSK_MODEL = Model(VOSK_MODEL_PATH)
    print(f"[VOSK] ✅ Модель загружена: {VOSK_MODEL_PATH}")
except Exception as e:
    print(f"[VOSK] ❌ Не удалось загрузить модель: {e}")
    print(f"[VOSK] Убедитесь, что папка '{VOSK_MODEL_PATH}' лежит в корне проекта")

CSV_FIELDS = [
    "timestamp", "celBooking", "celName", "celAge",
    "celArrestDate", "celArrestTime", "celSex", "celDOB",
    "celHeight", "celWeight", "celEyeColor", "celHairColor",
    "celArrestAgency", "celHousingFacility", "celArrestLocation",
    "celReleaseDate", "celReleasedTo", "celBailable", "celJailType",
]

# 
# STATE
# 

STATE = {
    "year": YEAR, "month": MONTH,
    "last_seq": SEQ_MIN - 1, "last_facility_hit": None,
    "last_updated": datetime.now().isoformat(),
}

CURRENT_SEARCH_BOOKING = None
CURRENT_FACILITY = None

# 
# ЛОГИ
# 

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


# 
# EXCEL
# 

def save_to_excel(record):
    if os.path.exists(OUTPUT_FILE):
        wb = load_workbook(OUTPUT_FILE)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Inmates"
        ws.append(CSV_FIELDS)
    ws.append([record.get(f, "") for f in CSV_FIELDS])
    wb.save(OUTPUT_FILE)


# 
# STATE
# 

def load_state():
    if not os.path.exists(STATE_FILE):
        save_state()
        return
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        loaded = json.load(f)
    if loaded.get("year") != YEAR or loaded.get("month") != MONTH:
        log(f"[*] Смена периода. Сброс.")
        STATE["last_seq"] = SEQ_MIN - 1
        STATE["last_facility_hit"] = None
    else:
        STATE["last_seq"] = loaded.get("last_seq", SEQ_MIN - 1)
        STATE["last_facility_hit"] = loaded.get("last_facility_hit")
    save_state()


def save_state():
    STATE["last_updated"] = datetime.now().isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(STATE, f, ensure_ascii=False, indent=2)


# 
# === РЕШЕНИЕ КАПЧИ ЧЕРЕЗ VOSK ===
# 

async def solve_recaptcha_audio(page):
    """
    Решает аудио-капчу reCAPTCHA v2 через Vosk.
    Возвращает True при успехе.
    """
    log("")
    log("=" * 60)
    log("[CAPTCHA] 🎯 Начинаем решение аудио-капчи через Vosk")
    log("=" * 60)

    if not VOSK_MODEL:
        log("[CAPTCHA] ❌ Модель Vosk не загружена. Пропуск.")
        return False

    os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)
    ts = int(asyncio.get_event_loop().time() * 1000)
    mp3_path = os.path.join(TEMP_AUDIO_DIR, f"captcha_{ts}.mp3")
    wav_path = os.path.join(TEMP_AUDIO_DIR, f"captcha_{ts}.wav")

    try:
        # --- ШАГ 1: Ищем iframe с челленджем ---
        log("[CAPTCHA] Шаг 1: Ищем iframe с челленджем (challenge)...")

        challenge_frame = None
        # Ищем через локатор по всем подходящим iframe
        for attempt in range(10):
            frames = page.frames
            for fr in frames:
                url = fr.url or ""
                if "recaptcha" in url and ("bframe" in url or "challenge" in url):
                    challenge_frame = fr
                    log(f"[CAPTCHA] ✅ Найден iframe: {url[:80]}...")
                    break
            if challenge_frame:
                break
            await asyncio.sleep(0.5)

        if not challenge_frame:
            log("[CAPTCHA] ❌ Не нашли iframe с челленджем")
            return False

        # --- ШАГ 2: Переключаемся на аудио ---
        log("[CAPTCHA] Шаг 2: Ищем кнопку аудио (#recaptcha-audio-button)...")
        audio_btn = challenge_frame.locator("#recaptcha-audio-button")

        try:
            await audio_btn.wait_for(state="visible", timeout=8000)
            log("[CAPTCHA] ✅ Кнопка аудио видна")
        except Exception as e:
            log(f"[CAPTCHA] ❌ Кнопка аудио не появилась: {str(e)[:100]}")
            return False

        await audio_btn.click()
        log("[CAPTCHA] ✅ Кликнули по кнопке аудио. Ждём загрузки mp3...")
        await asyncio.sleep(2.5)

        # --- ШАГ 3: Получаем ссылку на mp3 ---
        log("[CAPTCHA] Шаг 3: Ищем ссылку на mp3 (#audio-source)...")
        audio_source = challenge_frame.locator("#audio-source")

        try:
            await audio_source.wait_for(state="attached", timeout=10000)
        except Exception as e:
            log(f"[CAPTCHA] ❌ Ссылка на mp3 не появилась: {str(e)[:100]}")
            # Возможная причина — Google заблокировал аудио
            return False

        audio_url = await audio_source.get_attribute("src")
        if not audio_url:
            log("[CAPTCHA] ❌ У #audio-source нет src")
            return False
        log(f"[CAPTCHA] ✅ URL mp3: {audio_url[:90]}...")

        # --- ШАГ 4: Скачиваем mp3 через Playwright ---
        log("[CAPTCHA] Шаг 4: Скачиваем mp3...")
        response = await page.request.get(audio_url)
        if response.status != 200:
            log(f"[CAPTCHA] ❌ Скачивание: HTTP {response.status}")
            return False
        body = await response.body()
        with open(mp3_path, "wb") as f:
            f.write(body)
        log(f"[CAPTCHA] ✅ Сохранено: {mp3_path} ({len(body)} байт)")

        # --- ШАГ 5: Конвертируем MP3 → WAV ---
        log("[CAPTCHA] Шаг 5: Конвертация MP3 → WAV (16kHz, mono) через ffmpeg...")
        cmd = [
            FFMPEG_PATH, "-y", "-i", mp3_path,
            "-ar", "16000", "-ac", "1", "-f", "wav", wav_path
        ]
        log(f"[CAPTCHA] Команда: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log(f"[CAPTCHA] ❌ ffmpeg stderr: {result.stderr[:300]}")
            return False
        log(f"[CAPTCHA] ✅ WAV создан: {wav_path}")

        # --- ШАГ 6: Транскрибируем через Vosk ---
        log("[CAPTCHA] Шаг 6: Распознаём речь через Vosk...")
        rec = KaldiRecognizer(VOSK_MODEL, 16000)
        with open(wav_path, "rb") as f:
            while True:
                data = f.read(4000)
                if len(data) == 0:
                    break
                rec.AcceptWaveform(data)

        final = json.loads(rec.FinalResult())
        text = final.get("text", "").strip()
        log(f"[CAPTCHA] 🎤 Vosk распознал: '{text}'")

        if not text:
            log("[CAPTCHA] ❌ Пустой результат распознавания")
            return False

        # --- ШАГ 7: Вводим текст в поле ответа ---
        log("[CAPTCHA] Шаг 7: Вводим текст в #audio-response...")
        response_input = challenge_frame.locator("#audio-response")

        try:
            await response_input.wait_for(state="visible", timeout=5000)
        except Exception as e:
            log(f"[CAPTCHA] ❌ Поле ввода не появилось: {str(e)[:80]}")
            return False

        await response_input.click()
        await asyncio.sleep(0.3)
        # Печатаем по буквам
        for ch in text:
            await response_input.type(ch, delay=random.randint(50, 120))
        log(f"[CAPTCHA] ✅ Текст введён")

        # --- ШАГ 8: Нажимаем Verify ---
        log("[CAPTCHA] Шаг 8: Нажимаем #recaptcha-verify-button...")
        verify_btn = challenge_frame.locator("#recaptcha-verify-button")
        try:
            await verify_btn.wait_for(state="visible", timeout=5000)
        except Exception as e:
            log(f"[CAPTCHA] ❌ Кнопка Verify не видна: {str(e)[:80]}")
            return False

        await verify_btn.click()
        log("[CAPTCHA] ✅ Клик Verify отправлен. Ждём проверки...")
        await asyncio.sleep(3)

        log("[CAPTCHA] 🎉 Процесс решения капчи завершён")
        log("=" * 60)
        return True

    except Exception as e:
        log(f"[CAPTCHA] ❌ Критическая ошибка: {e}")
        import traceback
        log(f"[CAPTCHA] Traceback:\n{traceback.format_exc()}")
        return False

    finally:
        for p in (mp3_path, wav_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def captcha_present(page):
    """Проверяет, есть ли сейчас iframe с челленджем."""
    try:
        for fr in page.frames:
            url = fr.url or ""
            if "recaptcha" in url and ("bframe" in url or "challenge" in url):
                # Проверяем, что внутри есть хоть что-то видимое
                try:
                    cnt = await fr.locator("#recaptcha-audio-button, #audio-source, #audio-response").count()
                    if cnt > 0:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


# 
# КЛИК ПО КНОПКЕ ВСЕМИ СПОСОБАМИ
# 

async def click_any_way(page, by_id=None, by_class=None, by_text=None, label="кнопка"):
    log(f"  [click] ── Ищем '{label}' ──")

    try:
        if page.is_closed():
            log(f"  [click] ❌ Страница закрыта!")
            return False
    except Exception:
        return False

    selectors = []
    if by_id:
        selectors.append(f"#{by_id}")
    if by_class:
        selectors.append(f".{by_class}")
    if by_text:
        selectors.append(f"input[value='{by_text}']")
        selectors.append(f"input[value='{by_text} ']")
        selectors.append(f"button:has-text('{by_text}')")
        selectors.append(f"a:has-text('{by_text}')")

    found_sel = None
    for sel in selectors:
        try:
            cnt = await page.locator(sel).count()
            if cnt > 0:
                found_sel = sel
                log(f"  [click] найден селектор: {sel}")
                break
        except Exception:
            continue

    if not found_sel:
        log(f"  [click] ❌ '{label}' не найден")
        return False

    # 1
    try:
        await page.locator(found_sel).first.click(timeout=2000)
        log(f"  [click] ✅ УСПЕХ (locator.click)")
        return True
    except Exception as e:
        log(f"  [click] ❌ locator.click: {str(e)[:90]}")

    # 2
    try:
        await page.locator(found_sel).first.click(force=True, timeout=2000)
        log(f"  [click] ✅ УСПЕХ (force)")
        return True
    except Exception as e:
        log(f"  [click] ❌ force: {str(e)[:90]}")

    # 3
    try:
        box = await page.locator(found_sel).first.bounding_box()
        if box:
            cx = box['x'] + box['width'] / 2
            cy = box['y'] + box['height'] / 2
            await page.mouse.move(cx, cy)
            await asyncio.sleep(0.1)
            await page.mouse.click(cx, cy)
            log(f"  [click] ✅ УСПЕХ (mouse.click)")
            return True
    except Exception as e:
        log(f"  [click] ❌ mouse.click: {str(e)[:90]}")

    # 4
    try:
        res = await page.evaluate(
            "(sel) => { const el = document.querySelector(sel); if (!el) return 'no'; el.click(); return 'ok'; }",
            found_sel
        )
        if res == 'ok':
            log(f"  [click] ✅ УСПЕХ (JS click)")
            return True
    except Exception as e:
        log(f"  [click] ❌ JS: {str(e)[:90]}")

    # 5
    try:
        res = await page.evaluate("""
            (sel) => {
                const el = document.querySelector(sel);
                if (!el) return 'no';
                const evt = new MouseEvent('click', {bubbles:true, cancelable:true, view:window});
                el.dispatchEvent(evt);
                return 'ok';
            }
        """, found_sel)
        if res == 'ok':
            log(f"  [click] ✅ УСПЕХ (dispatchEvent)")
            return True
    except Exception as e:
        log(f"  [click] ❌ dispatchEvent: {str(e)[:90]}")

    log(f"  [click] ❌❌❌ ВСЕ СПОСОБЫ ПРОВАЛИЛИСЬ: '{label}'")
    return False


# 
# ПРОВЕРКИ ВИДИМОСТИ
# 

async def is_visible(page, selector):
    try:
        loc = page.locator(selector)
        if await loc.count() > 0:
            return await loc.first.is_visible()
    except Exception:
        pass
    return False


async def wait_for_any(page, selectors, timeout_sec):
    end = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < end:
        if page.is_closed():
            return -1
        for i, sel in enumerate(selectors):
            try:
                if await page.locator(sel).count() > 0:
                    if await page.locator(sel).first.is_visible():
                        return i
            except Exception:
                pass
        await asyncio.sleep(0.3)
    return -1


# 
# ВОЗВРАТ НА ФОРМУ ПОИСКА
# 

async def ensure_search_page(page):
    try:
        if page.is_closed():
            return False
    except Exception:
        return False

    if await is_visible(page, "#txtBookNo"):
        return True

    log("  [nav] Не на форме — ищем Search Again")
    await click_any_way(page, by_id="btnSearchAgain", by_text="Search Again", label="Search Again")

    idx = await wait_for_any(page, ["#txtBookNo"], 8)
    if idx == 0:
        log("  [nav] Вернулись на форму поиска")
        return True

    log("  [nav] Fallback: goto")
    try:
        await page.goto(
            "https://jimsnetil.shr.sbcounty.gov/bookingsearch.aspx",
            wait_until="domcontentloaded"
        )
        await asyncio.sleep(2)
        return await is_visible(page, "#txtBookNo")
    except Exception as e:
        log(f"  [!] goto fail: {e}")
        return False


# 
# ВВОД НОМЕРА
# 

async def type_slow(page, text):
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.2)
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(*TYPING_SPEED))


# 
# ОДИН ПОИСК
# 

async def search_one(page, booking_no, facility):
    global CURRENT_SEARCH_BOOKING, CURRENT_FACILITY

    if page.is_closed():
        log("  [!] Страница закрыта")
        return "error"

    CURRENT_SEARCH_BOOKING = booking_no
    CURRENT_FACILITY = facility

    if not await ensure_search_page(page):
        return "error"

    # Ввод номера
    try:
        inp = page.locator("#txtBookNo").first
        await inp.wait_for(state="visible", timeout=8000)
        await inp.click()
        await asyncio.sleep(0.2)
        await type_slow(page, booking_no)
    except Exception as e:
        log(f"  [!] Ввод: {e}")
        return "error"

    # Жмём "Search by Booking"
    await asyncio.sleep(0.3)
    await click_any_way(
        page,
        by_id="btnSearchBooking",
        by_text="Search by Booking",
        label="Search by Booking"
    )

    # Небольшая пауза — появление капчи или результата
    log(f"  [ui] Пауза {WAIT_AFTER_SEARCH} сек...")
    await asyncio.sleep(WAIT_AFTER_SEARCH)

    if page.is_closed():
        log("  [!] Страница закрылась после Search")
        return "error"

    # ==========================================
    # ПРОВЕРКА КАПЧИ
    # ==========================================
    if await captcha_present(page):
        log("  [captcha] 🔒 Обнаружена капча! Решаем через Vosk...")
        solved = await solve_recaptcha_audio(page)
        if not solved:
            log("  [captcha] ❌ Не удалось решить. Пропуск.")
            # Попробуем вернуться на форму
            await ensure_search_page(page)
            return "error"

        # После решения капчи — ждём результат
        log("  [captcha] ✅ Капча решена. Ждём Continue/#spnResults...")
        idx = await wait_for_any(
            page,
            ["input[value='Continue'], #btnContinue", "#spnResults"],
            timeout_sec=60
        )
        if idx == -1:
            log("  [!] После капчи не дождались результата")
            return "error"
    else:
        # Ждём обычное появление результата
        log("  [ui] Ждём Continue или #spnResults...")
        idx = await wait_for_any(
            page,
            ["input[value='Continue'], #btnContinue", "#spnResults"],
            timeout_sec=30
        )
        if idx == -1:
            # Может, капча появилась с задержкой
            if await captcha_present(page):
                log("  [captcha] 🔒 Капча появилась с задержкой. Решаем...")
                solved = await solve_recaptcha_audio(page)
                if not solved:
                    await ensure_search_page(page)
                    return "error"
                idx = await wait_for_any(
                    page,
                    ["input[value='Continue'], #btnContinue", "#spnResults"],
                    timeout_sec=60
                )
                if idx == -1:
                    log("  [!] После капчи не дождались результата")
                    return "error"
            else:
                log("  [!] Таймаут ожидания результата")
                return "error"

    log(f"  [ui] Маркер idx={idx} (0=Continue, 1=spnResults)")
    await asyncio.sleep(0.5)

    # ============ НАЙДЕНО ============
    continue_visible = await is_visible(page, "input[value='Continue'], #btnContinue")
    log(f"  [ui] Continue видна: {continue_visible}")

    if continue_visible:
        log("  [ui] → НАЙДЕНО")
        log("  [click] Жму Continue...")
        await click_any_way(page, by_id="btnContinue", by_text="Continue", label="Continue")
        await asyncio.sleep(WAIT_AFTER_CONTINUE)

        if page.is_closed():
            return "error"

        log("  [click] Жму Search Again...")
        await click_any_way(page, by_id="btnSearchAgain", by_text="Search Again", label="Search Again")
        await asyncio.sleep(1.5)
        return "found"

    # ============ НЕ НАЙДЕНО ============
    notfound_present = await is_visible(page, "#spnResults")
    log(f"  [ui] #spnResults видна: {notfound_present}")

    if notfound_present:
        log("  [ui] → НЕ НАЙДЕНО")
        await click_any_way(page, by_id="btnSearchAgain", by_text="Search Again", label="Search Again")
        await asyncio.sleep(1.0)
        return "not_found"

    log("  [!] Ни Continue, ни #spnResults. Пробуем Search Again")
    await click_any_way(page, by_id="btnSearchAgain", by_text="Search Again", label="Search Again")
    await asyncio.sleep(1.0)
    return "error"


# 
# ГЛАВНЫЙ БЛОК
# 

async def main():
    found_count = 0
    not_found_count = 0
    total_checked = 0

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            log(f"[!] Chrome не подключился: {e}")
            sys.exit(1)

        if not browser.contexts:
            log("[!] Нет контекстов Chrome")
            sys.exit(1)

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        log(f"[*] Chrome подключён. URL: {page.url}")

        load_state()
        log(f"[*] Период: {STATE['year']}-{STATE['month']}")
        log(f"[*] last_seq = {STATE['last_seq']}")
        log(f"[*] last_facility_hit = {STATE['last_facility_hit']}")

        # ===== ПЕРЕХВАТ ОТВЕТОВ =====
        async def handle_response(response):
            nonlocal found_count
            try:
                if "GetInmateStatus" not in response.url:
                    return
                if response.request.method != "POST":
                    return

                json_data = await response.json()
                inmate_data = json_data.get('d', {})

                if inmate_data.get('ErrorMessage') == 'Captcha Verification Failed':
                    log("  [api] Капча не пройдена (сессия)")
                    return

                if inmate_data.get('BookNo') or inmate_data.get('Name'):
                    booking_no = inmate_data.get('BookNo', '') or (CURRENT_SEARCH_BOOKING or '')

                    record = {
                        "timestamp": datetime.now().isoformat(),
                        "celBooking": booking_no,
                        "celName": inmate_data.get('Name', ''),
                        "celAge": inmate_data.get('Age', ''),
                        "celArrestDate": inmate_data.get('ArrestDate', ''),
                        "celArrestTime": inmate_data.get('ArrestTime', ''),
                        "celSex": inmate_data.get('Sex', ''),
                        "celDOB": inmate_data.get('DOB', ''),
                        "celHeight": inmate_data.get('Height', ''),
                        "celWeight": inmate_data.get('Weight', ''),
                        "celEyeColor": inmate_data.get('EyeColor', ''),
                        "celHairColor": inmate_data.get('HairColor', ''),
                        "celArrestAgency": inmate_data.get('ArrestAgency', ''),
                        "celHousingFacility": inmate_data.get('HousingFacility', ''),
                        "celArrestLocation": inmate_data.get('ArrestLocation', ''),
                        "celReleaseDate": inmate_data.get('ReleaseDate', ''),
                        "celReleasedTo": inmate_data.get('ReleasedTo', ''),
                        "celBailable": inmate_data.get('Bailable', ''),
                        "celJailType": inmate_data.get('JailType', ''),
                    }

                    try:
                        save_to_excel(record)
                        log(f"  [excel] ✅ Записано")
                    except Exception as e:
                        log(f"  [!] Excel: {e}")

                    found_count += 1

                    try:
                        seq_val = int(booking_no[-4:])
                        STATE["last_seq"] = seq_val
                        STATE["last_facility_hit"] = CURRENT_FACILITY
                        save_state()
                        log(f"  [state] ✅ last_seq={seq_val}, fac={CURRENT_FACILITY}")
                    except Exception as e:
                        log(f"  [!] State: {e}")

                    log(f"  [+] НАЙДЕН: {record['celName']} | {record['celBooking']} | "
                        f"{record['celArrestDate']} {record['celArrestTime']} | "
                        f"{record['celHousingFacility']}")
            except Exception as e:
                log(f"  [-] handle_response: {e}")

        page.on("response", handle_response)

        # ===== ОТКРЫТИЕ =====
        try:
            await page.goto("https://jimsnetil.shr.sbcounty.gov/bookingsearch.aspx",
                            wait_until="domcontentloaded")
            await asyncio.sleep(2)
        except Exception as e:
            log(f"[!] Goto: {e}")

        # ===== ОСНОВНОЙ ЦИКЛ =====
        seq = STATE["last_seq"] + 1
        last_hit = STATE.get("last_facility_hit")

        if last_hit and last_hit in FACILITIES:
            ordered = [last_hit] + [f for f in FACILITIES if f != last_hit]
        else:
            ordered = FACILITIES[:]

        log("")
        log("=" * 60)
        log(f"[*] Старт seq = {seq}")
        log(f"[*] Порядок: {ordered}")
        log("=" * 60)

        consecutive_misses = 0
        caught_up = False

        try:
            while seq <= SEQ_MAX:
                facility_found = None

                for facility in ordered:
                    if page.is_closed():
                        log("[!] Страница закрыта, выход")
                        caught_up = True
                        break

                    booking_no = f"{YEAR}{MONTH}{facility}{seq:04d}"
                    total_checked += 1
                    log(f"[seq {seq:04d}] Пробуем {booking_no}...")

                    try:
                        result = await search_one(page, booking_no, facility)
                    except Exception as e:
                        log(f"  [!] Исключение: {e}")
                        result = "error"

                    if result == "found":
                        facility_found = facility
                        last_hit = facility
                        ordered = [facility] + [f for f in FACILITIES if f != facility]
                        break
                    elif result == "not_found":
                        not_found_count += 1

                    await asyncio.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))

                if page.is_closed():
                    break

                if facility_found:
                    consecutive_misses = 0
                    log(f"  [✓] seq {seq:04d} → {facility_found}")
                else:
                    consecutive_misses += 1
                    log(f"  [–] seq {seq:04d} не найден ({consecutive_misses}/{MAX_CONSECUTIVE_MISSES})")

                    if consecutive_misses >= MAX_CONSECUTIVE_MISSES:
                        log("")
                        log("=" * 60)
                        log(f"[*] {MAX_CONSECUTIVE_MISSES} подряд пусто. Стоп.")
                        log(f"[*] Продолжим с seq {STATE['last_seq'] + 1}")
                        log("=" * 60)
                        caught_up = True
                        break

                seq += 1

        except KeyboardInterrupt:
            log("\n[*] Ctrl+C")

        # ===== ИТОГИ =====
        log("")
        log("=" * 60)
        log(f"[*] Проверено: {total_checked}")
        log(f"[*] Найдено: {found_count}")
        log(f"[*] Не найдено: {not_found_count}")
        log(f"[*] last_seq: {STATE['last_seq']}")
        log(f"[*] Следующий: seq = {STATE['last_seq'] + 1}")
        log("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())