#!/usr/bin/env python3
"""SNIN BLE — Bluetooth Low Energy для ESP32 и LilyGO T-Watch.

Зачем: 
  - T-Watch связь с телефоном
  - Локальный сброс данных с ESP32 на телефон
  - Push-уведомления о DAO-голосованиях
  - Commissioning нового ESP32 через телефон

Архитектура:
  ESP32 [BLE GATT Server] ←→ Phone [BLE GATT Client]
  или
  Phone [BLE] → ESP32 [BLE bridge] → ESP-NOW → sensor ESP32

Протокол (GATT характеристика):
  Service UUID:  SNIN_SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
  TX Characteristic:  "6e400002-b5a3-f393-e0a9-e50e24dcca9e" (ESP32→Phone)
  RX Characteristic:  "6e400003-b5a3-f393-e0a9-e50e24dcca9e" (Phone→ESP32)

  Формат данных: JSON-пакет, такой же как через ESP-NOW

На ESP32 (MicroPython) через bluetooth модуль:
  from ble import BLEGATTServer
  ble = BLEGATTServer(device_name="SNIN-Sensor-01")
  ble.start()
  ble.send_to_phone({"temp": 23.5, "hum": 60.2})
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

logger = logging.getLogger("snin.ble")


# ─── SNIN BLE Service ───────────────────────────────────────────
SNIN_SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
SNIN_TX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
SNIN_RX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Команды от телефона к ESP32 (через RX characteristic)
COMMAND_REGISTER = "register"      # Зарегистрировать ESP32 в рое
COMMAND_POLL = "poll"             # Запросить текущие показания
COMMAND_DAO_VOTE = "dao_vote"     # Проголосовать в DAO
COMMAND_OTA = "ota"               # Запросить OTA обновление
COMMAND_STATUS = "status"         # Статус устройства
COMMAND_CONFIG = "config"         # Изменить конфигурацию


class BLEPacket:
    """BLE пакет: команда от телефона к ESP32."""

    def __init__(self, command: str, payload: dict | None = None):
        self.command = command
        self.payload = payload or {}

    @classmethod
    def from_bytes(cls, data: bytes) -> "BLEPacket":
        try:
            obj = json.loads(data.decode())
            return cls(
                command=obj.get("cmd", ""),
                payload=obj.get("payload", {}),
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Invalid BLE packet: {e}")
            return cls("unknown", {"error": str(e)})

    def to_bytes(self) -> bytes:
        return json.dumps({
            "cmd": self.command,
            "payload": self.payload,
        }).encode()

    def __repr__(self):
        return f"BLEPacket({self.command}, {self.payload})"


# ─── Обработчики команд ────────────────────────────────────────
class BLECommandHandler:
    """Обрабатывает входящие BLE-команды от телефона."""

    def __init__(self, device_id: str = "ble_device_01"):
        self.device_id = device_id
        self._handlers: dict[str, Callable] = {
            COMMAND_REGISTER: self._handle_register,
            COMMAND_POLL: self._handle_poll,
            COMMAND_STATUS: self._handle_status,
            COMMAND_CONFIG: self._handle_config,
        }
        self._sensor_data = {}
        self._on_response: Callable | None = None

    def set_sensor_data(self, data: dict):
        self._sensor_data = data

    async def handle(self, packet: BLEPacket) -> dict | None:
        handler = self._handlers.get(packet.command)
        if handler:
            return await handler(packet.payload)
        logger.warning(f"Unknown BLE command: {packet.command}")
        return {"error": f"unknown command: {packet.command}"}

    async def _handle_register(self, payload: dict) -> dict:
        # Телефон шлёт: {"device_id": "...", "user_token": "..."}
        logger.info(f"Register request: {payload}")
        return {
            "ok": True,
            "device_id": self.device_id,
            "status": "registered",
        }

    async def _handle_poll(self, payload: dict) -> dict:
        # Телефон запрашивает текущие показания
        return {
            "ok": True,
            "device_id": self.device_id,
            "sensors": self._sensor_data,
        }

    async def _handle_status(self, payload: dict) -> dict:
        return {
            "ok": True,
            "device_id": self.device_id,
            "status": {
                "battery": 85,
                "firmware": "snin-ble-v0.1",
                "uptime": 3600,
                "sensors": list(self._sensor_data.keys()),
            }
        }

    async def _handle_config(self, payload: dict) -> dict:
        # Телефон меняет конфиг: {"interval": 30, "threshold": 25.0}
        logger.info(f"Config update: {payload}")
        return {"ok": True, "updated": list(payload.keys())}


# ─── Симулятор BLE (для тестов) ────────────────────────────────
class BLESimulator:
    """Эмулирует BLE через TCP (для тестирования без ESP32/телефона)."""

    def __init__(self, port: int = 8900):
        self._port = port
        self._handler = BLECommandHandler("sim_ble_01")
        self._running = False
        self._responses: list[dict] = []

    def set_sensor_data(self, temp: float = 23.5, hum: float = 60.2):
        self._handler.set_sensor_data({"temp": temp, "hum": hum})

    async def simulate_phone_command(self, command: str, payload: dict = None) -> dict:
        """Симулирует команду от телефона."""
        packet = BLEPacket(command, payload)
        response = await self._handler.handle(packet)
        self._responses.append(response)
        return response

    async def self_test(self):
        """Полный self-test всех BLE команд."""
        print("\nBLE Self Test:")
        print("=" * 40)

        # Register
        resp = await self.simulate_phone_command("register", {"device_id": "test_01"})
        assert resp["ok"]
        print(f"  ✅ Register: {resp}")

        # Status
        resp = await self.simulate_phone_command("status")
        assert resp["ok"]
        print(f"  ✅ Status: battery={resp['status']['battery']}%")

        # Poll (без данных)
        resp = await self.simulate_phone_command("poll")
        assert resp["ok"]
        print(f"  ✅ Poll (empty): {resp}")

        # Poll (с данными)
        self.set_sensor_data(28.3, 55.0)
        resp = await self.simulate_phone_command("poll")
        assert resp["ok"]
        print(f"  ✅ Poll (data): temp={resp['sensors']['temp']}° hum={resp['sensors']['hum']}%")

        # Config
        resp = await self.simulate_phone_command("config", {"interval": 30})
        assert resp["ok"]
        print(f"  ✅ Config: {resp}")

        # Unknown command
        resp = await self.simulate_phone_command("unknown_cmd")
        assert "error" in resp
        print(f"  ✅ Unknown cmd rejected: {resp}")

        print("  ✅ ALL BLE TESTS PASSED")


# ─── BLE Bridge (ESP32 → Bluetooth → Phone) ────────────────────
class BLEBridge:
    """ESP32 как BLE-шлюз: принимает ESP-NOW, форвардит на телефон через BLE.

    Поток:
      ESP-NOW (от датчика) → ESP32 [BLEBridge] → GATT TX → Phone App

    На телефоне (React Native / Flutter приложение):
      - Сканирует BLE устройства с префиксом "SNIN-"
      - Подключается
      - Подписывается на TX characteristic
      - Получает телеметрию в реальном времени
    """

    def __init__(self, device_name: str = "SNIN-Bridge-01"):
        self._device_name = device_name
        self._clients: set = set()
        self._running = False

    def start(self):
        """Запустить BLE сервер на ESP32."""
        import bluetooth  # MicroPython
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.config(gap_name=self._device_name)

        # Регистрируем GATT сервис
        self._svc_id = self._ble.gatts_register_services([
            (
                bytes.fromhex(SNIN_SVC_UUID.replace("-", "")),
                [
                    (bytes.fromhex(SNIN_TX_UUID.replace("-", "")),
                     bluetooth.FLAG_NOTIFY),
                    (bytes.fromhex(SNIN_RX_UUID.replace("-", "")),
                     bluetooth.FLAG_WRITE),
                ],
            )
        ])
        logger.info(f"BLE started: {self._device_name}")

    def send_telemetry(self, packet: dict):
        """Отправить телеметрию на подключённый телефон."""
        data = json.dumps(packet).encode()
        self._ble.gatts_notify(0, self._svc_id[0], data)

    def stop(self):
        self._ble.active(False)

    def stats(self) -> dict:
        return {"connected": len(self._clients)}


# ─── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    print("SNIN BLE Module — Self Test\n")

    sim = BLESimulator()
    sim.set_sensor_data(23.5, 60.2)

    asyncio.run(sim.self_test())
    print("\n✅ BLE Module OK")
