# -*- coding: utf-8 -*-
import asyncio
import os
import json
import random
import subprocess
from vosk import Model, KaldiRecognizer, SetLogLevel
import other.Zek_parser.models.config as config
from other.Zek_parser.models.storage import log
from other.Zek_parser.models.page_helpers import human_move_to

SetLogLevel(-1)

VOSK_MODEL = None
try:
    VOSK_MODEL = Model(config.VOSK_MODEL_PATH)
    print(f"[VOSK]  Модель загружена: {config.VOSK_MODEL_PATH}")
except Exception as e:
    print(f"[VOSK]  Модель не загружена: {e}")


async def _find_frames(page):
    """Возвращает (anchor, challenge). Любой может быть None."""
    anchor = None
    challenge = None
    try:
        for fr in page.frames:
            url = fr.url or ""
            if "recaptcha" not in url:
                continue
            if "anchor" in url:
                anchor = fr
            elif "bframe" in url or "challenge" in url:
                challenge = fr
    except Exception:
        pass
    return anchor, challenge


async def captcha_is_visible(page):
    """
    True, если капча РЕАЛЬНО видна пользователю (чекбокс или активный challenge).
    Проверяет видимость, а не просто наличие в DOM.
    """
    try:
        anchor, challenge = await _find_frames(page)
    except Exception:
        return False

    # Чекбокс
    if anchor:
        try:
            cb = anchor.locator(".recaptcha-checkbox-border, .recaptcha-checkbox")
            if await cb.count() > 0 and await cb.first.is_visible():
                return True
        except Exception:
            pass

    # Активный challenge (кнопка аудио видна = челлендж ждёт ответа)
    if challenge:
        try:
            audio_btn = challenge.locator("#recaptcha-audio-button")
            if await audio_btn.count() > 0 and await audio_btn.first.is_visible():
                return True
        except Exception:
            pass
        try:
            resp_input = challenge.locator("#audio-response")
            if await resp_input.count() > 0 and await resp_input.first.is_visible():
                return True
        except Exception:
            pass

    return False


async def click_captcha_checkbox(page, timeout=15):
    """Кликает по чекбоксу 'Я не робот'. True при успехе."""
    log("[CAPTCHA] 🖱️ Кликаем по чекбоксу")
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        anchor, _ = await _find_frames(page)
        if anchor:
            try:
                cb = anchor.locator(".recaptcha-checkbox-border, .recaptcha-checkbox")
                if await cb.count() > 0:
                    try:
                        await cb.first.click(timeout=2000)
                        log("[CAPTCHA]  Чекбокс нажат (обычный)")
                        return True
                    except Exception as e:
                        log(f"[CAPTCHA] обычный: {str(e)[:60]}")
                    try:
                        await cb.first.click(force=True, timeout=2000)
                        log("[CAPTCHA]  Чекбокс нажат (force)")
                        return True
                    except Exception as e:
                        log(f"[CAPTCHA] force: {str(e)[:60]}")
                    try:
                        box = await cb.first.bounding_box()
                        if box:
                            cx = box['x'] + box['width'] / 2
                            cy = box['y'] + box['height'] / 2
                            await human_move_to(page, cx, cy)
                            await asyncio.sleep(0.1)
                            await page.mouse.click(cx, cy)
                            log("[CAPTCHA]  Чекбокс нажат (mouse)")
                            return True
                    except Exception as e:
                        log(f"[CAPTCHA] mouse: {str(e)[:60]}")
            except Exception:
                pass
        await asyncio.sleep(0.5)
    log("[CAPTCHA]  Чекбокс не найден")
    return False


async def solve_recaptcha_audio(page, timeout_challenge=20):
    """Решает аудио-challenge через Vosk."""
    log("")
    log("=" * 60)
    log("[CAPTCHA] 🎯 Решаем challenge через Vosk")
    log("=" * 60)

    if not VOSK_MODEL:
        log("[CAPTCHA]  Нет модели Vosk")
        return False

    os.makedirs(config.TEMP_AUDIO_DIR, exist_ok=True)
    ts = int(asyncio.get_event_loop().time() * 1000)
    mp3_path = os.path.join(config.TEMP_AUDIO_DIR, f"c_{ts}.mp3")
    wav_path = os.path.join(config.TEMP_AUDIO_DIR, f"c_{ts}.wav")

    try:
        log("[CAPTCHA] 1. Ждём challenge...")
        challenge_frame = None
        deadline = asyncio.get_event_loop().time() + timeout_challenge
        while asyncio.get_event_loop().time() < deadline:
            _, challenge = await _find_frames(page)
            if challenge:
                challenge_frame = challenge
                break
            await asyncio.sleep(0.4)

        if not challenge_frame:
            log("[CAPTCHA]  Challenge не появился")
            return False
        log(f"[CAPTCHA]  Challenge найден")

        log("[CAPTCHA] 2. Клик #recaptcha-audio-button")
        audio_btn = challenge_frame.locator("#recaptcha-audio-button")
        try:
            await audio_btn.wait_for(state="visible", timeout=6000)
        except Exception as e:
            log(f"[CAPTCHA]  Кнопка аудио: {str(e)[:80]}")
            return False
        await audio_btn.click()
        await asyncio.sleep(2)

        log("[CAPTCHA] 3. Ищем #audio-source")
        audio_source = challenge_frame.locator("#audio-source")
        try:
            await audio_source.wait_for(state="attached", timeout=8000)
        except Exception as e:
            log(f"[CAPTCHA]  Нет audio-source: {str(e)[:80]}")
            return False
        audio_url = await audio_source.get_attribute("src")
        if not audio_url:
            log("[CAPTCHA]  src пустой")
            return False
        log(f"[CAPTCHA]  URL: {audio_url[:80]}...")

        log("[CAPTCHA] 4. Скачиваем mp3")
        resp = await page.request.get(audio_url)
        if resp.status != 200:
            log(f"[CAPTCHA]  HTTP {resp.status}")
            return False
        body = await resp.body()
        with open(mp3_path, "wb") as f:
            f.write(body)
        log(f"[CAPTCHA]  {len(body)} байт")

        log("[CAPTCHA] 5. MP3 → WAV")
        cmd = [config.FFMPEG_PATH, "-y", "-i", mp3_path,
               "-ar", "16000", "-ac", "1", "-f", "wav", wav_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[CAPTCHA]  ffmpeg: {r.stderr[:150]}")
            return False
        log("[CAPTCHA]  WAV готов")

        log("[CAPTCHA] 6. Распознаём")
        rec = KaldiRecognizer(VOSK_MODEL, 16000)
        with open(wav_path, "rb") as f:
            while True:
                data = f.read(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
        text = json.loads(rec.FinalResult()).get("text", "").strip()
        log(f"[CAPTCHA] 🎤 Распознано: '{text}'")
        if not text:
            log("[CAPTCHA]  Пусто")
            return False

        log("[CAPTCHA] 7. Ввод в #audio-response")
        resp_input = challenge_frame.locator("#audio-response")
        try:
            await resp_input.wait_for(state="visible", timeout=5000)
        except Exception as e:
            log(f"[CAPTCHA]  Поле ввода: {str(e)[:80]}")
            return False
        await resp_input.click()
        await asyncio.sleep(0.2)
        for ch in text:
            await resp_input.type(ch, delay=random.randint(45, 110))
        log("[CAPTCHA]  Введено")

        log("[CAPTCHA] 8. Клик Verify")
        verify_btn = challenge_frame.locator("#recaptcha-verify-button")
        try:
            await verify_btn.wait_for(state="visible", timeout=5000)
        except Exception as e:
            log(f"[CAPTCHA]  Verify: {str(e)[:80]}")
            return False
        try:
            box = await verify_btn.bounding_box()
            if box:
                vx = box['x'] + box['width'] / 2
                vy = box['y'] + box['height'] / 2
                await human_move_to(page, vx, vy)
                await asyncio.sleep(0.1)
                await page.mouse.click(vx, vy)
            else:
                await verify_btn.click()
        except Exception:
            await verify_btn.click()

        log("[CAPTCHA]  Verify отправлен")
        await asyncio.sleep(3)
        log("[CAPTCHA] 🎉 Challenge пройден")
        log("=" * 60)
        return True

    except Exception as e:
        log(f"[CAPTCHA]  Ошибка: {e}")
        return False
    finally:
        for p in (mp3_path, wav_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def solve_captcha_once(page):
    """
    ОДИН проход решения капчи:
      1. Если чекбокс — кликнуть
      2. Если появился challenge — решить через Vosk
    Возвращает True, если капчи больше нет (или её не было).
    НЕ зацикливается.
    """
    if not await captcha_is_visible(page):
        return True

    log("  [captcha] 🔒 Капча видна, решаем ОДИН раз")

    # Шаг 1: чекбокс
    anchor, _ = await _find_frames(page)
    if anchor:
        try:
            cb = anchor.locator(".recaptcha-checkbox-border, .recaptcha-checkbox")
            if await cb.count() > 0 and await cb.first.is_visible():
                if not await click_captcha_checkbox(page, timeout=10):
                    return False
                log("  [captcha] Ждём 3 сек после чекбокса...")
                await asyncio.sleep(3)
        except Exception as e:
            log(f"  [captcha] Ошибка чекбокса: {str(e)[:80]}")

    # Шаг 2: challenge (если появился)
    if not await captcha_is_visible(page):
        log("  [captcha]  Капча прошла без challenge")
        return True

    # Проверяем именно challenge, а не чекбокс снова
    _, challenge = await _find_frames(page)
    if challenge:
        try:
            audio_btn = challenge.locator("#recaptcha-audio-button")
            if await audio_btn.count() > 0 and await audio_btn.first.is_visible():
                ok = await solve_recaptcha_audio(page)
                return ok
        except Exception as e:
            log(f"  [captcha] Ошибка challenge: {str(e)[:80]}")

    # Если после чекбокса всё ещё что-то видно — считаем, что не решили
    if await captcha_is_visible(page):
        log("  [captcha]  Капча всё ещё видна после попытки решения")
        return False

    return True