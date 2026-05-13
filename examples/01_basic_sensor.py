"""
Пример 1: ESP32 датчик температуры (DHT22 + ESP-NOW + Ed25519).

Минимальный рабочий скетч для ESP32.
Измеряет температуру/влажность раз в 30 секунд,
подписывает Ed25519, отправляет ESP-NOW на bridge.

Требуется:
  - ESP32 с DHT22 (GPIO4)
  - bridge.py на RPi или сервере
  - relay-v2 на сервере

Запуск (после прошивки на ESP32):
  - Включить ESP32
  - bridge.py принимает ESP-NOW пакеты
  - relay публикует kind:31000

Работает без интернета (ESP-NOW — Layer 2).
Mesh раздаётся через bridge.
"""

# Это псевдокод. Реальная прошивка на ESP32 пишется на MicroPython.
# См. hardware/esp32/firmware/snin_sensor.py — реальный файл прошивки.

"""
ИМПОРТЫ:
    from machine import Pin
    from dht import DHT22
    from espnow import ESPNow
    from ucryptolib import ed25519

ПОДКЛЮЧЕНИЕ:
    dht = DHT22(Pin(4))          # DHT22 на GPIO4
    espnow = ESPNow()             # ESP-NOW интерфейс
    sk, pk = ed25519.new()       # сгенерировать ключ (один раз)

ЦИКЛ (каждые 30 секунд):
    dht.measure()                # измерить
    payload = {
        "temp": dht.temperature(),
        "hum": dht.humidity(),
        "batt": battery_level(),
    }
    sig = sk.sign(json.dumps(payload))
    packet = json.dumps({
        "topic": "esp32:telemetry",
        "device_id": "sensor_01",
        "seq": seq_counter(),
        "payload": payload,
        "sig": sig.hex(),
        "pk": pk.hex(),
    })
    espnow.send(bridge_mac, packet)
    sleep(30)

РЕЗУЛЬТАТ:
  ESP-NOW -> bridge (верифицирует Ed25519, публикует kind:31000)
  -> relay-v2 -> DAO Pilot (читает телеметрию)
"""
