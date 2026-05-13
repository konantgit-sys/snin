# SNIN — Sovereign Nostr Infrastructure Network

**AI Agents + IoT Hardware + DAO Governance on Nostr**

![Python](https://img.shields.io/badge/python-3.10+-blue)
![MIT](https://img.shields.io/badge/license-MIT-green)
![ESP32](https://img.shields.io/badge/platform-ESP32-orange)
![RPi](https://img.shields.io/badge/platform-RaspberryPi-red)
![Arduino](https://img.shields.io/badge/platform-Arduino-00979D)
![Nostr](https://img.shields.io/badge/protocol-Nostr-8B5CFE)
![dePIN](https://img.shields.io/badge/sector-dePIN-22C55E)
![tests](https://img.shields.io/badge/tests-7%2F7%20passing-brightgreen)

SNIN — открытая инфраструктура для роя физических устройств (ESP32, Arduino, Raspberry Pi),
объединённых в P2P mesh через Nostr-реле с DAO-управлением.

**Уникальность:** первый стек, где AI-агент живёт на микроконтроллере
и голосует в DAO через Nostr. Никто так не делает.

---

## Архитектура

```
ESP32 (DHT22) ─── ESP-NOW ─── Bridge ─── AgentMesh ─── relay-v2 (Nostr)
  │                               │           │          kind:8010-8012
  │ LoRa (15km)                   │           │
  │ BLE (10m, T-Watch)            │           │
  │ mDNS (auto-discovery)         │           │
  │                               │           │
  Raspberry Pi (Hub/Display) ─────┤           │
  Arduino (ESP8266, C++) ───── ESP-NOW ───────┤
  M5Stack/TTGO (DAO Terminal) ────┤           │
                                          DAO Pilot
                                        (3 агента)
```

## Быстрый старт

```bash
git clone https://github.com/konantgit-sys/snin.git
cd snin/hardware/esp32
pip install cryptography aiohttp
python3 test_smoke.py              # 7 тестов, все PASSED
python3 lora/lora_phy.py           # LoRa self-test
python3 ble/ble_phy.py             # BLE self-test
```

## Что внутри

```
hardware/
├── SPECIFICATION.md         — 10 платформ, матрица, протокол
├── STACK_OPTIMIZATION.md    — GAP-анализ: LoRa, BLE, OTA, mDNS
│
├── esp32/
│   ├── sdk/transport.py     — TCP/HTTP/IPFS/ESP-NOW transport
│   ├── bridge/bridge.py     — ESP-NOW → AgentMesh + Ed25519 + WAL
│   ├── relay/device_handler.py — Nostr kinds 8010-8012 plugin
│   ├── firmware/
│   │   ├── snin_sensor.py    — ESP32 DHT22 + Ed25519 + ESP-NOW
│   │   └── snin_bridge_fw.py — ESP32 bridge (ESP-NOW → UART)
│   ├── lora/lora_phy.py     — SX1278/SX1262, 2-15km, фрагментация
│   ├── ble/ble_phy.py       — GATT сервер, телефон ↔ ESP32
│   ├── mdns/mdns_discovery.py — автоматический поиск bridge
│   └── sim/sim_sensor.py    — симулятор ESP32 (self-test)
│
├── raspberry/
│   └── raspberry_node.py    — RPi: bridge + agent + HDMI dashboard
├── arduino/
│   └── src/snin_arduino.ino — C++ прошивка ESP8266/ESP32
└── display/
    └── display_module.py    — M5Stack/TTGO/LilyGO DAO terminal

specs/ESP32_AGENT_SPEC.md    — полная спека протокола
research/                    — open-source review, crypto stack
```

## Платформы

| Платформа | Язык | Транспорт | Роль в рое |
|-----------|------|-----------|-----------|
| ESP32-S3 | MicroPython | ESP-NOW / LoRa / BLE / TCP | Sensor node |
| ESP8266 | C++ (Arduino) | ESP-NOW | Ultra-cheap sensor |
| Raspberry Pi 4/5 | Python | TCP / Ethernet | Hub, relay, display |
| Raspberry Pi Zero 2W | Python | TCP + USB-ESP32 | Portable bridge |
| M5Stack Core2 | MicroPython | ESP-NOW + TFT | DAO terminal |
| TTGO T-Display | MicroPython | ESP-NOW + ST7789 | Wearable display |
| LilyGO T-Watch | MicroPython | BLE + GPS | Wrist DAO terminal |

## Протокол (один для всех платформ)

```
1. DHT22 читает температуру на ESP32
2. ESP32 подписывает Ed25519, шлёт ESP-NOW (250 байт) / LoRa (64 байта)
3. Bridge принимает, верифицирует, шлёт в AgentMesh
4. AgentMesh публикует в relay-v2 (kind:8010)
5. DAO Pilot видит событие, может голосовать
6. DAO → kind:8012 → bridge → ESP-NOW → ESP32
```

## Nostr Kinds

| Kind | Название | Назначение | Статус |
|------|----------|-----------|--------|
| 8010 | Device Telemetry | Температура, влажность, батарея | ✅ |
| 8014 | Device Registration | Регистрация нового ESP32 | ✅ |
| 8012 | Device Command | Команда от DAO к ESP32 | ⏳ |
| 8013 | OTA Update | Обновление прошивки | ⏳ |

## Статус разработки

```
Фаза 0-2: ✅ Transport + Bridge + Multi-Platform (27 файлов, ~200 KB)
Фаза 3:   ✅ LoRa + BLE + mDNS (закрыты транспортные дыры)
Фаза 4:   ⏳ Cognitive Swarm (команды, GPS, Edge AI, камера)
Фаза 5:   ⏳ Production (1000 устройств, CI/CD, PyPI)
```

## Связанные репозитории

| Репозиторий | Описание |
|-------------|----------|
| [p2p-agent-mesh](https://github.com/konantgit-sys/p2p-agent-mesh) | P2P pub/sub transport для AI-агентов (v0.5.0, 133 теста) |

## Лицензия

MIT © SNIN Network
