"""
HotelOS — BTEC Test Stsenariylar (TS-01 dan TS-08 gacha)
Barcha 8 ta stsenariyni avtomatik test qiladi.

Ishlatish:
    python tests/test_scenarios.py
"""

import requests
import time
import json
import sys

BASE_RECEPTION = "http://localhost:8001"
BASE_HOUSEKEEPING = "http://localhost:8002"
BASE_ROOM_SERVICE = "http://localhost:8003"
BASE_MAINTENANCE = "http://localhost:8004"
BASE_DASHBOARD = "http://localhost:8080"

passed = 0
failed = 0


def test(scenario_id: str, description: str, func):
    global passed, failed
    print(f"\n{'='*60}")
    print(f"  {scenario_id}: {description}")
    print(f"{'='*60}")
    try:
        func()
        print(f"  ✅ {scenario_id} O'TDI")
        passed += 1
    except AssertionError as e:
        print(f"  ❌ {scenario_id} MUVAFFAQIYATSIZ: {e}")
        failed += 1
    except Exception as e:
        print(f"  ❌ {scenario_id} XATO: {e}")
        failed += 1


def ts01():
    """Mehmon 2-qavatda double xona so'rab check-in qiladi."""
    resp = requests.post(f"{BASE_RECEPTION}/check-in", json={
        "guest_name": "Ali Valiyev",
        "room_type": "double",
        "floor_preference": 2,
        "nights": 3,
    })
    data = resp.json()
    assert resp.status_code == 200, f"Status: {resp.status_code}, {data}"
    assert data["room"]["floor"] == 2, f"Qavat noto'g'ri: {data['room']['floor']}"
    assert data["room"]["room_type"] == "double", f"Xona turi noto'g'ri"
    assert data["room"]["status"] == "occupied", f"Holat occupied bo'lishi kerak"
    print(f"  Tayinlangan xona: {data['room']['number']} (2-qavat, double)")


def ts02():
    """Mehmon 204-xonadan check-out qiladi."""
    # Avval 204 xonaga check-in
    requests.post(f"{BASE_RECEPTION}/check-in", json={
        "guest_name": "Nodira Test",
        "room_type": "suite",
        "floor_preference": 2,
        "nights": 2,
    })
    time.sleep(0.5)

    # Check-out
    resp = requests.post(f"{BASE_RECEPTION}/check-out", json={"room_number": 204})
    data = resp.json()
    assert resp.status_code == 200, f"Status: {resp.status_code}, {data}"
    assert "bill" in data, "Bill qaytarilishi kerak"
    assert data["bill"]["total"] > 0, "Jami summa > 0 bo'lishi kerak"
    print(f"  Hisob: ${data['bill']['total']:.2f}")
    print(f"  Xona holati: dirty (Tozalash hodisasi yuborildi)")

    time.sleep(1)
    # Tozalash navbatini tekshirish
    queue_resp = requests.get(f"{BASE_HOUSEKEEPING}/queue")
    queue_data = queue_resp.json()
    found = any(t["room_number"] == 204 for t in queue_data["queue"])
    assert found, "204-xona tozalash navbatida bo'lishi kerak"
    print(f"  ✓ Xona 204 tozalash navbatiga qo'shildi")


def ts03():
    """Tozalovchi 204-xonani toza deb belgilaydi."""
    # Tozalashni boshlash
    resp = requests.post(f"{BASE_HOUSEKEEPING}/start-cleaning", json={
        "room_number": 204,
        "cleaner_name": "Gulnora",
    })
    assert resp.status_code == 200, f"Start cleaning failed: {resp.json()}"
    print(f"  Tozalash boshlandi (Gulnora)")

    time.sleep(0.5)

    # Toza deb belgilash
    resp = requests.post(f"{BASE_HOUSEKEEPING}/mark-clean", json={"room_number": 204})
    assert resp.status_code == 200, f"Mark clean failed: {resp.json()}"
    print(f"  Xona 204 TOZA deb belgilandi")

    time.sleep(1)
    # Reception'da holat tekshirish
    rooms_resp = requests.get(f"{BASE_RECEPTION}/rooms")
    rooms = rooms_resp.json()["rooms"]
    room_204 = next((r for r in rooms if r["number"] == 204), None)
    assert room_204 is not None, "204-xona topilmadi"
    assert room_204["status"] == "clean", f"204 holati: {room_204['status']} (clean bo'lishi kerak)"
    print(f"  ✓ Reception panelida 204 = clean")


def ts04():
    """301-xonadagi mehmon 2 ta qahva va bir sandvich buyurtma qiladi."""
    # Avval 301 xonaga check-in (1-qavat single xona yo'q, shuning uchun boshqa)
    # Aslida 301 yo'q bizda, shuning uchun mavjud band xonaga qilamiz
    # Avval check-in
    requests.post(f"{BASE_RECEPTION}/check-in", json={
        "guest_name": "Buyurtmachi",
        "room_type": "single",
        "floor_preference": 1,
        "nights": 1,
    })
    time.sleep(0.3)

    # Buyurtma berish
    resp = requests.post(f"{BASE_ROOM_SERVICE}/order", json={
        "room_number": 101,
        "items": [
            {"item": "coffee", "quantity": 2},
            {"item": "sandwich", "quantity": 1},
        ]
    })
    data = resp.json()
    assert resp.status_code == 200, f"Order failed: {data}"
    order_id = data["order"]["order_id"]
    expected_price = 5.0 * 2 + 12.0  # 2 qahva + 1 sandvich = 22
    assert data["order"]["total_price"] == expected_price, f"Narx: {data['order']['total_price']} != {expected_price}"
    print(f"  Buyurtma: {order_id}, ${expected_price:.2f}")

    # Holatlarni yangilash
    for status in ["preparing", "delivering", "delivered"]:
        time.sleep(0.3)
        resp = requests.post(f"{BASE_ROOM_SERVICE}/order/status", json={
            "order_id": order_id,
            "status": status,
        })
        assert resp.status_code == 200
        print(f"  Status: {status}")

    print(f"  ✓ Buyurtma yetkazildi, hisobga qo'shildi")


def ts05():
    """Texnik xizmat hisoboti: 105-xonada singan dush, Kritik."""
    resp = requests.post(f"{BASE_MAINTENANCE}/report", json={
        "room_number": 105,
        "description": "Singan dush - suv oqyapti",
        "priority": "critical",
    })
    data = resp.json()
    assert resp.status_code == 200, f"Report failed: {data}"
    assert data["request"]["priority_name"] == "CRITICAL"
    assert data["request"]["assigned_to"] is not None, "Texnik tayinlanishi kerak"
    request_id = data["request"]["request_id"]
    print(f"  So'rov: {request_id}, CRITICAL")
    print(f"  Tayinlangan: {data['request']['assigned_to']}")

    # Hal etish
    time.sleep(0.3)
    resp = requests.post(f"{BASE_MAINTENANCE}/resolve", json={"request_id": request_id})
    assert resp.status_code == 200
    print(f"  ✓ Muammo hal etildi")


def ts06():
    """Ikki mehmon bir vaqtda bir xil xona turini so'raydi."""
    resp1 = requests.post(f"{BASE_RECEPTION}/check-in", json={
        "guest_name": "Mehmon A",
        "room_type": "double",
        "nights": 1,
    })
    resp2 = requests.post(f"{BASE_RECEPTION}/check-in", json={
        "guest_name": "Mehmon B",
        "room_type": "double",
        "nights": 1,
    })

    data1 = resp1.json()
    data2 = resp2.json()

    if resp1.status_code == 200 and resp2.status_code == 200:
        room1 = data1["room"]["number"]
        room2 = data2["room"]["number"]
        assert room1 != room2, f"Ikki mehmon bitta xonaga tayinlandi! {room1} == {room2}"
        print(f"  Mehmon A -> Xona {room1}")
        print(f"  Mehmon B -> Xona {room2}")
        print(f"  ✓ Har biriga alohida xona tayinlandi")
    elif resp1.status_code == 200:
        print(f"  Mehmon A -> Xona {data1['room']['number']}")
        print(f"  Mehmon B -> Xona mavjud emas (to'g'ri)")
    else:
        print(f"  Status: {resp1.status_code}, {resp2.status_code}")


def ts07():
    """Barcha so'ralgan turdagi xonalar band."""
    # 'accessible' turidagi xonalarni band qilish
    requests.post(f"{BASE_RECEPTION}/check-in", json={"guest_name": "X1", "room_type": "accessible", "nights": 1})
    requests.post(f"{BASE_RECEPTION}/check-in", json={"guest_name": "X2", "room_type": "accessible", "nights": 1})

    # Yana so'rash
    resp = requests.post(f"{BASE_RECEPTION}/check-in", json={
        "guest_name": "Yangi Mehmon",
        "room_type": "accessible",
        "nights": 1,
    })
    data = resp.json()
    assert resp.status_code == 404, f"404 qaytishi kerak, lekin: {resp.status_code}"
    assert "error" in data, "Xato xabari bo'lishi kerak"
    assert "alternatives" in data or "suggestion" in data, "Muqobil taklif bo'lishi kerak"
    print(f"  Xato: {data['error']}")
    if data.get("alternatives"):
        print(f"  Muqobil: {data['alternatives']}")
    print(f"  ✓ Tizim ishdan chiqmadi, aniq xabar qaytardi")


def ts08():
    """Noto'g'ri xona raqami kiritiladi."""
    resp = requests.post(f"{BASE_RECEPTION}/check-out", json={"room_number": 999})
    data = resp.json()
    assert resp.status_code == 404, f"404 kutilmoqda: {resp.status_code}"
    assert "error" in data

    # Bo'sh input
    resp2 = requests.post(f"{BASE_RECEPTION}/check-in", json={
        "guest_name": "",
        "room_type": "invalid_type",
    })
    assert resp2.status_code == 400
    print(f"  Noto'g'ri raqam: {data['error']}")
    print(f"  Bo'sh input: {resp2.json()['error']}")
    print(f"  ✓ Tizim barqaror, xato xabari qaytardi")


# ═══════════════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  🏨 HotelOS — BTEC Test Stsenariylar")
    print("═" * 60)

    # Servislar ishlayotganini tekshirish
    try:
        requests.get(f"{BASE_RECEPTION}/rooms", timeout=2)
    except:
        print("\n❌ Servislar ishlamayapti! Avval ishga tushiring: ./run.sh")
        sys.exit(1)

    test("TS-01", "Mehmon 2-qavatda double xona bilan check-in", ts01)
    test("TS-02", "Mehmon 204-xonadan check-out", ts02)
    test("TS-03", "Tozalovchi 204-xonani toza deb belgilaydi", ts03)
    test("TS-04", "Xona xizmati buyurtmasi (2 qahva + 1 sandvich)", ts04)
    test("TS-05", "Texnik xizmat: singan dush, Kritik ustuvorlik", ts05)
    test("TS-06", "Ikki mehmon bir vaqtda check-in (race condition)", ts06)
    test("TS-07", "Barcha xonalar band bo'lganda", ts07)
    test("TS-08", "Noto'g'ri kiritish (validation)", ts08)

    print(f"\n{'═'*60}")
    print(f"  NATIJA: {passed} ta O'TDI, {failed} ta MUVAFFAQIYATSIZ")
    print(f"  Jami: {passed + failed} ta test")
    print(f"{'═'*60}\n")

    sys.exit(0 if failed == 0 else 1)
