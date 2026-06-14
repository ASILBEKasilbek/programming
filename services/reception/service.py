"""
HotelOS Reception Service (Qabul Servisi)
Port: 8001

Vazifalar:
- Mehmon check-in (xona tayinlash algoritmini ishga tushiradi)
- Mehmon check-out (hisob-kitob algoritmi + 'room.vacated' hodisasini nashr etadi)
- Xona inventar so'rovlari
- Mehmon ma'lumotlarini boshqarish

Bu servis boshqa servislarni TO'G'RIDAN-TO'G'RI chaqirmaydi.
Barcha aloqa Redis Pub/Sub broker orqali amalga oshiriladi.
"""

import asyncio
import json
import logging
import sys
import os
import re
from datetime import datetime, timedelta
from typing imp1qqort Optional, List, Dict
from aiohttp import web

# Loyiha root papkasini path'ga qo'shish
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.models import Room, Guest, RoomType, RoomStatus
from broker.message_broker import MessageBroker

logging.basicConfig(level=logging.INFO, format='%(asctime)s [RECEPTION] %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# MA'LUMOTLAR TUZILMALARI
# ═══════════════════════════════════════════════════════

# Xona inventari — Array/List
rooms: List[Room] = []

# Mehmon yozuvlari — Dictionary/Map
guests: Dict[str, Guest] = {}

# Broker instance
broker: Optional[MessageBroker] = None


def initialize_rooms():
    """Boshlang'ich xona inventarini yaratish (10 xona, 2 qavat)."""
    global rooms
    room_configs = [
        # 1-qavat
        (101, 1, RoomType.SINGLE, False, 80.0),
        (102, 1, RoomType.DOUBLE, True, 120.0),
        (103, 1, RoomType.DOUBLE, False, 120.0),
        (104, 1, RoomType.SUITE, True, 250.0),
        (105, 1, RoomType.ACCESSIBLE, True, 130.0),
        # 2-qavat
        (201, 2, RoomType.SINGLE, False, 90.0),
        (202, 2, RoomType.DOUBLE, True, 140.0),
        (203, 2, RoomType.DOUBLE, False, 140.0),
        (204, 2, RoomType.SUITE, False, 280.0),
        (205, 2, RoomType.ACCESSIBLE, True, 140.0),
    ]

    # Har xil vaqt bilan tozalangan holda
    base_time = datetime.now()
    rooms = []
    for i, (num, floor, rtype, elevator, price) in enumerate(room_configs):
        room = Room(
            number=num,
            floor=floor,
            room_type=rtype,
            status=RoomStatus.CLEAN,
            clean_since=base_time - timedelta(hours=10 - i),  # Har xil vaqt
            near_elevator=elevator,
            price_per_night=price,
        )
        rooms.append(room)

    logger.info(f"{len(rooms)} ta xona yaratildi")


# ═══════════════════════════════════════════════════════
# XONA TAYINLASH ALGORITMI
# ═══════════════════════════════════════════════════════

def assign_room(
    room_type: RoomType,
    floor_preference: Optional[int] = None,
    near_elevator: bool = False
) -> Optional[Room]:
    """
    Xona tayinlash algoritmi — BTEC talablariga mos.

    Qadamlar:
    1. Xona turi mos kelishini tekshir (SINGLE, DOUBLE, SUITE, ACCESSIBLE)
    2. Faqat CLEAN holatdagi xonalarni tanla
    3. Eng uzoq toza xonani ustunlik ber (tekis aylantirish)
    4. Qavat afzalligi — ikkinchi darajali filtr
    5. Yaqinlik afzalligi — yakuniy hal qiluvchi

    Args:
        room_type: So'ralgan xona turi
        floor_preference: Afzal qavat (optional)
        near_elevator: Liftga yaqinlik afzalligi

    Returns:
        Room yoki None (xona topilmasa)
    """
    # 1-QADAM: Xona turi bo'yicha filtrlash
    matching_rooms = [r for r in rooms if r.room_type == room_type]

    if not matching_rooms:
        logger.warning(f"Xona turi topilmadi: {room_type.value}")
        return None

    # 2-QADAM: Faqat CLEAN holatdagi xonalar
    clean_rooms = [r for r in matching_rooms if r.status == RoomStatus.CLEAN]

    if not clean_rooms:
        logger.warning(f"Toza {room_type.value} xona yo'q")
        return None

    # 3-QADAM: Eng uzoq toza bo'yicha tartiblash (birinchi = eng uzoq toza)
    clean_rooms.sort(key=lambda r: r.clean_since or datetime.now())

    # 4-QADAM: Qavat afzalligi (ikkinchi darajali filtr)
    if floor_preference is not None:
        preferred_floor_rooms = [r for r in clean_rooms if r.floor == floor_preference]
        if preferred_floor_rooms:
            clean_rooms = preferred_floor_rooms
            # Agar o'sha qavatda yo'q — barcha mos qavatga o'tamiz (clean_rooms o'zgarmaydi)

    # 5-QADAM: Yaqinlik afzalligi (yakuniy hal qiluvchi)
    if near_elevator:
        elevator_rooms = [r for r in clean_rooms if r.near_elevator]
        if elevator_rooms:
            clean_rooms = elevator_rooms

    # Birinchi xonani tanlash (eng uzoq toza)
    selected = clean_rooms[0]
    return selected


# ═══════════════════════════════════════════════════════
# HISOB-KITOB ALGORITMI
# ═══════════════════════════════════════════════════════

def calculate_bill(guest: Guest, room: Room) -> dict:
    """
    Hisob-kitob algoritmi — check-outda.

    Qadamlar:
    1. Xona narxi × tunlar sonini hisoblash
    2. Barcha xona xizmati to'lovlarini qo'shish
    3. Umumiy summani chiqarish

    Chegaraviy holatlar:
    - Erta check-out: haqiqiy tunlar soni hisoblanadi
    - Nol to'lovlar: faqat xona narxi
    - Minimal 1 kecha

    Args:
        guest: Mehmon ma'lumotlari
        room: Xona ma'lumotlari

    Returns:
        Hisob-kitob tafsilotlari (dict)
    """
    # Tunlar sonini hisoblash (minimal 1)
    nights = max(1, guest.nights)

    # Erta check-out tekshiruvi
    if guest.check_in_time:
        actual_nights = max(1, (datetime.now() - guest.check_in_time).days)
        nights = min(nights, actual_nights)  # Erta check-out uchun

    # Xona narxi
    room_charge = room.price_per_night * nights

    # Xona xizmati to'lovlari
    service_charges = []
    service_total = 0.0
    for charge in guest.charges:
        amount = charge.get("price", 0) * charge.get("quantity", 1)
        service_charges.append({
            "description": charge.get("description", "Xizmat"),
            "amount": amount,
        })
        service_total += amount

    # Umumiy summa
    total = room_charge + service_total

    return {
        "guest_name": guest.name,
        "room_number": room.number,
        "nights": nights,
        "room_price_per_night": room.price_per_night,
        "room_charge": room_charge,
        "service_charges": service_charges,
        "service_total": service_total,
        "total": total,
    }


# ═══════════════════════════════════════════════════════
# EVENT HANDLERS (Brokerdan kelgan hodisalar)
# ═══════════════════════════════════════════════════════

async def handle_room_cleaned(data: dict):
    """Tozalash servisi xonani toza deb belgilaganda."""
    room_number = data.get("room_number")
    for room in rooms:
        if room.number == room_number:
            room.status = RoomStatus.CLEAN
            room.clean_since = datetime.now()
            logger.info(f"Xona {room_number} toza — tayinlash uchun mavjud")
            break


async def handle_order_delivered(data: dict):
    """Xona xizmati buyurtmasi yetkazilganda — hisobga qo'shish."""
    room_number = data.get("room_number")
    total = data.get("total_price", 0)
    items = data.get("items", [])

    # Mehmonning hisobiga qo'shish
    for guest_name, guest in guests.items():
        if guest.room_number == room_number:
            guest.charges.append({
                "description": f"Xona xizmati buyurtmasi",
                "price": total,
                "quantity": 1,
            })
            logger.info(f"Xona {room_number} hisobiga {total}$ qo'shildi")
            break


async def handle_maintenance_resolved(data: dict):
    """Texnik muammo hal etilganda — xona holatini yangilash."""
    room_number = data.get("room_number")
    for room in rooms:
        if room.number == room_number and room.status == RoomStatus.MAINTENANCE:
            room.status = RoomStatus.DIRTY
            logger.info(f"Xona {room_number}: texnik xizmat tugadi -> Iflos")
            break


# ═══════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════

async def handle_check_in(request: web.Request) -> web.Response:
    """
    POST /check-in
    Mehmon check-in — xona tayinlash algoritmini ishga tushiradi.

    Request Body:
        guest_name (str): Mehmon ismi (majburiy)
        room_type (str): Xona turi - single/double/suite/accessible (majburiy)
        floor_preference (int): Qavat afzalligi - 1 yoki 2 (ixtiyoriy)
        near_elevator (bool): Liftga yaqin xona (ixtiyoriy, default: false)
        nights (int): Tunlar soni (ixtiyoriy, default: 1)

    Returns:
        200: Muvaffaqiyatli check-in + tayinlangan xona ma'lumotlari
        400: Validatsiya xatosi
        404: Mos xona topilmadi
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Noto'g'ri JSON formati"}, status=400)

    guest_name = data.get("guest_name", "").strip()
    room_type_str = data.get("room_type", "").strip().lower()
    floor_pref = data.get("floor_preference")
    near_elev = data.get("near_elevator", False)
    nights = data.get("nights", 1)

    # KIRITISHNI TEKSHIRISH (Input Validation)
    if not guest_name:
        return web.json_response({"error": "Mehmon ismi kiritilishi shart"}, status=400)

    if len(guest_name) > 100:
        return web.json_response({"error": "Ism juda uzun (max 100)"}, status=400)

    # Xavfsizlik: faqat harflar, bo'shliqlar va asosiy belgilar
    if not re.match(r"^[a-zA-Z\u0400-\u04FF\u0600-\u06FF\s'.\\-]{1,100}$", guest_name):
        return web.json_response({"error": "Ism faqat harflar va bo'shliqdan iborat bo'lishi kerak"}, status=400)

    # Xona turini tekshirish
    try:
        room_type = RoomType(room_type_str)
    except ValueError:
        valid_types = [t.value for t in RoomType]
        return web.json_response(
            {"error": f"Noto'g'ri xona turi. Mavjud: {valid_types}"},
            status=400
        )

    # Qavat raqamini tekshirish
    if floor_pref is not None:
        try:
            floor_pref = int(floor_pref)
            if floor_pref < 1 or floor_pref > 2:
                return web.json_response(
                    {"error": "Qavat 1 yoki 2 bo'lishi kerak"},
                    status=400
                )
        except (ValueError, TypeError):
            return web.json_response({"error": "Noto'g'ri qavat raqami"}, status=400)

    # Xona tayinlash algoritmi
    assigned_room = assign_room(room_type, floor_pref, near_elev)

    if assigned_room is None:
        # TS-07: Xona topilmasa
        alternatives = [r for r in rooms if r.status == RoomStatus.CLEAN and r.room_type != room_type]
        alt_types = list(set(r.room_type.value for r in alternatives))
        return web.json_response({
            "error": f"'{room_type.value}' turidagi xonalar mavjud emas",
            "alternatives": alt_types if alt_types else None,
            "suggestion": "Boshqa xona turini sinab ko'ring yoki kutish ro'yxatiga qo'shiling"
        }, status=404)

    # Xonani band qilish
    assigned_room.status = RoomStatus.OCCUPIED
    assigned_room.guest_name = guest_name

    # Mehmon yozuvini yaratish
    guest = Guest(
        name=guest_name,
        room_number=assigned_room.number,
        check_in_time=datetime.now(),
        room_type_requested=room_type,
        floor_preference=floor_pref,
        near_elevator=near_elev,
        nights=nights,
    )
    guests[guest_name] = guest

    # Hodisa nashr etish
    await broker.publish("guest.checked_in", {
        "guest_name": guest_name,
        "room_number": assigned_room.number,
        "room_type": room_type.value,
        "floor": assigned_room.floor,
    })

    logger.info(f"CHECK-IN: {guest_name} -> Xona {assigned_room.number} ({room_type.value}, {assigned_room.floor}-qavat)")

    return web.json_response({
        "message": f"Muvaffaqiyatli check-in!",
        "guest": guest_name,
        "room": assigned_room.to_dict(),
    })


async def handle_check_out(request: web.Request) -> web.Response:
    """
    POST /check-out
    Mehmon check-out — hisob-kitob + xona bo'shatish.
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Noto'g'ri JSON formati"}, status=400)

    room_number = data.get("room_number")

    # Kiritish tekshiruvi
    if room_number is None:
        return web.json_response({"error": "Xona raqami kiritilishi shart"}, status=400)

    try:
        room_number = int(room_number)
    except (ValueError, TypeError):
        return web.json_response({"error": "Noto'g'ri xona raqami formati"}, status=400)

    # Xonani topish
    room = None
    for r in rooms:
        if r.number == room_number:
            room = r
            break

    if room is None:
        return web.json_response({"error": f"Xona {room_number} topilmadi"}, status=404)

    if room.status != RoomStatus.OCCUPIED:
        return web.json_response(
            {"error": f"Xona {room_number} hozir band emas (holat: {room.status.value})"},
            status=400
        )

    # Mehmonni topish
    guest = None
    for g_name, g in guests.items():
        if g.room_number == room_number:
            guest = g
            break

    if guest is None:
        return web.json_response({"error": f"Xona {room_number}da mehmon topilmadi"}, status=404)

    # HISOB-KITOB ALGORITMI
    bill = calculate_bill(guest, room)

    # Xona holatini o'zgartirish
    room.status = RoomStatus.DIRTY
    room.guest_name = None
    room.clean_since = None

    # Mehmonni o'chirish
    guest.room_number = None
    del guests[guest.name]

    # Hodisa nashr etish — Tozalash servisi oladi
    await broker.publish("guest.checked_out", {
        "guest_name": guest.name,
        "room_number": room_number,
        "bill": bill,
    })

    # Room vacated hodisasi — Tozalash uchun maxsus
    await broker.publish("room.vacated", {
        "room_number": room_number,
    })

    logger.info(f"CHECK-OUT: {guest.name} <- Xona {room_number} | Jami: ${bill['total']:.2f}")

    return web.json_response({
        "message": "Muvaffaqiyatli check-out!",
        "bill": bill,
    })


async def handle_get_rooms(request: web.Request) -> web.Response:
    """GET /rooms — Barcha xonalar holati."""
    return web.json_response({
        "rooms": [r.to_dict() for r in rooms],
        "summary": {
            "total": len(rooms),
            "clean": sum(1 for r in rooms if r.status == RoomStatus.CLEAN),
            "occupied": sum(1 for r in rooms if r.status == RoomStatus.OCCUPIED),
            "dirty": sum(1 for r in rooms if r.status == RoomStatus.DIRTY),
            "cleaning": sum(1 for r in rooms if r.status == RoomStatus.CLEANING),
            "maintenance": sum(1 for r in rooms if r.status == RoomStatus.MAINTENANCE),
        }
    })


async def handle_get_guests(request: web.Request) -> web.Response:
    """GET /guests — Joriy mehmonlar."""
    return web.json_response({
        "guests": {name: g.to_dict() for name, g in guests.items()},
        "count": len(guests),
    })


# ═══════════════════════════════════════════════════════
# SERVER SETUP
# ═══════════════════════════════════════════════════════

async def start_broker(app):
    """Server boshlanganda broker'ga ulanish."""
    global broker
    broker = MessageBroker("reception")
    await broker.connect()

    # Obunalar
    broker.subscribe("room.cleaned", handle_room_cleaned)
    broker.subscribe("order.delivered", handle_order_delivered)
    broker.subscribe("maintenance.resolved", handle_maintenance_resolved)

    await broker.start_listening()


async def stop_broker(app):
    """Server to'xtaganda broker'ni yopish."""
    if broker:
        await broker.disconnect()


def create_app() -> web.Application:
    """Aiohttp application yaratish."""
    app = web.Application()

    # Routes
    app.router.add_post("/check-in", handle_check_in)
    app.router.add_post("/check-out", handle_check_out)
    app.router.add_get("/rooms", handle_get_rooms)
    app.router.add_get("/guests", handle_get_guests)

    # Lifecycle
    app.on_startup.append(start_broker)
    app.on_cleanup.append(stop_broker)

    return app


if __name__ == "__main__":
    initialize_rooms()
    app = create_app()
    logger.info("Reception Service ishga tushmoqda: http://localhost:8001")
    web.run_app(app, host="0.0.0.0", port=8001, print=None)
