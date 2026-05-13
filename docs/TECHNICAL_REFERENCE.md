# SNIN Protocol v0.6 — Technical Reference

## Ядро
- **NIP**: 80
- **Кинды**: 8010–8017
- **Relay**: ws://localhost:8198
- **Dashboard**: https://cryter-dash.v2.site/snin.html

## Структура киндов
```
NIP-80
├── 8010  Telemetry       — температура, влажность, батарея
├── 8011  Alert           — battery_low, temp_high, offline, panic
├── 8012  Command         — set_interval, reboot, pause, resume
├── 8013  OTA             — прошивка по воздуху
├── 8014  Registration    — привязка нового устройства
├── 8015  GPS Location    — координаты, скорость, спутники
├── 8016  Commission      — процесс commissioning (auto/paired/approved)
└── 8017  System Status   — healthcheck, uptime, heap, RSSI
```

## Стек модулей (17 шт)
```
hardware/
├── crypto/nostr_signer.py         — Ed25519 + Schnorr подпись
├── display/display_module.py      — LCD/OLED вывод
├── esp32/
│   ├── firmware/                   — snin_sensor, snin_bridge_fw, ota
│   ├── relay/                     — device_handler, alert_handler
│   ├── command/                   — cmd_handler, command_consumer
│   ├── mesh/                      — gps_tracker
│   ├── commission/                — commission_handler
│   ├── power/                     — power_manager
│   ├── sim/                       — sim_sensor
│   ├── lora/lora_phy.py          — LoRa SX1278/SX1262
│   ├── ble/ble_phy.py            — BLE GATT
│   ├── mdns/mdns_discovery.py    — mDNS
│   ├── test_smoke.py             — интеграционный тест
│   └── test/unit/                 — unit-тесты
├── arduino/src/snin_arduino.ino  — C++ порт
├── raspberry/raspberry_node.py   — RPi bridge
└── ...
```

## Спецификации
- `specs/NIP-80.md` — полная NIP спецификация
- `specs/V0_6_SPECIFICATION.md` — v0.6 spec
- `specs/ESP32_AGENT_SPEC.md` — ESP32 spec
- `nip-80-snin.md` — копия NIP-80

## Локальный git
- Репозиторий: /home/agent/data/projects/snin-public
- Ветка: main
- Последний коммит: baacaf6 (32 files, +718)
- Пуш в GitHub: ❌ НЕТ, до команды пользователя
