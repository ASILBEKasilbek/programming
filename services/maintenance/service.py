"""
HotelOS Maintenance Service (Texnik Xizmat Servisi)
Port: 8004

Vazifalar:
- Xona raqamiga bog'liq texnik muammo hisobotlarini qabul qiladi
- Ustuvorlik navbat algoritmi (Priority Queue) muammolarni texniklarga tayinlaydi
- Hal qilish texnik uni tugallangan deb belgilaganda qayd etiladi
- Barcha hodisalar brokerga nashr etiladi

Priority Queue Algorithm:
1. Kritik (1) > Yuqori (2) > Normal (3) > Past (4)
2. Bir xil ustuvorlikdagilar: FIFO (avval topshirilgan birinchi)
"""

import asyncio
import json
import logging
import sys
import os
import uuid
import heapq
from datetime import datetime
from typing import Optional, List, Dict
from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.models import MaintenancePriority, MaintenanceStatus, MaintenanceRequest
from broker.message_broker import MessageBroker

logging.basicConfig(level=logging.INFO, format='%(asctime)s [MAINTENANCE] %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# MA'LUMOTLAR TUZILMALARI
# ═══════════════════════════════════════════════════════

# Ustuvorlik navbati — Priority Queue (heapq)
# (priority_value, timestamp, request_id)
priority_queue: List[tuple] = []

# Barcha so'rovlar
all_requests: Dict[str, MaintenanceRequest] = {}

# Mavjud texniklar
technicians = ["Bobur", "Jasur", "Sardor"]
technician_assignments: Dict[str, List[str]] = {t: [] for t in technicians}

broker: Optional[MessageBroker] = None


# ═══════════════════════════════════════════════════════
# USTUVORLIK NAVBAT ALGORITMI
# ═══════════════════════════════════════════════════════

def assign_to_technician(request: MaintenanceRequest) -> str:
    """
    Keyingi mavjud texnikni tayinlash.
    Eng kam ish yukiga ega texnikni tanlaydi.
    """
    # Eng kam faol topshiriqlarga ega texnik
    min_load = float('inf')
    best_tech = technicians[0]

    for tech in technicians:
        active_count = sum(
            1 for rid in technician_assignments[tech]
            if rid in all_requests and all_requests[rid].status not in
            [MaintenanceStatus.COMPLETED]
        )
        if active_count < min_load:
            min_load = active_count
            best_tech = tech

    return best_tech


# ═══════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════

async def handle_report_issue(request: web.Request) -> web.Response:
    """
    POST /report
    Texnik muammo hisoboti.
    Body: {"room_number": 115, "description": "Singan dush", "priority": "critical"}
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Noto'g'ri format"}, status=400)

    room_number = data.get("room_number")
    description = data.get("description", "").strip()
    priority_str = data.get("priority", "normal").lower()

    # Kiritish tekshiruvi
    if not room_number:
        return web.json_response({"error": "room_number kerak"}, status=400)
    if not description:
        return web.json_response({"error": "Muammo tavsifi kerak"}, status=400)

    room_number = int(room_number)

    # Priority tekshiruvi
    priority_map = {
        "critical": MaintenancePriority.CRITICAL,
        "high": MaintenancePriority.HIGH,
        "normal": MaintenancePriority.NORMAL,
        "low": MaintenancePriority.LOW,
    }
    if priority_str not in priority_map:
        return web.json_response(
            {"error": f"Noto'g'ri ustuvorlik. Mavjud: {list(priority_map.keys())}"},
            status=400
        )

    priority = priority_map[priority_str]

    # So'rov yaratish
    request_id = f"MNT-{uuid.uuid4().hex[:6].upper()}"
    maint_request = MaintenanceRequest(
        request_id=request_id,
        room_number=room_number,
        description=description,
        priority=priority,
        status=MaintenanceStatus.OPEN,
    )

    all_requests[request_id] = maint_request

    # Priority Queue'ga qo'shish (heapq)
    heapq.heappush(priority_queue, (priority.value, maint_request.created_at.timestamp(), request_id))

    # Texnik tayinlash
    assigned_tech = assign_to_technician(maint_request)
    maint_request.assigned_to = assigned_tech
    maint_request.status = MaintenanceStatus.ASSIGNED
    technician_assignments[assigned_tech].append(request_id)

    # Broker orqali nashr etish
    await broker.publish("maintenance.reported", {
        "request_id": request_id,
        "room_number": room_number,
        "description": description,
        "priority": priority.name,
        "priority_value": priority.value,
    })

    await broker.publish("maintenance.assigned", {
        "request_id": request_id,
        "room_number": room_number,
        "technician": assigned_tech,
        "priority": priority.name,
    })

    logger.info(f"MUAMMO: Xona {room_number} - {description} [{priority.name}] -> {assigned_tech}")

    return web.json_response({
        "message": "Muammo qayd etildi va texnikka tayinlandi",
        "request": maint_request.to_dict(),
    })


async def handle_resolve(request: web.Request) -> web.Response:
    """
    POST /resolve
    Texnik muammoni hal etdi deb belgilaydi.
    Body: {"request_id": "MNT-ABC123"}
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Noto'g'ri format"}, status=400)

    request_id = data.get("request_id")
    if not request_id or request_id not in all_requests:
        return web.json_response({"error": "So'rov topilmadi"}, status=404)

    maint_request = all_requests[request_id]
    maint_request.status = MaintenanceStatus.COMPLETED
    maint_request.resolved_at = datetime.now()

    # Broker orqali nashr etish
    await broker.publish("maintenance.resolved", {
        "request_id": request_id,
        "room_number": maint_request.room_number,
        "technician": maint_request.assigned_to,
        "description": maint_request.description,
    })

    logger.info(f"HAL ETILDI: {request_id} (Xona {maint_request.room_number}) ✓")

    return web.json_response({
        "message": "Muammo hal etildi!",
        "request": maint_request.to_dict(),
    })


async def handle_get_requests(request: web.Request) -> web.Response:
    """GET /requests — Barcha so'rovlar."""
    status_filter = request.query.get("status")
    requests_list = list(all_requests.values())

    if status_filter:
        requests_list = [r for r in requests_list if r.status.value == status_filter]

    # Priority bo'yicha tartiblash
    requests_list.sort(key=lambda r: (r.priority.value, r.created_at))

    return web.json_response({
        "requests": [r.to_dict() for r in requests_list],
        "summary": {
            "total": len(all_requests),
            "open": sum(1 for r in all_requests.values() if r.status in [MaintenanceStatus.OPEN, MaintenanceStatus.ASSIGNED, MaintenanceStatus.IN_PROGRESS]),
            "completed": sum(1 for r in all_requests.values() if r.status == MaintenanceStatus.COMPLETED),
        },
        "technicians": {
            tech: {
                "active": sum(1 for rid in tasks if rid in all_requests and all_requests[rid].status != MaintenanceStatus.COMPLETED),
                "total": len(tasks),
            }
            for tech, tasks in technician_assignments.items()
        },
    })


async def handle_get_queue(request: web.Request) -> web.Response:
    """GET /queue — Ustuvorlik navbati."""
    queue_items = []
    for prio, ts, rid in sorted(priority_queue):
        if rid in all_requests and all_requests[rid].status != MaintenanceStatus.COMPLETED:
            queue_items.append(all_requests[rid].to_dict())
    return web.json_response({"priority_queue": queue_items})


# ═══════════════════════════════════════════════════════
# SERVER
# ═══════════════════════════════════════════════════════

async def start_broker(app):
    global broker
    broker = MessageBroker("maintenance")
    await broker.connect()
    await broker.start_listening()


async def stop_broker(app):
    if broker:
        await broker.disconnect()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/report", handle_report_issue)
    app.router.add_post("/resolve", handle_resolve)
    app.router.add_get("/requests", handle_get_requests)
    app.router.add_get("/queue", handle_get_queue)
    app.on_startup.append(start_broker)
    app.on_cleanup.append(stop_broker)
    return app


if __name__ == "__main__":
    app = create_app()
    logger.info("Maintenance Service ishga tushmoqda: http://localhost:8004")
    web.run_app(app, host="0.0.0.0", port=8004, print=None)
