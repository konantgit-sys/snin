#!/usr/bin/env python3
"""SNIN LoRa — дальняя связь для ESP32 через SX1278/SX1262.

Зачем: ESP-NOW ограничен ~200м. LoRa даёт 2-15km.
Когда: датчики в поле, лес, гора, сельское хозяйство.

Совместимость:
  - SX1278 (433/868/915 MHz) — micropython-lora или lora-sx127x
  - SX1262 (868/915 MHz) — SPI интерфейс, современнее
  - Heltec LoRa (ESP32 + SX1276 в одном корпусе)

Протокол:
  LoRa пакет ≤ 64 байта (режим SF12, BW125).
  ESP-NOW пакет 250 байт. Разница в 4x.
  Решение: fragmentation — большой пакет режется на 4 части.

  bridge принимает фрагменты, собирает, проверяет подпись.

Архитектура:
  ESP32 [DHT22 + LoRa] --RF--> [LoRa Gateway on RPi] --USB--> bridge.py
  или:
  ESP32 [DHT22 + ESP-NOW] --200m--> ESP32 [LoRa bridge] --15km--> [LoRa Gateway]

Usage:
    from hardware.esp32.lora.lora_phy import SX1278Transport
    
    lora = SX1278Transport(spi_id=1, cs=5, freq=868)
    await lora.start()
    await lora.send(bridge_mac, packet_bytes)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable

logger = logging.getLogger("snin.lora")


# ─── Фрагментация (LoRa ≤ 64 байт vs ESP-NOW 250 байт) ────────
MAX_LORA_PAYLOAD = 64
MAX_ESPNOW_PAYLOAD = 250

class PacketFragmenter:
    """Делит ESP-NOW пакет (≤250B) на LoRa фрагменты (≤64B).

    Формат фрагмента:
    [0xAA] [total:1] [index:1] [payload:≤61] [CRC8:1]
    """

    HEADER_SIZE = 4  # 0xAA + total + index + CRC8
    MAX_FRAGMENT_PAYLOAD = MAX_LORA_PAYLOAD - HEADER_SIZE  # 60 байт

    @staticmethod
    def fragment(packet: bytes) -> list[bytes]:
        if len(packet) == 0:
            return []

        total = (len(packet) + PacketFragmenter.MAX_FRAGMENT_PAYLOAD - 1) // \
                PacketFragmenter.MAX_FRAGMENT_PAYLOAD
        if total > 255:
            raise ValueError(f"Packet too large: {len(packet)} bytes, max {255 * 60}")

        fragments = []
        for i in range(total):
            start = i * PacketFragmenter.MAX_FRAGMENT_PAYLOAD
            end = start + PacketFragmenter.MAX_FRAGMENT_PAYLOAD
            chunk = packet[start:end]

            # CRC8 от чанка
            crc = PacketFragmenter._crc8(chunk)

            frag = bytes([0xAA, total, i]) + chunk + bytes([crc])
            fragments.append(frag)

        return fragments

    @staticmethod
    def defragment(fragments: list[bytes]) -> bytes | None:
        if not fragments:
            return b''  # пустой пакет — валидный случай
        fragments.sort(key=lambda f: f[2])  # по index
        total = fragments[0][1]

        if len(fragments) != total:
            logger.warning(f"Missing fragments: {len(fragments)}/{total}")
            return None

        payload = bytearray()
        for frag in fragments:
            if frag[0] != 0xAA:
                logger.warning(f"Bad marker: {frag[0]:02x}")
                return None
            chunk = frag[3:-1]  # без маркера, total, index, CRC
            crc = PacketFragmenter._crc8(chunk)
            if crc != frag[-1]:
                logger.warning(f"CRC mismatch: expected {frag[-1]:02x}, got {crc:02x}")
                return None
            payload.extend(chunk)

        return bytes(payload)

    @staticmethod
    def _crc8(data: bytes) -> int:
        crc = 0
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ 0x07
                else:
                    crc <<= 1
                crc &= 0xFF
        return crc


# ─── PC симулятор LoRa (для тестов без железа) ──────────────────
class LoRaSimulator:
    """Эмулирует LoRa модуль через UDP (для тестирования bridge)."""

    def __init__(self, recv_port: int = 8700, send_addr: tuple = None):
        self._recv_port = recv_port
        self._send_addr = send_addr or ("127.0.0.1", 8701)
        self._running = False
        self._on_message: Callable | None = None
        self._sent = 0
        self._received = 0

    async def start(self):
        import asyncio
        self._running = True
        logger.info(f"LoRa simulator started on UDP:{self._recv_port}")
        # В реальности — SPI + SX1278

    async def send(self, data: bytes):
        import asyncio
        # Симуляция: LoRa latency ~100ms + вариация
        await asyncio.sleep(0.1 + (time.time() % 0.1))
        self._sent += 1
        logger.debug(f"LoRa sent: {len(data)} bytes (simulated)")

    async def receive(self) -> bytes | None:
        # Симуляция: чтение из UDP сокета
        await asyncio.sleep(0.05)
        return None

    def stats(self) -> dict:
        return {"sent": self._sent, "received": self._received}

    async def stop(self):
        self._running = False


# ─── LoRa Transport (реальный, для MicroPython) ─────────────────
class SX1278Transport:
    """Транспорт через SX1278/SX1262 для SNIN.

    В реальном коде на ESP32 (MicroPython):
        import machine
        from lora.sx127x import SX127X
        
        spi = machine.SPI(1, baudrate=10000000,
                          sck=machine.Pin(18), mosi=machine.Pin(23), miso=machine.Pin(19))
        lora = SX127X(spi, cs=machine.Pin(5), dio0=machine.Pin(26))
        lora.set_frequency(868000000)  # 868 MHz
        lora.set_tx_power(20)  # +20 dBm
    """

    def __init__(self, spi_id: int = 1, cs: int = 5, dio0: int = 26,
                 freq: int = 868, sf: int = 12, bw: int = 125,
                 tx_power: int = 20):
        self._spi_id = spi_id
        self._cs = cs
        self._dio0 = dio0
        self._freq = freq
        self._sf = sf
        self._bw = bw
        self._tx_power = tx_power
        self._lora = None
        self._fragmenter = PacketFragmenter()

    def init_micropython(self):
        """Инициализация на реальном ESP32 (MicroPython)."""
        try:
            import machine
            from lora.sx127x import SX127X

            spi = machine.SPI(self._spi_id, baudrate=10000000,
                              sck=machine.Pin(18), mosi=machine.Pin(23),
                              miso=machine.Pin(19))
            self._lora = SX127X(
                spi, cs=machine.Pin(self._cs),
                dio0=machine.Pin(self._dio0)
            )
            self._lora.set_frequency(self._freq * 1000000)
            self._lora.set_tx_power(self._tx_power)
            self._lora.set_spreading_factor(self._sf)
            self._lora.set_bandwidth(self._bw * 1000)
            logger.info(f"LoRa initialized: {self._freq}MHz SF{self._sf} BW{self._bw}")
            return True
        except Exception as e:
            logger.error(f"LoRa init failed: {e}")
            return False

    def send_packet(self, packet: bytes):
        """Отправить SNIN-пакет через LoRa (с фрагментацией)."""
        if not self._lora:
            raise RuntimeError("LoRa not initialized")

        fragments = self._fragmenter.fragment(packet)
        for frag in fragments:
            self._lora.send(frag)
            # LoRa TX time: ~100ms на фрагмент (SF12, BW125)
            time.sleep_ms(200)

        logger.info(f"Sent {len(fragments)} LoRa fragments ({len(packet)} bytes)")

    def receive_packet(self, timeout_ms: int = 5000) -> bytes | None:
        """Принять полный SNIN-пакет (с дефрагментацией)."""
        if not self._lora:
            raise RuntimeError("LoRa not initialized")

        fragments = []
        start = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            frag = self._lora.receive()
            if frag and len(frag) > 0:
                if frag[0] == 0xAA:
                    fragments.append(frag)
                    total = frag[1]
                    if len(fragments) >= total:
                        break

        if fragments:
            packet = self._fragmenter.defragment(fragments)
            if packet:
                logger.info(f"Received: {len(packet)} bytes from {len(fragments)} fragments")
                return packet

        return None


# ─── Self-test: фрагментация + симуляция LoRa ──────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("SNIN LoRa Module — Self Test")
    print("=" * 50)

    # 1. Тест фрагментации
    print("\n1. Fragment/Defragment...")
    test_packet = json.dumps({
        "topic": "esp32:telemetry",
        "device_id": "lora_test_01",
        "seq": 42,
        "payload": {"temp": 23.5, "hum": 60.2},
        "pk": "a1b2c3d4e5f6" * 5,
        "sig": "deadbeef" * 16,
    }).encode()
    print(f"  Original: {len(test_packet)} bytes")

    fragments = PacketFragmenter.fragment(test_packet)
    print(f"  Fragments: {len(fragments)} x {len(fragments[0])} bytes")

    restored = PacketFragmenter.defragment(fragments)
    assert restored == test_packet
    print("  ✅ Fragment/Defragment OK")

    # 2. Тест CRC8
    print("\n2. CRC8...")
    crc_a = PacketFragmenter._crc8(b"test")
    crc_b = PacketFragmenter._crc8(b"test")
    crc_c = PacketFragmenter._crc8(b"test!")
    assert crc_a == crc_b
    assert crc_a != crc_c
    print(f"  CRC8('test')={crc_a} CRC8('test!')={crc_c} ✅ OK")

    # 3. Self-test через симулятор
    print("\n3. LoRa Simulator...")
    async def test():
        lora = LoRaSimulator()
        await lora.start()
        await lora.send(test_packet)
        stats = lora.stats()
        print(f"  Sent: {stats['sent']} ✅")
        await lora.stop()

    import asyncio
    asyncio.run(test())

    print("\n✅ ALL LORA TESTS PASSED")
