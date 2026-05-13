#!/usr/bin/env python3
"""SNIN ESP32 — OTA Update (kind:31003).

Обновление прошивки ESP32 по воздуху через relay-v2.

Поток:
  1. OTA Server публикует kind:31003 с firmware
  2. ESP32 получает команду start_ota (kind:31002)
  3. ESP32 скачивает firmware по URL из content
  4. ESP32 проверяет CRC32, записывает, перезагружается

kind:31003 format:
  {
    "kind": 31003,
    "pubkey": "<ota_server_pk>",
    "tags": [
      ["d", "<device_id>"],
      ["fw_version", "v0.5.1"],
      ["fw_size", "<bytes>"],
      ["fw_crc32", "<hex>"],
      ["target", "esp32|esp8266|arduino"],
    ],
    "content": '{"url": "https://...",
                 "changelog": "Fix: ...",
                 "required": true}'
  }
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

logger = logging.getLogger("snin.ota")


class OTAState(Enum):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    READY = "ready"
    APPLIED = "applied"
    FAILED = "failed"


class OTATarget(Enum):
    ESP32 = "esp32"
    ESP8266 = "esp8266"
    ARDUINO = "arduino"


@dataclass
class OTAUpdate:
    """Одно OTA-обновление."""
    device_id: str
    fw_version: str
    fw_size: int
    fw_crc32: str
    url: str
    target: OTATarget = OTATarget.ESP32
    changelog: str = ""
    required: bool = False
    timestamp: float = 0.0


class OTAManager:
    """OTA менеджер на стороне bridge/RPi.

    Хранит версии прошивок, публикует kind:31003.
    """

    def __init__(self, firmware_dir: str = "firmware/releases"):
        self.firmware_dir = Path(firmware_dir)
        self.firmware_dir.mkdir(parents=True, exist_ok=True)
        self._versions: dict[str, str] = {}  # device_id -> fw_version
        self._updates: list[OTAUpdate] = []

    def add_firmware(self, name: str, data: bytes, version: str,
                     target: OTATarget = OTATarget.ESP32) -> dict:
        """Добавить прошивку в локальное хранилище."""
        path = self.firmware_dir / f"{name}_v{version}.bin"
        path.write_bytes(data)

        crc32 = hex(zlib.crc32(data) & 0xFFFFFFFF)[2:].zfill(8)

        manifest = {
            "name": name,
            "version": version,
            "size": len(data),
            "crc32": crc32,
            "target": target.value,
            "path": str(path),
        }

        meta_path = path.with_suffix(".json")
        meta_path.write_text(json.dumps(manifest, indent=2))

        logger.info(f"Firmware added: {name} v{version} ({len(data)}B, CRC:{crc32})")
        return manifest

    def create_update_event(
        self, device_id: str, fw_version: str,
        base_url: str = "",
    ) -> dict | None:
        """Создать kind:31003 для устройства."""
        fw_path = self.firmware_dir / f"{device_id}_v{fw_version}.bin"
        meta_path = fw_path.with_suffix(".json")

        if not fw_path.exists():
            # Ищем по маске
            candidates = list(self.firmware_dir.glob(f"*_v{fw_version}.bin"))
            if not candidates:
                logger.error(f"Firmware v{fw_version} not found for {device_id}")
                return None
            fw_path = candidates[0]
            meta_path = fw_path.with_suffix(".json")

        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        download_url = f"{base_url}/{fw_path.name}"

        event = {
            "kind": 31003,
            "pubkey": "ota_server",
            "tags": [
                ["d", device_id],
                ["fw_version", fw_version],
                ["fw_size", str(meta.get("size", fw_path.stat().st_size))],
                ["fw_crc32", meta.get("crc32", "")],
                ["target", meta.get("target", "esp32")],
            ],
            "content": json.dumps({
                "url": download_url,
                "changelog": f"Update to v{fw_version}",
                "required": False,
            }),
        }

        update = OTAUpdate(
            device_id=device_id,
            fw_version=fw_version,
            fw_size=meta.get("size", 0),
            fw_crc32=meta.get("crc32", ""),
            url=download_url,
            target=OTATarget(meta.get("target", "esp32")),
            timestamp=time.time(),
        )
        self._updates.append(update)
        return event

    def stats(self) -> dict:
        return {
            "firmware_files": len(list(self.firmware_dir.glob("*.bin"))),
            "updates_pushed": len(self._updates),
            "latest_versions": self._versions,
        }


class OTAClient:
    """OTA клиент (на ESP32 / в симуляции).

    Скачивает прошивку, проверяет CRC32, сообщает о готовности.
    """

    def __init__(self):
        self.state = OTAState.IDLE
        self._downloaded: bytes | None = None
        self._target_crc32: str = ""

    async def download(self, url: str, expected_crc32: str = "",
                       chunk_callback: Callable | None = None) -> bool:
        """Скачать прошивку по URL. С поддержкой HTTP и file://."""
        self.state = OTAState.DOWNLOADING
        self._target_crc32 = expected_crc32

        try:
            if url.startswith("file://"):
                path = url[7:]
                with open(path, "rb") as f:
                    data = f.read()
            elif url.startswith("http"):
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        resp.raise_for_status()
                        data = await resp.read()
            else:
                # local path
                with open(url, "rb") as f:
                    data = f.read()

            self._downloaded = data
            self.state = OTAState.VERIFYING
            return self._verify()
        except Exception as e:
            logger.error(f"OTA download failed: {e}")
            self.state = OTAState.FAILED
            return False

    def _verify(self) -> bool:
        """Проверить CRC32."""
        if not self._downloaded:
            self.state = OTAState.FAILED
            return False
        if not self._target_crc32:
            self.state = OTAState.READY
            return True

        actual = hex(zlib.crc32(self._downloaded) & 0xFFFFFFFF)[2:].zfill(8)
        if actual != self._target_crc32:
            logger.error(f"CRC32 mismatch: expected {self._target_crc32}, got {actual}")
            self.state = OTAState.FAILED
            return False

        self.state = OTAState.READY
        logger.info(f"OTA verified: {len(self._downloaded)}B, CRC:{actual}")
        return True

    def apply(self) -> bool:
        """Применить прошивку (в симуляции — просто сменить статус)."""
        if self.state != OTAState.READY:
            return False
        self.state = OTAState.APPLIED
        logger.info(f"OTA applied: {len(self._downloaded or b'')}B")
        return True

    def stats(self) -> dict:
        return {
            "state": self.state.value,
            "downloaded_bytes": len(self._downloaded) if self._downloaded else 0,
        }


import zlib  # noqa: E402 — for CRC32


def _self_test():
    logging.basicConfig(level=logging.INFO)

    server = OTAManager(firmware_dir="/tmp/snin_ota_test")
    server.firmware_dir.mkdir(parents=True, exist_ok=True)

    # 1. Add firmware
    fw_data = os.urandom(1024 * 16)  # 16KB test firmware
    meta = server.add_firmware("sensor_01", fw_data, "0.5.1")
    assert meta["version"] == "0.5.1"
    assert meta["size"] == 16384
    print(f"  ✅ Firmware added: {meta['name']} v{meta['version']} ({meta['size']}B)")

    # 2. Create update event
    event = server.create_update_event("sensor_01", "0.5.1", base_url="file://")
    assert event is not None
    assert event["kind"] == 31003
    assert event["tags"][1][1] == "0.5.1"
    print(f"  ✅ kind:31003 created: v{event['tags'][1][1]}")

    # 3. OTA client download
    client = OTAClient()
    fw_path = list(server.firmware_dir.glob("*.bin"))[0]
    import asyncio
    ok = asyncio.run(client.download(str(fw_path), meta["crc32"]))
    assert ok
    assert client.state == OTAState.READY
    print(f"  ✅ OTA download + verify: {len(client._downloaded)}B")

    # 4. Apply
    assert client.apply()
    assert client.state == OTAState.APPLIED
    print("  ✅ OTA apply")

    # 5. CRC mismatch
    client2 = OTAClient()
    ok2 = asyncio.run(client2.download(str(fw_path), "deadbeef"))
    assert not ok2
    assert client2.state == OTAState.FAILED
    print("  ✅ CRC mismatch rejected")

    # 6. Cleanup
    import shutil
    shutil.rmtree("/tmp/snin_ota_test")
    print("  ✅ Cleanup")

    print("\n✅ ALL OTA TESTS PASSED")


if __name__ == "__main__":
    _self_test()
