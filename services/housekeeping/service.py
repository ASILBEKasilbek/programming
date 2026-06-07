"""
HotelOS Housekeeping Service (Tozalash Servisi)
Port: 8002

Vazifalar:
- 'room.vacated' hodisasini qabul qiladi va xonani tozalash navbatiga qo'shadi
- Tozalovchilar xonalarni 'Tozalanmoqda' -> 'Toza' deb belgilaydi
- Har bir holat o'zgarishi brokerga nashr etiladi
- Tozalash navbatini boshqaradi (Queue ma'lumot tuzilmasi)

Bu servis Reception yoki boshqa servisni TO'G'RIDAN-TO'G'RI chaqirmaydi.
"""

import asyncio
import json
import logging
import sys
import os
from datetime import datetime
from typing import Optional, List, Dict
from collections import deque
from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.models import RoomStatus
from broker.message_broker import MessageBroker

logging.basicConfig(level=logging.INFO, format='%(asctime)s [HOUSEKEEPING] %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# MA'LUMOTLAR TUZILMALARI
# ═══════════════════════════════════════════════════════

# Tozalash navbati — Queue (FIFO)
cleaning_queue: deque = deque()

# Tozalanayotgan xonalar
cleaning_in_progress: Dict[int, dict] = {}

# Tozalangan xonalar tarixi
cleaning_history: List[dict] = []

# Broker
broker: Optional[MessageBroker] = None


# ═══════════════════════════════════════════════════════
# EVENT HANDLERS
# ═══════════════════════════════════════════════════════

async def handle_room_vacated(data: dict):
    """
    Reception servisi 'room.vacated' hodisasini nashr etganda.
    Xonani tozalash navbatiga qo'shadi.
    """
    room_number = data.get("room_number")
    if room_number is None:
        return

    task = {
        "room_number": room_number,
        "added_at": datetime.now().isoformat(),
        "status": "queued",
    }
    cleaning_queue.append(task)

    logger.info(f"Xona {room_number} tozalash navbatiga qo'shildi (navbatda: {len(cleaning_queue)})")

    # Dashboard'ga xabar
    await broker.publish("room.status_changed", {
        "room_number": room_number,
        "old_status": "occupied",
        "new_status": "dirty",
    })


# ═══════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════

async def handle_get_queue(request: web.Request) -> web.Response:
    """GET /queue — Tozalash navbati."""
    return web.json_response({
        "queue": list(cleaning_queue),
        "in_progress": cleaning_in_progress,
        "queue_length": len(cleaning_queue),
        "in_progress_count": len(cleaning_in_progress),
    })


async def handle_start_cleaning(request: web.Request) -> web.Response:
    """
    POST /start-cleaning
    Tozalovchi xonani tozalashni boshlaydi.
    Navbatdan birinchi xonani oladi yoki aniq xona raqami beriladi.
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        data = {}

    room_number = data.get("room_number")
    cleaner_name = data.get("cleaner_name", "Tozalovchi")

    if room_number:
        # Aniq xona — navbatdan olib tashlash
        task = None
        for i, t in enumerate(cleaning_queue):
            if t["room_number"] == room_number:
                task = t
                del cleaning_queue[i]
                break
        if task is None:
            return web.json_response(
                {"error": f"Xona {room_number} navbatda emas"},
                status=404
            )
    else:
        # Navbatdan birinchisini olish (FIFO)
        if not cleaning_queue:
            return web.json_response({"error": "Navbat bo'sh"}, status=404)
        task = cleaning_queue.popleft()
        room_number = task["room_number"]

    # Tozalash boshlandi
    cleaning_in_progress[room_number] = {
        "room_number": room_number,
        "cleaner": cleaner_name,
        "started_at": datetime.now().isoformat(),
        "status": "cleaning",
    }

    # Broker orqali nashr etish
    await broker.publish("room.cleaning_started", {
        "room_number": room_number,
        "cleaner": cleaner_name,
    })

    await broker.publish("room.status_changed", {
        "room_number": room_number,
        "old_status": "dirty",
        "new_status": "cleaning",
    })

    logger.info(f"Xona {room_number} tozalanmoqda ({cleaner_name})")

    return web.json_response({
        "message": f"Xona {room_number} tozalash boshlandi",
        "room_number": room_number,
        "cleaner": cleaner_name,
    })


async def handle_mark_clean(request: web.Request) -> web.Response:
    """
    POST /mark-clean
    Tozalovchi xonani toza deb belgilaydi.
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Noto'g'ri format"}, status=400)

    room_number = data.get("room_number")
    if room_number is None:
        return web.json_response({"error": "room_number kerak"}, status=400)

    room_number = int(room_number)

    if room_number not in cleaning_in_progress:
        return web.json_response(
            {"error": f"Xona {room_number} hozir tozalanmayapti"},
            status=400
        )

    # Tugallash
    task = cleaning_in_progress.pop(room_number)
    task["completed_at"] = datetime.now().isoformat()
    task["status"] = "completed"
    cleaning_history.append(task)

    # Broker orqali nashr etish — Reception va Dashboard oladi
    await broker.publish("room.cleaned", {
        "room_number": room_number,
        "cleaner": task.get("cleaner"),
    })

    await broker.publish("room.status_changed", {
        "room_number": room_number,
        "old_status": "cleaning",
        "new_status": "clean",
    })

    logger.info(f"Xona {room_number} TOZA deb belgilandi ✓")

    return web.json_response({
        "message": f"Xona {room_number} toza!",
        "room_number": room_number,
    })


async def handle_get_history(request: web.Request) -> web.Response:
    """GET /history — Tozalash tarixi."""
    return web.json_response({
        "history": cleaning_history[-20:],
        "total_cleaned": len(cleaning_history),
    })


# ═══════════════════════════════════════════════════════
# SERVER
# ═══════════════════════════════════════════════════════

async def start_broker(app):
    global broker
    broker = MessageBroker("housekeeping")
    await broker.connect()
    broker.subscribe("room.vacated", handle_room_vacated)
    await broker.start_listening()


async def stop_broker(app):
    if broker:
        await broker.disconnect()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/queue", handle_get_queue)
    app.router.add_post("/start-cleaning", handle_start_cleaning)
    app.router.add_post("/mark-clean", handle_mark_clean)
    app.router.add_get("/history", handle_get_history)
    app.on_startup.append(start_broker)
    app.on_cleanup.append(stop_broker)
    return app


if __name__ == "__main__":
    app = create_app()
    logger.info("Housekeeping Service ishga tushmoqda: http://localhost:8002")
    web.run_app(app, host="0.0.0.0", port=8002, print=None)
