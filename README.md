# HotelOS — Real Vaqtli Mehmonxona Boshqaruv Tizimi

Mikroservislar arxitekturasi, Redis Pub/Sub xabar brokeri va WebSocket real-time dashboard bilan qurilgan mehmonxona boshqaruv tizimi.

## Arxitektura

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  Reception   │────▶│  Redis Pub/Sub  │◀────│  Housekeeping    │
│  Service     │     │  (Message       │     │  Service         │
│  :8001       │     │   Broker)       │     │  :8002           │
└──────────────┘     └────────┬────────┘     └──────────────────┘
                              │
┌──────────────┐              │              ┌──────────────────┐
│  Room        │──────────────┘──────────────│  Maintenance     │
│  Service     │                             │  Service         │
│  :8003       │                             │  :8004           │
└──────────────┘                             └──────────────────┘
                              │
                     ┌────────▼────────┐
                     │   Dashboard     │
                     │  (WebSocket)    │
                     │   :8080         │
                     └─────────────────┘
```

## Tez ishga tushirish

```bash
# 1. Redis o'rnatish va ishga tushirish
brew install redis
redis-server --daemonize yes

# 2. HotelOS ishga tushirish (bitta buyruq!)
./run.sh

# 3. Ngrok bilan (ixtiyoriy)
./run.sh --ngrok
```

## Texnologiya Steki

- **Til:** Python 3.12
- **Framework:** aiohttp (async HTTP server)
- **Xabar Brokeri:** Redis Pub/Sub
- **WebSocket:** aiohttp WebSocket
- **Ma'lumot tuzilmalari:** List (xona inventar), Dict (mehmonlar), Queue/Deque (navbat), Heap (priority queue)

## Servislar

| Servis | Port | Vazifasi |
|--------|------|----------|
| Reception | 8001 | Check-in/out, xona tayinlash, hisob-kitob |
| Housekeeping | 8002 | Tozalash navbati, xona holati |
| Room Service | 8003 | Ovqat buyurtmalari, yetkazish |
| Maintenance | 8004 | Texnik muammolar, ustuvorlik navbat |
| Dashboard | 8080 | WebSocket real-time panel |

## API Endpointlar

### Reception Service (:8001)
```
POST /check-in    - Mehmon check-in
POST /check-out   - Mehmon check-out + hisob-kitob
GET  /rooms       - Barcha xonalar holati
GET  /guests      - Joriy mehmonlar
```

### Housekeeping Service (:8002)
```
GET  /queue           - Tozalash navbati
POST /start-cleaning  - Tozalashni boshlash
POST /mark-clean      - Toza deb belgilash
GET  /history         - Tarix
```

### Room Service (:8003)
```
GET  /menu          - Menyu
POST /order         - Buyurtma berish
POST /order/status  - Holat yangilash
GET  /orders        - Barcha buyurtmalar
```

### Maintenance Service (:8004)
```
POST /report    - Muammo hisobot qilish
POST /resolve   - Muammoni hal etish
GET  /requests  - Barcha so'rovlar
GET  /queue     - Ustuvorlik navbati
```

## Test Stsenariylar

```bash
python tests/test_scenarios.py
```

Barcha 8 ta BTEC test stsenariysi (TS-01 — TS-08) qo'llab-quvvatlanadi.

## Loyiha Tuzilmasi

```
HotelOS/
├── services/
│   ├── reception/service.py      # Qabul Servisi
│   ├── housekeeping/service.py   # Tozalash Servisi
│   ├── room_service/service.py   # Xona Xizmati Servisi
│   └── maintenance/service.py    # Texnik Xizmat Servisi
├── broker/
│   └── message_broker.py         # Redis Pub/Sub broker
├── dashboard/
│   └── server.py                 # WebSocket Dashboard
├── shared/
│   └── models.py                 # Umumiy ma'lumot modellari
├── tests/
│   └── test_scenarios.py         # BTEC test stsenariylar
├── requirements.txt
├── run.sh                        # Ishga tushirish scripti
└── README.md
```

## Git Log

```
git log --oneline
```
