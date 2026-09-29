# -*- coding: utf-8 -*-
import asyncio
import random
import math
from other.Zek_parser.models.storage import log

# Последняя известная позиция мыши (для траектории)
_last_mouse = {"x": 100, "y": 100}


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
        try:
            if page.is_closed():
                return -1
        except Exception:
            return -1
        for i, sel in enumerate(selectors):
            try:
                if await page.locator(sel).count() > 0:
                    if await page.locator(sel).first.is_visible():
                        return i
            except Exception:
                pass
        await asyncio.sleep(0.25)
    return -1


async def human_move_to(page, tx, ty, steps_scale=1.0):
    """
    Движение мыши по кривой Безье + закон Фиттса (время зависит от расстояния).
    """
    global _last_mouse

    sx, sy = _last_mouse["x"], _last_mouse["y"]

    # Закон Фиттса: T = a + b * log2(D/W + 1)
    dist = math.hypot(tx - sx, ty - sy)
    if dist < 3:
        _last_mouse["x"], _last_mouse["y"] = tx, ty
        return

    # Длительность (имитация)
    base = 0.15
    duration = base + 0.08 * math.log2(dist + 1) * steps_scale
    duration = min(duration, 1.5)

    # Контрольные точки Безье — со случайным смещением
    cx1 = sx + (tx - sx) * 0.3 + random.randint(-60, 60)
    cy1 = sy + (ty - sy) * 0.3 + random.randint(-60, 60)
    cx2 = sx + (tx - sx) * 0.7 + random.randint(-60, 60)
    cy2 = sy + (ty - sy) * 0.7 + random.randint(-60, 60)

    steps = max(8, min(30, int(dist / 15)))
    for i in range(1, steps + 1):
        t = i / steps
        # Кубическая кривая Безье
        x = ((1 - t) ** 3 * sx + 3 * (1 - t) ** 2 * t * cx1
             + 3 * (1 - t) * t ** 2 * cx2 + t ** 3 * tx)
        y = ((1 - t) ** 3 * sy + 3 * (1 - t) ** 2 * t * cy1
             + 3 * (1 - t) * t ** 2 * cy2 + t ** 3 * ty)
        x += random.uniform(-1.5, 1.5)
        y += random.uniform(-1.5, 1.5)
        try:
            await page.mouse.move(x, y)
        except Exception:
            return
        await asyncio.sleep(duration / steps * random.uniform(0.7, 1.3))

    # Финальная коррекция
    try:
        await page.mouse.move(tx, ty)
    except Exception:
        pass
    _last_mouse["x"], _last_mouse["y"] = tx, ty


async def human_click_at(page, x, y):
    """Клик в точку с человеческой траекторией."""
    await human_move_to(page, x, y)
    await asyncio.sleep(random.uniform(0.05, 0.18))
    try:
        await page.mouse.click(x, y)
        return True
    except Exception:
        return False


async def click_any_way(page, by_id=None, by_class=None, by_text=None, label="кнопка"):
    """Пробует все способы клика."""
    log(f"  [click] ── Ищем '{label}' ──")

    try:
        if page.is_closed():
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
            if await page.locator(sel).count() > 0:
                found_sel = sel
                break
        except Exception:
            continue

    if not found_sel:
        log(f"  [click]  '{label}' не найден")
        return False

    # 1) обычный click
    try:
        await page.locator(found_sel).first.click(timeout=2000)
        log(f"  [click]  locator.click")
        return True
    except Exception as e:
        log(f"  [click] locator.click: {str(e)[:80]}")

    # 2) force
    try:
        await page.locator(found_sel).first.click(force=True, timeout=2000)
        log(f"  [click]  force")
        return True
    except Exception as e:
        log(f"  [click] force: {str(e)[:80]}")

    # 3) mouse по координатам (с траекторией)
    try:
        box = await page.locator(found_sel).first.bounding_box()
        if box:
            cx = box['x'] + box['width'] / 2
            cy = box['y'] + box['height'] / 2
            if await human_click_at(page, cx, cy):
                log(f"  [click]  mouse.click (human)")
                return True
    except Exception as e:
        log(f"  [click] mouse: {str(e)[:80]}")

    # 4) JS
    try:
        res = await page.evaluate(
            "(sel)=>{const el=document.querySelector(sel);if(!el)return'no';el.click();return'ok';}",
            found_sel
        )
        if res == 'ok':
            log(f"  [click]  JS click")
            return True
    except Exception as e:
        log(f"  [click] JS: {str(e)[:80]}")

    log(f"  [click]  провал: '{label}'")
    return False


async def human_type(page, text):
    """Печатает текст с человеческими задержками."""
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.15)
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(*__import__('config').TYPING_SPEED))