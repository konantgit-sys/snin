# SNIN Hardware Platforms — Specification v0.2

**Дата:** 2026-05-13  
**Автор:** Юрий Писаренко (@ayupro)  
**Статус:** Черновик  

---

## 1. Purpose

Единый SNIN-клиент для всех популярных аппаратных платформ.
Каждая платформа реализует одинаковый протокол:
**read sensor → sign Ed25519 → send to bridge → mesh → relay-v2 → DAO**

---

## 2. Platform Matrix

| Платформа | CPU | RAM | Flash | Язык | Сеть | Экран | Роль в рое |
|-----------|-----|-----|-------|------|------|-------|-----------|
| **ESP32-S3** | Xtensa LX7 240MHz | 512KB | 16MB | MicroPython / C | WiFi + ESP-NOW | опционально TFT | Sensor node / Bridge |
| **ESP8266** | Xtensa LX3 80MHz | 80KB | 4MB | C++ (Arduino) | WiFi | нет | Sensor (лёгкий) |
| **Arduino R4** | ARM Cortex-M4 48MHz | 32KB | 256KB | C++ | WiFi | LED matrix | Sensor (базовый) |
| **Raspberry Pi 4/5** | ARM Cortex-A72 1.8GHz | 4-8GB | microSD | Python | WiFi + Eth | HDMI | Bridge / Full agent / Relay |
| **Raspberry Pi Zero 2W** | ARM Cortex-A53 1GHz | 512MB | microSD | Python | WiFi | mini HDMI | Bridge / Light agent |
| **M5Stack Core2** | ESP32-D0WDQ6 | 520KB | 16MB | MicroPython / C++ | WiFi + BT | TFT 320x240 | Sensor + Display |
| **TTGO T-Display** | ESP32-S3 | 512KB | 16MB | MicroPython / C++ | WiFi | ST7789 170x320 | Wearable display |
| **LilyGO T-Watch** | ESP32-S3 | 512KB | 16MB | MicroPython | WiFi + BT | LCD 240x240 | Wrist DAO terminal |
| **Banana Pi M5** | ARM Cortex-A55 1.5GHz | 4GB | 32GB eMMC | Python | WiFi + Eth | HDMI | Full node |

---

## 3. Protocol Layers (все платформы)

```
┌──────────────────────────────────────────────────┐
│                    APPLICATION                     │
│  sensor read / display render / DAO vote          │
├──────────────────────────────────────────────────┤
│                  SNIN PROTOCOL                     │
│  Ed25519 sign/verify + seq + topic + payload      │
├──────────────────────────────────────────────────┤
│                  TRANSPORT                         │
│  ESP-NOW  │  WiFi TCP  │  Ethernet  │  Serial     │
├──────────────────────────────────────────────────┤
│                  HARDWARE                          │
│  ESP32  │  Arduino  │  RPi  │  M5Stack  │  ...    │
└──────────────────────────────────────────────────┘
```

### 3.1 Packet format (все платформы — идентичный)

```json
{
  "topic": "esp32:telemetry",
  "device_id": "sensor_kitchen_01",
  "seq": 42,
  "payload": {"temp": 23.5, "hum": 60.2},
  "ts": 1700000000,
  "pk": "a1b2c3...",
  "signature": "ed25519_hex_sig"
}
```

**Ограничения по платформам:**

| Платформа | Макс размер пакета | Транспорт |
|-----------|-------------------|-----------|
| ESP32 (ESP-NOW) | 250 байт | ESP-NOW |
| ESP32 (WiFi) | 4096 байт | TCP/UDP |
| Arduino R4 | 512 байт | WiFiUDP |
| RPi (все) | 65535 байт | TCP full |
| M5Stack (ESP-NOW) | 250 байт | ESP-NOW |
| TTGO T-Display | 250 байт | ESP-NOW |

---

## 4. Platform Feature Comparison

| Feature | ESP32 (uP) | Arduino (C++) | RPi (Python) | Display devices |
|---------|-----------|--------------|--------------|-----------------|
| Ed25519 sign | ✅ ucrypto | ⚠️ Ed25519-Micro | ✅ cryptography | ✅ ucrypto |
| ESP-NOW | ✅ встроен | ✅ ESP-NOW lib | ❌ | ✅ встроен |
| TCP client | ✅ usocket | ✅ WiFiClient | ✅ socket | ✅ usocket |
| GPIO read | ✅ machine | ✅ digitalRead | ✅ gpiozero/RPi.GPIO | ✅ machine |
| I2C/SPI | ✅ machine | ✅ Wire/SPI | ✅ smbus/spidev | ✅ machine |
| Display | ⚠️ framebuf | ✅ TFT_eSPI, U8g2 | ✅ pygame, tkinter | ✅ framebuf/LVGL |
| Deep sleep | ✅ machine | ✅ ESP.deepSleep | ⚠️ (не нужно) | ✅ machine |
| WAL | ✅ SPIFFS | ✅ EEPROM/SD | ✅ SQLite/file | ✅ SPIFFS |
| Raft | ❌ (тяжело) | ❌ | ✅ coordination/ | ❌ |
| Full AgentMesh | ❌ | ❌ | ✅ | ❌ |
| relay-v2 node | ❌ | ❌ | ✅ | ❌ |

---

## 5. Роли платформ в рое

```
                    INTERNET
                       │
              ┌────────▼────────┐
              │  Raspberry Pi   │ ← Полный узел: relay-v2 + AgentMesh + DAO
              │  (4/5 / Zero)   │    Python full-stack, база данных
              └────────┬────────┘
                       │ TCP / HTTP relay
                       │
              ┌────────▼────────┐
              │  ESP32 Bridge   │ ← Принимает ESP-NOW, форвардит в TCP
              │  (S3 / C6)      │    WAL, Ed25519 verify, bridge.py
              └────────┬────────┘
                       │ ESP-NOW (250B, ~200м)
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ╔══════════╗  ╔══════════╗  ╔══════════╗
   ║ ESP32    ║  ║ Arduino  ║  ║ M5Stack  ║
   ║ Sensor   ║  ║ Sensor   ║  ║ Display  ║
   ║ DHT22    ║  ║ BME280   ║  ║ OLED     ║
   ╚══════════╝  ╚══════════╝  ╚══════════╝
         ▲             ▲             ▲
         │             │             │
   ╔══════════╗  ╔══════════╗  ╔══════════╗
   ║ TTGO    ║  ║ LilyGO   ║  ║ ESP8266  ║
   ║ T-Watch ║  ║ T-Watch  ║  ║ Light    ║
   ║ Wear    ║  ║ Wrist    ║  ║ Sensor   ║
   ╚══════════╝  ╚══════════╝  ╚══════════╝
```

---

## 6. Code Reuse Strategy

| Компонент | ESP32 (uP) | Arduino (C++) | RPi (Python) | Display |
|-----------|-----------|--------------|--------------|---------|
| Crypto Ed25519 | ucrypto | crypto_sign Ed25519 | cryptography | ucrypto |
| Packet format | ujson | ArduinoJson | json | ujson |
| WAL | spiffs + ujson | SD + ArduinoJson | sqlite3 | spiffs |
| Display render | — | — | — | LVGL / framebuf |
| Bridge client | urequests | HTTPClient | aiohttp | urequests |
| CLI config | upython | Serial menu | argparse | upython |

**80% кода — один протокол.** Разные только:
- Язык (MicroPython vs C++ vs Python)
- Библиотеки под конкретную платформу
- Дисплей (если есть)
- Энергопотребление (если батарея)

---

## 7. Arduino Specific (C++)

### Ограничения
- Arduino Uno R3: 2KB RAM — **не может** Ed25519 (32KB ключи не влезут)
- Arduino R4: 32KB RAM — может Ed25519, но без ESP-NOW
- ESP8266 (Arduino IDE): 80KB RAM — может, ESP-NOW есть

### Решение
Arduino SDK **только для ESP8266 + ESP32 (Arduino framework)**.
Для Uno/Nano — слишком мало RAM.

### Стек
```
Platform: ESP8266 / ESP32 (Arduino IDE)
Framework: Arduino Core + ESP-NOW
Crypto: Ed25519-Micro (port of ucrypto to C++)
JSON: ArduinoJson (v7)
Display: TFT_eSPI (if present)
```

---

## 8. Raspberry Pi Specific

### Возможности (нет ограничений)
- Полный Python, полный p2p-agent-mesh
- Может работать как **bridge + agent + relay** одновременно
- GPIO для подключения датчиков
- HDMI для подключения монитора/дисплея
- USB для камеры, SDR, LoRa

### Стек
```
AgentMesh (полный, из p2p-agent-mesh)
relay-v2 (может запустить Nostr relay)
GPIO: gpiozero / RPi.GPIO
Display: pygame / tkinter / kivy
Files: SQLite (WAL), SD card
```

---

## 9. Display Devices Specific

### Что это
- M5Stack (ESP32 + TFT 320x240)
- TTGO T-Display (ESP32 + ST7789)
- LilyGO T-Watch (ESP32 + LCD + сенсор)
- Waveshare RP2040 (RP2040 + LCD)

### Что дают
- DAO-голосование на экране: показать вопрос → кнопки Да/Нет
- Статус роя: количество ESP32, температура сети
- Личный dashboard для агента

### Стек дисплея
```
MicroPython: framebuf + machine.SPI + ili9341/st7789
C++: LVGL (Light and Versatile Graphics Library) — 8KB RAM
```

---

## 10. Implementation Priority

| Приоритет | Платформа | Срок | Зависит от |
|-----------|-----------|------|-----------|
| P0 | ESP32 (MicroPython) | ✅ готов | — |
| P1 | Raspberry Pi (Python) | 1 день | p2p-agent-mesh |
| P2 | ESP32 + Display (uP) | 2 дня | framebuf libs |
| P3 | Arduino C++ (ESP8266) | 3 дня | Ed25519 C порт |
| P4 | M5Stack | 2 дня | LVGL порт |
| P5 | TTGO / LilyGO | 1 день | готовый драйвер |
| P6 | Arduino R4 | 5 дней | RAM ограничения |
