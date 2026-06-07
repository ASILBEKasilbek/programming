#!/bin/bash
#
# HotelOS — Barcha servislarni ishga tushirish
# Bitta buyruq bilan to'liq tizim ishlaydi
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🏨 HotelOS — Microservices Architecture"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Cleanup
cleanup() {
    echo ""
    echo "🛑 Barcha servislar to'xtatilmoqda..."
    kill $PID_RECEPTION $PID_HOUSEKEEPING $PID_ROOMSERVICE $PID_MAINTENANCE $PID_DASHBOARD $PID_NGROK 2>/dev/null
    wait 2>/dev/null
    echo "✅ To'xtatildi"
    exit 0
}
trap cleanup SIGINT SIGTERM

# Portlarni tozalash
for port in 8001 8002 8003 8004 8080; do
    lsof -ti:$port | xargs kill -9 2>/dev/null
done
pkill -f "ngrok http" 2>/dev/null
sleep 1

# Venv tekshirish
if [ ! -d "venv" ]; then
    echo "📦 Virtual environment yaratilmoqda..."
    python3 -m venv venv
    venv/bin/pip install -q -r requirements.txt
fi

# Redis tekshirish
echo "🔍 Redis tekshirilmoqda..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "⚠️  Redis ishlamayapti. Ishga tushiring: brew services start redis"
    echo "   Yoki: redis-server --daemonize yes"
    echo ""
    # Redis'ni ishga tushirishga urinish
    redis-server --daemonize yes 2>/dev/null || true
    sleep 1
    if ! redis-cli ping > /dev/null 2>&1; then
        echo "❌ Redis ishga tushmadi. O'rnating: brew install redis"
        exit 1
    fi
fi
echo "✅ Redis: OK"
echo ""

# Servislarni ishga tushirish
echo "🚀 Servislar ishga tushmoqda..."
echo ""

# 1. Reception Service
echo "  [1/5] Reception Service (port 8001)..."
venv/bin/python services/reception/service.py > /tmp/hotelos_reception.log 2>&1 &
PID_RECEPTION=$!
sleep 1

# 2. Housekeeping Service
echo "  [2/5] Housekeeping Service (port 8002)..."
venv/bin/python services/housekeeping/service.py > /tmp/hotelos_housekeeping.log 2>&1 &
PID_HOUSEKEEPING=$!
sleep 1

# 3. Room Service
echo "  [3/5] Room Service (port 8003)..."
venv/bin/python services/room_service/service.py > /tmp/hotelos_roomservice.log 2>&1 &
PID_ROOMSERVICE=$!
sleep 1

# 4. Maintenance Service
echo "  [4/5] Maintenance Service (port 8004)..."
venv/bin/python services/maintenance/service.py > /tmp/hotelos_maintenance.log 2>&1 &
PID_MAINTENANCE=$!
sleep 1

# 5. Dashboard (WebSocket)
echo "  [5/5] Dashboard + WebSocket (port 8080)..."
venv/bin/python dashboard/server.py > /tmp/hotelos_dashboard.log 2>&1 &
PID_DASHBOARD=$!
sleep 2

# Tekshirish
echo ""
echo "🔍 Servislar tekshirilmoqda..."
ALL_OK=true
for port in 8001 8002 8003 8004 8080; do
    if curl -s -o /dev/null http://localhost:$port/ 2>/dev/null; then
        echo "  ✅ Port $port: OK"
    else
        echo "  ❌ Port $port: XATO"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    echo "⚠️  Ba'zi servislar ishga tushmadi. Loglarni tekshiring:"
    echo "    cat /tmp/hotelos_reception.log"
    echo "    cat /tmp/hotelos_housekeeping.log"
    echo "    cat /tmp/hotelos_roomservice.log"
    echo "    cat /tmp/hotelos_maintenance.log"
    echo "    cat /tmp/hotelos_dashboard.log"
fi

# Ngrok (ixtiyoriy)
NGROK_URL=""
if [ "$1" = "--ngrok" ] || [ "$1" = "-n" ]; then
    echo ""
    echo "🌍 Ngrok tunnel ochilmoqda (port 8080)..."
    ngrok http 8080 --log=stdout > /tmp/ngrok_hotelos.log 2>&1 &
    PID_NGROK=$!
    sleep 4
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for t in d.get('tunnels',[]):
        if 'https' in t.get('public_url',''):
            print(t['public_url']); break
except: pass
" 2>/dev/null)
fi

# NATIJA
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  🏨 HotelOS TAYYOR!"
echo ""
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │  📊 Dashboard:      http://localhost:8080           │"
echo "  │  🏨 Reception:      http://localhost:8001           │"
echo "  │  🧹 Housekeeping:   http://localhost:8002           │"
echo "  │  🍽️  Room Service:   http://localhost:8003           │"
echo "  │  🔧 Maintenance:    http://localhost:8004           │"
echo "  └─────────────────────────────────────────────────────┘"
if [ -n "$NGROK_URL" ]; then
echo ""
echo "  🌍 Ngrok:  $NGROK_URL"
fi
echo ""
echo "  API Endpointlar:"
echo "    POST localhost:8001/check-in    {guest_name, room_type, floor_preference}"
echo "    POST localhost:8001/check-out   {room_number}"
echo "    GET  localhost:8001/rooms"
echo "    POST localhost:8003/order       {room_number, items: [{item, quantity}]}"
echo "    POST localhost:8004/report      {room_number, description, priority}"
echo ""
echo "  Ngrok bilan: ./run.sh --ngrok"
echo "  To'xtatish:  Ctrl+C"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

wait
