#!/usr/bin/env python3
"""SNIN ESP32 — relay-v2 handler for ESP32 device events.

Добавляет поддержку kinds 8010-8012 в relay-v2:
  - kind:8010 — Device Telemetry (телеметрия от ESP32)
  - kind:8014 — Device Registration (регистрация нового датчика)
  - kind:8012 — Device Command (команда от DAO к ESP32)

Монтируется как плагин к relay-v2/relay/relay_server_v2.py.

Usage:
    # В relay_server_v2.py:
    from esp32.relay.device_handler import ESP32DeviceHandler
    handler = ESP32DeviceHandler()
    app.router.add_post("/esp32/telemetry", handler.handle_telemetry)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("snin.esp32_relay")

# ─── Device kinds ───────────────────────────────────────────────
KIND_TELEMETRY = 8010
KIND_REGISTER = 8014
KIND_COMMAND = 8012
KIND_DEVICE_NIP = 8010  # range: 8010-31009 reserved for SNIN devices


class DeviceRegistry:
    """Реестр ESP32-устройств в relay-v2.

    Хранит: device_id, pubkey, capabilities, last_seen, ipfs_cid (если есть).
    """
    def __init__(self):
        self._devices: dict[str, dict] = {}

    def register(self, device_id: str, info: dict) -> bool:
        is_new = device_id not in self._devices
        info["_last_seen"] = time.time()
        self._devices[device_id] = info
        logger.info(f"Device {'registered' if is_new else 'updated'}: {device_id}")
        return is_new

    def get(self, device_id: str) -> dict | None:
        return self._devices.get(device_id)

    def unregister(self, device_id: str) -> bool:
        return self._devices.pop(device_id, None) is not None

    def list(self) -> list[dict]:
        return [
            {"device_id": k, **v}
            for k, v in self._devices.items()
        ]

    def stats(self) -> dict:
        return {
            "total": len(self._devices),
            "online": sum(
                1 for d in self._devices.values()
                if time.time() - d.get("_last_seen", 0) < 300  # 5 min
            ),
        }


# ─── Главный обработчик ────────────────────────────────────────
class ESP32DeviceHandler:
    """Плагин для relay-v2: ESP32 телеметрия, регистрация, команды."""

    def __init__(self, registry: DeviceRegistry | None = None):
        self.registry = registry or DeviceRegistry()

    # ── Входящие: телеметрия от ESP32 ────────────────────────────
    def handle_telemetry(self, event: dict) -> dict:
        """Обработать kind:8010 (Device Telemetry).

        Формат события (Nostr):
        {
            "kind": 8010,
            "pubkey": "hex_public_key_esp32",
            "tags": [
                ["d", "sensor_kitchen_01"],       # device_id
                ["t", "temperature"],               # sensor type
                ["seq", "42"],                      # sequence
                ["batt", "85"],                     # battery %
            ],
            "content": '{"temp": 23.5, "hum": 60.2}'
        }
        """
        device_id = self._tag_value(event, "d", "unknown")
        device_type = self._tag_value(event, "t", "generic")
        seq = int(self._tag_value(event, "seq", "0"))
        battery = int(float(self._tag_value(event, "batt", "100")))

        try:
            payload = json.loads(event.get("content", "{}"))
        except json.JSONDecodeError:
            payload = {}

        # Регистрируем/обновляем устройство
        self.registry.register(device_id, {
            "device_type": device_type,
            "pubkey": event.get("pubkey", ""),
            "last_seq": seq,
            "battery": battery,
            "capabilities": [device_type],
        })

        logger.info(
            f"Telemetry: {device_id} type={device_type} "
            f"seq={seq} batt={battery}% payload={payload}"
        )

        return {
            "ok": True,
            "device_id": device_id,
            "seq": seq,
            "stored": True,
        }

    # ── Входящие: регистрация ────────────────────────────────────
    def handle_register(self, event: dict) -> dict:
        """Обработать kind:8014 (Device Registration).

        Формат:
        {
            "kind": 8014,
            "pubkey": "hex",
            "tags": [
                ["d", "sensor_kitchen_01"],
                ["t", "temperature_sensor"],
                ["fw", "snin-esp32-v0.1"],
                ["caps", "temperature,humidity"],
            ],
            "content": '{"model": "ESP32-S3", "flash": "16MB"}'
        }
        """
        device_id = self._tag_value(event, "d", "unknown")
        device_type = self._tag_value(event, "t", "generic")
        fw_version = self._tag_value(event, "fw", "unknown")
        caps = self._tag_value(event, "caps", "").split(",")

        content = event.get("content", "{}")

        self.registry.register(device_id, {
            "device_type": device_type,
            "pubkey": event.get("pubkey", ""),
            "fw_version": fw_version,
            "capabilities": caps,
            "metadata": content,
        })

        logger.info(
            f"Registered: {device_id} type={device_type} fw={fw_version} "
            f"caps={caps}"
        )

        return {
            "ok": True,
            "device_id": device_id,
            "registered": True,
        }

    # ── Исходящие: команда от DAO к ESP32 ────────────────────────
    def build_command(
        self,
        target_device_id: str,
        action: str,
        params: dict | None = None,
    ) -> dict:
        """Создать kind:8012 (Device Command).

        DAO голосует → команда отправляется через relay-v2 →
        bridge получает → ESP-NOW → ESP32 исполняет.
        """
        return {
            "kind": KIND_COMMAND,
            "tags": [
                ["d", target_device_id],
                ["action", action],
                ["created_at", str(int(time.time()))],
            ],
            "content": json.dumps(params or {}),
            "created_at": int(time.time()),
        }

    def get_device(self, device_id: str) -> dict | None:
        return self.registry.get(device_id)

    def list_devices(self) -> list[dict]:
        return self.registry.list()

    def stats(self) -> dict:
        return self.registry.stats()

    # ── Утилиты ──────────────────────────────────────────────────
    @staticmethod
    def _tag_value(event: dict, key: str, default: str = "") -> str:
        """Взять значение тега из Nostr-события."""
        for tag in event.get("tags", []):
            if len(tag) >= 2 and tag[0] == key:
                return tag[1]
        return default


# ─── Admin REST endpoints для relay-v2 ──────────────────────────
def register_routes(app, handler: ESP32DeviceHandler):
    """Подключить REST роуты к relay-v2."""
    import aiohttp.web as web

    async def handle_telemetry(request):
        try:
            event = await request.json()
            result = handler.handle_telemetry(event)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_register(request):
        try:
            event = await request.json()
            result = handler.handle_register(event)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_list_devices(request):
        return web.json_response(handler.list_devices())

    async def handle_device_stats(request):
        return web.json_response(handler.stats())

    app.router.add_post("/esp32/telemetry", handle_telemetry)
    app.router.add_post("/esp32/register", handle_register)
    app.router.add_get("/esp32/devices", handle_list_devices)
    app.router.add_get("/esp32/stats", handle_device_stats)
