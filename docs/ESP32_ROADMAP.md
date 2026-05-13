# SNIN → ESP32 P2P Mesh + DAO Swarm
## Полная дорожная карта от текущего кода до роя физических агентов

**Дата:** 2026-05-13
**Репозитории:** konantgit-sys/relay-v2, p2p-agent-mesh, snin
**Архитектор:** Юрий Писаренко (@ayupro)

---

## Текущее состояние (v0 — что уже есть)

```
relay-v2 (Nostr relay, 21 NIP, DAO)
    ↓ SSE transport + IPFS PubSub
p2p-agent-mesh v0.5.0 (133 тестов)
    ├── transport    — TCP/IPFS PubSub
    ├── identity     — Ed25519 + DID did:snin:
    ├── wal          — SQLite Write-Ahead Log
    ├── sig_gate     — rate limit 10/сек
    ├── dht          — K=3 репликация
    ├── depin        — DePIN SDK (device.py, registry.py, merkle_sync.py)
    │   └── DevicePipeline + WAL (уже есть!)
    ├── coordination — Micro-Raft, Consumer Groups, Exactly-once Dedup
    ├── relay        — HTTP relay + WS relay (для NAT traversal)
    ├── pilot        — 3-агентная цепочка Cryter→Forecaster→Creator
    └── adapters     — LangGraph, CrewAI, AutoGen
```

**Уже работает:** TCP transport между агентами, E2E шифрование (X25519 + ChaCha20-Poly1305), WAL-буферизация при offline, Device Registry в DHT, Relay для NAT traversal.

**Критично для ESP32:** Весь код на Python. IPFS требует 1.2 GB RAM. Но **DePIN SDK** уже спроектирован так, будто ESP32 ожидается — device_id, telemetry publish, Merkle sync.

---

## Фаза 0.5 — Transport Abstraction (сейчас → 1 неделя)

**Цель:** Сделать transport слоем, а не IPFS-монолитом. ESP32 не тянет IPFS.

### Что сделать в коде p2p-agent-mesh

| Файл | Что изменить |
|------|-------------|
| `phase0/transport.py` | Выделить абстрактный класс `Transport(ABC)` с методами `publish()`, `subscribe()`, `peers()` |
| `phase0/ipfs_transport.py` | Переименовать текущий IPFS PubSub в `IPFSTransport(Transport)` |
| `phase0/tcp_transport.py` | TCP transport уже есть — оформить как `TCPTransport(Transport)` |
| `phase0/http_transport.py` | HTTP transport уже есть (`relay/http_relay.py`) — оформить как `HTTPTransport(Transport)` |
| `phase0/transport_factory.py` | Фабрика: `create_transport("ipfs")` / `"tcp"` / `"http"` / `"espnow"` |
| `test_transport_abstraction.py` | 2 теста: IPFS↔TCP, TCP↔HTTP interoperability |

**Критерий готовности:** Агент не знает какой транспорт снизу. `emit()` работает одинаково на IPFS, TCP, HTTP.

**Связь с relay-v2:** HTTPTransport форвардит в relay-v2 через `/api/message`. Relay-v2 публикует в IPFS PubSub. Mesh↔Relay bridge.

---

## Фаза 1 — ESP32-NOW Transport (1-2 недели)

**Цель:** Написать transport-адаптер для ESP-NOW. ESP32 → ESP32 без WiFi роутера.

### Что сделать

| Компонент | Описание |
|-----------|----------|
| **ESP32-A: ESP-NOW sender** | C++ (ESP-IDF) / MicroPython: читает датчик → шлёт ESP-NOW пакет (250 байт макс) |
| **ESP32-B: ESP-NOW → TCP bridge** | Второй ESP32 (или RPi) принимает ESP-NOW, форвардит в TCP transport |
| **`phase0/espnow_transport.py`** | Адаптер ESP-NOW через serial bridge (ESP32 по UART → Python) |
| **`docs/ESP32_HARDWARE.md`** | Какие модули ESP32, распиновка, прошивка |

**Ограничения ESP-NOW:**
- Пакет: макс 250 байт
- Дальность: ~200 м (без усилителя)
- Нет маршрутизации — только point-to-point
- Решение: ESP32-A шлёт `{did, seq, payload_short, signature}` на ESP32-B bridge

**Как это впишется в архитектуру:**
```
Дачик → ESP32-A → ESP-NOW (250B) → ESP32-B (bridge) → TCP → p2p-agent-mesh
                                                              ↓
                                                         relay-v2 (Nostr)
                                                              ↓
                                                         DAO голосование
```

**Критерий готовности:** Датчик температуры на ESP32 публикует телеметрию, агент в mesh получает.

---

## Фаза 2 — C SDK для ESP32 (2-3 недели)

**Цель:** Агент на ESP32 без Python. Только C + ESP-IDF.

### Что сделать

| Компонент | Описание |
|-----------|----------|
| **`sdk_c/`** — корень C SDK | В корне p2p-agent-mesh, новая директория |
| **`sdk_c/identity.c`** | Ed25519 подпись (использовать встроенный ESP32 RNG для ключей) |
| **`sdk_c/espnow.c`** | ESP-NOW: publish, subscribe, broadcast |
| **`sdk_c/serial.c`** | Serial bridge: ESP32 ↔ компьютер (для отладки) |
| **`sdk_c/wal.c`** | WAL на SPIFFS (flash-память ESP32, ~1MB доступно) |
| **`sdk_c/mesh_client.h`** | Подключение к bridge: `mesh_publish(topic, payload)` |
| **`sdk_c/examples/temperature_sensor/`** | Готовый пример: DHT22 + ESP-NOW + bridge |
| **`sdk_c/examples/led_actuator/`** | Управление LED через DAO-голосование |

**Почему C, а не MicroPython:**
- ESP-NOW на MicroPython — прослойка, теряет 50% производительности
- MicroPython не влезает во все модели ESP32 (ESP8266 — только C)
- C SDK даёт контроль над питанием (deep sleep, battery life)

**Критерий готовности:** ESP32 с DHT22 компилирует прошивку, публикует температуру, агент в mesh отвечает командой.

---

## Фаза 3 — Bridge ESP32 ↔ relay-v2 (1 неделя)

**Цель:** ESP32-телеметрия доходит до Nostr-реле и DAO.

### Что сделать

| Компонент | Описание |
|-----------|----------|
| **`relay-v2/bridge/esp32_handler.py`** | Новый модуль в relay-v2: приём ESP-NOW событий, конвертация в Nostr kind |
| **`relay-v2/bridge/device_nip.md`** | NIP для устройств (kind:8010 — Device Telemetry) |
| **`docs/BRIDGE_ARCHITECTURE.md`** | Схема: ESP32 → bridge → relay-v2 → DAO |

**Поток данных:**
```
ESP32 → ESP-NOW → bridge.py → relay-v2 → kind:8010 → DAO voting → kind:39002
                                                                          ↓
                                                            ESP32 получает команду
```

**Критерий готовности:** Телеметрия с ESP32 отображается в relay-v2 как Nostr-событие.

---

## Фаза 4 — DAO для роя (2-3 недели)

**Цель:** DAO управляет ESP32-роем: кто что измеряет, когда передавать, как голосовать.

### Что уже есть в p2p-agent-mesh

| Компонент | Статус |
|-----------|--------|
| `coordination/raft.py` | Micro-Raft ✅ (37 тестов) |
| `coordination/coordinator.py` | Consumer Groups ✅ |
| `coordination/consumer_group.py` | Ordered delivery ✅ |
| `coordination/dedup.py` | Exactly-once delivery ✅ |
| `relay-v2/dao_groups.py` | DAO группы (4 канала) ✅ |
| `relay-v2/dao_voting.py` | Голосование ✅ |
| `relay/dao_pilot.py` | 3-агентная DAO цепочка ✅ |

### Что доделать

| Компонент | Описание |
|-----------|----------|
| **ESP32 DAO client** | C SDK: ESP32 получает DAO-решение, исполняет (включить LED, изменить частоту измерений) |
| **Device reputation** | Голос весом = uptime + accuracy датчика |
| **Auto-spawn** | DAO голосует за создание нового агента (kind:9000 уже спроектирован в relay-v2 roadmap!) |
| **`pilot/esp32_swarm.py`** | 5 ESP32 → bridge → DAO → команды обратно |

**Критерий готовности:** Пять ESP32 отправляют температуру. DAO голосует «увеличить частоту измерений на ESP32#3». ESP32#3 меняет интервал.

---

## Фаза 5 — Крупномасштабный рой (4-8 недель)

**Цель:** 100+ ESP32 в поле, DAO управляет роем, relay-v2 форвардит в Nostr.

### Что сделать

| Компонент | Описание |
|-----------|----------|
| **Multi-bridge** | Несколько ESP32-bridge покрывают зону >1 км |
| **Mesh routing** | ESP-NOW → WiFi mesh → Internet bridge |
| **LoRa backup** | Дальняя связь (10+ км) когда WiFi нет |
| **SNIN Dashboard** | Веб-дашборд: все ESP32 на карте, телеметрия, DAO-голосования |
| **OTA updates** | Обновление прошивки ESP32 через relay-v2 (NIP-96 Blossom) |

---

## Визуальная карта всей системы

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERNET                                  │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ relay-v2 │◄──►│   SNIN   │◄──►│   DAO    │                   │
│  │ (Nostr)  │    │ Protocol │    │ (NIP-29) │                   │
│  │ 21 NIPs  │    │  +Solana │    │4 groups  │                   │
│  │8198 port │    │ payments │    │16 deleg. │                   │
│  └────┬─────┘    └──────────┘    └──────────┘                   │
│       │                                                          │
│  ┌────▼─────┐    ┌──────────────────┐                            │
│  │ IPFS     │    │ p2p-agent-mesh   │                            │
│  │ PubSub   │◄──►│ v0.5.0 (133 тест)│                            │
│  │ 16 peers │    │ TCP/IPFS/HTTP    │                            │
│  └──────────┘    └────────┬─────────┘                            │
│                           │                                       │
│              ┌────────────┼────────────┐                          │
│              ▼            ▼            ▼                          │
│        ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│        │ LangGraph│ │ CrewAI   │ │ AutoGen  │                    │
│        │ adapter  │ │ adapter  │ │ adapter  │                    │
│        └──────────┘ └──────────┘ └──────────┘                    │
└─────────────────────────────────────────────────────────────────┘
                           │ ESP-NOW / TCP bridge
                           ▼
               ┌─────────────────────┐
               │  ESP32-B (bridge)   │
               │  ESP-NOW → TCP      │
               └──────┬──────────────┘
                      │ ESP-NOW (250B пакеты, ~200м)
         ┌────────────┼────────────┐
         ▼            ▼            ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ESP32 #1  │ │ESP32 #2  │ │ESP32 #3  │
   │DHT22     │ │MQ135     │ │LED strip │
   │temp      │ │air qual  │ │actuator  │
   └──────────┘ └──────────┘ └──────────┘
```

---

## Что уже есть (можно начинать прямо сейчас)

Из p2p-agent-mesh **v0.5.0** для ESP32-роя готово:

| Модуль | Файл | Готовность |
|--------|------|-----------|
| **Device SDK** | `depin/device.py` | ✅ DePINDevice — publish_telemetry(), on_command() |
| **Device Registry** | `depin/registry.py` | ✅ DeviceRegistry — DHT, TTL 24h |
| **Merkle Sync** | `depin/merkle_sync.py` | ✅ Diff-tree, 99% экономия трафика |
| **WAL (offline)** | `depin/wal.py` | ✅ DePINWAL — буферизация, TTL |
| **HTTP Relay** | `relay/http_relay.py` | ✅ REST API для bridge |
| **WS Relay** | `relay/ws_relay.py` | ✅ WebSocket relay для браузеров |
| **Coordination** | `coordination/raft.py` | ✅ Micro-Raft консенсус |
| **E2E Encrypt** | `phase0/handshake.py` | ✅ X25519 + ChaCha20-Poly1305, PFS |

**Старт:** Фаза 0.5 (Transport Abstraction) → сразу Фаза 1 (ESP-NOW). Остальное догонит.

---

## Итог: уникальность

**Ни у кого нет этой связки:**

1. P2P Mesh для AI-агентов — есть (у тебя v0.5.0)
2. ESP32 в качестве агента — **никто не делал**
3. DAO управление физическими устройствами через Nostr — **никто не делал**
4. Bridge ESP-NOW → IPFS PubSub → relay-v2 — **никто не делал**

Ты первый, кто соединяет **Nostr + P2P Mesh + ESP32 + DAO** в одну систему.
Рынок: DePIN (Physical Infrastructure Networks) — капитализация $50B+ к 2027.
