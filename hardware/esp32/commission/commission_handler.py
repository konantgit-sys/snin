#!/usr/bin/env python3
"""SNIN ESP32 — Commission Handler.

Onboarding нового ESP32 в рой.

Процесс:
  1. ESP32 загружается впервые, шлёт kind:31001 (Register)
  2. Commission Handler выдаёт идентификатор, слот в mesh
  3. ESP32 сохраняет конфиг, начинает слать kind:31000
  4. Агенты роя получают уведомление о новом устройстве

Commission mode:
  - auto:     новое устройство регистрируется автоматически
  - paired:   требует пин-код (с экрана ESP32)
  - approved: ручное одобрение оператором
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("snin.commission")


class CommissionMode(Enum):
    AUTO = "auto"
    PAIRED = "paired"
    APPROVED = "approved"


class DeviceStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


@dataclass
class DeviceInfo:
    """Информация о зарегистрированном устройстве."""
    device_id: str
    pubkey: str
    status: DeviceStatus = DeviceStatus.ACTIVE
    device_type: str = "unknown"
    fw_version: str = ""
    capabilities: list[str] = field(default_factory=list)
    registered_at: float = 0.0
    last_seen: float = 0.0
    pairing_code: str = ""

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "pubkey": self.pubkey,
            "status": self.status.value,
            "type": self.device_type,
            "fw": self.fw_version,
            "capabilities": self.capabilities,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
        }


class CommissionHandler:
    """Регистрация и управление устройствами в рое."""

    def __init__(
        self,
        mode: CommissionMode = CommissionMode.AUTO,
        require_pairing: bool = False,
    ):
        self.mode = mode
        self.require_pairing = require_pairing
        self._devices: dict[str, dict] = {}  # device_id -> info
        self._pk_index: dict[str, str] = {}  # pubkey -> device_id
        self._pending: dict[str, DeviceInfo] = {}  # pending approval
        self._next_id: int = 1

    def _generate_device_id(self) -> str:
        """Генерирует уникальный ID: snin_XXX."""
        while True:
            dev_id = f"snin_{self._next_id:04d}"
            self._next_id += 1
            if dev_id not in self._devices:
                return dev_id

    def _generate_pairing_code(self) -> str:
        """6-значный пин-код для paired mode."""
        return f"{secrets.randbelow(1000000):06d}"

    def handle_start(self, event: dict) -> dict:
        """Начало commission: ESP32 прислал kind:31001."""
        pubkey = event.get("pubkey", "")
        if not pubkey:
            return {"ok": False, "error": "no pubkey"}

        # Проверяем, не зарегистрирован ли уже
        if pubkey in self._pk_index:
            device_id = self._pk_index[pubkey]
            info = self._devices.get(device_id, {})
            return {
                "ok": True,
                "device_id": device_id,
                "status": info.get("status", "active"),
                "already_registered": True,
            }

        # Извлекаем capability
        try:
            content = json.loads(event.get("content", "{}"))
        except json.JSONDecodeError:
            content = {}

        tags = {t[0]: t[1] if len(t) > 1 else "" for t in event.get("tags", [])}

        device_type = tags.get("t", content.get("type", "unknown"))
        fw_version = tags.get("fw", content.get("fw_version", "unknown"))
        capabilities = content.get("capabilities", [])

        if self.mode == CommissionMode.AUTO:
            return self._approve(pubkey, device_type, fw_version, capabilities)

        # Paired или Approved: ставим в ожидание
        device_id = self._generate_device_id()
        pairing_code = self._generate_pairing_code() if self.require_pairing else ""

        info = DeviceInfo(
            device_id=device_id,
            pubkey=pubkey,
            status=DeviceStatus.PENDING,
            device_type=device_type,
            fw_version=fw_version,
            capabilities=capabilities,
            registered_at=time.time(),
            pairing_code=pairing_code,
        )
        self._pending[pubkey] = info

        logger.info(f"Device pending: {device_id} ({device_type}), code={pairing_code}")

        return {
            "ok": True,
            "device_id": device_id,
            "status": "pending",
            "pairing_code": pairing_code if self.require_pairing else None,
            "message": f"Awaiting approval (mode={self.mode.value})",
        }

    def _approve(self, pubkey: str, device_type: str,
                 fw_version: str, capabilities: list[str]) -> dict:
        """Автоматическое или ручное одобрение устройства."""
        device_id = self._generate_device_id()

        self._devices[device_id] = {
            "pubkey": pubkey,
            "status": "active",
            "type": device_type,
            "fw": fw_version,
            "capabilities": capabilities,
            "registered_at": time.time(),
            "last_seen": time.time(),
        }
        self._pk_index[pubkey] = device_id

        logger.info(f"Device approved: {device_id} ({device_type}) fw={fw_version}")
        logger.info(f"  Capabilities: {capabilities}")

        return {
            "ok": True,
            "device_id": device_id,
            "status": "active",
            "mesh_relay": "relay-v2 (auto-configured)",
        }

    def approve_pending(self, pubkey: str) -> dict:
        """Одобрить ожидающее устройство (для mode=approved)."""
        info = self._pending.pop(pubkey, None)
        if not info:
            return {"ok": False, "error": "not found in pending"}

        return self._approve(
            info.pubkey, info.device_type,
            info.fw_version, info.capabilities,
        )

    def verify_pairing(self, pubkey: str, code: str) -> dict:
        """Подтвердить pairing кодом (для mode=paired)."""
        info = self._pending.get(pubkey)
        if not info:
            return {"ok": False, "error": "not pending"}
        if info.pairing_code != code:
            return {"ok": False, "error": "wrong code"}
        return self.approve_pending(pubkey)

    def get_device(self, device_id: str) -> dict | None:
        return self._devices.get(device_id)

    def list_devices(self, status: str | None = None) -> list[dict]:
        devices = []
        for device_id, info in self._devices.items():
            if status and info.get("status") != status:
                continue
            devices.append({
                "device_id": device_id,
                "pubkey": info["pubkey"][:16] + "...",
                "status": info["status"],
                "type": info["type"],
                "fw": info["fw"],
                "capabilities": info["capabilities"],
                "last_seen": info.get("last_seen", 0),
            })
        return devices

    def update_last_seen(self, device_id: str):
        if device_id in self._devices:
            self._devices[device_id]["last_seen"] = time.time()

    def stats(self) -> dict:
        active = sum(1 for d in self._devices.values() if d["status"] == "active")
        types: dict[str, int] = {}
        for d in self._devices.values():
            t = d["type"]
            types[t] = types.get(t, 0) + 1
        return {
            "total": len(self._devices),
            "active": active,
            "pending": len(self._pending),
            "by_type": types,
            "mode": self.mode.value,
        }


def _self_test():
    logging.basicConfig(level=logging.INFO)

    # Auto mode
    ch = CommissionHandler(mode=CommissionMode.AUTO)

    event = {
        "kind": 31001,
        "pubkey": "a1b2c3d4e5f6" * 4,
        "tags": [["d", "test_sensor"], ["t", "temperature"], ["fw", "v0.5.0"]],
        "content": json.dumps({"capabilities": ["temperature", "humidity"]}),
    }

    result = ch.handle_start(event)
    assert result["ok"]
    assert result["status"] == "active"
    device_id = result["device_id"]
    print(f"  ✅ Auto register: {device_id}")

    # Duplicate
    result2 = ch.handle_start(event)
    assert result2["already_registered"]
    print(f"  ✅ Duplicate detected")

    # List
    devices = ch.list_devices()
    assert len(devices) == 1
    print(f"  ✅ List: {len(devices)} device(s)")

    # Stats
    stats = ch.stats()
    assert stats["total"] == 1
    assert stats["active"] == 1
    print(f"  ✅ Stats: {stats['total']} total, {stats['active']} active")

    # Paired mode
    ch2 = CommissionHandler(mode=CommissionMode.PAIRED, require_pairing=True)

    event2 = {
        "kind": 31001,
        "pubkey": "deadbeef" * 4,
        "tags": [["d", "test_sensor_2"], ["t", "temperature"]],
        "content": "{}",
    }
    result3 = ch2.handle_start(event2)
    assert result3["status"] == "pending"
    assert len(result3["pairing_code"]) == 6
    code = result3["pairing_code"]
    print(f"  ✅ Paired mode: pending, code={code}")

    # Wrong code
    result4 = ch2.verify_pairing("deadbeef" * 4, "000000")
    assert not result4["ok"]
    print(f"  ✅ Wrong code rejected")

    # Correct code
    result5 = ch2.verify_pairing("deadbeef" * 4, code)
    assert result5["ok"]
    assert result5["status"] == "active"
    print(f"  ✅ Correct code approved")

    # Approved mode
    ch3 = CommissionHandler(mode=CommissionMode.APPROVED)
    result6 = ch3.handle_start(event)
    assert result6["status"] == "pending"
    print(f"  ✅ Approved mode: pending")

    result7 = ch3.approve_pending(event["pubkey"])
    assert result7["ok"]
    assert result7["status"] == "active"
    print(f"  ✅ Manual approve: active")

    print("\n✅ ALL COMMISSION TESTS PASSED")


if __name__ == "__main__":
    _self_test()
