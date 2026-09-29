#!/bin/bash
# Создаёт network namespace 'zek_vpn' и поднимает WireGuard ТОЛЬКО внутри него.
# Основной сервер (и SSH) ходит напрямую.
#
# Запуск: sudo bash setup_netns.sh
# Идемпотентен — можно запускать повторно.

set -e

NS="zek_vpn"
WG_IF="wg0"
WG_CONF="/etc/wireguard/${WG_IF}.conf"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRST_CONF=$(ls "$PROJECT_DIR"/models/wg_configs/*.conf 2>/dev/null | head -n 1)

echo "=== setup_netns ==="
echo "Project: $PROJECT_DIR"

# --- 1. На всякий случай снять wg0 на основном namespace (если стоит) ---
if ip link show "$WG_IF" &>/dev/null; then
    echo "[!] На основном namespace найден $WG_IF — снимаем"
    wg-quick down "$WG_IF" 2>/dev/null || true
fi

# --- 2. Создать namespace ---
if ! ip netns list | grep -q "^$NS"; then
    ip netns add "$NS"
    echo "[+] Namespace '$NS' создан"
else
    echo "[=] Namespace '$NS' уже есть"
fi

# --- 3. Loopback ---
ip netns exec "$NS" ip link set lo up

# --- 4. Отдельный resolv.conf ---
mkdir -p "/etc/netns/$NS"
echo "nameserver 1.1.1.1" > "/etc/netns/$NS/resolv.conf"
echo "[+] DNS для netns: /etc/netns/$NS/resolv.conf"

# --- 5. Копируем первый конфиг ---
if [ -z "$FIRST_CONF" ]; then
    echo "[!] Не найдено конфигов в $PROJECT_DIR/models/wg_configs/"
    exit 1
fi
cp "$FIRST_CONF" "$WG_CONF"
chmod 600 "$WG_CONF"
echo "[+] Первый конфиг: $(basename "$FIRST_CONF")"

# --- 6. Поднять WireGuard внутри netns ---
ip netns exec "$NS" wg-quick down "$WG_IF" 2>/dev/null || true
ip netns exec "$NS" wg-quick up "$WG_IF"
echo "[+] WireGuard поднят внутри $NS"

# --- 7. Проверка ---
echo ""
echo "=== Проверка ==="
echo -n "IP внутри netns: "
ip netns exec "$NS" curl -s --max-time 6 ifconfig.me || echo "(нет ответа)"
echo ""
echo -n "IP снаружи (основной сервер): "
curl -s --max-time 6 ifconfig.me || echo "(нет ответа)"
echo ""
echo ""
echo "✅ Готово."
echo ""
echo "Запуск парсера:"
echo "   sudo bash run_parser.sh"