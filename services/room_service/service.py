"""
HotelOS Room Service (Xona Xizmati Servisi)
Port: 8003

Vazifalar:
- Xona raqamiga bog'liq ovqat va ichimlik buyurtmalarini qabul qiladi
- Buyurtma holatlari: Received -> Preparing -> Delivering -> Delivered
- Har bir holat o'zgarishi brokerga nashr etiladi
- Buyurtmalar navbati (Queue) boshqariladi

Bu servis boshqa servislarni TO'G'RIDAN-TO'G'RI chaqirmaydi.
"""

import asyncio
import json
import logging
import sys
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict
from collections import deque
from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.models import OrderStatus, RoomServiceOrder
from broker.message_broker import MessageBroker

logging.basicConfig(level=logging.INFO, format='%(asctime)s [ROOM_SERVICE] %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# MA'LUMOTLAR TUZILMALARI
# ═══════════════════════════════════════════════════════

# Buyurtmalar navbati — Queue (FIFO)
order_queue: deque = deque()

# Barcha buyurtmalar (lug'at)
all_orders: Dict[str, RoomServiceOrder] = {}

# Menyu
MENU = {
    "coffee": {"name": "Qahva", "price": 5.0},
    "tea": {"name": "Choy", "price": 3.0},
    "sandwich": {"name": "Sandvich", "price": 12.0},
    "burger": {"name": "Burger", "price": 15.0},
    "pasta": {"name": "Pasta", "price": 18.0},
    "salad": {"name": "Salat", "price": 10.0},
    "water": {"name": "Suv", "price": 2.0},
    "juice": {"name": "Sharbat", "price": 6.0},
}

broker: Optional[MessageBroker] = None


# ═══════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════

async def handle_get_menu(request: web.Request) -> web.Response:
    """GET /menu — Menyu."""
    return web.json_response({"menu": MENU})


async def handle_place_order(request: web.Request) -> web.Response:
    """
    POST /order
    Yangi buyurtma qabul qilish.
    Body: {"room_number": 301, "items": [{"item": "coffee", "quantity": 2}]}
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Noto'g'ri format"}, status=400)

    room_number = data.get("room_number")
    items_raw = data.get("items", [])

    # Kiritish tekshiruvi
    if not room_number:
        return web.json_response({"error": "room_number kerak"}, status=400)
    if not items_raw:
        return web.json_response({"error": "Kamida bitta buyurtma kerak"}, status=400)

    try:
        room_number = int(room_number)
    except (ValueError, TypeError):
        return web.json_response({"error": "Noto'g'ri xona raqami formati"}, status=400)

    # Buyurtma elementlarini tekshirish
    items = []
    for item_data in items_raw:
        item_name = item_data.get("item", "").lower()
        quantity = item_data.get("quantity", 1)

        if item_name not in MENU:
            return web.json_response(
                {"error": f"'{item_name}' menyuda yo'q. Mavjud: {list(MENU.keys())}"},
                status=400
            )
        if quantity < 1 or quantity > 10:
            return web.json_response({"error": "Miqdor 1 dan 10 gacha"}, status=400)

        menu_item = MENU[item_name]
        items.append({
            "item": item_name,
            "name": menu_item["name"],
            "price": menu_item["price"],
            "quantity": quantity,
        })

    # Buyurtma yaratish
    order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
    order = RoomServiceOrder(
        order_id=order_id,
        room_number=room_number,
        items=items,
        status=OrderStatus.RECEIVED,
    )

    all_orders[order_id] = order
    order_queue.append(order_id)

    # Broker orqali nashr etish
    await broker.publish("order.placed", {
        "order_id": order_id,
        "room_number": room_number,
        "items": items,
        "total_price": order.total_price,
        "status": order.status.value,
    })

    logger.info(f"BUYURTMA: Xona {room_number} -> {order_id} (${order.total_price:.2f})")

    return web.json_response({
        "message": "Buyurtma qabul qilindi!",
        "order": order.to_dict(),
    })


async def handle_update_status(request: web.Request) -> web.Response:
    """
    POST /order/status
    Buyurtma holatini yangilash.
    Body: {"order_id": "ORD-ABC123", "status": "preparing"}
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Noto'g'ri format"}, status=400)

    order_id = data.get("order_id")
    new_status_str = data.get("status", "").lower()

    if not order_id or order_id not in all_orders:
        return web.json_response({"error": "Buyurtma topilmadi"}, status=404)

    try:
        new_status = OrderStatus(new_status_str)
    except ValueError:
        valid = [s.value for s in OrderStatus]
        return web.json_response({"error": f"Noto'g'ri holat. Mavjud: {valid}"}, status=400)

    order = all_orders[order_id]
    old_status = order.status
    order.status = new_status

    # Navbatdan olib tashlash
    if new_status != OrderStatus.RECEIVED and order_id in order_queue:
        try:
            order_queue.remove(order_id)
        except ValueError:
            pass

    # Broker orqali nashr etish
    await broker.publish("order.status_changed", {
        "order_id": order_id,
        "room_number": order.room_number,
        "old_status": old_status.value,
        "new_status": new_status.value,
    })

    # Agar yetkazildi — Reception'ga billing uchun xabar
    if new_status == OrderStatus.DELIVERED:
        await broker.publish("order.delivered", {
            "order_id": order_id,
            "room_number": order.room_number,
            "items": order.items,
            "total_price": order.total_price,
        })
        logger.info(f"YETKAZILDI: {order_id} -> Xona {order.room_number} (${order.total_price:.2f})")
    else:
        logger.info(f"STATUS: {order_id} -> {new_status.value}")

    return web.json_response({
        "message": f"Buyurtma holati yangilandi: {new_status.value}",
        "order": order.to_dict(),
    })


async def handle_get_orders(request: web.Request) -> web.Response:
    """GET /orders — Barcha buyurtmalar."""
    room = request.query.get("room")
    orders = list(all_orders.values())
    if room:
        orders = [o for o in orders if o.room_number == int(room)]
    return web.json_response({
        "orders": [o.to_dict() for o in orders],
        "queue_length": len(order_queue),
        "active_orders": sum(1 for o in all_orders.values() if o.status != OrderStatus.DELIVERED),
    })


# ═══════════════════════════════════════════════════════
# SERVER
# ═══════════════════════════════════════════════════════

async def start_broker(app):
    global broker
    broker = MessageBroker("room_service")
    await broker.connect()
    await broker.start_listening()


async def stop_broker(app):
    if broker:
        await broker.disconnect()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/menu", handle_get_menu)
    app.router.add_post("/order", handle_place_order)
    app.router.add_post("/order/status", handle_update_status)
    app.router.add_get("/orders", handle_get_orders)
    app.on_startup.append(start_broker)
    app.on_cleanup.append(stop_broker)
    return app


def initialize_test_data():
    """Test ma'lumotlarini yaratish — demo buyurtmalar."""
    import uuid

    test_orders = [
        {"room": 102, "items": [
            {"item": "coffee", "name": "Qahva", "price": 5.0, "quantity": 2},
            {"item": "sandwich", "name": "Sandvich", "price": 12.0, "quantity": 1},
        ]},
        {"room": 104, "items": [
            {"item": "burger", "name": "Burger", "price": 15.0, "quantity": 1},
            {"item": "juice", "name": "Sharbat", "price": 6.0, "quantity": 2},
        ]},
        {"room": 202, "items": [
            {"item": "pasta", "name": "Pasta", "price": 18.0, "quantity": 1},
            {"item": "water", "name": "Suv", "price": 2.0, "quantity": 1},
        ]},
    ]

    statuses = [OrderStatus.RECEIVED, OrderStatus.PREPARING, OrderStatus.DELIVERING]

    for i, odata in enumerate(test_orders):
        order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
        order = RoomServiceOrder(
            order_id=order_id,
            room_number=odata["room"],
            items=odata["items"],
            status=statuses[i],
        )
        all_orders[order_id] = order
        if statuses[i] == OrderStatus.RECEIVED:
            order_queue.append(order_id)

    logger.info(f"Test ma'lumotlar yuklandi: {len(test_orders)} buyurtma")


if __name__ == "__main__":
    initialize_test_data()
    app = create_app()
    logger.info("Room Service ishga tushmoqda: http://localhost:8003")
    web.run_app(app, host="0.0.0.0", port=8003, print=None)
