# SNIN — Sovereign Nostr Infrastructure Network

**IoT hardware stack: ESP32, Arduino, Raspberry Pi, M5Stack.**

Ed25519-signed telemetry over ESP-NOW, LoRa, BLE — published to Nostr kinds 8010-8012. P2P mesh relay for decentralized sensor networks with DAO governance.

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![ESP32](https://img.shields.io/badge/platform-ESP32-orange)]()
[![RPi](https://img.shields.io/badge/platform-RaspberryPi-red)]()
[![Arduino](https://img.shields.io/badge/platform-Arduino-00979D)]()
[![Nostr](https://img.shields.io/badge/protocol-Nostr-8B5CFE)]()
[![dePIN](https://img.shields.io/badge/sector-dePIN-22C55E)]()
[![CI](https://github.com/konantgit-sys/snin/actions/workflows/ci.yml/badge.svg)](https://github.com/konantgit-sys/snin/actions/workflows/ci.yml)

---

## Why SNIN?

| Problem | Solution |
|---------|----------|
| IoT clouds lock you in (AWS IoT, Azure) | Open Nostr protocol, no vendor |
| ESP-NOW limited to 200m | LoRa (15km) via same protocol |
| No end-to-end authentication | Ed25519 from MCU to relay |
| No DAO for physical devices | DAO votes → kind:8012 → ESP32 |
| One-off firmwares, no ecosystem | Single protocol for 10+ platforms |

**This is the first stack where an AI agent lives on a microcontroller and votes in a DAO through Nostr.**

---

## Architecture

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
                                        (3 agents)
```

## Quickstart (30 seconds, no hardware)

```bash
git clone https://github.com/konantgit-sys/snin.git
cd snin/hardware/esp32
pip install cryptography aiohttp

python3 test_smoke.py              # 7 tests, all PASSED
python3 lora/lora_phy.py           # LoRa self-test
python3 ble/ble_phy.py             # BLE self-test
```

## Package Index

```
hardware/
├── SPECIFICATION.md         — 10 platforms spec + capability matrix
├── STACK_OPTIMIZATION.md    — Gap analysis: LoRa, BLE, OTA, mDNS
│
├── esp32/
│   ├── sdk/transport.py     — Unified transport API (TCP/HTTP/IPFS/ESP-NOW)
│   ├── bridge/bridge.py     — ESP-NOW → AgentMesh + Ed25519 + WAL
│   ├── relay/device_handler.py — Nostr kinds 8010-8012 plugin
│   ├── firmware/
│   │   ├── snin_sensor.py    — ESP32 DHT22 + Ed25519 + ESP-NOW
│   │   └── snin_bridge_fw.py — ESP32 bridge (ESP-NOW → UART)
│   ├── lora/lora_phy.py     — SX1278/SX1262, 2-15km, 250B→64B×4 frag
│   ├── ble/ble_phy.py       — GATT server, phone ↔ ESP32 commands
│   ├── mdns/mdns_discovery.py — Bridge auto-discovery in LAN
│   └── sim/sim_sensor.py    — ESP32 simulator (self-test without hardware)
│
├── raspberry/
│   └── raspberry_node.py    — RPi: bridge + agent + HDMI dashboard
├── arduino/
│   ├── src/snin_arduino.ino — C++ firmware ESP8266/ESP32
│   └── library.json         — PlatformIO metadata
└── display/
    └── display_module.py    — M5Stack/TTGO/LilyGO DAO terminal

specs/ESP32_AGENT_SPEC.md   — Full protocol spec
examples/                   — 5 copy-paste examples
```

## Supported Platforms

| Platform | Language | Transport | Role |
|----------|----------|-----------|------|
| ESP32-S3 | MicroPython | ESP-NOW / LoRa / BLE / TCP | Sensor node |
| ESP8266 | C++ (Arduino) | ESP-NOW | Ultra-cheap sensor |
| Raspberry Pi 4/5 | Python | TCP / Ethernet | Hub, relay, display |
| RPi Zero 2W | Python | TCP + USB-ESP32 | Portable bridge |
| M5Stack Core2 | MicroPython | ESP-NOW + TFT | DAO terminal |
| TTGO T-Display | MicroPython | ESP-NOW + ST7789 | Wearable display |
| LilyGO T-Watch | MicroPython | BLE + GPS | Wrist DAO terminal |

## Protocol (one for all platforms)

```
1. DHT22 reads temperature on ESP32
2. ESP32 signs with Ed25519, sends ESP-NOW (250B) / LoRa (64B×4)
3. Bridge verifies signature, forwards to AgentMesh
4. AgentMesh publishes to relay-v2 (kind:8010)
5. DAO Pilot observes event, may vote
6. DAO → kind:8012 → bridge → ESP-NOW → ESP32
```

## Nostr Kinds

| Kind | Name | Purpose | Status |
|------|------|---------|--------|
| 8010 | Device Telemetry | Temperature, humidity, battery | ✅ |
| 8014 | Device Registration | New ESP32 onboarding | ✅ |
| 8012 | Device Command | DAO-to-device action | ⏳ |
| 8013 | Device OTA | Firmware update payload | ⏳ |

## Development Status

```
Phase 0-2: ✅ Transport + Bridge + Multi-Platform (32 files, ~216 KB)
Phase 3:   ✅ LoRa + BLE + mDNS (transport gaps closed)
Phase 4:   ⏳ Cognitive Swarm (commands, GPS, Edge AI, camera)
Phase 5:   ⏳ Production (1000 devices, CI/CD, PyPI + PlatformIO)
```

## Related Repositories

| Repo | Description |
|------|-------------|
| [p2p-agent-mesh](https://github.com/konantgit-sys/p2p-agent-mesh) | P2P pub/sub transport for AI agents (v0.5.0, 133 tests, 3 stars) |

## Unique Value

- **AgentMesh on an ESP32** — no one else does this
- **ESP-NOW → Nostr relay** — Linux P2P mesh + ESP-NOW LoRa in one architecture
- **DAO voting on M5Stack/TTGO screen** — hardware DAO terminal
- **Ed25519 end-to-end** — bridge cannot decrypt, MCU→relay trust
- **One protocol for 10 platforms** — ESP32, Arduino, RPi, M5Stack, T-Watch

## License

MIT © SNIN Network
