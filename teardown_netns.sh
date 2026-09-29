#!/bin/bash
# Полностью сносит netns. Не трогает основной сервер.
NS="zek_vpn"

echo "=== teardown_netns ==="

if ! ip netns list | grep -q "^$NS"; then
    echo "[=] Namespace '$NS' и так нет"
    exit 0
fi

ip netns exec "$NS" wg-quick down wg0 2>/dev/null || true
ip netns delete "$NS"
echo "[+] Namespace '$NS' удалён"