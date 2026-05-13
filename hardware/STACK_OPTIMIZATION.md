# SNIN Full Stack — Platform Optimization & Gap Analysis

**Дата:** 2026-05-13  
**Репозитории:** snin → relay-v2 → p2p-agent-mesh  

---

## 1. Текущий стек (что уже есть)

```
┌──────────────────────────────────────────────────┐
│  APPLICATION LAYER                                │
│  Sensor read / DAO vote / Display render          │
├──────────────────────────────────────────────────┤
│  AGENT LAYER                                      │
│  AgentMesh (p2p-agent-mesh)                       │
│  AgentSDK (emit/listen/capabilities)              │
├──────────────────────────────────────────────────┤
│  TRANSPORT LAYER  (sdk/transport.py)              │
│  TCP  │  HTTP  │  IPFS  │  ESP-NOW  │  Serial     │
├──────────────────────────────────────────────────┤
│  CRYPTO LAYER                                     │
│  Ed25519 (ucrypto / cryptography)                │
│  Sequence nonce / Anti-replay                     │
├──────────────────────────────────────────────────┤
│  STORAGE LAYER                                    │
│  WAL (SPIFFS / SQLite / JSON files)              │
│  Merkle sync (depin/merkle_sync.py)              │
├──────────────────────────────────────────────────┤
│  PROTOCOL LAYER                                   │
│  relay-v2 (Nostr kinds 31000-31002)              │
│  Device Registry (kind:31001)                    │
│  Device Telemetry (kind:31000)                   │
│  Device Command (kind:31002)                     │
├──────────────────────────────────────────────────┤
│  HARDWARE ADAPTERS                                │
│  ESP32 (MicroPython)          ✅                   │
│  Arduino/ESP8266 (C++)       ✅                   │
│  Raspberry Pi (Python)       ✅                   │
│  Display devices             ✅                   │
└──────────────────────────────────────────────────┘
```

---

## 2. GAP-анализ: чего нет, но нужно

### 2.1 Communication Gaps (отсутствующие транспорты)

| Транспорт | Нужен для | Приоритет | Сложность |
|-----------|-----------|-----------|-----------|
| **LoRa/LoRaWAN** | Дальняя связь >2km (поле, лес) | P1 | Средняя (SPI + SX1278) |
| **BLE** | Wearables, T-Watch, телефоны рядом | P1 | Низкая (встроен в ESP32) |
| **Zigbee/Thread/Matter** | Smart Home, ESP32-C6 | P2 | Средняя |
| **CAN bus** | Автомобили, промышленность | P3 | Высокая (MCP2515) |
| **NFC** | Tap-to-pair, идентификация | P3 | Низкая (PN532) |
| **LR-WPAN (6LoWPAN)** | IPv6 over IEEE 802.15.4 | P4 | Высокая |
| **Sigfox** | Ultra-low power, 10km | P4 | Средняя (RCZ1-4) |

### 2.2 Protocol Gaps (отсутствующие kinds в relay-v2)

| Kind | Описание | Статус |
|------|----------|--------|
| 31000 | Device Telemetry | ✅ готов |
| 31001 | Device Registration | ✅ готов |
| 31002 | Device Command (DAO→ESP32) | ⚠️ bridge не слушает |
| 31003 | Device OTA Update | ❌ нет |
| 31004 | Device Logs | ❌ нет |
| 31005 | Device Config | ❌ нет |
| 31006 | Device Location (GPS) | ❌ нет |
| 31007 | Device Alert | ❌ нет |
| 31008 | Device Pairing Request | ❌ нет |
| 31009 | Device Heartbeat | ❌ нет |

### 2.3 Infrastructure Gaps

| Компонент | Зачем | Приоритет |
|-----------|-------|-----------|
| **mDNS Discovery** | Авто-поиск ESP32 в сети | P1 |
| **OTA Update Server** | Обновление прошивок по воздуху | P1 |
| **Power Manager** | Батарея/солнце/deep sleep | P1 |
| **GPS Tracker** | Привязка ESP32 к координатам | P2 |
| **Task Scheduler** | Распределение задач между агентами | P2 |
| **Metrics/Telemetry API** | Сбор метрик со всего роя | P2 |
| **Log Collector** | Централизованные логи | P3 |
| **Watchdog Timer** | Авто-перезагрузка при зависании | P3 |

---

## 3. Оптимизированный стек по платформам

### 3.1 ESP32-S3 (основной датчик)

```
Роль: Sensor Node
Текущий:   MicroPython + ESP-NOW + DHT22
Оптимум:   MicroPython + ESP-NOW + DHT22/BME280
           + LoRa (SX1278) — для поля/улицы
           + BLE — для локального сброса данных на телефон
           + Deep Sleep — батарея на 6 мес
           + mDNS — авто-поиск bridge
```

### 3.2 ESP32-C6 (новый стандарт)

```
Роль: Lite Agent / Border Router
Стек:  MicroPython + Thread + Matter
       + ESP-NOW (обратная совместимость)
       + BLE (commissioning)
Идея:  Thread = IPv6 mesh для умного дома
       Matter = стандарт для Home Assistant / Apple / Google
       ESP32-C6 = Thread + WiFi + BLE на одном чипе
```

### 3.3 ESP8266 (бюджетный датчик)

```
Роль: Ultra-cheap Sensor ($1.5)
Стек: C++ (Arduino) + ESP-NOW + DHT22
       НЕТ: Ed25519 (слишком много RAM)
       Вместо: HMAC-SHA256 (меньше, но совместимо)
       НЕТ: TCP напрямую (только через bridge)
       Не может: deep sleep с сохранением WiFi
```

### 3.4 Arduino R4 (образовательный)

```
Роль: Learning / Prototype
Стек: C++ + WiFi + Serial
       НЕТ: ESP-NOW (нет поддержки)
       Да:  LED Matrix (можно отображать статус роя)
       Да:  Ed25519 (32KB RAM хватает)
       НЕТ: Deep sleep
```

### 3.5 Raspberry Pi 4/5 (хаб)

```
Роль: Hub / Full Node
Стек: Python + p2p-agent-mesh full
       + relay-v2 (Nostr relay)
       + SQLite (WAL + база устройств)
       + GPIO (датчики напрямую)
       + HDMI (dashboard)
       + Docker (для изоляции)
       + LoRaWAN Gateway (SX130x) — приём от LoRa-ESP32
```

### 3.6 Raspberry Pi Zero 2W (портативный)

```
Роль: Portable Agent / Field Bridge
Стек: Python + AgentMesh + HTTP transport
       + USB-ESP32 (ESP-NOW bridge)
       + GPS HAT (трекинг)
       + Waveshare e-Ink (дисплей, low power)
       + LiPo battery (портативный)
```

### 3.7 M5Stack / TTGO T-Display (терминал)

```
Роль: DAO Terminal / Status Display
Стек: MicroPython + TFT + ESP-NOW
       + framebuf (рендеринг)
       + Кнопки (голосование Да/Нет)
       + Батарея (автономный)
       + BLE (push-уведомления от телефона)
```

### 3.8 LilyGO T-Watch (носимый)

```
Роль: Wearable DAO Terminal
Стек: MicroPython + LCD (240x240) + BLE
       + ESP-NOW (приём телеметрии с сенсоров)
       + Вибрация (уведомления о голосованиях)
       + GPS (трекинг положения)
       + Акселерометр (жесты)
```

### 3.9 ESP32 + Camera (OV2640)

```
Роль: Vision Agent
Стек: MicroPython + Camera + ESP-NOW/TCP
       + JPEG capture (QVGA — 320x240)
       + Edge AI (TensorFlow Lite Micro — цифры/текст)
       + Отправка изображения на bridge → relay-v2
       Kind: 31000 + base64 thumbnail (≤10KB)
```

### 3.10 LoRa ESP32 (SX1278 / SX1262)

```
Роль: Long Range Sensor
Стек: MicroPython + LoRa (SPI) + ESP-NOW
       Дальность: 2-15km (прямая видимость)
       Скорость: 300 bps — 37.5 kbps
       Пакет: ≤ 64 байт (LoRa) → fragmentation
       Использование: датчики в поле, лес, горы
       Bridge: через LoRaWAN Gateway на RPi
```

---

## 4. Сводка: какие модули связи нужны

| Модуль связи | Уже есть | Нужно добавить | Библиотека |
|-------------|----------|----------------|------------|
| WiFi TCP | ✅ | — | встроен |
| ESP-NOW | ✅ | — | встроен |
| HTTP | ✅ | — | urequests |
| IPFS | ✅ | — | p2p-agent-mesh |
| Serial UART | ✅ | — | встроен |
| **LoRa** | ❌ | **SPI driver + packet fragmentation** | micropython-lora / SX127x |
| **BLE** | ❌ | **GATT service + advertising** | bluetooth (ESP32) |
| **Thread/Matter** | ❌ | **OTBR + py-thread** | ESP32-C6 only |
| **CAN bus** | ❌ | **MCP2515 driver** | micropython-mcp2515 |
| **NFC** | ❌ | **PN532 I2C** | micropython-pn532 |
| **Ethernet** | ⚠️ | **LAN8720 on ESP32** | network.LAN |
| **4G/LTE** | ❌ | **AT commands over UART** | SIM800/SIM7600 |

---

## 5. Реальный план: что добавить в первую очередь

По приоритету (проверено на практике, а не в теории):

```
P1 — LoRa + BLE
  Зачем: 70% use-cases требуют или дальше 200м, или связь с телефоном
  Код:   ~500 строк на модуль, ~2 дня на каждый

P2 — OTA Update + mDNS Discovery
  Зачем: без OTA прошивка на ESP32 устареет за неделю
         без mDNS пользователь не найдёт bridge в сети
  Код:   ~300 строк

P3 — Device Command Loop (kind:31002)
  Зачем: замкнуть цикл: DAO проголосовал → ESP32 получил команду
  Код:   ~200 строк (bridge подписывается на mesh topic)

P4 — GPS Tracker + Task Scheduler
  Зачем: привязать телеметрию к координатам
         распределять задачи между агентами
  Код:   ~400 строк

P5 — CAM + Edge AI
  Зачем: визуальные агенты (счётчик людей, QR, текст)
  Код:   ~600 строк
```

---

## 6. Итоговая карта: полный стек SNIN

```
                    ┌─────────────────────┐
                    │       DAO LAYER      │
                    │  Proposal / Vote /   │
                    │  Treasury / Roles    │
                    └──────┬──────────────┘
                           │ kind:39002-39003
                    ┌──────▼──────────────┐
                    │    RELAY-V2 LAYER    │
                    │  Nostr kinds 31000-  │
                    │  31009 + 39000-      │
                    │  39099               │
                    └──────┬──────────────┘
                           │ AgentMesh.emit()
                    ┌──────▼──────────────┐
                    │   AGENT MESH LAYER   │
                    │  p2p-agent-mesh v0.5 │
                    │  Transport, Registry │
                    │  Raft, Dedup         │
                    └──────┬──────────────┘
                           │ TCP / HTTP / IPFS
                    ┌──────▼──────────────┐
                    │    BRIDGE LAYER      │
                    │  bridge.py + WAL     │
                    │  Ed25519 verify      │
                    └──────┬──────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
┌─────────────┐   ┌──────────────┐   ┌──────────────┐
│  ESP-NOW    │   │    TCP/IP    │   │    LoRa      │
│  ~200m      │   │  Full stack  │   │  ~15km       │
│  250B pkt   │   │  No limit    │   │  64B pkt     │
├─────────────┤   ├──────────────┤   ├──────────────┤
│ ESP32       │   │ RPi / Server │   │ LoRa ESP32   │
│ Arduino     │   │ M5Stack      │   │ SX1278       │
│ ESP8266     │   │ Desktop      │   │ Heltec       │
└─────────────┘   └──────────────┘   └──────────────┘
       │                                    │
       ▼                                    ▼
┌─────────────┐                    ┌──────────────┐
│    BLE      │                    │    NFC       │
│  ~10m       │                    │  Tap-to-pair  │
├─────────────┤                    ├──────────────┤
│ LilyGO Watch│                    │ Phone pairing│
│ Phone (app) │                    │ Auth         │
└─────────────┘                    └──────────────┘
```
