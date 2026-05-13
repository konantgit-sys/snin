# SNIN v0.6 — Device Control Loop

> Конкретная спецификация. Что строим, зачем, как запускаем.
> Дата: 2026-05-13

---

## 1. Проблема

Сейчас ESP32 может **отправить** телеметрию (kind:31000), но **не может принять команду** от DAO или другого агента. Kind:31002 определён в протоколе, но bridge не подписан на него. Это half-duplex — датчик кричит, но не слышит.

**Без управления нет роя.** Есть односторонние датчики.

---

## 2. Что делаем

### 2.1 Device Command Loop (kind:31002) — P0

Мост ESP32 → relay-v2:
- bridge подписывается на kind:31002
- При получении команды — шлёт ESP32 по ESP-NOW / UART
- ESP32 выполняет: вкл/выкл GPIO, изменение интервала, реле, вентилятор

```
DAO/Agent → kind:31002 → relay-v2 → bridge → ESP-NOW → ESP32
                                        ↓
                                    ACK kind:31000 (cmd_result)
```

**Что создать:**
- `hardware/esp32/command/cmd_handler.py` — парсинг kind:31002, маршрутизация по device_id
- `hardware/esp32/command/actions.py` — таблица действий: set_gpio, set_interval, reboot, read_sensor
- `bridge/command_consumer.py` — подписка bridge на kind:31002, форвард в UART
- `firmware/snin_sensor.py` — добавить listener ESP-NOW (сейчас только sender)

### 2.2 Power Manager — P1

ESP32 на батарейках должен спать. Сейчас он шлёт каждые N секунд и жрёт батарею.

**Что создать:**
- `hardware/esp32/power/sleep_scheduler.py` — deep sleep между отправками
- `hardware/esp32/power/battery_monitor.py` — уровень заряда, предупреждение на kind:31007
- Конфиг: интервал сна, порог батареи, wake-on-ESP-NOW (если поддерживается)

### 2.3 Device Alert (kind:31007) — P1

ESP32 шлёт алерт если: батарея < 10%, температура > 50°C, сенсор не отвечает.

- `relay/alert_handler.py` — фильтр алертов, дедупликация
- `firmware/snin_sensor.py` — условие алерта

### 2.4 OTA Update (kind:31003) — P2

Обновление прошивки ESP32 по воздуху через relay-v2.

- `firmware/ota_server.py` — на bridge: хранит версии, шлёт kind:31003
- `firmware/ota_client.py` — на ESP32: принимает, записывает, перезагружается

---

## 3. Схема (v0.6)

```
ESP32 ── ESP-NOW/LoRa/BLE ──→ bridge ── AgentMesh ── relay-v2
  │                                                    │
  │◄── kind:31002 (command) ─── bridge ◄───────────  DAO Pilot
  │◄── kind:31003 (OTA) ─────── bridge ◄───────────  OTA Server
  │──── kind:31007 (alert) ──── bridge ──────────►  relay-v2
  │──── kind:31000 (telemetry) ── bridge ──────────► relay-v2
```

---

## 4. Файлы (что создаём)

```
hardware/esp32/
├── command/
│   ├── cmd_handler.py      (~200 строк) — парсинг kind:31002, маршрут
│   ├── actions.py           (~150 строк) — таблица действий
│   └── command_consumer.py  (~120 строк) — bridge подписка
├── power/
│   ├── sleep_scheduler.py   (~150 строк) — deep sleep config
│   └── battery_monitor.py   (~100 строк) — заряд + алерт
├── relay/
│   └── alert_handler.py     (~120 строк) — kind:31007
├── firmware/
│   ├── ota_server.py        (~200 строк) — на bridge
│   └── ota_client.py        (~150 строк) — на ESP32
│
Всего: ~1200 строк, 8 файлов
```

---

## 5. Тесты

| Тест | Что проверяет |
|------|--------------|
| `test_smoke.py` | не сломалось ли старое |
| `test/command_test.py` | команда → bridge → ESP32 (симуляция) |
| `test/alert_test.py` | алерт при батарее < 10% |
| `test/ota_test.py` | цикл OTA (без железа) |

---

## 6. Что нужно от тебя

1. **Приоритет:** что делаем в первую очередь? (команды / питание / OTA / алерты)
2. **ESP32 железо:** какая конкретно плата? (ESP32-S3, T-Watch, M5Stack?) — влияет на deep sleep и ESP-NOW listener
3. **Питание:** датчик на батарейках всегда или USB? — deep sleep нужен или нет
4. **Канал связи:** команды будут приходить через какой транспорт? (ESP-NOW / LoRa / WiFi / BLE)
5. **Что нужно прямо сейчас:** Python модули для теста на PC или сразу прошивка для ESP32?

---

## 7. Статус репозитория (перед v0.6)

```
v0.5 ✅ — Production quality: CI/CD, PyPI, examples, EN docs
        (38 файлов, ~5500 строк, все тесты проходят)
──────────────────────────────────────────────────────────
v0.6 ⏳ — Device Control Loop
       (Эта спецификация + твой ответ)
```
