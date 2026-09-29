# -*- coding: utf-8 -*-
"""
VPN Manager. Работает ВНУТРИ network namespace 'zek_vpn'.
Все команды wg-quick выполняются в текущем namespace — изоляция автоматом.
"""
import os
import glob
import time
import subprocess
import requests
from other.Zek_parser.models.storage import log
import other.Zek_parser.models.config as config

# Имя namespace — должно совпадать с setup_netns.sh
NS_NAME = "zek_vpn"

_configs = []
_current_index = -1
_current_ip = None


def _sudo(cmd, timeout=30):
    """Выполняет команду с логированием. Автоматически добавляет sudo -n."""
    full_cmd = ["sudo", "-n"] + cmd
    log(f"[vpn] $ {' '.join(full_cmd)}")
    try:
        r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        if r.stdout.strip():
            log(f"[vpn]   out: {r.stdout.strip()[:200]}")
        if r.stderr.strip():
            log(f"[vpn]   err: {r.stderr.strip()[:200]}")
        log(f"[vpn]   rc={r.returncode}")
        return r
    except subprocess.TimeoutExpired:
        log(f"[vpn] ❌ ТАЙМАУТ (>{timeout}s): {' '.join(full_cmd)}")
        return None
    except FileNotFoundError as e:
        log(f"[vpn] ❌ Команда не найдена: {e}")
        return None


def _detect_namespace():
    """Возвращает имя текущего namespace ('main' или netns)."""
    try:
        r = subprocess.run(
            ["ip", "netns", "identify"],
            capture_output=True, text=True, timeout=3
        )
        ns = r.stdout.strip()
        return ns if ns else "main"
    except Exception:
        return "unknown"


def check_inside_namespace():
    """Проверяет, что мы запущены внутри NS_NAME."""
    ns = _detect_namespace()
    if ns == NS_NAME:
        log(f"[vpn] ✅ Мы внутри namespace '{NS_NAME}'")
        return True
    log(f"[vpn] ⚠️ ВНИМАНИЕ: мы в namespace '{ns}', а нужно '{NS_NAME}'")
    log(f"[vpn]    Запускайте парсер через: sudo bash run_parser.sh")
    log(f"[vpn]    Либо вручную: sudo ip netns exec {NS_NAME} xvfb-run -a python3 main.py")
    return False


def list_configs():
    global _configs
    pattern = os.path.join(config.WG_CONFIGS_DIR, "*.conf")
    log(f"[vpn] Ищем конфиги: {pattern}")
    _configs = sorted(glob.glob(pattern))
    return _configs


def get_current_ip():
    """Текущий внешний IP."""
    try:
        r = requests.get("https://api.ipify.org", timeout=8)
        return r.text.strip()
    except Exception as e:
        log(f"[vpn] ⚠️ IP не получен: {str(e)[:80]}")
        return None


def _wg_is_up():
    """True, если интерфейс wg0 существует в ТЕКУЩЕМ namespace."""
    try:
        r = subprocess.run(
            ["ip", "link", "show", config.WG_INTERFACE],
            capture_output=True, text=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def switch_to(config_path, verify=True):
    """Меняет wg0 внутри текущего namespace. True при успехе."""
    global _current_ip

    if not os.path.exists(config_path):
        log(f"[vpn] ❌ Файл не найден: {config_path}")
        return False

    target = f"/etc/wireguard/{config.WG_INTERFACE}.conf"
    log("")
    log(f"[vpn] ── Переключаемся на {os.path.basename(config_path)} ──")

    # down
    if _wg_is_up():
        log("[vpn] Интерфейс поднят — опускаем")
        _sudo(["wg-quick", "down", config.WG_INTERFACE])

    # cp
    r = _sudo(["cp", config_path, target])
    if not r or r.returncode != 0:
        log("[vpn] ❌ Не скопировали конфиг")
        return False

    _sudo(["chmod", "600", target])

    # up
    r = _sudo(["wg-quick", "up", config.WG_INTERFACE])
    if not r or r.returncode != 0:
        log("[vpn] ❌ wg-quick up не удался")
        return False

    log(f"[vpn] Ждём {config.VPN_SWITCH_DELAY} сек...")
    time.sleep(config.VPN_SWITCH_DELAY)

    _sudo(["wg", "show"], timeout=5)

    if verify:
        new_ip = get_current_ip()
        log(f"[vpn] IP: {_current_ip} → {new_ip}")
        _current_ip = new_ip

    return True


def rotate():
    """Следующий конфиг по кругу."""
    global _current_index
    if not _configs:
        list_configs()
    if not _configs:
        log(f"[vpn] ⚠️ Нет конфигов в {config.WG_CONFIGS_DIR}")
        return False

    _current_index = (_current_index + 1) % len(_configs)
    log(f"[vpn] Ротация: {_current_index + 1}/{len(_configs)}")
    return switch_to(_configs[_current_index])


def init():
    """Инициализация. Проверяет namespace + поднимает VPN."""
    global _current_index, _current_ip

    log("")
    log("[vpn] ═════════ Инициализация VPN ═════════")

    # Проверка namespace — критично для изоляции!
    if not check_inside_namespace():
        log("[vpn] ⚠️ Продолжаем, но трафик может идти через основной namespace!")

    log("[vpn] Шаг 1: IP ДО...")
    ip_before = get_current_ip()
    log(f"[vpn] IP до: {ip_before}")

    log("[vpn] Шаг 2: Ищем конфиги...")
    list_configs()
    log(f"[vpn] Найдено: {len(_configs)}")
    for c in _configs[:5]:
        log(f"[vpn]   - {os.path.basename(c)}")
    if len(_configs) > 5:
        log(f"[vpn]   ... и ещё {len(_configs) - 5}")

    if not _configs:
        log(f"[vpn] ❌ Нет .conf в {config.WG_CONFIGS_DIR}")
        return False

    # Если wg0 уже поднят (setup_netns.sh его поднял) — просто проверяем IP
    if _wg_is_up():
        log("[vpn] wg0 уже поднят (setup_netns.sh). Проверяем IP...")
        _current_index = 0
        _current_ip = get_current_ip()
        log(f"[vpn] ✅ VPN активен. IP: {_current_ip}")
        log("[vpn] ═══════════════════════════════════")
        return True

    # Иначе — поднимаем
    log("[vpn] Шаг 3: Поднимаем WireGuard...")
    _current_index = 0
    if not switch_to(_configs[0]):
        log("[vpn] ❌ Не удалось поднять VPN")
        return False

    log("[vpn] Шаг 4: Проверка смены IP...")
    ip_after = get_current_ip()
    log(f"[vpn] IP после: {ip_after}")

    if not ip_after:
        log("[vpn] ⚠️ Не получили IP")
        return False

    if ip_before and ip_before == ip_after:
        log("[vpn] ❌ IP не изменился! VPN не работает")
        return False

    log(f"[vpn] ✅ VPN активен. IP: {ip_after}")
    log("[vpn] ═══════════════════════════════════")
    return True