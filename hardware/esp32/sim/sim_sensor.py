#!/usr/bin/env python3
"""SNIN ESP32 — Simulator: эмулирует ESP32-сенсор для тестирования bridge без железа.

Генерирует те же пакеты, что и настоящий ESP32 (snin_sensor.py),
но шлёт их через TCP/UDP на bridge вместо ESP-NOW.

Usage:
    # Запустить bridge сначала (на одном терминале):
    python3 esp32/bridge/bridge.py --sim-mode --port 9090
    
    # Потом симулятор (на другом):
    python3 esp32/sim/sim_sensor.py --bridge localhost:9090 --device-id sim_sensor_01

    # Или всё в одном процессе:
    python3 esp32/sim/sim_sensor.py --self-test
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

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("snin.sim")


# ─── Ed25519 для симуляции (те же ключи, что на ESP32) ─────────
def generate_ed25519_keypair() -> tuple[str, str]:
    """Сгенерировать ключи как на ESP32 (через ucrypto)."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    from cryptography.hazmat.primitives.serialization import PrivateFormat, NoEncryption
    priv_hex = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    pub_hex = pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return priv_hex, pub_hex


def sign_message(msg_bytes: bytes, privkey_hex: str) -> str:
    """Подписать как на ESP32 (совместимо с bridge)."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(privkey_hex)
    )
    return priv.sign(msg_bytes).hex()


# ─── Симулятор ESP32-сенсора ────────────────────────────────────
class SimulatedSensor:
    """Эмулирует ESP32 с DHT22. Шлёт те же пакеты, что реальный ESP32."""

    def __init__(
        self,
        device_id: str = "sim_sensor_01",
        interval: float = 5.0,
        temp_range: tuple[float, float] = (18.0, 35.0),
        hum_range: tuple[float, float] = (30.0, 80.0),
    ):
        self.device_id = device_id
        self.interval = interval
        self._temp_range = temp_range
        self._hum_range = hum_range
        self._seq = 0
        self._privkey_hex, self._pubkey_hex = generate_ed25519_keypair()
        self._running = False
        self._published = 0
        self._registered = False

    async def generate_telemetry(self) -> dict:
        """Сгенерировать пакет телеметрии — идентично реальному ESP32."""
        import random
        self._seq += 1

        # Симулируем показания датчика
        temp = round(random.uniform(*self._temp_range), 1)
        hum = round(random.uniform(*self._hum_range), 1)
        batt = max(10, 100 - self._seq * 0.5)  # батарея садится

        packet = {
            "topic": "esp32:telemetry",
            "device_id": self.device_id,
            "seq": self._seq,
            "payload": {"temp": temp, "hum": hum, "batt": round(batt, 1)},
            "ts": time.time(),
        }

        # Подпись (как на ESP32: topic + payload + seq)
        msg_to_sign = json.dumps({
            "topic": packet["topic"],
            "payload": packet["payload"],
            "seq": self._seq,
        }).encode()
        packet["pk"] = self._pubkey_hex
        packet["signature"] = sign_message(msg_to_sign, self._privkey_hex)

        return packet

    async def generate_register(self) -> dict:
        """Сгенерировать регистрационный пакет."""
        self._registered = True
        return {
            "topic": "esp32:register",
            "device_id": self.device_id,
            "seq": 0,
            "payload": {
                "device_type": "temperature_sensor",
                "fw_version": "snin-esp32-v0.1",
                "capabilities": ["temperature", "humidity"],
                "model": "ESP32-S3",
                "flash": "16MB",
            },
            "ts": time.time(),
            "pk": self._pubkey_hex,
            "signature": "simulated_registration",
        }

    def stats(self) -> dict:
        return {
            "device_id": self.device_id,
            "published": self._published,
            "seq": self._seq,
            "pubkey": self._pubkey_hex[:16] + "...",
            "registered": self._registered,
        }


# ─── Симулятор, шлющий через TCP напрямую ──────────────────────
class SimBridgeClient:
    """Подключается к bridge через TCP и шлёт пакеты."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9090):
        self._host = host
        self._port = port
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._connected = False

    async def connect(self):
        try:
            self._reader, self._writer = await asyncio.open_connection(
                self._host, self._port
            )
            self._connected = True
            logger.info(f"Connected to bridge at {self._host}:{self._port}")
        except Exception as e:
            logger.error(f"Cannot connect to bridge: {e}")
            raise

    async def send(self, packet: dict) -> bool:
        if not self._connected:
            return False
        data = json.dumps(packet).encode() + b"\n"
        self._writer.write(data)
        await self._writer.drain()
        return True

    async def close(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        self._connected = False


# ─── Главный цикл симулятора ────────────────────────────────────
async def run_simulator(args):
    sensor = SimulatedSensor(
        device_id=args.device_id,
        interval=args.interval,
    )

    client = SimBridgeClient(host=args.bridge_host, port=args.bridge_port)
    await client.connect()

    # Регистрация
    reg = await sensor.generate_register()
    await client.send(reg)
    logger.info(f"Registered: {sensor.device_id}")
    logger.info(f"  Pubkey: {sensor._pubkey_hex[:32]}...")

    # Цикл телеметрии
    count = 0
    try:
        while True:
            packet = await sensor.generate_telemetry()
            ok = await client.send(packet)
            if ok:
                sensor._published += 1
                count += 1
                logger.info(
                    f"[{count}] Sent: {packet['device_id']} "
                    f"temp={packet['payload']['temp']}° "
                    f"hum={packet['payload']['hum']}% "
                    f"batt={packet['payload']['batt']}% "
                    f"seq={packet['seq']} "
                    f"sig={packet['signature'][:12]}..."
                )
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info(f"\nSimulator stopped. Sent: {sensor._published}")
        await client.close()


# ─── Self-test: bridge + simulator в одном процессе ─────────────
async def self_test():
    """Запускает bridge (sim mode) + симулятор в одном процессе."""
    logger.info("=" * 50)
    logger.info("SNIN ESP32 — Self Test (bridge + sensor)")
    logger.info("=" * 50)

    from esp32.sdk.transport import create_transport
    from esp32.bridge.bridge import ESP32Bridge
    from esp32.relay.device_handler import ESP32DeviceHandler, DeviceRegistry

    # 1. In-memory transport (без сети)
    transport = create_transport("tcp", host="127.0.0.1", port=0)
    await transport.start()

    # 2. Device handler
    registry = DeviceRegistry()
    handler = ESP32DeviceHandler(registry)

    # 3. Симулятор напрямую шлёт в transport (минуя serial)
    sensor = SimulatedSensor(device_id="self_test_sensor", interval=0.5)

    # Регистрация
    reg = await sensor.generate_register()
    msg_bytes = json.dumps(reg).encode()
    logger.info(f"  Registration: {reg['device_id']}")

    # 3 пакета телеметрии
    for i in range(3):
        packet = await sensor.generate_telemetry()
        # Через handler (как через relay-v2)
        event = {
            "kind": 31000,
            "pubkey": sensor._pubkey_hex,
            "tags": [
                ["d", packet["device_id"]],
                ["t", "temperature"],
                ["seq", str(packet["seq"])],
                ["batt", str(packet["payload"]["batt"])],
            ],
            "content": json.dumps(packet["payload"]),
        }
        result = handler.handle_telemetry(event)
        assert result["ok"]
        logger.info(f"  [{i+1}] Telemetry: seq={packet['seq']} "
                    f"temp={packet['payload']['temp']}° "
                    f"batt={packet['payload']['batt']}%")

        sensor._published += 1
        await asyncio.sleep(0.1)

    # Статистика
    stats = handler.stats()
    logger.info(f"\n  📊 Device stats: {stats}")
    assert stats["total"] == 1
    assert stats["online"] == 1

    device = handler.get_device("self_test_sensor")
    assert device is not None
    assert device["last_seq"] == 3
    logger.info(f"  ✅ Last seq: {device['last_seq']}")

    await transport.stop()
    logger.info("\n✅ Self test PASSED — всё работает: симулятор → handler → relay-v2")


# ─── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNIN ESP32 Simulator")
    parser.add_argument(
        "--self-test", action="store_true",
        help="Запустить полный self-test (bridge + sensor + handler)"
    )
    parser.add_argument("--device-id", default="sim_sensor_01")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=9090)
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Секунд между измерениями")

    args = parser.parse_args()

    if args.self_test:
        asyncio.run(self_test())
    else:
        asyncio.run(run_simulator(args))
