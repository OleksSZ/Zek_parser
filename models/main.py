#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
from playwright.async_api import async_playwright

import other.Zek_parser.models.config as config
import other.Zek_parser.models.chrome_launcher as chrome_launcher
import other.Zek_parser.models.vpn_manager as vpn_manager
from other.Zek_parser.models.storage import log, load_state, init_db, STATE, get_facility_seq
from other.Zek_parser.models.parser import run_parser


async def main():
    log("=" * 60)
    log("[MAIN]  Запуск парсера")
    log("=" * 60)

    
    # 0. База данных
    
    log("[MAIN] Шаг 0: Инициализация БД...")
    if not init_db():
        log("[MAIN]  Не удалось инициализировать БД, выход")
        sys.exit(1)

    
    # 1. VPN
    
    log("[MAIN] Шаг 1: Поднимаем VPN...")
    if not vpn_manager.init():
        log("[MAIN]  VPN не запустился, выход")
        sys.exit(1)

    ip = vpn_manager.get_current_ip()
    log(f"[MAIN] Текущий IP: {ip}")

    
    # 2. Chrome
    
    log("[MAIN] Шаг 2: Запускаем Chrome...")
    if not chrome_launcher.launch_chrome():
        log("[MAIN]  Chrome не запустился")
        sys.exit(1)

    
    # 3. State
    
    load_state()
    log("[MAIN] Текущее состояние по тюрьмам:")
    for fac in config.FACILITIES_ALL:
        log(f"    {fac}: last_seq = {get_facility_seq(fac)}")

    
    # 4. Playwright
    
    async with async_playwright() as p:
        log("[MAIN] Шаг 4: Подключаемся к Chrome по CDP...")
        try:
            browser = await p.chromium.connect_over_cdp(config.CDP_URL)
        except Exception as e:
            log(f"[MAIN]  CDP: {e}")
            sys.exit(1)

        if not browser.contexts:
            log("[MAIN]  Нет контекстов Chrome")
            sys.exit(1)

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        log(f"[MAIN]  CDP подключён. URL: {page.url}")

        
        # 5. Проверка сайта
        
        log("[MAIN] Шаг 5: Проверяем доступность сайта...")
        try:
            resp = await page.goto(
                "https://jimsnetil.shr.sbcounty.gov/bookingsearch.aspx",
                wait_until="domcontentloaded",
                timeout=60000
            )
            if resp:
                log(f"[MAIN]  HTTP {resp.status}. Title: {await page.title()}")
        except Exception as e:
            log(f"[MAIN]  Сайт недоступен: {str(e)[:200]}")
            sys.exit(1)

        
        # 6. Парсер
        
        log("[MAIN] Шаг 6: Запуск парсера...")
        await run_parser(page)

        log("[MAIN]  Завершено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[MAIN] Прервано пользователем")
    finally:
        chrome_launcher.kill_chrome()