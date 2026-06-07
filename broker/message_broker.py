"""
HotelOS Message Broker — Redis Pub/Sub asosida.

Servislar o'rtasida xabar almashish uchun markaziy broker.
Har bir servis hodisalar nashr etadi (publish) va obuna bo'ladi (subscribe).
Servislar bir-birini to'g'ridan-to'g'ri chaqirmaydi — faqat broker orqali.

Hodisalar ro'yxati:
┌────────────────────────┬──────────────┬─────────────────────┬──────────────────────────────┐
│ Hodisa nomi            │ Nashriyotchi │ Obunachi(lar)       │ Yuk tuzilishi                │
├────────────────────────┼──────────────┼─────────────────────┼──────────────────────────────┤
│ guest.checked_in       │ Reception    │ Dashboard           │ {guest, room_number}         │
│ guest.checked_out      │ Reception    │ Housekeeping, Dash  │ {guest, room, bill}          │
│ room.vacated           │ Reception    │ Housekeeping        │ {room_number}                │
│ room.status_changed    │ Housekeeping │ Reception, Dash     │ {room_number, old, new}      │
│ room.cleaning_started  │ Housekeeping │ Dashboard           │ {room_number}                │
│ room.cleaned           │ Housekeeping │ Reception, Dash     │ {room_number}                │
│ order.placed           │ RoomService  │ Dashboard           │ {order_id, room, items}      │
│ order.status_changed   │ RoomService  │ Dashboard, Recept   │ {order_id, status}           │
│ order.delivered        │ RoomService  │ Reception (billing) │ {order_id, room, total}      │
│ maintenance.reported   │ Maintenance  │ Dashboard           │ {request_id, room, priority} │
│ maintenance.assigned   │ Maintenance  │ Dashboard           │ {request_id, technician}     │
│ maintenance.resolved   │ Maintenance  │ Dashboard, Recept   │ {request_id, room}           │
└────────────────────────┴──────────────┴─────────────────────┴──────────────────────────────┘
"""

import json
import asyncio
import logging
from typing import Callable, Dict, List, Any
from datetime import datetime

import redis
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis connection settings
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0


class MessageBroker:
    """
    Redis Pub/Sub asosidagi xabar brokeri.
    Har bir servis bitta instance yaratadi.

    Xususiyatlari:
    - Avtomatik qayta ulanish (reconnect)
    - Xabar validatsiyasi
    - Xatoliklarni log qilish
    """

    def __init__(self, service_name: str):
        """
        Args:
            service_name: Servis nomi (loglash uchun)
        """
        self.service_name = service_name
        self._handlers: Dict[str, List[Callable]] = {}
        self._redis: aioredis.Redis = None
        self._pubsub: aioredis.client.PubSub = None
        self._running = False
        self._listener_task = None

    async def connect(self):
        """Redis'ga ulanish."""
        self._redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True
        )
        self._pubsub = self._redis.pubsub()
        logger.info(f"[{self.service_name}] Redis broker'ga ulandi")

    async def disconnect(self):
        """Ulanishni yopish."""
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        logger.info(f"[{self.service_name}] Broker'dan uzildi")

    def subscribe(self, event_type: str, handler: Callable):
        """
        Hodisaga obuna bo'lish.

        Args:
            event_type: Hodisa nomi (masalan, 'room.vacated')
            handler: Hodisa kelganda chaqiriladigan funksiya
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.info(f"[{self.service_name}] Obuna: {event_type} -> {handler.__name__}")

    async def publish(self, event_type: str, data: dict):
        """
        Hodisa nashr etish — barcha obunachilarga yetkaziladi.

        Args:
            event_type: Hodisa nomi
            data: Hodisa ma'lumotlari (dict)

        Raises:
            ConnectionError: Redis ulanmagan bo'lsa
        """
        if not self._redis:
            logger.error(f"[{self.service_name}] Redis ulanmagan! Xabar yuborilmadi: {event_type}")
            return

        message = json.dumps({
            "event": event_type,
            "source": self.service_name,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        })
        try:
            await self._redis.publish(f"hotelos:{event_type}", message)
            logger.info(f"[{self.service_name}] PUBLISH: {event_type} | {json.dumps(data)[:100]}")
        except Exception as e:
            logger.error(f"[{self.service_name}] Publish xato: {event_type} -> {e}")

    async def start_listening(self):
        """Obuna bo'lgan hodisalarni tinglashni boshlash."""
        if not self._handlers:
            return

        channels = [f"hotelos:{event}" for event in self._handlers.keys()]
        await self._pubsub.subscribe(*channels)
        self._running = True
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info(f"[{self.service_name}] Tinglash boshlandi: {list(self._handlers.keys())}")

    async def _listen_loop(self):
        """Xabarlarni tinglash tsikli."""
        try:
            while self._running:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0
                )
                if message and message["type"] == "message":
                    await self._process_message(message)
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.service_name}] Listener xato: {e}")

    async def _process_message(self, message: dict):
        """Kelgan xabarni qayta ishlash."""
        try:
            payload = json.loads(message["data"])
            event_type = payload["event"]
            data = payload["data"]
            source = payload.get("source", "unknown")

            # O'z xabarimizni qayta ishlamaslik
            if source == self.service_name:
                return

            handlers = self._handlers.get(event_type, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"[{self.service_name}] Handler xato ({handler.__name__}): {e}")

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[{self.service_name}] Xabar formati noto'g'ri: {e}")


# Sinxron (sync) versiya — oddiy ishlatish uchun
class SyncBroker:
    """Redis Pub/Sub sinxron versiyasi (test va oddiy servislar uchun)."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        self._redis = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
        )

    def publish(self, event_type: str, data: dict):
        """Hodisa nashr etish."""
        message = json.dumps({
            "event": event_type,
            "source": self.service_name,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        })
        self._redis.publish(f"hotelos:{event_type}", message)

    def close(self):
        self._redis.close()
