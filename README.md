# SNIN — Sovereign Nostr Infrastructure Network

**AI Agents + IoT Hardware + DAO Governance on Nostr**

SNIN — это открытая инфраструктура для роя AI-агентов на физических устройствах. ESP32, Arduino, Raspberry Pi объединены в P2P mesh через Nostr-реле с DAO-управлением.

---

## Архитектура

```
ESP32 (DHT22) ─── ESP-NOW ─── Bridge ─── AgentMesh ─── relay-v2 (Nostr)
                   250B pkt        │           │            kind:31000-31002
                                   │           │
                              Raspberry Pi    DAO Pilot
                              (Hub/Display)   (3 агента)
```

**Уникальность:** первый стек, где AI-агент живёт на микроконтроллере и голосует в DAO через Nostr.

---

## Что внутри

```
hardware/
├── SPECIFICATION.md        — 10 платформ, матрица, протокол
├── STACK_OPTIMIZATION.md   — GAP-анализ: LoRa, BLE, OTA
├── esp32/
│   ├── sdk/transport.py    — абстрактный транспорт (TCP/HTTP/IPFS/ESP-NOW)
│   ├── bridge/bridge.py    — bridge ESP-NOW → AgentMesh + Ed25519 + WAL
│   ├── relay/device_handler.py — плагин relay-v2 (kind:31000-31002)
│   ├── firmware/
│   │   ├── snin_sensor.py     — прошивка ESP32 (DHT22 + подпись + ESP-NOW)
│   │   └── snin_bridge_fw.py  — прошивка ESP32-bridge (ESP-NOW → UART)
│   └── sim/sim_sensor.py   — симулятор ESP32 + self-test
├── raspberry/
│   └── raspberry_node.py   — RPi: bridge + agent + HDMI dashboard
├── arduino/
│   └── src/snin_arduino.ino — C++ прошивка (ESP8266/ESP32 + Ed25519)
└── display/
    └── display_module.py   — M5Stack/TTGO/LilyGO + DAO голосование на экране

specs/ESP32_AGENT_SPEC.md  — полная спецификация протокола
research/                  — обзор open-source альтернатив, крипто-стек
docs/PHASE_PLAN.md         — 5 фаз развития
docs/ESP32_ROADMAP.md      — дорожная карта ESP32
```

---

## Быстрый старт

```bash
# Симуляция без железа (self-test всей цепочки)
cd hardware/esp32
pip install cryptography aiohttp
python3 test_smoke.py           # 4 теста
python3 sim/sim_sensor.py --self-test  # bridge + relay-v2
```

---

## Зависимости

| Компонент | Платформа | Язык |
|-----------|-----------|------|
| Transport SDK | Любая | Python 3.10+ |
| Bridge | Сервер/RPi | Python 3.10+ |
| Sensor Firmware | ESP32 | MicroPython |
| Bridge Firmware | ESP32 | MicroPython |
| Arduino Sensor | ESP8266/ESP32 | C++ (Arduino) |
| Display | M5Stack/TTGO | MicroPython |

---

## Статус

```
Фаза 0-2: ✅ Transport + Bridge + Multi-Platform (17 файлов, ~3000 строк)
Фаза 3:   ⏳ LoRa + BLE + OTA + mDNS
Фаза 4:   ⏳ Cognitive Swarm (Task Scheduler, GPS, Edge AI)
Фаза 5:   ⏳ Production (1000 devices, InfluxDB, Grafana)
```

---

## Репозитории

- [p2p-agent-mesh](https://github.com/konantgit-sys/p2p-agent-mesh) — P2P pub/sub transport для AI-агентов
- [snin](https://github.com/konantgit-sys/snin) — Hardware адаптеры, прошивки, документация (этот репозиторий)

---

## Лицензия

MIT © SNIN Network
