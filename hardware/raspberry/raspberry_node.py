#!/usr/bin/env python3
"""SNIN Raspberry Pi — полноценный узел роя.

RPi может выполнять 3 роли одновременно:
1. Bridge — приём ESP-NOW (через USB-ESP32) → форвард в mesh
2. Agent — полноценный AgentMesh с capabilities
3. Relay — Nostr relay (через relay-v2)

Особенности RPi vs ESP32:
- Неограниченная RAM/CPU — полный p2p-agent-mesh
- GPIO для прямого подключения датчиков
- HDMI для монитора/dashboard
- Может запустить relay-v2 внутри

Usage:
    sudo python3 raspberry_node.py --role bridge+agent --display hdmi

Зависимости:
    pip install RPi.GPIO gpiozero  # для GPIO
    pip install pygame              # для HDMI display (опционально)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "p2p-agent-mesh"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("snin.rpi")

# ─── GPIO датчики (опционально) ─────────────────────────────────
try:
    import gpiozero
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("gpiozero not installed — GPIO sensors disabled")


class RPiSensor:
    """Чтение датчиков через GPIO Raspberry Pi."""
    
    def __init__(self):
        self._sensors = {}

    def add_dht22(self, pin: int = 4, name: str = "indoor"):
        """Подключить DHT22 к пину GPIO."""
        if not GPIO_AVAILABLE:
            logger.warning(f"DHT22 on pin {pin}: gpiozero not available")
            return
        from gpiozero import DigitalInputDevice
        import Adafruit_DHT
        self._sensors[name] = {"type": "dht22", "pin": pin, "lib": Adafruit_DHT}

    def add_bme280(self, i2c_addr: int = 0x76, name: str = "outdoor"):
        """Подключить BME280 по I2C."""
        if not GPIO_AVAILABLE:
            return
        import board
        import adafruit_bme280
        i2c = board.I2C()
        self._sensors[name] = {
            "type": "bme280",
            "sensor": adafruit_bme280.Adafruit_BME280_I2C(i2c, address=i2c_addr),
        }

    def read_all(self) -> dict:
        """Прочитать все датчики."""
        data = {}
        for name, cfg in self._sensors.items():
            try:
                if cfg["type"] == "dht22":
                    hum, temp = cfg["lib"].read_retry(cfg["lib"].DHT22, cfg["pin"])
                    data[name] = {"temp": round(temp, 1), "hum": round(hum, 1)}
                elif cfg["type"] == "bme280":
                    s = cfg["sensor"]
                    data[name] = {
                        "temp": round(s.temperature, 1),
                        "hum": round(s.humidity, 1),
                        "pressure": round(s.pressure, 1),
                    }
            except Exception as e:
                data[name] = {"error": str(e)}
        return data


# ─── HDMI Display (опционально) ─────────────────────────────────
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class RPiDisplay:
    """Dashboard роя на HDMI/мониторе."""

    def __init__(self, width: int = 800, height: int = 480):
        self._width = width
        self._height = height
        self._screen = None
        self._font = None
        self._data = {}
        self._running = False

    def start(self):
        if not PYGAME_AVAILABLE:
            logger.warning("pygame not installed — display disabled")
            return
        os.environ["SDL_FBDEV"] = "/dev/fb0"
        pygame.init()
        self._screen = pygame.display.set_mode(
            (self._width, self._height), pygame.FULLSCREEN
        )
        self._font = pygame.font.Font(None, 36)
        pygame.mouse.set_visible(False)
        self._running = True
        logger.info(f"Display started: {self._width}x{self._height}")

    def update(self, devices: list[dict]):
        """Обновить экран с информацией об устройствах роя."""
        if not self._running:
            return
        self._data = {"devices": devices}
        self._render()

    def _render(self):
        self._screen.fill((10, 10, 10))  # тёмный фон

        y = 20
        devices = self._data.get("devices", [])

        # Заголовок
        title = self._font.render("SNIN Device Swarm", True, (0, 212, 255))
        self._screen.blit(title, (20, y))
        y += 50

        # Список устройств
        for d in devices:
            did = d.get("device_id", "?")
            temp = d.get("payload", {}).get("temp", "?")
            batt = d.get("payload", {}).get("batt", "?")
            text = f"{did}: {temp}°C  batt:{batt}%"
            color = (100, 255, 100) if batt != "?" and batt > 20 else (255, 100, 100)
            line = self._font.render(text, True, color)
            self._screen.blit(line, (40, y))
            y += 35

        # Нижняя строка
        y = self._height - 40
        status = self._font.render(
            f"Online: {len(devices)}  |  SNIN Network",
            True, (100, 100, 100)
        )
        self._screen.blit(status, (20, y))

        pygame.display.flip()


# ─── RPi Node (главный класс) ──────────────────────────────────
class RPiNode:
    """Raspberry Pi как полноценный узел SNIN.

    Роли:
    - bridge: принимает от ESP32 по USB/UART, форвардит в mesh
    - agent: полноценный AgentMesh узел
    - display: показывает dashboard на HDMI
    - sensor: читает GPIO датчики напрямую
    """

    def __init__(
        self,
        node_id: str = "rpi_hub_01",
        roles: list[str] | None = None,
        transport_type: str = "tcp",
        relay_write: bool = False,
    ):
        self.node_id = node_id
        self.roles = roles or ["agent"]
        self._transport_type = transport_type
        self._relay_write = relay_write

        # Компоненты
        self._bridge = None
        self._agent_mesh = None
        self._display = RPiDisplay() if "display" in self.roles else None
        self._sensor = RPiSensor() if "sensor" in self.roles else None
        self._transport = None

    async def start(self):
        logger.info(f"Starting RPiNode: {self.node_id}")
        logger.info(f"Roles: {', '.join(self.roles)}")

        # 1. Транспорт
        from esp32.sdk.transport import create_transport
        self._transport = create_transport(self._transport_type)
        await self._transport.start()

        # 2. AgentMesh
        from sdk.agent import AgentMesh
        self._agent_mesh = AgentMesh(
            self.node_id,
            capabilities=["rpi_bridge", "sensor_hub", "display"],
            transport=self._transport,
        )
        await self._agent_mesh.start()

        # 3. Bridge (если есть ESP32 через USB)
        if "bridge" in self.roles:
            from esp32.bridge.bridge import ESP32Bridge
            self._bridge = ESP32Bridge(
                agent_id=f"{self.node_id}_bridge",
                serial_port="/dev/ttyUSB0",
                transport_type=self._transport_type,
            )
            await self._bridge.start()
            asyncio.create_task(self._bridge_stats_loop())

        # 4. Display
        if self._display:
            self._display.start()
            asyncio.create_task(self._display_loop())

        # 5. Публикация в relay-v2 (если есть write-доступ)
        if self._relay_write:
            from esp32.relay.device_handler import ESP32DeviceHandler
            from relay.client import RelayClient
            self._relay_client = RelayClient("https://mesh-relay.v2.site")
            asyncio.create_task(self._relay_loop())

        logger.info("RPiNode started")

    async def _bridge_stats_loop(self):
        while self._bridge:
            await asyncio.sleep(60)
            stats = self._bridge.stats()
            logger.info(f"Bridge stats: {stats}")

    async def _display_loop(self):
        """Обновлять dashboard каждые 5 секунд."""
        while self._display:
            try:
                # Получить список устройств из mesh
                if self._agent_mesh:
                    devices = await self._agent_mesh.query_agents(
                        capability="sensor"
                    )
                    self._display.update(devices)
            except Exception as e:
                logger.error(f"Display update error: {e}")
            await asyncio.sleep(5)

    async def _relay_loop(self):
        """Публиковать телеметрию RPi в relay-v2."""
        seq = 0
        while self._relay_client:
            try:
                if self._sensor:
                    data = self._sensor.read_all()
                    seq += 1
                    await self._relay_client.publish({
                        "kind": 31000,
                        "tags": [
                            ["d", self.node_id],
                            ["t", "rpi_sensor_hub"],
                            ["seq", str(seq)],
                        ],
                        "content": json.dumps(data),
                    })
            except Exception as e:
                logger.error(f"Relay publish error: {e}")
            await asyncio.sleep(60)

    async def stop(self):
        if self._bridge:
            await self._bridge.stop()
        if self._agent_mesh:
            await self._agent_mesh.stop()
        if self._transport:
            await self._transport.stop()
        logger.info("RPiNode stopped")


# ─── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNIN Raspberry Pi Node")
    parser.add_argument("--id", default="rpi_hub_01", help="Node ID")
    parser.add_argument(
        "--role", nargs="+",
        default=["agent"],
        choices=["agent", "bridge", "display", "sensor"],
        help="Роли узла"
    )
    parser.add_argument(
        "--transport", default="tcp",
        choices=["tcp", "http", "ipfs"],
    )
    parser.add_argument("--relay-write", action="store_true",
                        help="Публиковать телеметрию в relay-v2")
    args = parser.parse_args()

    node = RPiNode(
        node_id=args.id,
        roles=args.role,
        transport_type=args.transport,
        relay_write=args.relay_write,
    )

    async def run():
        await node.start()
        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            await node.stop()

    asyncio.run(run())
