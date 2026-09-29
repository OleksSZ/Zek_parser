# -*- coding: utf-8 -*-
import asyncio
import random
from datetime import datetime
import other.Zek_parser.models.config as config
import other.Zek_parser.models.vpn_manager as vpn_manager
from other.Zek_parser.models.storage import (
    log, save_to_db, STATE, set_facility_seq, get_facility_seq,
)
from other.Zek_parser.models.page_helpers import click_any_way, human_type, is_visible
from other.Zek_parser.models.captcha_solver import captcha_is_visible, solve_captcha_once

CURRENT_SEARCH_BOOKING = None
CURRENT_FACILITY = None

URL_SEARCH = "https://jimsnetil.shr.sbcounty.gov/bookingsearch.aspx"


# ============================================================
# ПРОСТЫЕ ПРОВЕРКИ
# ============================================================

async def _is_rate_limited(page):
    try:
        loc = page.locator("#spnResults")
        if await loc.count() > 0:
            if await loc.first.is_visible():
                txt = (await loc.first.inner_text()).lower()
                if "exceeded the maximum" in txt or "maximum number of requests" in txt:
                    return True
    except Exception:
        pass
    return False


async def _is_not_found(page):
    try:
        loc = page.locator("#spnResults")
        if await loc.count() > 0:
            if await loc.first.is_visible():
                txt = (await loc.first.inner_text()).lower()
                if "exceeded" not in txt:
                    return True
    except Exception:
        pass
    return False


async def _is_continue_visible(page):
    return await is_visible(page, "input[value='Continue'], #btnContinue")


async def _goto_form(page):
    try:
        await page.goto(URL_SEARCH, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        return await is_visible(page, "#txtBookNo")
    except Exception as e:
        log(f"  [!] goto fail: {str(e)[:120]}")
        return False


async def _ensure_form(page):
    if page.is_closed():
        return False
    if await is_visible(page, "#txtBookNo"):
        return True
    log("  [nav] Не на форме → goto")
    return await _goto_form(page)


# ============================================================
# RATE LIMIT
# ============================================================

async def handle_rate_limit(page):
    log("")
    log("🚫 [RATE LIMIT] Превышен лимит запросов!")
    log("[RATE LIMIT] Меняем VPN...")

    ok = vpn_manager.rotate()
    if not ok:
        log("[RATE LIMIT] ❌ Смена VPN не удалась, ждём 60 сек")
        await asyncio.sleep(60)
    else:
        log("[RATE LIMIT] ✅ VPN сменён")
        await asyncio.sleep(2)

    if page.is_closed():
        return

    await _goto_form(page)


# ============================================================
# ОДИН ПОИСК
# ============================================================

async def search_one(page, booking_no, facility):
    """'found' / 'not_found' / 'error' / 'rate_limited'."""
    global CURRENT_SEARCH_BOOKING, CURRENT_FACILITY

    if page.is_closed():
        return "error"

    CURRENT_SEARCH_BOOKING = booking_no
    CURRENT_FACILITY = facility

    if not await _ensure_form(page):
        return "error"

    # Ввод
    try:
        inp = page.locator("#txtBookNo").first
        await inp.wait_for(state="visible", timeout=6000)
        await inp.click()
        await asyncio.sleep(0.15)
        await human_type(page, booking_no)
    except Exception as e:
        log(f"  [!] Ввод: {str(e)[:120]}")
        return "error"

    # Search by Booking
    await asyncio.sleep(0.2)
    await click_any_way(page, by_id="btnSearchBooking",
                        by_text="Search by Booking", label="Search by Booking")

    await asyncio.sleep(config.WAIT_AFTER_SEARCH)

    if page.is_closed():
        return "error"

    # Rate limit
    if await _is_rate_limited(page):
        return "rate_limited"

    # Капча (один проход)
    if await captcha_is_visible(page):
        log("  [captcha] 🔒 Капча обнаружена")
        ok = await solve_captcha_once(page)
        if not ok:
            log("  [captcha] ❌ Не решили → goto")
            await _goto_form(page)
            return "error"
        if page.is_closed():
            return "error"
        await asyncio.sleep(2.5)
        if page.is_closed():
            return "error"
        if await _is_rate_limited(page):
            return "rate_limited"

    # Continue
    if await _is_continue_visible(page):
        log("  [ui] → НАЙДЕНО")
        await click_any_way(page, by_id="btnContinue",
                            by_text="Continue", label="Continue")
        await asyncio.sleep(config.WAIT_AFTER_CONTINUE)
        if page.is_closed():
            return "error"
        await click_any_way(page, by_id="btnSearchAgain",
                            by_text="Search Again", label="Search Again")
        await asyncio.sleep(1.0)
        return "found"

    # Not found
    if await _is_not_found(page):
        log("  [ui] → НЕ НАЙДЕНО")
        await click_any_way(page, by_id="btnSearchAgain",
                            by_text="Search Again", label="Search Again")
        await asyncio.sleep(0.8)
        return "not_found"

    # Непонятно
    log("  [!] Ни Continue, ни #spnResults → goto")
    await _goto_form(page)
    return "error"


# ============================================================
# ОСНОВНОЙ ЦИКЛ — идём по тюрьмам
# ============================================================

async def run_parser(page):
    found_count = 0
    not_found_count = 0
    total_checked = 0

    # ---- Перехват ответов ----
    async def handle_response(response):
        nonlocal found_count
        try:
            if "GetInmateStatus" not in response.url:
                return
            if response.request.method != "POST":
                return

            data = await response.json()
            inmate = data.get('d', {})

            if inmate.get('ErrorMessage') == 'Captcha Verification Failed':
                log("  [api] Капча не прошла (сессия)")
                return

            if inmate.get('BookNo') or inmate.get('Name'):
                booking_no = inmate.get('BookNo', '') or (CURRENT_SEARCH_BOOKING or '')

                record = {
                    "timestamp": datetime.now().isoformat(),
                    "celBooking": booking_no,
                    "celName": inmate.get('Name', ''),
                    "celAge": inmate.get('Age', ''),
                    "celArrestDate": inmate.get('ArrestDate', ''),
                    "celArrestTime": inmate.get('ArrestTime', ''),
                    "celSex": inmate.get('Sex', ''),
                    "celDOB": inmate.get('DOB', ''),
                    "celHeight": inmate.get('Height', ''),
                    "celWeight": inmate.get('Weight', ''),
                    "celEyeColor": inmate.get('EyeColor', ''),
                    "celHairColor": inmate.get('HairColor', ''),
                    "celArrestAgency": inmate.get('ArrestAgency', ''),
                    "celHousingFacility": inmate.get('HousingFacility', ''),
                    "celArrestLocation": inmate.get('ArrestLocation', ''),
                    "celReleaseDate": inmate.get('ReleaseDate', ''),
                    "celReleasedTo": inmate.get('ReleasedTo', ''),
                    "celBailable": inmate.get('Bailable', ''),
                    "celJailType": inmate.get('JailType', ''),
                }

                if save_to_db(record):
                    log("  [db] ✅ Записано")
                found_count += 1

                # Мгновенно обновляем state для ЭТОЙ тюрьмы
                try:
                    seq_val = int(booking_no[-4:])
                    set_facility_seq(CURRENT_FACILITY, seq_val)
                    log(f"  [state] ✅ {CURRENT_FACILITY} → last_seq={seq_val}")
                except Exception as e:
                    log(f"  [!] State: {e}")

                log(f"  [+] НАЙДЕН: {record['celName']} | {record['celBooking']} | "
                    f"{record['celArrestDate']} {record['celArrestTime']} | "
                    f"{record['celHousingFacility']}")
        except Exception as e:
            log(f"  [-] handle_response: {e}")

    page.on("response", handle_response)

    # ---- Открытие страницы ----
    await _goto_form(page)

    log("")
    log("=" * 60)
    log(f"[*] Тюрьмы в очереди: {config.FACILITIES_ALL}")
    log(f"[*] Стоп: {config.MAX_CONSECUTIVE_MISSES} seq подряд без находок → к следующей")
    log("=" * 60)

    try:
        # ========================================================
        # ИТЕРАЦИЯ ПО ТЮРЬМАМ
        # ========================================================
        for facility in config.FACILITIES_ALL:
            if page.is_closed():
                log("[!] Страница закрыта, выход")
                break

            last_seq = get_facility_seq(facility)
            seq = last_seq + 1
            consecutive_misses = 0

            log("")
            log("=" * 60)
            log(f"[{facility}] Старт: seq = {seq} (последний сохранённый: {last_seq})")
            log("=" * 60)

            while seq <= config.SEQ_MAX:
                if page.is_closed():
                    log("[!] Страница закрыта, выход")
                    break

                booking_no = f"{config.YEAR}{config.MONTH}{facility}{seq:04d}"
                total_checked += 1
                log(f"[{facility}] seq {seq:04d} → {booking_no}")

                try:
                    result = await search_one(page, booking_no, facility)
                except Exception as e:
                    log(f"  [!] Исключение: {e}")
                    result = "error"

                # ==== RATE LIMIT ====
                if result == "rate_limited":
                    await handle_rate_limit(page)
                    log(f"[{facility}] Пробуем тот же seq после смены VPN")
                    continue  # не двигаем seq

                # ==== FOUND ====
                if result == "found":
                    consecutive_misses = 0
                    # state уже обновлён в handle_response
                    seq += 1
                    continue

                # ==== NOT FOUND ====
                if result == "not_found":
                    not_found_count += 1
                    consecutive_misses += 1

                # ==== ERROR ====
                else:
                    # ошибку не считаем за miss, но и не даём крутиться бесконечно
                    consecutive_misses += 1
                    log(f"  [–] error/unknown ({consecutive_misses}/{config.MAX_CONSECUTIVE_MISSES})")

                # ==== Проверка стопа для этой тюрьмы ====
                if consecutive_misses >= config.MAX_CONSECUTIVE_MISSES:
                    log("")
                    log("=" * 60)
                    log(f"[{facility}] {config.MAX_CONSECUTIVE_MISSES} подряд пусто.")
                    log(f"[{facility}] Завершили эту тюрьму, переходим к следующей.")
                    log("=" * 60)
                    break

                seq += 1
                await asyncio.sleep(random.uniform(*config.DELAY_BETWEEN_REQUESTS))

            # После окончания тюрьмы — небольшая пауза
            await asyncio.sleep(2)

    except KeyboardInterrupt:
        log("\n[*] Ctrl+C")

    # ---- Итоги ----
    log("")
    log("=" * 60)
    log(f"[*] Проверено: {total_checked}")
    log(f"[*] Найдено: {found_count}")
    log(f"[*] Не найдено: {not_found_count}")
    log(f"[*] State по тюрьмам:")
    for fac in config.FACILITIES_ALL:
        log(f"    {fac}: last_seq = {get_facility_seq(fac)}")
    log("=" * 60)


__all__ = ["run_parser"]