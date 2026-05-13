#!/usr/bin/env python3
"""SNIN ESP32 — Smoke test: проверка Transport + Bridge без ESP32.

Запускает 2 агента через TCP transport, эмулирует ESP32-сенсор.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("snin.test")


async def test_transport_pubsub():
    """Тест: 2 агента через TCP transport."""
    from esp32.sdk.transport import TCPTransport, TransportMessage

    received = []

    async def callback(msg: TransportMessage):
        received.append(msg)
        logger.info(f"  ✅ Получено: {msg.topic} payload={msg.payload}")

    # Агент A: слушает
    transport_a = TCPTransport(host="127.0.0.1", port=0)
    await transport_a.start()
    await transport_a.subscribe("esp32:telemetry", callback)
    port = transport_a._server.sockets[0].getsockname()[1]
    logger.info(f"Transport A listening on port {port}")

    # Агент B: подключается и шлёт
    transport_b = TCPTransport(host="127.0.0.1", port=0, peers=[f"127.0.0.1:{port}"])
    await transport_b.start()

    msg = TransportMessage(
        topic="esp32:telemetry",
        payload={"temp": 23.5, "hum": 60.2, "batt": 85},
        sender="test_esp32_01",
        signature="",
        pubkey="aabb" + "00" * 30,
        seq=1,
    )
    ok = await transport_b.publish("esp32:telemetry", msg)
    logger.info(f"  Published: {'✅' if ok else '❌'}")

    await asyncio.sleep(0.5)

    # Проверка
    assert len(received) == 1, f"Expected 1 message, got {len(received)}"
    assert received[0].payload["temp"] == 23.5
    logger.info(f"\n  📊 Получено сообщений: {len(received)}")
    logger.info(f"  📦 Пейлоад: {received[0].payload}")

    await transport_a.stop()
    await transport_b.stop()
    logger.info("  ✅ Transport test PASSED")


async def test_transport_factory():
    """Тест фабрики транспортов."""
    from esp32.sdk.transport import create_transport, TCPTransport, HTTPTransport

    tcp = create_transport("tcp")
    http = create_transport("http")
    assert isinstance(tcp, TCPTransport)
    assert isinstance(http, HTTPTransport)
    logger.info("  ✅ Factory test PASSED")


async def test_bridge_verify():
    """Тест верификации подписи: симуляция ESP32 → bridge."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from esp32.bridge.bridge import verify_esp32_signature

    # Генерируем ключ (как на ESP32)
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    pubkey_hex = pub_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

    # Подписываем сообщение (как ESP32 через ucrypto)
    msg = json.dumps({"topic": "esp32:telemetry", "payload": {"temp": 23.5}, "seq": 1}).encode()
    sig = priv_key.sign(msg)
    sig_hex = sig.hex()

    # Верифицируем (как bridge)
    assert verify_esp32_signature(msg, sig_hex, pubkey_hex), "Signature should be valid!"
    logger.info("  ✅ Bridge verify test PASSED")

    # Неверная подпись
    assert not verify_esp32_signature(msg, "00" * 64, pubkey_hex), "Bad sig should fail!"
    logger.info("  ✅ Invalid sig correctly rejected")


async def test_device_handler():
    """Тест relay-v2 handler для ESP32."""
    from esp32.relay.device_handler import ESP32DeviceHandler, DeviceRegistry

    registry = DeviceRegistry()
    handler = ESP32DeviceHandler(registry)

    # Симуляция телеметрии
    event = {
        "kind": 31000,
        "pubkey": "ab" * 32,
        "tags": [
            ["d", "test_sensor_01"],
            ["t", "temperature"],
            ["seq", "42"],
            ["batt", "85"],
        ],
        "content": '{"temp": 23.5, "hum": 60.2}',
    }
    result = handler.handle_telemetry(event)
    assert result["ok"]
    assert result["device_id"] == "test_sensor_01"

    # Проверка реестра
    device = handler.get_device("test_sensor_01")
    assert device is not None
    assert device["battery"] == 85
    assert device["device_type"] == "temperature"
    logger.info(f"  ✅ Device registered: test_sensor_01 batt={device['battery']}% type={device['device_type']}")

    stats = handler.stats()
    assert stats["total"] == 1
    logger.info(f"  ✅ Device stats: {stats}")

    logger.info("  ✅ Device handler test PASSED")


async def main():
    logger.info("=" * 50)
    logger.info("SNIN ESP32 — Smoke Tests")
    logger.info("=" * 50)

    logger.info("\n1. Transport pub/sub...")
    await test_transport_pubsub()

    logger.info("\n2. Transport factory...")
    await test_transport_factory()

    logger.info("\n3. Bridge signature verify...")
    await test_bridge_verify()

    logger.info("\n4. Device handler...")
    await test_device_handler()

    logger.info("\n" + "=" * 50)
    logger.info("ALL TESTS PASSED ✅")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
