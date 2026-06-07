"""
HotelOS Shared Data Models
Barcha servislar uchun umumiy ma'lumotlar tuzilmalari.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from datetime import datetime
import json


# ═══════════════════════════════════════════════════════
# ENUMS - Holatlar va turlar
# ═══════════════════════════════════════════════════════

class RoomType(Enum):
    """Xona turlari."""
    SINGLE = "single"
    DOUBLE = "double"
    SUITE = "suite"
    ACCESSIBLE = "accessible"


class RoomStatus(Enum):
    """Xona holatlari."""
    CLEAN = "clean"
    DIRTY = "dirty"
    CLEANING = "cleaning"
    MAINTENANCE = "maintenance"
    OCCUPIED = "occupied"


class OrderStatus(Enum):
    """Buyurtma holatlari."""
    RECEIVED = "received"
    PREPARING = "preparing"
    DELIVERING = "delivering"
    DELIVERED = "delivered"


class MaintenancePriority(Enum):
    """Texnik xizmat ustuvorligi."""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


class MaintenanceStatus(Enum):
    """Texnik xizmat holati."""
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# ═══════════════════════════════════════════════════════
# DATA CLASSES - Ma'lumot tuzilmalari
# ═══════════════════════════════════════════════════════

@dataclass
class Room:
    """Xona ma'lumotlar tuzilmasi (Array/List uchun)."""
    number: int
    floor: int
    room_type: RoomType
    status: RoomStatus = RoomStatus.CLEAN
    clean_since: Optional[datetime] = None
    near_elevator: bool = False
    guest_name: Optional[str] = None
    price_per_night: float = 100.0

    def __post_init__(self):
        if self.clean_since is None and self.status == RoomStatus.CLEAN:
            self.clean_since = datetime.now()

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "floor": self.floor,
            "room_type": self.room_type.value,
            "status": self.status.value,
            "clean_since": self.clean_since.isoformat() if self.clean_since else None,
            "near_elevator": self.near_elevator,
            "guest_name": self.guest_name,
            "price_per_night": self.price_per_night,
        }


@dataclass
class Guest:
    """Mehmon yozuvi (Dictionary/Map uchun)."""
    name: str
    room_number: Optional[int] = None
    check_in_time: Optional[datetime] = None
    room_type_requested: RoomType = RoomType.DOUBLE
    floor_preference: Optional[int] = None
    near_elevator: bool = False
    charges: List[dict] = field(default_factory=list)
    nights: int = 1

    def total_bill(self, room_price: float) -> float:
        """Hisob-kitob algoritmi."""
        room_total = room_price * self.nights
        charges_total = sum(item.get("price", 0) for item in self.charges)
        return room_total + charges_total

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "room_number": self.room_number,
            "check_in_time": self.check_in_time.isoformat() if self.check_in_time else None,
            "room_type_requested": self.room_type_requested.value,
            "floor_preference": self.floor_preference,
            "near_elevator": self.near_elevator,
            "charges": self.charges,
            "nights": self.nights,
        }


@dataclass
class RoomServiceOrder:
    """Xona xizmati buyurtmasi (Queue/Navbat uchun)."""
    order_id: str
    room_number: int
    items: List[dict]
    status: OrderStatus = OrderStatus.RECEIVED
    created_at: datetime = field(default_factory=datetime.now)
    total_price: float = 0.0

    def __post_init__(self):
        self.total_price = sum(item.get("price", 0) * item.get("quantity", 1) for item in self.items)

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "room_number": self.room_number,
            "items": self.items,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "total_price": self.total_price,
        }


@dataclass
class MaintenanceRequest:
    """Texnik xizmat so'rovi (Priority Queue uchun)."""
    request_id: str
    room_number: int
    description: str
    priority: MaintenancePriority = MaintenancePriority.NORMAL
    status: MaintenanceStatus = MaintenanceStatus.OPEN
    assigned_to: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None

    def __lt__(self, other):
        """Priority queue uchun solishtirish (heapq talab qiladi)."""
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        return self.created_at < other.created_at

    def __eq__(self, other):
        """Tenglikni tekshirish."""
        if not isinstance(other, MaintenanceRequest):
            return False
        return self.request_id == other.request_id

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "room_number": self.room_number,
            "description": self.description,
            "priority": self.priority.value,
            "priority_name": self.priority.name,
            "status": self.status.value,
            "assigned_to": self.assigned_to,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
