# SNIN ESP32 — Архитектура и Спецификация v1.0

> SNIN (Sensor Network Interoperability Nostr) — децентрализованная mesh-сеть IoT-устройств на базе Nostr.
> ESP32 — конечное устройство сети: читает датчики, публикует kind:8010, принимает kind:8012 команды.

---

## 1. МЕСТО В АРХИТЕКТУРЕ

```
ESP32 (реальное устройство)
  │ WiFi / ESP-NOW / LoRa / BLE
  ▼
Bridge (опционально — Raspberry Pi / PC)
  │ WebSocket (WSS)
  ▼
Relay (relay-snin.v2.site) ────→ IPFS архив
  ▲
  │ HTTP poll (20s)
  ▼
Telegram Bot (@Snindaobot)
  │
  └──→ Пользователь (Telegram)
       /telemetry — список устройств
       /cmd <device> <action> — команды
       /chart temp 24 — графики
       /watch <device> — подписка на алерты
```

**Два режима работы ESP32:**

| Режим | Транспорт | Когда нужен |
|-------|-----------|-------------|
| **Direct** | ESP32 → WiFi → WSS → Relay | ESP32 дома/в офисе, есть WiFi |
| **Mesh** | ESP32 → ESP-NOW/LoRa → Bridge → Relay | Полевые устройства, несколько ESP32 в сети |

---

## 2. NIP-80 ПРОТОКОЛ (kind:8010–8017)

Протокол использует 8 кастомных Nostr kinds:

| kind | Название | Направление | Частота |
|------|----------|-------------|---------|
| **8010** | Device Telemetry | ESP32 → Relay | Каждые N секунд (по умолч. 60) |
| **8011** | Device Alert | ESP32 → Relay | При превышении порога |
| **8012** | Device Command | Bot → Relay → ESP32 | По запросу пользователя |
| **8013** | OTA Update | Админ → Relay → ESP32 | По необходимости |
| **8014** | Device Registration | ESP32 → Relay | При старте (один раз) |
| **8015** | Device Location | ESP32 → Relay | По запросу или периодически |
| **8016** | Commission | ESP32 ↔ Bridge | Процесс привязки |
| **8017** | System Status | ESP32 → Relay | Healthcheck |

### kind:8010 — Telemetry (content)

```json
{
  "temp": 23.5,
  "hum": 60.2,
  "battery": 85,
  "voltage": 4.12
}
```

**Tags:**
| Tag | Значение | Пример |
|-----|----------|--------|
| `d` | Device ID | `esp32_sensor_01` |
| `t` | Тип сенсора | `temperature`, `multi` |
| `seq` | Sequence number | `42` |
| `batt` | Уровень батареи | `85` |

### kind:8012 — Command (content)

```json
{"action": "read_sensor"}
{"action": "set_interval", "params": {"interval": 120}}
{"action": "reboot"}
{"action": "pause"}
{"action": "resume"}
{"action": "status"}
```

Ответ ESP32 (тоже kind:8012):
```json
{"action": "read_sensor", "ok": true, "result": "sensor read triggered"}
{"action": "reboot", "ok": true, "result": "restarting"}
```

### kind:8011 — Alert (content)

```json
{"alert": "sensor_fail", "msg": "DHT read error", "ts": 1778728000}
{"alert": "battery_low", "msg": "battery at 5%", "ts": 1778729000}
```

---

## 3. FIRMWARE — snin-esp32-firmware (PlatformIO)

### Текущее состояние: ✅ v1.0 Direct Mode

**Возможности:**
- ✅ WiFi + WebSocket (WSS) → relay-snin.v2.site
- ✅ DHT22: температура + влажность
- ✅ kind:8010 публикация каждые N секунд
- ✅ kind:8012 приём и исполнение: read_sensor, set_interval, reboot, pause, resume, status
- ✅ kind:8011 алерты (sensor_fail, battery_low)
- ✅ kind:8014 регистрация при старте
- ✅ Мониторинг батареи через ADC

**Платформа:** ESP32 (WROOM / S3)
**Фреймворк:** Arduino (PlatformIO)
**Зависимости:** ArduinoJson v7, WebSocketsClient, DHT sensor library
**Пин-аут:**
| ESP32 | DHT22 |
|-------|-------|
| 3.3V | VCC |
| GND | GND |
| GPIO4 | DATA |

### Планируется: v1.1 Mesh Mode (следующий шаг)

- ESP-NOW транспорт между ESP32
- LoRa для дальних дистанций
- Bridge-режим (ESP32 → ESP-NOW → Bridge → WSS → Relay)

### Структура проекта

```
snin-esp32-firmware/
├── platformio.ini          # Конфигурация сборки (3 платформы)
├── README.md               # Документация
├── firmware.html            # Веб-страница прошивки
└── src/
    └── main.cpp             # Прошивка (480 строк)
```

---

## 4. HARDWARE LAYER — snin-public/hardware/esp32/ (19 модулей)

Эти модули — полная архитектура ESP32-слоя, опубликованная в репо `snin` на GitHub:

### 4.1 Транспорты

| Модуль | Строк | Назначение |
|--------|:-----:|-----------|
| `ble/ble_phy.py` | 263 | BLE физический уровень |
| `lora/lora_phy.py` | 294 | LoRa физический уровень |
| `mdns/mdns_discovery.py` | 259 | mDNS обнаружение устройств в сети |
| `sdk/transport.py` | 290 | Абстракция транспорта |
| `bridge/bridge.py` | 292 | Bridge ESP-NOW → Relay |

### 4.2 Команды и управление

| Модуль | Строк | Назначение |
|--------|:-----:|-----------|
| `command/cmd_handler.py` | 344 | Обработчик команд kind:8012 |
| `command/command_consumer.py` | 175 | Потребитель команд из relay |
| `commission/commission_handler.py` | 314 | Процесс привязки устройства |

### 4.3 Прошивка

| Модуль | Строк | Назначение |
|--------|:-----:|-----------|
| `firmware/snin_sensor.py` | 421 | Основная прошивка (симуляция) |
| `firmware/snin_bridge_fw.py` | 155 | Bridge-прошивка |
| `firmware/ota.py` | 294 | Обновление по воздуху OTA |
| `firmware/config_example.py` | 33 | Пример конфигурации |

### 4.4 Сеть и релей

| Модуль | Строк | Назначение |
|--------|:-----:|-----------|
| `mesh/gps_tracker.py` | 274 | GPS-трекер (kind:8015) |
| `relay/alert_handler.py` | 204 | Обработчик алертов kind:8011 |
| `relay/device_handler.py` | 241 | Регистрация и управление устройствами |
| `power/power_manager.py` | 199 | Управление питанием |

### 4.5 Тестирование

| Модуль | Строк | Назначение |
|--------|:-----:|-----------|
| `sim/sim_sensor.py` | 300 | Симулятор сенсора (Python) |
| `test_smoke.py` | 174 | Smoke-тесты |
| `test/integration_v0.6.py` | 126 | Интеграционные тесты |

---

## 5. MESH-СЕТЬ (топология)

```
                    ┌──────────────┐
                    │  Relay       │
                    │  (relay-snin)│
                    └──────┬───────┘
                           │ WSS
                    ┌──────┴───────┐
                    │  Bridge      │
                    │  (RPi/PC)    │
                    └──────┬───────┘
                           │ ESP-NOW / LoRa / BLE
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐     ┌──────────┐     ┌──────────┐
   │ ESP32 #1 │     │ ESP32 #2 │     │ ESP32 #N │
   │ sensor_01│     │ sensor_02│     │ sensor_N │
   └──────────┘     └──────────┘     └──────────┘
   DHT22 + ADC      BME280 + GPS     DHT22 + ADC
```

Каждый ESP32:
- Публикует kind:8010 с частотой MEASURE_INTERVAL
- Подписан на kind:8012 с фильтром по `#d` (свой device_id)
- При старте публикует kind:8014 (регистрация)
- При ошибке датчика публикует kind:8011 (алерт)

---

## 6. ПОЛНЫЙ ПОТОК ДАННЫХ (end-to-end)

```
Шаг 1: ESP32 регистрируется
  ESP32 → kind:8014 → Relay
  Relay сохраняет: device_id, pubkey, firmware version
  Bot видит: новое устройство в /telemetry

Шаг 2: ESP32 публикует телеметрию
  ESP32 → kind:8010 (раз в 60с) → Relay
  Bot poll (20с): видит новый event
  Bot: "📊 esp32_sensor_01: 23.5°C, 60.2%"

Шаг 3: Пользователь даёт команду
  Telegram: /cmd esp32_sensor_01 read_sensor
  Bot → kind:8012 → Relay
  ESP32 poll (подписка kind:8012 #d=esp32_sensor_01):
    Получает команду → читает DHT22 → публикует kind:8010

Шаг 4: ESP32 шлёт алерт
  ESP32: DHT22 сбой чтения
  ESP32 → kind:8011 (alert: sensor_fail) → Relay
  Bot: "🚨 esp32_sensor_01: sensor_fail — DHT read error"
```

---

## 7. ТЕКУЩИЙ СТАТУС НА 2026-05-14

### На сервере (работает):
```
Relay V2      ☑ relay-snin.v2.site (WSS, REST API)
Telegram Bot  ☑ @Snindaobot (v3.3, 16 команд)
Dashboard     ☑ cryter-dash.v2.site/snin.html
Firmware docs ☑ relay-snin.v2.site/firmware
Multi-Relay   ☑ Симуляция 26 устройств (каждые 10 мин kind:8010)
Chart Gen     ☑ /chart temp, /chart alerts (matplotlib → PNG)
```

### На GitHub (опубликовано):
```
snin                      ☑ NIP-80 протокол + hardware слой (88 файлов)
relay-v2                  ☑ Релей сервер (229 KB)
p2p-agent-mesh            ☑ Mesh networking (177 KB)
analion                   ☑ Analysis Prompts (376 KB)
snin-esp32-firmware       ☑ ESP32 прошивка PlatformIO (v1.0 Direct)
```

### Чего нет на GitHub (инфраструктура):
```
bot.py           ✕ Telegram gateway (825 строк) — токен внутри
snin.html        ✕ Дашборд (11 KB) — привязка к relay-snin
relay_monitor    ✕ Мониторинг релея + webhook
```

---

## 8. СЛЕДУЮЩИЙ ШАГ — v1.1 Mesh Mode

После Direct Mode (v1.0) → **Mesh Mode (v1.1)**:

- ESP32 → ESP-NOW → Bridge → Relay (ESP32 без WiFi, только ESP-NOW)
- LoRa поддержка для километровых дистанций
- Спящий режим между публикациями (глубокий сон ESP32)
- Одноранговая mesh: ESP32 ←→ ESP32 без bridge

Модули для Mesh Mode уже написаны:
- `ble/ble_phy.py` — BLE транспорт
- `lora/lora_phy.py` — LoRa транспорт
- `mdns/mdns_discovery.py` — mDNS обнаружение
- `bridge/bridge.py` — ESP-NOW → Bridge → Relay
- `mesh/gps_tracker.py` — GPS трекер
- `power/power_manager.py` — управление питанием

План: выбрать транспорт, прошить ESP32 как mesh-узел, протестировать.

---

## 9. СТАТИСТИКА

| Метрика | Значение |
|---------|----------|
| Всего ESP32-модулей | 19 .py файлов |
| Строк кода ESP32 | ~4,800 |
| Строк прошивки (C++) | 480 |
| Симулируемых устройств | 26 |
| Режимов работы | 2 (Direct + Mesh) |
| Поддерживаемых транспортов | 4 (WiFi, ESP-NOW, LoRa, BLE) |
| kind-событий в минуту | ~3 (26 устройств × каждые 10 мин) |
| GitHub репозиториев всего | 5 |
| GitHub репозиториев по ESP32 | 2 (snin + snin-esp32-firmware) |
