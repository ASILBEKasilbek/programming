"""
HotelOS Operations Dashboard — WebSocket Real-Time Panel
Port: 8080

WebSocket orqali barcha hodisalarni real vaqtda ko'rsatadi.
Foydalanuvchi sahifani yangilamasdan jonli yangilanishlarni oladi.

Funksiyalar:
- Barcha 10 xonaning joriy holati
- Faol xona xizmati buyurtmalari
- Ochiq texnik muammolar va ustuvorlik
- Har bir band xonadagi joriy mehmon
- Real-time yangilanishlar (WebSocket)
"""

import asyncio
import json
import logging
import sys
import os
from datetime import datetime
from typing import Set
from aiohttp import web
import aiohttp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.message_broker import MessageBroker

logging.basicConfig(level=logging.INFO, format='%(asctime)s [DASHBOARD] %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# WEBSOCKET CONNECTIONS
# ═══════════════════════════════════════════════════════

# Ulangan WebSocket mijozlar
connected_clients: Set[web.WebSocketResponse] = set()

# Broker
broker = None

# Event log (oxirgi 50 ta)
event_log = []


async def broadcast_to_clients(data: dict):
    """Barcha ulangan mijozlarga xabar yuborish."""
    if not connected_clients:
        return

    message = json.dumps(data)
    disconnected = set()

    for ws in connected_clients:
        try:
            await ws.send_str(message)
        except Exception:
            disconnected.add(ws)

    connected_clients.difference_update(disconnected)


# ═══════════════════════════════════════════════════════
# EVENT HANDLERS — Brokerdan kelgan hodisalar
# ═══════════════════════════════════════════════════════

async def handle_any_event(data: dict, event_type: str):
    """Har qanday hodisani dashboard'ga uzatish."""
    event_entry = {
        "event": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }
    event_log.append(event_entry)
    if len(event_log) > 50:
        event_log.pop(0)

    await broadcast_to_clients(event_entry)
    logger.info(f"EVENT -> clients ({len(connected_clients)}): {event_type}")


async def handle_guest_checked_in(data):
    await handle_any_event(data, "guest.checked_in")

async def handle_guest_checked_out(data):
    await handle_any_event(data, "guest.checked_out")

async def handle_room_status_changed(data):
    await handle_any_event(data, "room.status_changed")

async def handle_room_cleaning_started(data):
    await handle_any_event(data, "room.cleaning_started")

async def handle_room_cleaned(data):
    await handle_any_event(data, "room.cleaned")

async def handle_order_placed(data):
    await handle_any_event(data, "order.placed")

async def handle_order_status_changed(data):
    await handle_any_event(data, "order.status_changed")

async def handle_maintenance_reported(data):
    await handle_any_event(data, "maintenance.reported")

async def handle_maintenance_assigned(data):
    await handle_any_event(data, "maintenance.assigned")

async def handle_maintenance_resolved(data):
    await handle_any_event(data, "maintenance.resolved")


# ═══════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════

async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """WebSocket ulanishi — real vaqtli yangilanishlar."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    connected_clients.add(ws)
    logger.info(f"WebSocket client ulandi (jami: {len(connected_clients)})")

    # Dastlabki holat yuborish
    await ws.send_str(json.dumps({
        "event": "connected",
        "data": {"message": "HotelOS Dashboard'ga ulandi", "clients": len(connected_clients)},
        "timestamp": datetime.now().isoformat(),
    }))

    # Oxirgi hodisalarni yuborish
    for event in event_log[-10:]:
        await ws.send_str(json.dumps(event))

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                # Client xabar yuborishi mumkin (masalan, ping)
                if msg.data == "ping":
                    await ws.send_str(json.dumps({"event": "pong", "timestamp": datetime.now().isoformat()}))
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        connected_clients.discard(ws)
        logger.info(f"WebSocket client uzildi (qoldi: {len(connected_clients)})")

    return ws


# ═══════════════════════════════════════════════════════
# HTTP ENDPOINTS
# ═══════════════════════════════════════════════════════

async def handle_dashboard_page(request: web.Request) -> web.Response:
    """GET / — Dashboard HTML sahifasi."""
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    html_path = os.path.join(static_dir, 'index.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
    else:
        html = get_dashboard_html()
    return web.Response(text=html, content_type='text/html')


async def handle_get_state(request: web.Request) -> web.Response:
    """GET /state — Joriy holat (barcha servislardan)."""
    try:
        async with aiohttp.ClientSession() as session:
            rooms_data = {}
            orders_data = {}
            maintenance_data = {}

            try:
                async with session.get("http://localhost:8001/rooms") as resp:
                    rooms_data = await resp.json()
            except:
                rooms_data = {"error": "Reception service unavailable"}

            try:
                async with session.get("http://localhost:8003/orders") as resp:
                    orders_data = await resp.json()
            except:
                orders_data = {"error": "Room service unavailable"}

            try:
                async with session.get("http://localhost:8004/requests") as resp:
                    maintenance_data = await resp.json()
            except:
                maintenance_data = {"error": "Maintenance service unavailable"}

        return web.json_response({
            "rooms": rooms_data,
            "orders": orders_data,
            "maintenance": maintenance_data,
            "event_log": event_log[-20:],
            "connected_clients": len(connected_clients),
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_get_events(request: web.Request) -> web.Response:
    """GET /events — Hodisalar jurnali."""
    return web.json_response({"events": event_log})


# ═══════════════════════════════════════════════════════
# API PROXY (Dashboard orqali barcha servislarni birlashtirish)
# ═══════════════════════════════════════════════════════

SERVICE_MAP = {
    "reception": "http://localhost:8001",
    "housekeeping": "http://localhost:8002",
    "roomservice": "http://localhost:8003",
    "maintenance": "http://localhost:8004",
}


async def proxy_to_service(request: web.Request) -> web.Response:
    """API so'rovlarini tegishli mikroservisga yo'naltirish."""
    path = request.path
    # /api/reception/check-in -> http://localhost:8001/check-in
    parts = path.split("/")
    # parts = ['', 'api', 'reception', 'check-in']
    if len(parts) < 3:
        return web.json_response({"error": "Invalid path"}, status=400)

    service_name = parts[2]
    service_path = "/" + "/".join(parts[3:]) if len(parts) > 3 else "/"

    base_url = SERVICE_MAP.get(service_name)
    if not base_url:
        return web.json_response({"error": f"Service '{service_name}' not found"}, status=404)

    target_url = base_url + service_path

    try:
        async with aiohttp.ClientSession() as session:
            method = request.method
            headers = {"Content-Type": "application/json"}

            if method in ("POST", "PUT", "PATCH"):
                body = await request.read()
                async with session.request(method, target_url, data=body, headers=headers) as resp:
                    data = await resp.json()
                    return web.json_response(data, status=resp.status)
            else:
                async with session.request(method, target_url) as resp:
                    data = await resp.json()
                    return web.json_response(data, status=resp.status)
    except aiohttp.ClientConnectorError:
        return web.json_response({"error": f"Service '{service_name}' unavailable"}, status=503)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def get_dashboard_html() -> str:
    """Dashboard HTML sahifasi — WebSocket bilan real-time yangilanadi."""
    return """<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HotelOS — Operations Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0f1419; color: #e7e9ea; min-height: 100vh; }
        .header { background: #1a1a2e; padding: 20px 30px; border-bottom: 2px solid #c9a96e; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 24px; color: #c9a96e; }
        .status-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; margin-right: 8px; }
        .status-dot.connected { background: #2ecc71; animation: pulse 2s infinite; }
        .status-dot.disconnected { background: #e74c3c; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
        .container { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 20px; max-width: 1400px; margin: 0 auto; }
        .panel { background: #1e2732; border-radius: 12px; padding: 20px; border: 1px solid #2d3748; }
        .panel h2 { color: #c9a96e; font-size: 16px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #2d3748; }
        .room-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
        .room-card { padding: 10px; border-radius: 8px; text-align: center; font-size: 12px; border: 1px solid #2d3748; }
        .room-card .number { font-weight: bold; font-size: 14px; }
        .room-card .guest { font-size: 10px; color: #a0aec0; margin-top: 4px; }
        .room-clean { background: #1a3a2a; border-color: #2ecc71; }
        .room-occupied { background: #1a2a3a; border-color: #3498db; }
        .room-dirty { background: #3a2a1a; border-color: #f39c12; }
        .room-cleaning { background: #2a2a3a; border-color: #9b59b6; }
        .room-maintenance { background: #3a1a1a; border-color: #e74c3c; }
        .event-list { max-height: 300px; overflow-y: auto; }
        .event-item { padding: 8px 12px; border-left: 3px solid #c9a96e; margin-bottom: 8px; background: #0f1419; border-radius: 0 6px 6px 0; font-size: 12px; }
        .event-item .time { color: #718096; font-size: 10px; }
        .event-item .type { color: #c9a96e; font-weight: bold; }
        .order-item, .maint-item { padding: 10px; background: #0f1419; border-radius: 8px; margin-bottom: 8px; font-size: 12px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: bold; }
        .badge-critical { background: #e74c3c; color: white; }
        .badge-high { background: #f39c12; color: white; }
        .badge-normal { background: #3498db; color: white; }
        .badge-low { background: #718096; color: white; }
        .full-width { grid-column: 1 / -1; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🏨 HotelOS — Operations Dashboard</h1>
        <div id="connection-status">
            <span class="status-dot disconnected" id="status-dot"></span>
            <span id="status-text">Ulanmoqda...</span>
        </div>
    </div>

    <div class="container">
        <div class="panel">
            <h2>🛏️ Xonalar Holati</h2>
            <div class="room-grid" id="rooms-grid">
                <div class="room-card">Yuklanmoqda...</div>
            </div>
        </div>

        <div class="panel">
            <h2>📋 Jonli Hodisalar</h2>
            <div class="event-list" id="event-list"></div>
        </div>

        <div class="panel">
            <h2>🍽️ Xona Xizmati Buyurtmalari</h2>
            <div id="orders-list"><p style="color:#718096">Hozircha yo'q</p></div>
        </div>

        <div class="panel">
            <h2>🔧 Texnik Muammolar</h2>
            <div id="maintenance-list"><p style="color:#718096">Hozircha yo'q</p></div>
        </div>
    </div>

    <script>
        let ws;
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(protocol + '//' + location.host + '/ws');

            ws.onopen = () => {
                statusDot.className = 'status-dot connected';
                statusText.textContent = 'Ulangan ✓';
                loadState();
            };

            ws.onmessage = (e) => {
                const data = JSON.parse(e.data);
                handleEvent(data);
            };

            ws.onclose = () => {
                statusDot.className = 'status-dot disconnected';
                statusText.textContent = 'Uzildi — qayta ulanmoqda...';
                setTimeout(connect, 3000);
            };

            ws.onerror = (e) => {
                console.error('WebSocket xato:', e);
                statusDot.className = 'status-dot disconnected';
                statusText.textContent = 'Xato — qayta ulanmoqda...';
            };
        }

        function handleEvent(event) {
            addEventToLog(event);
            // Hodisa turiga qarab panelni yangilash
            if (event.event && event.event.includes('room') || event.event.includes('guest')) {
                loadState();
            }
            if (event.event && event.event.includes('order')) {
                loadState();
            }
            if (event.event && event.event.includes('maintenance')) {
                loadState();
            }
        }

        function addEventToLog(event) {
            const list = document.getElementById('event-list');
            const item = document.createElement('div');
            item.className = 'event-item';
            const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '';
            item.innerHTML = '<span class="time">' + time + '</span> <span class="type">' + (event.event||'') + '</span><br>' + JSON.stringify(event.data || {}).substring(0, 80);
            list.insertBefore(item, list.firstChild);
            if (list.children.length > 30) list.removeChild(list.lastChild);
        }

        async function loadState() {
            try {
                const resp = await fetch('/state');
                const state = await resp.json();
                renderRooms(state.rooms);
                renderOrders(state.orders);
                renderMaintenance(state.maintenance);
            } catch(e) { console.error(e); }
        }

        function renderRooms(data) {
            const grid = document.getElementById('rooms-grid');
            if (!data || !data.rooms) { grid.innerHTML = '<p>Yuklanmadi</p>'; return; }
            grid.innerHTML = data.rooms.map(r => {
                const cls = 'room-' + r.status;
                const guest = r.guest_name ? '<div class="guest">👤 ' + r.guest_name + '</div>' : '';
                return '<div class="room-card ' + cls + '"><div class="number">' + r.number + '</div><div>' + r.status + '</div>' + guest + '</div>';
            }).join('');
        }

        function renderOrders(data) {
            const el = document.getElementById('orders-list');
            if (!data || !data.orders || data.orders.length === 0) {
                el.innerHTML = '<p style="color:#718096">Hozircha buyurtma yo\\'q</p>';
                return;
            }
            el.innerHTML = data.orders.filter(o => o.status !== 'delivered').map(o =>
                '<div class="order-item">🍽️ Xona ' + o.room_number + ' — ' + o.order_id + ' <span class="badge badge-normal">' + o.status + '</span><br><small>$' + o.total_price.toFixed(2) + '</small></div>'
            ).join('') || '<p style="color:#718096">Barcha buyurtmalar yetkazildi</p>';
        }

        function renderMaintenance(data) {
            const el = document.getElementById('maintenance-list');
            if (!data || !data.requests || data.requests.length === 0) {
                el.innerHTML = '<p style="color:#718096">Hozircha muammo yo\\'q</p>';
                return;
            }
            el.innerHTML = data.requests.filter(r => r.status !== 'completed').map(r => {
                const pClass = 'badge-' + r.priority_name.toLowerCase();
                return '<div class="maint-item">🔧 Xona ' + r.room_number + ' — ' + r.description + ' <span class="badge ' + pClass + '">' + r.priority_name + '</span><br><small>' + r.status + (r.assigned_to ? ' → ' + r.assigned_to : '') + '</small></div>';
            }).join('') || '<p style="color:#718096">Barcha muammolar hal etildi</p>';
        }

        connect();
        setInterval(loadState, 10000);
    </script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════
# SERVER
# ═══════════════════════════════════════════════════════

async def start_broker_sub(app):
    global broker
    broker = MessageBroker("dashboard")
    await broker.connect()

    # Barcha hodisalarga obuna
    broker.subscribe("guest.checked_in", handle_guest_checked_in)
    broker.subscribe("guest.checked_out", handle_guest_checked_out)
    broker.subscribe("room.status_changed", handle_room_status_changed)
    broker.subscribe("room.cleaning_started", handle_room_cleaning_started)
    broker.subscribe("room.cleaned", handle_room_cleaned)
    broker.subscribe("order.placed", handle_order_placed)
    broker.subscribe("order.status_changed", handle_order_status_changed)
    broker.subscribe("maintenance.reported", handle_maintenance_reported)
    broker.subscribe("maintenance.assigned", handle_maintenance_assigned)
    broker.subscribe("maintenance.resolved", handle_maintenance_resolved)

    await broker.start_listening()


async def stop_broker_sub(app):
    if broker:
        await broker.disconnect()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_dashboard_page)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/state", handle_get_state)
    app.router.add_get("/events", handle_get_events)

    # Proxy API routes (for single-origin access from browser)
    app.router.add_route("*", "/api/reception/{path:.*}", proxy_to_service)
    app.router.add_route("*", "/api/housekeeping/{path:.*}", proxy_to_service)
    app.router.add_route("*", "/api/roomservice/{path:.*}", proxy_to_service)
    app.router.add_route("*", "/api/maintenance/{path:.*}", proxy_to_service)

    app.on_startup.append(start_broker_sub)
    app.on_cleanup.append(stop_broker_sub)
    return app


if __name__ == "__main__":
    app = create_app()
    logger.info("Dashboard ishga tushmoqda: http://localhost:8080")
    web.run_app(app, host="0.0.0.0", port=8080, print=None)
