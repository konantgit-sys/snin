# NIP-80: SNIN Device Protocol

`draft` `optional`

SNIN (Sensor Network Interoperability Nostr) — протокол для IoT-устройств на базе Nostr: ESP32-сенсоры, mesh-сеть, телеметрия, команды, алерты.

## Мотивация

Существующие IoT-протоколы (MQTT, CoAP, LwM2M) завязаны на центральный брокер. Nostr даёт:
- Децентрализованную маршрутизацию через relay
- Криптографическую подпись каждого события (Ed25519 mesh + Schnorr relay)
- Несколько транспортов: ESP-NOW, LoRa, BLE, mDNS, UART
- Автономность без облака

## Event Kinds

| kind | name | description |
|------|------|-------------|
| `8010` | Device Telemetry | Периодические данные с датчика |
| `8011` | Device Alert | Алерт при выходе за порог |
| `8012` | Device Command | Команда управления устройством |
| `8013` | OTA Update | Обновление прошивки по воздуху |
| `8014` | Device Registration | Регистрация нового устройства в сети |
| `8015` | Device Location | GPS-координаты устройства |
| `8016` | Commission | Процесс привязки (commissioning) |
| `8017` | System Status | Healthcheck / статус системы |

## Диапазон киндов

Все кинды NIP-80 находятся в диапазоне **8010–8017**:
- `80` = номер NIP
- `10`–`17` = тип сообщения

## Поток данных

```
┌──────────┐    ESP-NOW/LoRa/BLE    ┌──────────┐    Nostr WS     ┌──────────┐
│ ESP32    │ ──────────────────────→ │ Bridge   │ ─────────────→ │ Relay    │
│ (Sensor) │ ←────────────────────── │ (RPi/PC) │ ←───────────── │ (:8198)  │
└──────────┘     kind:8012 (cmd)     └──────────┘   kind:8010    └──────────┘
                                                         │
                                                    ┌────┴────┐
                                                    │ Dashboard│
                                                    │ /snin   │
                                                    └─────────┘
```

**Mesh-уровень** (ESP32 ↔ ESP32): Ed25519 подпись, ESP-NOW/LoRa/BLE.

**Relay-уровень** (Bridge → Nostr Relay): Schnorr BIP-340 подпись, kind:8010–8017.

## Спецификация киндов

### kind:8010 — Device Telemetry

Периодические данные с ESP32-сенсора.

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID (строка, уникальная в сети) |
| `t` | Тип сенсора (`temperature`, `humidity`, `multi`) |
| `seq` | Sequence number (монотонный счётчик) |
| `batt` | Уровень батареи (0–100) |

**Content (JSON):**
```json
{
  "temp": 23.5,
  "hum": 60.2,
  "battery": 85,
  "voltage": 4.12
}
```

### kind:8011 — Device Alert

Алерт при выходе за порог.

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID |
| `alert` | Тип алерта (`battery_low`, `temp_high`, `offline`, `sensor_fail`, `signal_low`, `panic`) |
| `severity` | `low`, `high`, `critical` |
| `seq` | Sequence number |

**Content:**
```json
{
  "message": "Battery at 8%",
  "value": 8,
  "threshold": 10,
  "triggered_at": 1778679546
}
```

### kind:8012 — Device Command

Команда от bridge к ESP32.

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID (получатель) |
| `cmd` | Action (`set_gpio`, `set_interval`, `read_sensor`, `reboot`, `pause`, `resume`, `factory_reset`) |
| `seq` | Sequence number |

**Content (JSON):**
```json
{
  "params": {
    "pin": 4,
    "state": 1
  }
}
```

Поддерживаемые действия:
- `set_gpio` — `{"pin": int, "state": 0|1}`
- `set_interval` — `{"seconds": int}`
- `read_sensor` — `{"sensor": "temperature"|"humidity"|"all"}`
- `reboot` — `{"delay_ms": 1000}` (опционально)
- `pause` — приостановить отправку телеметрии
- `resume` — возобновить отправку
- `factory_reset` — сброс к заводским настройкам

### kind:8013 — OTA Update

Обновление прошивки ESP32 по воздуху.

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID |
| `ver` | Версия прошивки (semver) |
| `size` | Размер в байтах |
| `sha256` | Хеш прошивки для верификации |

**Content:** base64-encoded firmware binary (опционально URL вместо тела).

### kind:8014 — Device Registration

Регистрация нового устройства в mesh-сети.

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID |
| `pubkey` | Ed25519 публичный ключ устройства |
| `model` | Модель (`esp32`, `esp8266`, `rp2040`) |
| `caps` | capabilities (`sensor`, `lora`, `ble`, `display`) |

**Content:** JSON с метаданными устройства.

### kind:8015 — Device Location

GPS-координаты устройства (для трекеров).

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID |
| `lat` | Широта (decimal degrees) |
| `lon` | Долгота |
| `alt` | Высота над уровнем моря (м) |
| `speed` | Скорость (км/ч) |
| `satellites` | Количество спутников |

**Content:**
```json
{
  "hdop": 1.2,
  "fix_quality": 3,
  "accuracy": "excellent"
}
```

### kind:8016 — Commission

Процесс привязки нового устройства.

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID |
| `mode` | `auto`, `paired`, `approved` |
| `pubkey` | Публичный ключ устройства |

### kind:8017 — System Status

Healthcheck / статус системы.

**Tags:**
| Tag | Значение |
|-----|----------|
| `d` | Device ID |
| `uptime` | Время работы (сек) |

**Content:**
```json
{
  "uptime": 3600,
  "firmware": "v0.6.0",
  "heap_free": 182400,
  "wifi_rssi": -65,
  "battery": 85,
  "alerts_active": 0
}
```

## Транспорты

Устройства SNIN могут использовать любой транспорт в зависимости от hardware:

| Transport | Дальность | Скорость | Применение |
|-----------|-----------|----------|------------|
| ESP-NOW | 200м | 1Mbps | Основной mesh |
| LoRa SX1278/SX1262 | 2–10км | 37.5kbps | Дальняя связь |
| BLE GATT | 10м | 1Mbps | Телефон ↔ ESP32 |
| mDNS + WiFi | LAN | 100Mbps | Bridge/RPi |
| UART | кабель | 115200bps | ESP32 ↔ bridge |

## Подписи

- **Mesh (ESP32 ↔ ESP32):** Ed25519 — быстрая, малый размер подписи (64 байта)
- **Relay (Bridge → Nostr):** Schnorr BIP-340 — стандарт Nostr

Bridge конвертирует: получает Ed25519-подпись от ESP32, создаёт Nostr-событие, подписывает Schnorr для relay.

## Примеры

Публикация телеметрии:
```json
["EVENT", {
  "id": "<sha256>",
  "pubkey": "<32-byte x-only hex>",
  "created_at": 1778679546,
  "kind": 8010,
  "tags": [
    ["d", "garden_sensor_01"],
    ["t", "temperature"],
    ["seq", "42"],
    ["batt", "85"]
  ],
  "content": "{\"temp\":23.5,\"hum\":60.2,\"battery\":85}",
  "sig": "<64-byte schnorr sig>"
}]
```

Подписка на команды (REQ kind:8012):
```json
["REQ", "sub_cmds", {"kinds": [8012], "#d": ["garden_sensor_01"]}]
```

## Ссылки

- [NIP-01: Basic protocol flow](https://github.com/nostr-protocol/nips/blob/master/01.md)
- [SNIN Protocol — реализация](https://github.com/notdefined/snin-public)
- relay: `ws://localhost:8198` (SNIN Network Relay V2)
