"""
SNIN ESP32 — Firmware: ESP-NOW → UART Bridge

Вторая ESP32 в системе. Принимает ESP-NOW пакеты от сенсоров,
форвардит их по UART (Serial) на bridge.py (на компьютере/RPi).

Почему нужна вторая ESP32:
  - Сенсорная ESP32 может быть глубоко во дворе/поле (без USB)
  - Bridge ESP32 стоит рядом с компьютером и подключена по USB
  - ESP-NOW работает на ~200м между ESP32

Прошивка: MicroPython v1.23+
Соединение: UART (USB) → bridge.py @ 115200 baud
"""

import json
import time
import machine
import network
import espnow


# ─── Настройки ──────────────────────────────────────────────────
CONFIG = {
    "wifi_ssid": "SNIN_MESH",
    "wifi_password": "",
    "bridge_id": "esp32_bridge_unit",
    # Если известны MAC сенсоров — добавить для фильтрации
    "sensor_whitelist": [],  # ["aabbccddeeff", ...]
}

# ─── LED индикатор ──────────────────────────────────────────────
class StatusLED:
    def __init__(self, pin: int = 2):
        self._led = machine.Pin(pin, machine.Pin.OUT)
        self._led.value(0)

    def blink(self, times: int = 1, delay_ms: int = 100):
        for _ in range(times):
            self._led.value(1)
            time.sleep_ms(delay_ms)
            self._led.value(0)
            time.sleep_ms(delay_ms)

    def on(self):
        self._led.value(1)

    def off(self):
        self._led.value(0)


# ─── ESP-NOW слушатель ──────────────────────────────────────────
class ESPNOWListener:
    """Слушает ESP-NOW от сенсоров, передаёт в callback."""
    def __init__(self, whitelist: list[bytes] | None = None):
        self._esp = espnow.ESPNow()
        self._esp.active(True)
        self._whitelist = whitelist or []

    def receive(self) -> tuple[bytes | None, bytes | None]:
        """Получить пакет. Возвращает (mac, data) или (None, None)."""
        mac, data = self._esp.recv(0)  # non-blocking
        if mac is None:
            return None, None
        if self._whitelist and mac not in self._whitelist:
            return None, None
        return mac, data


# ─── UART форвардер ─────────────────────────────────────────────
class UARTForwarder:
    """Отправляет JSON-строки по UART на bridge.py."""
    def __init__(self, uart_id: int = 0, baud: int = 115200):
        self._uart = machine.UART(uart_id, baud)
        self._forwarded = 0

    def forward(self, data: bytes, mac: bytes | None = None):
        """Форвард пакета на bridge.py.
        Формат: JSON-строка + \\n (readline на bridge.py).
        """
        import ustruct
        # Добавляем MAC отправителя если есть
        packet = {
            "mac": mac.hex() if mac else "unknown",
            "data": data.decode("utf-8", errors="replace"),
            "rssi": 0,
            "ts": time.time(),
        }
        line = json.dumps(packet) + "\n"
        self._uart.write(line)
        self._forwarded += 1

    @property
    def count(self) -> int:
        return self._forwarded


# ─── Главный класс bridge-прошивки ──────────────────────────────
class SNINBridgeFirmware:
    """ESP32-bridge: ESP-NOW → UART → bridge.py.
    Работает бесконечно, форвардит пакеты сенсоров на компьютер.
    """
    def __init__(self, config: dict):
        self._config = config
        self._led = StatusLED(pin=2)
        self._whitelist = [
            bytes.fromhex(m) for m in config.get("sensor_whitelist", [])
            if len(m) == 12
        ]
        self._listener = ESPNOWListener(whitelist=self._whitelist)
        self._forwarder = UARTForwarder(uart_id=0, baud=115200)
        self._running = False
        self._stats = {"received": 0, "forwarded": 0, "errors": 0}

    def start(self):
        """Запустить bridge."""
        self._running = True
        self._init_wifi()

        print(f"SNIN Bridge firmware started")
        print(f"Whitelist: {[m.hex() for m in self._whitelist] or 'ALL'}")

        # Сигнал готовности: 3 коротких моргания
        self._led.blink(3, 100)
        self._led.on()

        while self._running:
            try:
                mac, data = self._listener.receive()
                if mac is None:
                    time.sleep_ms(10)
                    continue

                self._stats["received"] += 1

                if data:
                    self._forwarder.forward(data, mac)
                    self._stats["forwarded"] += 1
                    # Моргание при каждом пакете
                    self._led.blink(1, 30)
                else:
                    self._stats["errors"] += 1

            except Exception as e:
                self._stats["errors"] += 1
                print(f"Error: {e}")
                time.sleep_ms(100)

    def _init_wifi(self):
        """Включить WiFi (нужен для ESP-NOW)."""
        wlan = network.WLAN(network.STA_IF)
        wlan.active(False)
        time.sleep_ms(200)
        wlan.active(True)
        if self._config.get("wifi_password"):
            wlan.connect(self._config["wifi_ssid"], self._config["wifi_password"])
            timeout = 10
            while not wlan.isconnected() and timeout > 0:
                time.sleep_ms(500)
                timeout -= 1
            if wlan.isconnected():
                print(f"WiFi connected: {wlan.ifconfig()}")
            else:
                print(f"WiFi timeout — ESP-NOW всё равно работает")
        print(f"MAC: {wlan.config('mac').hex()}")

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "uart_sent": self._forwarder.count,
        }


# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 40)
    print("SNIN ESP32 Bridge Firmware v0.1")
    print("=" * 40)

    try:
        import config
        CONFIG.update({k: v for k, v in config.__dict__.items() if not k.startswith("_")})
    except ImportError:
        pass

    bridge = SNINBridgeFirmware(CONFIG)
    bridge.start()
