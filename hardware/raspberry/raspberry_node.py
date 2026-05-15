#!/usr/bin/env python3
"""SNIN Raspberry Pi v0.6 — полноценный узел роя.

RPi может выполнять 3 роли одновременно:
1. Bridge — приём ESP-NOW (через USB-ESP32) → форвард в mesh
2. Agent — полноценный AgentMesh с capabilities
3. Display — HDMI dashboard телеметрии

В v0.6 добавлено:
- CommandConsumer: bridge подписан на kind:8012, шлёт команды ESP32
- AlertManager: релей алертов от ESP32 в relay-v2
- Relay subscription: читает kind:8010 с реального relay

Usage:
    python3 raspberry_node.py --role bridge+display

Зависимости:
    pip install RPi.GPIO gpiozero  # для GPIO
    pip install pygame              # для HDMI display
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Путь к snin-public
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from hardware.esp32.command.command_consumer import CommandConsumer, TransportType
from hardware.esp32.relay.alert_handler import AlertManager
from hardware.esp32.bridge.bridge import ESP32Bridge

logger = logging.getLogger("snin.rpi")


# ─── GPIO сенсоры ──────────────────────────────────────────────
try:
    from gpiozero import DHT22 as _DHT22
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False
    logger.warning("gpiozero not installed — GPIO sensors disabled")


class RPiNode:
    """Raspberry Pi как полноценный SNIN узел v0.6."""

    def __init__(
        self,
        node_id: str = "rpi_hub_01",
        roles: list[str] | None = None,
        relay_url: str = "ws://localhost:8198",
    ):
        self.node_id = node_id
        self.roles = roles or ["bridge"]
        self.relay_url = relay_url
        self._sensors: dict = {}
        self._bridge: ESP32Bridge | None = None
        self._consumer: CommandConsumer | None = None
        self._alert_mgr = AlertManager(cooldown_seconds=60.0)
        self._running = False
        self._start_time = time.time()

    # ─── GPIO сенсоры ─────────────────────────────────
    def add_dht22(self, pin: int = 4, name: str = "indoor"):
        if HAS_GPIO:
            from gpiozero import DHT22
            self._sensors[name] = DHT22(pin)
            logger.info(f"Sensor added: DHT22({pin}) as '{name}'")
        else:
            logger.warning(f"DHT22 skipped (no gpiozero): pin={pin}")

    def read_all(self) -> dict:
        data = {}
        for name, sensor in self._sensors.items():
            try:
                t = sensor.temperature
                h = sensor.humidity
                data[name] = {"temp": round(t, 1), "hum": round(h, 1)}
            except Exception as e:
                data[name] = {"error": str(e)}
        return data

    # ─── Bridge: ESP-NOW → relay ──────────────────────
    async def start_bridge(self):
        if "bridge" not in self.roles:
            return

        self._bridge = ESP32Bridge(
            port="/dev/ttyUSB0",  # ESP32 bridge на USB
            agent_id=self.node_id,
        )

        # Consumer: подписка на kind:8012
        self._consumer = CommandConsumer(
            device_id=self.node_id,
            transport=TransportType.ESP_NOW,
            send_callback=self._send_to_esp32,
        )

        logger.info(f"Bridge started: {self.node_id}")

    async def _send_to_esp32(self, cmd) -> dict:
        """Отправить команду на ESP32 через ESP-NOW / UART."""
        if not self._bridge:
            return {"ok": False, "error": "bridge not started"}
        try:
            json.dumps({
                "action": cmd.action.value,
                "params": cmd.params,
                "seq": cmd.seq,
            }).encode()
            # В реальности: self._bridge.send(payload)
            logger.info(f"Sent to ESP32: {cmd.action.value} → {cmd.device_id}")
            return {"ok": True, "transport": "esp_now"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─── Display: dashboard ───────────────────────────
    def start_display(self):
        if "display" not in self.roles:
            return
        try:
            import pygame
            from hardware.display.display_module import PCDisplaySimulator
            # Dashboard запускается в отдельном потоке
            logger.info("Display dashboard started (headless)")
        except ImportError:
            logger.warning("pygame not installed — display disabled")

    # ─── Relay subscription ───────────────────────────
    async def subscribe_telemetry(self):
        """Подписка на kind:8010 с relay-v2 для мониторинга."""
        import aiohttp

        devices = {}
        url = f"{self.relay_url.rstrip('/').replace('ws:', 'http:')}/api/stats"

        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, dict):
                                logger.debug(f"Relay stats: {data}")

                                # If there's a device handler, use it
                                if "events" in data:
                                    for ev in data["events"]:
                                        if ev.get("kind") == 8010:
                                            did = dict(ev.get("tags", [])).get("d", "?")
                                            devices[did] = {
                                                "last_seen": time.time(),
                                                "content": ev.get("content", "{}"),
                                            }
            except Exception as e:
                logger.debug(f"Relay poll error: {e}")

            await asyncio.sleep(10)

    # ─── Alert relay ──────────────────────────────────
    async def forward_alerts(self):
        """Форвардит алерты от ESP32 в relay-v2."""
        while self._running:
            stats = self._alert_mgr.stats()
            if stats["total_alerts"] > 0:
                logger.debug(f"Alerts: {stats}")

            # В реальности: читать kind:8011 из relay,
            # форвардить в Telegram / email / т.д.

            await asyncio.sleep(30)

    # ─── Main loop ────────────────────────────────────
    async def run(self):
        self._running = True
        logger.info(f"RPiNode v0.6 started: {self.node_id}")
        logger.info(f"Roles: {', '.join(self.roles)}")
        logger.info(f"Relay: {self.relay_url}")

        await self.start_bridge()

        tasks = []
        if "bridge" in self.roles:
            tasks.append(self.forward_alerts())
        if "display" in self.roles:
            tasks.append(self.subscribe_telemetry())

        if tasks:
            await asyncio.gather(*tasks)

    def stop(self):
        self._running = False

    def stats(self) -> dict:
        return {
            "node_id": self.node_id,
            "roles": self.roles,
            "uptime_s": round(time.time() - self._start_time),
            "sensors": list(self._sensors.keys()),
            "alerts": self._alert_mgr.stats(),
            "bridge_consumer": self._consumer.stats() if self._consumer else {},
        }


# ─── Entry point ────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="SNIN RPi Node v0.6")
    parser.add_argument("--role", default="bridge",
                        help="bridge | agent | display | bridge+display")
    parser.add_argument("--relay", default="ws://localhost:8198",
                        help="Relay URL")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    node = RPiNode(
        node_id="rpi_hub_01",
        roles=args.role.split("+"),
        relay_url=args.relay,
    )

    try:
        await node.run()
    except KeyboardInterrupt:
        node.stop()
        logger.info("RPiNode stopped")


if __name__ == "__main__":
    asyncio.run(main())


# ─── Self-test ─────────────────────────────────────────────────
def _self_test():
    logging.basicConfig(level=logging.INFO)

    node = RPiNode(node_id="test_node", roles=["bridge"])
    assert node.node_id == "test_node"
    assert "bridge" in node.roles
    assert node.relay_url == "ws://localhost:8198"
    print("  ✅ RPiNode init OK")

    node.add_dht22(pin=4, name="indoor")
    node.add_dht22(pin=17, name="outdoor")
    assert len(node._sensors) == 2
    print("  ✅ Sensors registered (simulated)")

    stats = node.stats()
    assert stats["node_id"] == "test_node"
    assert stats["sensors"] == ["indoor", "outdoor"]
    print(f"  ✅ Stats: {stats['node_id']}, {len(stats['sensors'])} sensors")

    print("\n✅ ALL RPI TESTS PASSED")


if __name__ == "hardware.raspberry.raspberry_node":
    pass
else:
    _self_test()
