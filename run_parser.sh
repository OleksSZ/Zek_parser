#!/bin/bash
# Запускает парсер ВНУТРИ netns. SSH и другие скрипты не затрагиваются.
NS="zek_vpn"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG="$PROJECT_DIR/models/parser_nohup.log"
PID_FILE="$PROJECT_DIR/models/parser.pid"

# Проверка, что netns есть
if ! ip netns list | grep -q "^$NS"; then
    echo "❌ Namespace '$NS' не найден. Сначала: sudo bash setup_netns.sh"
    exit 1
fi

# Проверка, что в netns есть интерфейс wg0
if ! ip netns exec "$NS" ip link show wg0 &>/dev/null; then
    echo "❌ wg0 внутри netns не поднят. Запустите setup_netns.sh"
    exit 1
fi

cd "$PROJECT_DIR"
source venv/bin/activate

# Запуск через xvfb-run ВНУТРИ namespace
nohup ip netns exec "$NS" \
    xvfb-run -a python3 models/main.py \
    > "$LOG" 2>&1 &

echo $! > "$PID_FILE"
deactivate

echo "🚀 Парсер запущен в netns '$NS'"
echo "   PID: $(cat "$PID_FILE")"
echo "   Лог: $LOG"
echo "   Смотреть: tail -f $LOG"