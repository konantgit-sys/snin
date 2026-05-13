# SNIN ESP32 Agent — Technical Specification v0.1

**Статус:** Черновик спецификации  
**Дата:** 2026-05-13  
**Автор:** Юрий Писаренко (@ayupro)  
**Репозитории:** konantgit-sys/relay-v2, p2p-agent-mesh, snin  

---

## 1. Purpose

ESP32 как физический AI-агент в P2P Mesh сети с DAO-управлением.

ESP32 не тянет IPFS PubSub (1.2 GB RAM) и полный Python-стек.  
Решение: **ESP32 → ESP-NOW → bridge → p2p-agent-mesh → relay-v2 (Nostr) → DAO**

---

## 2. Target Hardware

| Модель | Flash | RAM | Подходит для | Цена |
|--------|-------|-----|-------------|------|
| ESP32-WROOM-32 | 4MB | 520KB | Базовый сенсор | $3-5 |
| ESP32-S3 | 16MB | 512KB | + шифрование + SPIFFS | $5-8 |
| ESP32-C6 | 4MB | 512KB | + Thread/Zigbee | $4-6 |
| ESP32-C5 (2026) | 8MB | 512KB | + WiFi 6, RISC-V | $5-7 |

**Рекомендация:** ESP32-S3 (16MB) — достаточно для WAL, Ed25519, ESP-NOW буфера.

---

## 3. Software Stack (ESP32 side)

| Слой | Технология | Источник |
|------|-----------|----------|
| OS | MicroPython v1.23+ | micropython.org |
| Mesh Transport | ESP-NOW (встроен в MicroPython) | docs.micropython.org |
| Identity | Ed25519 via ucrypto | github.com/dmazzella/ucrypto |
| WAL | SPIFFS + ujson | p2p-agent-mesh/depin/wal.py → порт |
| Merkle Sync | uhashlib SHA256 | github.com/droid76/Merkle-Tree |
| Serial Bridge | UART (115200 baud) для debug/power | — |

### Почему MicroPython, а не C/ESP-IDF

| Фактор | MicroPython | ESP-IDF (C) |
|--------|------------|-------------|
| Время разработки | 1 день | 2-3 недели |
| RAM для Ed25519 | ~15 KB | ~8 KB |
| ESP-NOW API | Встроен, 3 строки | manual init |
| WAL на flash | SPIFFS (FAT-like) | nvs + spiffs |
| **Когда выбрать** | Прототип, <10 устройств | Production, >100 устройств |

**Стратегия:** Фаза 1–2 на MicroPython (прототип), Фаза 3+ порт на C (ESP-IDF) для продакшена.

---

## 4. Communication Protocol

### 4.1 ESP-NOW Packet Format (250 bytes max)

```
┌────────────────────────────────────────────────────┐
│ Byte 0-31:   Ed25519 signature                      │
│ Byte 32-63:  Pubkey (32 bytes)                      │
│ Byte 64-67:  Sequence number (uint32)               │
│ Byte 68:     Message type (1 byte)                  │
│ Byte 69-249: Payload (181 bytes)                    │
└────────────────────────────────────────────────────┘
```

### 4.2 Message Types

| Type | Code | Payload | Description |
|------|------|---------|-------------|
| TELEMETRY | 0x01 | `{temp, hum, batt, ts}` | Sensor data |
| COMMAND_ACK | 0x02 | `{cmd_id, status}` | Command response |
| REGISTER | 0x03 | `{device_id, caps}` | Device registration |
| DAO_VOTE | 0x04 | `{proposal_id, vote}` | DAO vote |
| HEARTBEAT | 0x05 | `{seq, uptime}` | Keepalive |
| OTA_REQ | 0x06 | `{version, hash}` | Firmware update request |

### 4.3 Flow: Sensor → Mesh → Relay → DAO

```
ESP32 Sensor
  │
  ├── ESP-NOW (250B, signed)
  │
  ▼
ESP32 Bridge (round-robin MAC listeners)
  │
  ├── TCP → p2p-agent-mesh (emit telemetry)
  │
  ▼
p2p-agent-mesh (AgentMesh.emit)
  │
  ├── IPFS PubSub / TCP (в зависимости от transport)
  │
  ▼
relay-v2 bridge
  │
  ├── Nostr kind:8010 (Device Telemetry)
  │   ├── kind:8014 (Device Registration)
  │   └── kind:8012 (Device Command)
  │
  ▼
DAO (Voting via NIP-29 groups)
  │
  ├── kind:39002 (Proposal: "increase measurement frequency on ESP32#3")
  ├── kind:39003 (Vote)
  │
  ▼
ESP32 Bridge ← relay-v2 fanout
  │
  └── ESP-NOW → ESP32 Sensor (command received)
```

---

## 5. Bridge Architecture

### 5.1 ESP32-Bridge Responsibilities

- Слушает ESP-NOW (циклический обход MAC-адресов сенсоров)
- Верифицирует Ed25519 подпись каждого пакета
- Буферизирует в WAL (SPIFFS) при потере TCP-соединения
- Форвардит в p2p-agent-mesh через TCP transport
- Получает команды из relay-v2 и отправляет ESP-NOW обратно

### 5.2 Bridge как часть p2p-agent-mesh

Bridge — это полноценный AgentMesh-узел с дополнительным ESP-NOW транспортом:

```python
bridge = AgentMesh("esp32_bridge_01", ["esp32_sensors"])
await bridge.start()

# Регистрируем ESP-NOW как дополнительный транспорт
await bridge.add_transport(ESPNOWTransport(esp_now_config))

# Подписка на команды от DAO
@bridge.on("esp32:command")
async def handle_command(msg):
    target_mac = msg["device_mac"]
    payload = msg["command"]
    await esp_now_send(target_mac, payload)
```

---

## 6. Existing Code That Maps Directly (from p2p-agent-mesh v0.5.0)

| p2p-agent-mesh файл | Берётся как есть | Нужен порт | Примечание |
|--------------------|:---------------:|:----------:|-----------|
| `depin/device.py` | — | ✅→MicroPython | `DePINDevice` → `ESP32Device` |
| `depin/registry.py` | ✅ | — | Device Registry в DHT |
| `depin/merkle_sync.py` | — | ✅→MicroPython | MerkleTree на uhashlib |
| `depin/wal.py` | — | ✅→MicroPython | SPIFFS вместо SQLite |
| `phase0/identity.py` | — | ✅→MicroPython | Ed25519 через ucrypto |
| `phase0/sig_gate.py` | ✅ | — | Rate limiting на bridge |
| `relay/http_relay.py` | ✅ | — | Bridge → relay-v2 HTTP API |
| `sdk/agent.py` | ✅ | — | AgentMesh.emit — bridge side |
| `coordination/raft.py` | — | ✅→MicroPython | raft-lite порт для ESP32 bridge |

---

## 7. Security Model

| Уровень | Угроза | Защита |
|---------|--------|--------|
| L0 | ESP-NOW сниффер | Ed25519 подпись каждого пакета |
| L1 | Replay attack | Sequence number + nonce |
| L2 | Bridge compromise | E2E между ESP32 и relay-v2 (X25519) |
| L3 | Relay compromise | DAO multi-sig, K=3 репликация DHT |
| L4 | Physical ESP32 theft | Key erase on tamper, factory reset |

---

## 8. Open Source Solutions to Use (не писать с нуля)

| Что нужно | Готовое решение | Экономия |
|-----------|----------------|----------|
| ESP-NOW MicroPython API | Встроен в MicroPython v1.21+ | 100% |
| ESP-NOW utils | glenn20/micropython-espnow-utils | 80% |
| Ed25519 for MicroPython | dmazzella/ucrypto | 90% |
| Merkle Tree for ESP32 | droid76/Merkle-Tree → порт | 70% |
| Raft consensus | nikwl/raft-lite → порт | 60% |
| Nostr sensor client | nitroxgas/nostrmachines (reference) | 40% |

---

## 9. Code Generation Strategy

Не писать с нуля, а:

1. **Взять** `p2p-agent-mesh/depin/*.py` — это DePIN SDK, уже спроектирован под IoT
2. **Портировать** под MicroPython: заменить SQLite → SPIFFS, hashlib → uhashlib, socket → usocket
3. **Добавить** ESP-NOW transport как новый класс в `phase0/transport.py` (абстракция)
4. **Связать** с relay-v2 через HTTP bridge (уже есть `relay/http_relay.py`)
5. **Не трогать** relay-v2 — он принимает любые Nostr-события, ESP32-телеметрия — просто новый kind

---

## 10. Acceptance Criteria

- [ ] ESP32 с DHT22 публикует температуру в mesh через ESP-NOW
- [ ] Bridge получает, верифицирует, форвардит в p2p-agent-mesh
- [ ] Агент в mesh видит событие от ESP32
- [ ] DAO может отправить команду обратно на ESP32
- [ ] WAL буферизирует при offline bridge
- [ ] Merkle sync при rejoin (99% экономия трафика)
- [ ] Весь цикл <2 секунд (sensor → mesh → relay → DAO → sensor)
