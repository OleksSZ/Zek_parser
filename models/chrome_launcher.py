# -*- coding: utf-8 -*-
import subprocess
import time
import socket
import atexit
import os
import signal
import other.Zek_parser.models.config as config
from other.Zek_parser.models.storage import log

_chrome_process = None


def _is_port_open(host, port, timeout=1):
    with socket.socket() as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False


def launch_chrome():
    global _chrome_process

    log("[chrome] Проверяем порт 9222...")
    if _is_port_open("127.0.0.1", config.CHROME_PORT):
        log(f"[chrome] Порт {config.CHROME_PORT} уже открыт — используем существующий Chrome")
        return True

    os.makedirs(config.CHROME_USER_DATA_DIR, exist_ok=True)

    args = [
        config.CHROME_PATH,
        f"--remote-debugging-port={config.CHROME_PORT}",
        f"--user-data-dir={config.CHROME_USER_DATA_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1366,900",
    ]
    if config.HEADLESS:
        args.append("--headless=new")

    log(f"[chrome] Запуск: {' '.join(args)}")
    try:
        _chrome_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
    except FileNotFoundError:
        log(f"[chrome]  Браузер не найден: {config.CHROME_PATH}")
        return False
    except Exception as e:
        log(f"[chrome]  Ошибка запуска: {e}")
        return False

    atexit.register(kill_chrome)

    log("[chrome] Ждём открытия порта...")
    for i in range(30):
        if _is_port_open("127.0.0.1", config.CHROME_PORT):
            log(f"[chrome]  Порт открыт (попытка {i + 1})")
            time.sleep(1)
            return True
        time.sleep(0.5)

    log("[chrome]  Chrome не открыл порт за 15 сек")
    return False


def kill_chrome():
    global _chrome_process
    if _chrome_process:
        try:
            os.killpg(os.getpgid(_chrome_process.pid), signal.SIGTERM)
            _chrome_process.wait(timeout=5)
            log("[chrome] Процесс Chrome завершён")
        except Exception:
            try:
                os.killpg(os.getpgid(_chrome_process.pid), signal.SIGKILL)
            except Exception:
                pass
        _chrome_process = None