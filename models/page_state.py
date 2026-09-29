# -*- coding: utf-8 -*-
from other.Zek_parser.models.page_helpers import is_visible
from other.Zek_parser.models.storage import log


async def _find_recaptcha_frames(page):
    """Возвращает (anchor_frame, challenge_frame). Любой может быть None."""
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


async def captcha_checkbox_present(page):
    """True, если чекбокс капчи РЕАЛЬНО виден."""
    anchor, _ = await _find_recaptcha_frames(page)
    if not anchor:
        return False
    try:
        cb = anchor.locator(".recaptcha-checkbox-border, .recaptcha-checkbox")
        if await cb.count() > 0:
            return await cb.first.is_visible()
    except Exception:
        pass
    return False


async def captcha_challenge_present(page):
    """True, если челлендж РЕАЛЬНО виден (а не просто iframe висит в DOM)."""
    _, challenge = await _find_recaptcha_frames(page)
    if not challenge:
        return False
    try:
        for sel in ["#recaptcha-audio-button", "#audio-response", "#audio-source"]:
            loc = challenge.locator(sel)
            if await loc.count() > 0:
                try:
                    if await loc.first.is_visible():
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


async def captcha_present(page):
    """True, если есть любой тип капчи."""
    if await captcha_challenge_present(page):
        return True
    if await captcha_checkbox_present(page):
        return True
    return False


async def _check_rate_limit(page):
    """True, если в #spnResults текст про превышение лимита."""
    try:
        loc = page.locator("#spnResults")
        if await loc.count() > 0:
            txt = (await loc.first.inner_text()).lower()
            if "exceeded the maximum" in txt or "maximum number of requests" in txt:
                return True
    except Exception:
        pass
    return False


async def _has_found_content(page):
    """True, если видна кнопка Continue (значит запись найдена)."""
    return await is_visible(page, "input[value='Continue'], #btnContinue")


async def _has_not_found(page):
    """True, если видна #spnResults и текст НЕ про лимит."""
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


async def detect_state(page):
    """
    Возможные состояния:
      'dead'              — страница закрыта
      'rate_limited'      — превышен лимит запросов
      'captcha_checkbox'  — виден чекбокс капчи
      'captcha_challenge' — открыт challenge (аудио/картинки)
      'search_form'       — мы на форме поиска (#txtBookNo видно)
      'found'             — видна кнопка Continue
      'not_found'         — видна #spnResults (не про лимит)
      'search_again'      — видна только Search Again
      'unknown'           — ничего не подходит
    """
    try:
        if page.is_closed():
            return "dead"
    except Exception:
        return "dead"

    # 1. Rate limit — важнее всего
    if await _check_rate_limit(page):
        return "rate_limited"

    # 2. Капча — оба типа
    if await captcha_challenge_present(page):
        return "captcha_challenge"
    if await captcha_checkbox_present(page):
        return "captcha_checkbox"

    # 3. Форма поиска
    if await is_visible(page, "#txtBookNo"):
        return "search_form"

    # 4. Найдено
    if await _has_found_content(page):
        return "found"

    # 5. Не найдено
    if await _has_not_found(page):
        return "not_found"

    # 6. Только Search Again
    if await is_visible(page, "input[value='Search Again'], #btnSearchAgain"):
        return "search_again"

    return "unknown"