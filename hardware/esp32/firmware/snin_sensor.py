"""
SNIN ESP32 — Firmware: Sensor Node

Прошивка для ESP32 с датчиком. Читает сенсор, подписывает Ed25519, 
шлёт по ESP-NOW на bridge.

Прошивка: MicroPython v1.23+
Датчик: DHT22 (температура + влажность)
Транспорт: ESP-NOW → Serial bridge

Поток:
    DHT22 → ESP32 → ESP-NOW (250B пакет) → ESP32-bridge → UART → bridge.py

Установка на ESP32:
    1. Установить MicroPython: esptool.py write_flash 0x1000 firmware.bin
    2. Скопировать файлы: ampy put main.py && ampy put snin_sensor.py
    3. Настроить WiFi + ключи в config.py (создать на ESP32 вручную)
    4. Перезагрузить ESP32

Зависимости (на ESP32):
    - ucrypto (для Ed25519 подписей) — upip install ucrypto
    - DHT22 — встроен в MicroPython
"""

import json
import time
import machine
import network
import espnow
import ustruct

# ─── Настройки (редактировать перед прошивкой) ─────────────────
CONFIG = {
    "wifi_ssid": "SNIN_MESH",
    "wifi_password": "",
    "device_id": "sensor_kitchen_01",
    "sensor_type": "temperature",
    "measure_interval": 60,       # секунд между измерениями
    "bridge_mac": b'\xff\xff\xff\xff\xff\xff',  # MAC bridge (broadcast пока)
    # Приватный ключ Ed25519 (64 hex символа) — задаётся в config.py
    "private_key_hex": "",
}

# ─── DHT22 датчик ───────────────────────────────────────────────
class DHT22Sensor:
    """Чтение температуры и влажности с DHT22."""
    def __init__(self, pin: int = 4):
        from dht import DHT22
        self._sensor = DHT22(machine.Pin(pin))
        self._last_read = 0
        self._last_temp = 0.0
        self._last_hum = 0.0

    def read(self) -> dict | None:
        """Прочитать датчик. Кеширует 2 секунды."""
        now = time.time()
        if now - self._last_read < 2:
            return None  # слишком часто

        try:
            self._sensor.measure()
            self._last_temp = self._sensor.temperature()
            self._last_hum = self._sensor.humidity()
            self._last_read = now
            return {
                "temp": round(self._last_temp, 1),
                "hum": round(self._last_hum, 1),
            }
        except Exception as e:
            return {"error": str(e)}


# ─── Ed25519 подпись через ucrypto ──────────────────────────────
class Ed25519Signer:
    """Подпись сообщений Ed25519. Совместимо с bridge (Python cryptography)."""
    def __init__(self, private_key_hex: str):
        from ucrypto import ecdsa
        self._ecdsa = ecdsa
        self._privkey = bytes.fromhex(private_key_hex)
        self._pubkey = ecdsa.public_key(self._privkey)

    @property
    def pubkey_hex(self) -> str:
        return self._pubkey.hex()

    def sign(self, data: bytes) -> str:
        sig = self._ecdsa.sign(data, self._privkey)
        return sig.hex()


# ─── ESP-NOW интерфейс ──────────────────────────────────────────
class ESPNOWInterface:
    """Отправка сообщений через ESP-NOW на bridge."""
    def __init__(self, bridge_mac: bytes):
        import espnow as _espnow
        self._esp = _espnow.ESPNow()
        self._esp.active(True)
        self._esp.add_peer(bridge_mac)
        self._bridge_mac = bridge_mac
        self._sent = 0

    def send(self, data: bytes) -> bool:
        """Отправить пакет ESP-NOW. Макс 250 байт."""
        if len(data) > 250:
            data = data[:250]
        self._esp.send(self._bridge_mac, data)
        self._sent += 1
        return True

    @property
    def sent_count(self) -> int:
        return self._sent


# ─── Sequence counter ───────────────────────────────────────────
class SeqCounter:
    """Монотонный счётчик. Сохраняется в RTC memory."""
    def __init__(self):
        from machine import RTC
        self._rtc = RTC()
        self._seq = self._rtc.memory()[0] if self._rtc.memory() else 0

    def next(self) -> int:
        self._seq += 1
        from machine import RTC
        RTC().memory(bytes([self._seq & 0xFF]))
        return self._seq


# ─── Главный класс датчика ──────────────────────────────────────
class SNINSensorNode:
    """ESP32-узел SNIN: читает датчик, подписывает, шлёт в mesh."""
    def __init__(self, config: dict):
        self._config = config
        self._seq = SeqCounter()
        self._signer = Ed25519Signer(config["private_key_hex"])
        self._sensor = DHT22Sensor(pin=4)  # GPIO4
        self._espnow = ESPNOWInterface(
            bytes.fromhex(config["bridge_mac"].hex())
            if isinstance(config["bridge_mac"], str)
            else config["bridge_mac"]
        )
        self._running = False
        self._stats = {"published": 0, "errors": 0}

    def start(self):
        """Запустить цикл измерений."""
        self._running = True
        self._init_wifi()
        print(f"SNIN sensor started: {self._config['device_id']}")
        print(f"Pubkey: {self._signer.pubkey_hex}")

        while self._running:
            try:
                self._measure_and_send()
                self._stats["published"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                print(f"Error: {e}")

            # Глубокий сон между измерениями
            sleep_sec = self._config.get("measure_interval", 60)
            print(f"Sleep {sleep_sec}s... stats: {self._stats}")
            time.sleep(sleep_sec)

    def _init_wifi(self):
        """Инициализация WiFi + ESP-NOW.
        ESP-NOW требует активного WiFi (даже без подключения к роутеру).
        """
        import network
        wlan = network.WLAN(network.STA_IF)
        wlan.active(False)
        time.sleep_ms(200)
        wlan.active(True)
        if self._config.get("wifi_password"):
            wlan.connect(self._config["wifi_ssid"], self._config["wifi_password"])
            while not wlan.isconnected():
                time.sleep_ms(100)
        print(f"WiFi OK. MAC: {wlan.config('mac').hex()}")

    def _measure_and_send(self):
        """Измерить → подписать → отправить ESP-NOW → bridge."""
        # 1. Чтение датчика
        data = self._sensor.read()
        if data is None:
            return
        if "error" in data:
            print(f"Sensor error: {data['error']}")
            return

        # 2. Формируем пакет
        seq = self._seq.next()
        packet = {
            "topic": "esp32:telemetry",
            "device_id": self._config["device_id"],
            "seq": seq,
            "payload": data,
            "ts": time.time(),
        }

        # 3. Подписываем (только topic + payload + seq)
        msg_to_sign = json.dumps({
            "topic": packet["topic"],
            "payload": packet["payload"],
            "seq": seq,
        }).encode()

        packet["pk"] = self._signer.pubkey_hex
        packet["signature"] = self._signer.sign(msg_to_sign)

        # 4. Отправляем ESP-NOW (JSON ≤ 250 байт)
        payload_bytes = json.dumps(packet).encode()
        if len(payload_bytes) > 250:
            print(f"Packet too large: {len(payload_bytes)} bytes")
            return

        self._espnow.send(payload_bytes)
        print(f"Sent seq={seq} temp={data.get('temp')}° hum={data.get('hum')}% "
              f"sig={packet['signature'][:16]}...")
        print(f"  raw: {len(payload_bytes)}B / 250B ESP-NOW")

    def stats(self) -> dict:
        return {
            **self._stats,
            "espnow_sent": self._espnow.sent_count,
        }


# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 40)
    print("SNIN ESP32 Sensor Node v0.1")
    print("=" * 40)

    # Попробовать загрузить config из файла на ESP32
    try:
        import config
        CONFIG.update({k: v for k, v in config.__dict__.items() if not k.startswith("_")})
        print(f"Config loaded from config.py")
    except ImportError:
        print("No config.py — using defaults. Keys may be empty!")

    if not CONFIG.get("private_key_hex"):
        print("⚠️  PRIVATE_KEY не задан! Подпись будет пустой.")
        print("   Создай config.py на ESP32 с private_key_hex = '...'")
        # Генерация для теста
        from ucrypto import ecdsa
        import os
        priv = os.urandom(32)
        CONFIG["private_key_hex"] = priv.hex()
        print(f"   Сгенерирован тестовый ключ: {priv.hex()}")
        print(f"   Публичный: {ecdsa.public_key(priv).hex()}")
        print(f"   Сохрани этот ключ в bridge для верификации!")

    node = SNINSensorNode(CONFIG)
    node.start()
