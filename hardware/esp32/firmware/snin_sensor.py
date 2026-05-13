"""
SNIN ESP32 — Firmware: Sensor Node (v0.6 с поддержкой команд)

Прошивка для ESP32 с датчиком. Читает сенсор, подписывает Ed25519,
шлёт по ESP-NOW на bridge, принимает команды (kind:31002) по ESP-NOW.

Прошивка: MicroPython v1.23+
Датчик: DHT22 (температура + влажность)
Транспорт: ESP-NOW (duplex — отправка + приём команд)

Поток:
    DHT22 → ESP32 → ESP-NOW (250B) → ESP32-bridge → bridge.py → relay-v2
                                                          │
    ESP32 ◄── ESP-NOW (command) ◄── bridge.py ◄────── kind:31002

Установка:
    1. Установить MicroPython на ESP32
    2. ampy put snin_sensor.py
    3. Создать config.py с WiFi + private_key
    4. Перезагрузить ESP32
"""

import json
import time
import machine
import network
import espnow
import ustruct

# ─── Настройки по умолчанию ─────────────────────────────────────
CONFIG = {
    "wifi_ssid": "SNIN_MESH",
    "wifi_password": "",
    "device_id": "sensor_kitchen_01",
    "sensor_type": "temperature",
    "measure_interval": 60,          # секунд между измерениями
    "bridge_mac": b'\xff\xff\xff\xff\xff\xff',  # broadcast
    "private_key_hex": "",           # Ed25519 приватный ключ (64 hex)
    "adc_battery_pin": 35,           # ADC для мониторинга батареи
    "power_mode": "usb",             # usb | battery
    "low_battery_threshold": 10,     # % для алерта
}

# ─── Команды ESP32 ───────────────────────────────────────────────
class CommandAction:
    SET_GPIO = "set_gpio"
    SET_INTERVAL = "set_interval"
    READ_SENSOR = "read_sensor"
    REBOOT = "reboot"
    SET_CONFIG = "set_config"
    PAUSE = "pause"
    RESUME = "resume"
    START_OTA = "start_ota"


class CommandHandler:
    """Обработчик команд на ESP32. Вызывается при получении kind:31002."""

    def __init__(self, sensor_node):
        self.node = sensor_node
        self._paused = False

    def handle(self, cmd: dict) -> dict:
        action = cmd.get("action", "")
        params = cmd.get("params", {})

        if self._paused and action != CommandAction.RESUME:
            return {"ok": False, "error": "paused"}

        handler = {
            CommandAction.SET_GPIO: self._set_gpio,
            CommandAction.SET_INTERVAL: self._set_interval,
            CommandAction.READ_SENSOR: self._read_sensor,
            CommandAction.REBOOT: self._reboot,
            CommandAction.SET_CONFIG: self._set_config,
            CommandAction.PAUSE: self._pause,
            CommandAction.RESUME: self._resume,
        }.get(action)

        if not handler:
            return {"ok": False, "error": f"unknown action: {action}"}

        try:
            return handler(params)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _set_gpio(self, params: dict) -> dict:
        pin = params.get("pin", 0)
        state = params.get("state", 0)
        try:
            p = machine.Pin(pin, machine.Pin.OUT)
            p.value(state)
            return {"ok": True, "action": "set_gpio", "pin": pin, "state": state}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _set_interval(self, params: dict) -> dict:
        seconds = params.get("seconds", 30)
        self.node._config["measure_interval"] = seconds
        return {"ok": True, "action": "set_interval", "seconds": seconds}

    def _read_sensor(self, params: dict) -> dict:
        data = self.node._sensor.read()
        return {"ok": True, "action": "read_sensor", "data": data}

    def _reboot(self, params: dict) -> dict:
        delay = params.get("delay_ms", 1000)
        time.sleep_ms(delay)
        machine.reset()
        return {"ok": True, "action": "reboot"}  # не дойдёт

    def _set_config(self, params: dict) -> dict:
        key = params.get("key", "")
        value = params.get("value", "")
        if key:
            self.node._config[key] = value
            return {"ok": True, "action": "set_config", "key": key, "value": value}
        return {"ok": False, "error": "no key"}

    def _pause(self, params: dict) -> dict:
        self._paused = True
        return {"ok": True, "action": "pause"}

    def _resume(self, params: dict) -> dict:
        self._paused = False
        return {"ok": True, "action": "resume"}


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
        now = time.time()
        if now - self._last_read < 2:
            return None

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


# ─── Ed25519 ─────────────────────────────────────────────────────
class Ed25519Signer:
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


# ─── Батарея ─────────────────────────────────────────────────────
class BatteryMonitor:
    """Мониторинг батареи через ADC.

    На USB-питании — всегда 100%.
    На батарее — читает ADC, вычисляет % LiPo (3.0V–4.2V).
    """
    def __init__(self, adc_pin: int = 35, mode: str = "usb"):
        self._mode = mode
        self._adc_pin = adc_pin
        self._last_pct = 100

    def read(self) -> dict:
        if self._mode == "usb":
            return {"level": 100, "voltage": 5.0, "mode": "usb"}

        try:
            adc = machine.ADC(machine.Pin(self._adc_pin))
            adc.atten(machine.ADC.ATTN_11DB)
            raw = adc.read()
            voltage = raw / 4095.0 * 3.3 * 2.0  # делитель 2:1
            pct = max(0, min(100, int((voltage - 3.0) / (4.2 - 3.0) * 100)))
            self._last_pct = pct
            return {"level": pct, "voltage": round(voltage, 2), "mode": "battery"}
        except Exception:
            return {"level": 100, "voltage": 0.0, "mode": "unknown"}

    @property
    def level(self) -> int:
        return self._last_pct

    def is_low(self, threshold: int = 10) -> bool:
        return self._last_pct <= threshold


# ─── ESP-NOW (duplex: send + receive) ────────────────────────────
class ESPNOWDuplex:
    """ESP-NOW интерфейс с поддержкой отправки и приёма.

    Отправляет телеметрию на bridge.
    Принимает команды (kind:31002) от bridge.
    """
    def __init__(self, bridge_mac: bytes):
        import espnow as _espnow
        self._esp = _espnow.ESPNow()
        self._esp.active(True)
        self._esp.add_peer(bridge_mac)
        self._bridge_mac = bridge_mac
        self._sent = 0
        self._received_commands = 0

    def send(self, data: bytes) -> bool:
        if len(data) > 250:
            data = data[:250]
        self._esp.send(self._bridge_mac, data)
        self._sent += 1
        return True

    def poll_command(self, timeout_ms: int = 100) -> dict | None:
        """Проверить, нет ли входящей ESP-NOW команды."""
        try:
            host, msg = self._esp.recv(timeout_ms)
            if msg:
                data = json.loads(msg.decode())
                if isinstance(data, dict) and "action" in data:
                    self._received_commands += 1
                    return data
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return None

    @property
    def sent_count(self) -> int:
        return self._sent

    @property
    def received_count(self) -> int:
        return self._received_commands


# ─── Sequence counter ───────────────────────────────────────────
class SeqCounter:
    def __init__(self):
        from machine import RTC
        self._rtc = RTC()
        self._seq = self._rtc.memory()[0] if self._rtc.memory() else 0

    def next(self) -> int:
        self._seq += 1
        from machine import RTC
        RTC().memory(bytes([self._seq & 0xFF]))
        return self._seq


# ─── Главный узел ───────────────────────────────────────────────
class SNINSensorNode:
    """ESP32-узел SNIN v0.6: сенсор + команды + батарея."""

    def __init__(self, config: dict):
        self._config = config
        self._seq = SeqCounter()
        self._signer = Ed25519Signer(config["private_key_hex"])
        self._sensor = DHT22Sensor(pin=4)

        mac = config["bridge_mac"]
        if isinstance(mac, str):
            mac = bytes.fromhex(mac.replace(":", ""))
        self._espnow = ESPNOWDuplex(mac)

        self._battery = BatteryMonitor(
            adc_pin=config.get("adc_battery_pin", 35),
            mode=config.get("power_mode", "usb"),
        )
        self._cmd_handler = CommandHandler(self)
        self._running = False
        self._stats = {"published": 0, "errors": 0, "commands": 0}

    def start(self):
        self._running = True
        self._init_wifi()
        print(f"SNIN sensor v0.6: {self._config['device_id']}")
        print(f"Pubkey: {self._signer.pubkey_hex}")
        print(f"Power: {self._config.get('power_mode', 'usb')}")
        print(f"ESP-NOW duplex: ON")

        while self._running:
            try:
                # Периодическое измерение
                self._measure_and_send()

                # Проверка батареи
                batt = self._battery.read()
                if batt["mode"] == "battery" and batt["level"] <= self._config.get("low_battery_threshold", 10):
                    print(f"⚠️ LOW BATTERY: {batt['level']}% at {batt['voltage']}V")

                # Проверка входящих команд (ESP-NOW)
                cmd = self._espnow.poll_command(timeout_ms=50)
                if cmd:
                    self._stats["commands"] += 1
                    result = self._cmd_handler.handle(cmd)
                    print(f"Command: {cmd.get('action')} → {result}")
                    # Шлём ACK
                    ack = {
                        "topic": "esp32:cmd_ack",
                        "device_id": self._config["device_id"],
                        "seq": self._seq.next(),
                        "cmd_seq": cmd.get("seq", 0),
                        "result": result,
                    }
                    ack_json = json.dumps(ack).encode()
                    self._espnow.send(ack_json)

                self._stats["published"] += 1

            except Exception as e:
                self._stats["errors"] += 1
                print(f"Error: {e}")

            sleep_sec = self._config.get("measure_interval", 60)
            time.sleep(sleep_sec)

    def _init_wifi(self):
        """ESP-NOW требует активного WiFi."""
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
        data = self._sensor.read()
        if data is None:
            return
        if "error" in data:
            print(f"Sensor error: {data['error']}")
            return

        seq = self._seq.next()
        batt = self._battery.read()

        packet = {
            "topic": "esp32:telemetry",
            "device_id": self._config["device_id"],
            "seq": seq,
            "payload": {
                **data,
                "battery": batt["level"],
            },
            "ts": time.time(),
        }

        msg_to_sign = json.dumps({
            "topic": packet["topic"],
            "payload": packet["payload"],
            "seq": seq,
        }).encode()

        packet["pk"] = self._signer.pubkey_hex
        packet["signature"] = self._signer.sign(msg_to_sign)

        payload_bytes = json.dumps(packet).encode()
        if len(payload_bytes) > 250:
            print(f"Packet too large: {len(payload_bytes)}B")
            return

        self._espnow.send(payload_bytes)
        print(f"Sent seq={seq} t={data.get('temp')}° h={data.get('hum')}% "
              f"batt={batt['level']}% sig={packet['signature'][:12]}...")

    def stats(self) -> dict:
        return {
            **self._stats,
            "espnow_sent": self._espnow.sent_count,
            "espnow_recv": self._espnow.received_count,
            "battery": self._battery.read(),
        }


# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 45)
    print("SNIN ESP32 Sensor Node v0.6 (Command-Ready)")
    print("=" * 45)

    try:
        import config
        CONFIG.update({k: v for k, v in config.__dict__.items()
                      if not k.startswith("_")})
        print(f"Config loaded from config.py")
    except ImportError:
        print("No config.py — using defaults.")

    if not CONFIG.get("private_key_hex"):
        print("⚠️  PRIVATE_KEY not set! Generating test key...")
        from ucrypto import ecdsa
        import os
        priv = os.urandom(32)
        CONFIG["private_key_hex"] = priv.hex()
        print(f"   Key: {priv.hex()}")
        print(f"   Pub: {ecdsa.public_key(priv).hex()}")

    node = SNINSensorNode(CONFIG)
    node.start()
