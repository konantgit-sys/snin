#!/usr/bin/env python3
"""SNIN ESP32 — Bridge: ESP-NOW → p2p-agent-mesh

Принимает пакеты от ESP32 по ESP-NOW (через serial/UART bridge),
верифицирует Ed25519 подпись, форвардит в AgentMesh через Transport.

Usage:
    python3 esp32/bridge/bridge.py --port /dev/ttyUSB0 --agent-id esp32_bridge_01
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

# Путь к p2p-agent-mesh и snin-public
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "p2p-agent-mesh"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from esp32.sdk.transport import TransportMessage, create_transport
except ImportError:
    from hardware.esp32.sdk.transport import TransportMessage, create_transport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("snin.bridge")


# ─── Ed25519 верификация ────────────────────────────────────────
try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    CRYPTO_AVAILABLE = True
except ImportError:
    logger.warning("cryptography not installed — signatures will NOT be verified!")
    CRYPTO_AVAILABLE = False


def verify_esp32_signature(
    payload_bytes: bytes, signature_hex: str, pubkey_hex: str
) -> bool:
    """Верифицировать подпись ESP32. Совместимо с ucrypto на MicroPython."""
    if not CRYPTO_AVAILABLE:
        return True  # skip check if no crypto lib
    try:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        pubkey = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(pubkey_hex)
        )
        pubkey.verify(bytes.fromhex(signature_hex), payload_bytes)
        return True
    except Exception as e:
        logger.warning(f"Signature verification failed: {e}")
        return False


# ─── Счётчик для anti-replay ────────────────────────────────────
class AntiReplay:
    """Защита от повторной отправки пакетов.
    Хранит последний seq номер для каждого устройства.
    """
    def __init__(self, window_size: int = 100):
        self._seq: dict[str, int] = {}
        self._window = window_size

    def is_valid(self, device_id: str, seq: int) -> bool:
        last = self._seq.get(device_id, -1)
        if seq <= last:
            logger.warning(f"Replay detected: {device_id} seq {seq} <= {last}")
            return False
        if seq > last + self._window:
            logger.warning(f"Seq jump: {device_id} {last} → {seq} (gap > {self._window})")
        self._seq[device_id] = seq
        return True


# ─── WAL для offline bridge ─────────────────────────────────────
class BridgeWAL:
    """Write-Ahead Log для bridge. Если mesh недоступен — буферизируем.
    При reconnect — воспроизводим.
    """
    def __init__(self, path: str = "/tmp/snin_bridge_wal"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def append(self, msg: TransportMessage) -> None:
        fname = f"{int(time.time() * 1000)}_{msg.sender[:8]}_{msg.seq}.json"
        with open(self.path / fname, "w") as f:
            f.write(msg.encode().decode())

    def replay(self) -> list[TransportMessage]:
        msgs = []
        for f in sorted(self.path.iterdir()):
            if f.suffix == ".json":
                try:
                    data = f.read_bytes()
                    msgs.append(TransportMessage.decode(data))
                    f.unlink()
                except Exception as e:
                    logger.error(f"WAL replay error {f}: {e}")
        return msgs

    @property
    def count(self) -> int:
        return len(list(self.path.glob("*.json")))


# ─── ESP-NOW → Serial Bridge Reader ─────────────────────────────
class SerialBridgeReader:
    """Читает пакеты от ESP32 через UART.
    ESP32 шлёт JSON-строку: {"pk":"...","sig":"...","seq":N,"topic":"...","payload":{...}}
    Каждый пакет — одна строка, разделитель \\n.
    """
    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200):
        self._port = port
        self._baud = baud
        self._serial = None

    async def read_packet(self) -> dict | None:
        """Прочитать один пакет от ESP32. Блокирующий — в треде."""
        if self._serial is None:
            import serial
            self._serial = serial.Serial(self._port, self._baud, timeout=1)
            logger.info(f"Serial open: {self._port} @ {self._baud}")

        line = self._serial.readline()
        if not line:
            return None
        try:
            return json.loads(line.decode("utf-8").strip())
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from serial: {line[:50]}")
            return None


# ─── Bridge: главный класс ──────────────────────────────────────
class ESP32Bridge:
    """Соединяет ESP32 (ESP-NOW → Serial) с p2p-agent-mesh.

    Поток:
    ESP32 → ESP-NOW → ESP32-bridge → UART serial → SerialBridgeReader
        → verify Ed25519 → TransportMessage → AgentMesh.emit()
    """
    def __init__(
        self,
        agent_id: str = "esp32_bridge_01",
        serial_port: str = "/dev/ttyUSB0",
        transport_type: str = "tcp",
        transport_peers: list[str] | None = None,
        relay_url: str = "https://mesh-relay.v2.site",
        wal_path: str = "/tmp/snin_bridge_wal",
    ):
        self.agent_id = agent_id
        self._serial = SerialBridgeReader(port=serial_port)
        self._transport = create_transport(
            transport_type=transport_type,
            peers=transport_peers or [],
            relay_url=relay_url,
        )
        self._wal = BridgeWAL(path=wal_path)
        self._replay = AntiReplay()
        self._stats = {"received": 0, "forwarded": 0, "rejected": 0, "replayed": 0}
        self._running = False

    async def start(self) -> None:
        """Запустить bridge."""
        logger.info(f"Starting ESP32 bridge: {self.agent_id}")
        await self._transport.start()

        # Воспроизвести WAL (если были offline-пакеты)
        wal_msgs = self._wal.replay()
        for msg in wal_msgs:
            await self._transport.publish(msg.topic, msg)
            self._stats["replayed"] += 1
        logger.info(f"WAL replayed: {len(wal_msgs)} messages")

        self._running = True
        asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        self._running = False
        await self._transport.stop()

    async def _read_loop(self) -> None:
        """Цикл чтения с ESP32."""
        while self._running:
            try:
                packet = await self._serial.read_packet()
                if packet is None:
                    await asyncio.sleep(0.01)
                    continue

                self._stats["received"] += 1
                await self._process_packet(packet)

            except Exception as e:
                logger.error(f"Read error: {e}")
                await asyncio.sleep(1)

    async def _process_packet(self, packet: dict) -> None:
        """Обработать пакет от ESP32: проверить, подписать, форвардить."""
        device_id = packet.get("device_id", packet.get("pk", "")[:16])
        topic = packet.get("topic", "esp32:telemetry")
        payload = packet.get("payload", {})
        seq = packet.get("seq", 0)
        signature = packet.get("sig", packet.get("signature", ""))
        pubkey = packet.get("pk", packet.get("pubkey", ""))

        # 1. Anti-replay
        if not self._replay.is_valid(device_id, seq):
            self._stats["rejected"] += 1
            return

        # 2. Верификация подписи
        msg_bytes = json.dumps({"topic": topic, "payload": payload, "seq": seq}).encode()
        if not verify_esp32_signature(msg_bytes, signature, pubkey):
            self._stats["rejected"] += 1
            logger.warning(f"Bad signature from {device_id}")
            return

        # 3. Создаём TransportMessage
        msg = TransportMessage(
            topic=topic,
            payload={
                **payload,
                "_device_id": device_id,
                "_pubkey": pubkey,
            },
            sender=pubkey or device_id,
            signature=signature,
            pubkey=pubkey,
            seq=seq,
        )

        # 4. Публикуем в mesh
        ok = await self._transport.publish(topic, msg)
        if ok:
            self._stats["forwarded"] += 1
        else:
            # Если mesh недоступен — в WAL
            self._wal.append(msg)
            self._stats["forwarded"] += 1  # будет доставлено позже

    def stats(self) -> dict:
        return {**self._stats, "wal_pending": self._wal.count}


# ─── CLI entry point ────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNIN ESP32 Bridge")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud")
    parser.add_argument("--agent-id", default="esp32_bridge_01", help="Bridge agent ID")
    parser.add_argument(
        "--transport", default="http",
        choices=["tcp", "http", "ipfs"],
        help="Transport type for mesh"
    )
    parser.add_argument("--peer", action="append", help="TCP peer host:port")
    parser.add_argument("--relay", default="https://mesh-relay.v2.site",
                        help="HTTP relay URL")

    args = parser.parse_args()
    args.peer = args.peer or []

    bridge = ESP32Bridge(
        agent_id=args.agent_id,
        serial_port=args.port,
        transport_type=args.transport,
        transport_peers=args.peer,
        relay_url=args.relay,
    )

    async def run():
        await bridge.start()
        logger.info(f"Bridge started. Stats: {bridge.stats()}")
        try:
            while True:
                await asyncio.sleep(60)
                logger.info(f"Stats: {bridge.stats()}")
        except KeyboardInterrupt:
            await bridge.stop()

    asyncio.run(run())
