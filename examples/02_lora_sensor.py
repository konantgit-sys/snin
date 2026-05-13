"""
Пример 2: ESP32 + LoRa (дальняя связь, 2-15km).

Когда WiFi/ESP-NOW не работают — поле, лес, сельское хозяйство.
Используем SX1278 (433/868/915 MHz) через SPI.

Отличие от ESP-NOW:
  - Пакет 64 байта (не 250) → фрагментация
  - Latency ~100ms (не 1ms)
  - Дальность 15km (не 200m)

Требуется:
  - ESP32 + SX1278 (Heltec LoRa или отдельный модуль)
  - LoRa Gateway на RPi (вторая SX1278 + USB)

Запуск:
  1. Прошить ESP32 с LoRa
  2. Запустить bridge с LoRa-драйвером
  3. Включить ESP32

Схема подключения SX1278 к ESP32:
  ESP32          SX1278
  GPIO18  ───── SCK
  GPIO23  ───── MOSI
  GPIO19  ───── MISO
  GPIO5   ───── CS
  GPIO26  ───── DIO0
  3.3V    ───── VCC
  GND     ───── GND
"""

import json
from hardware.esp32.lora.lora_phy import SX1278Transport, PacketFragmenter

# Инициализация (на PC — симуляция, на ESP32 — SPI)
lora = SX1278Transport(
    spi_id=1,      # SPI bus
    cs=5,          # Chip select pin
    dio0=26,       # DIO0 pin
    freq=868,      # 868 MHz (EU) / 915 MHz (US) / 433 MHz
    sf=12,         # Spreading factor (12 = max range)
    bw=125,        # Bandwidth 125 kHz
    tx_power=20,   # +20 dBm
)

# На ESP32 (MicroPython): раскомментировать
# lora.init_micropython()

# Отправка пакета (авто-фрагментация)
packet = json.dumps({
    "topic": "esp32:telemetry",
    "device_id": "lora_sensor_01",
    "seq": 42,
    "payload": {"temp": 23.5, "hum": 60.2, "batt": 85},
    "pk": "...",  # Ed25519 публичный ключ
    "sig": "...",  # Ed25519 подпись
}).encode()

fragments = PacketFragmenter.fragment(packet)
print(f"Fragment: {len(packet)}B → {len(fragments)}×{len(fragments[0])}B")

# На ESP32:
# for frag in fragments:
#     lora.send_packet(frag)
#     time.sleep_ms(200)

# Приём на Gateway
# received = lora.receive_packet(timeout_ms=10000)
# if received:
#     restored = PacketFragmenter.defragment([received])
