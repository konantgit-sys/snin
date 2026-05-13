"""
SNIN ESP32 — Firmware: ESP-NOW ↔ UART Bridge (duplex v0.6)

Вторая ESP32 в системе. Два направления:

  Sensor ESP32 ──ESP-NOW──→ Bridge ESP32 ──UART──→ bridge.py

  Sensor ESP32 ←──ESP-NOW── Bridge ESP32 ←──UART── bridge.py (kind:31002)

Прошивка: MicroPython v1.23+
"""

import json
import time
import machine
import network
import espnow

# ─── Настройки ─────────────────────────────────────────────────
CONFIG = {
    "wifi_ssid": "SNIN_MESH",
    "wifi_password": "",
    "device_id": "bridge_esp_01",
    "uart_baud": 115200,
    "uart_tx_pin": 1,    # GPIO1 = TX
    "uart_rx_pin": 3,    # GPIO3 = RX
}


class ESPNowUARTBridge:
    """ESP-NOW ↔ UART двусторонний мост.

    Поток A (телеметрия):
        ESP-NOW ← sensor → UART → bridge.py

    Поток B (команды):
        UART ← bridge.py → ESP-NOW → sensor
    """

    def __init__(self, config: dict):
        self._config = config

        # UART
        self._uart = machine.UART(
            1,
            baudrate=config["uart_baud"],
            tx=machine.Pin(config["uart_tx_pin"]),
            rx=machine.Pin(config["uart_rx_pin"]),
        )
        self._uart.init(timeout=10)

        # ESP-NOW
        import espnow as _espnow
        self._esp = _espnow.ESPNow()
        self._esp.active(True)

        # Статистика
        self._stats = {
            "esp_to_uart": 0,
            "uart_to_esp": 0,
            "errors": 0,
        }

    def start(self):
        self._init_wifi()
        print(f"SNIN Bridge ESP32: {self._config['device_id']}")
        print(f"ESP-NOW → UART | UART → ESP-NOW")
        print(f"Listening...")

        while True:
            try:
                # Поток A: ESP-NOW → UART
                self._forward_esp_to_uart()

                # Поток B: UART → ESP-NOW (команды)
                self._forward_uart_to_esp()

            except Exception as e:
                self._stats["errors"] += 1
                print(f"Error: {e}")

            time.sleep_ms(10)  # небольшой idle

    def _init_wifi(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(False)
        time.sleep_ms(200)
        wlan.active(True)
        if self._config.get("wifi_password"):
            wlan.connect(self._config["wifi_ssid"], self._config["wifi_password"])
            while not wlan.isconnected():
                time.sleep_ms(100)
        print(f"WiFi OK. ESP-NOW active.")

    def _forward_esp_to_uart(self):
        """Принять ESP-NOW от сенсора → отправить в UART."""
        try:
            host, msg = self._esp.recv(0)  # non-blocking
            if msg:
                line = msg.decode().strip()
                # Добавляем маркер, чтобы bridge.py различал пакеты
                self._uart.write(f"[ESP]{line}\n")
                self._stats["esp_to_uart"] += 1
        except OSError:
            pass  # нет пакета
        except Exception as e:
            print(f"ESP→UART error: {e}")

    def _forward_uart_to_esp(self):
        """Принять команду из UART → отправить ESP-NOW сенсору."""
        try:
            if self._uart.any():
                line = self._uart.readline()
                if line:
                    text = line.decode().strip()
                    if text.startswith("[CMD]") or text.startswith("{"):
                        clean = text[5:] if text.startswith("[CMD]") else text
                        try:
                            cmd = json.loads(clean)
                            # Определяем получателя по device_id
                            target = cmd.get("device_id", "")
                            if target:
                                # Ищем MAC по device_id (в реальности — таблица)
                                self._esp.send(b'\xff\xff\xff\xff\xff\xff',
                                               json.dumps(cmd).encode())
                                self._stats["uart_to_esp"] += 1
                            else:
                                # Broadcast
                                self._esp.send(b'\xff\xff\xff\xff\xff\xff',
                                               json.dumps(cmd).encode())
                                self._stats["uart_to_esp"] += 1
                        except ValueError:
                            pass
        except Exception as e:
            print(f"UART→ESP error: {e}")

    def stats(self) -> dict:
        return dict(self._stats)


# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 40)
    print("SNIN ESP32 Bridge v0.6 (Duplex)")
    print("=" * 40)

    try:
        import config
        CONFIG.update({k: v for k, v in config.__dict__.items()
                      if not k.startswith("_")})
    except ImportError:
        pass

    bridge = ESPNowUARTBridge(CONFIG)
    bridge.start()
