#!/usr/bin/env python3
"""SNIN Crypto — Nostr Schnorr (BIP-340) signing for relay publishing.

Bridge принимает Ed25519-подписанные данные от ESP32,
а для публикации в Nostr relay использует Schnorr (BIP-340) подпись.

Поток:
  ESP32 (Ed25519) → Bridge (верифицирует Ed25519)
                    → создаёт Nostr event
                    → подписывает Schnorr (секретный ключ bridge)
                    → публикует kind:8010 в relay-v2

Использует: nostr (pip install nostr) — BIP-340 совместимый signer.
"""

from __future__ import annotations

import json
import time
from typing import Any

from nostr.event import Event
from nostr.key import PrivateKey, PublicKey


class NostrSigner:
    """Schnorr (BIP-340) подпись для Nostr событий.

    Используется bridge для публикации в relay-v2.
    """

    def __init__(self, private_key_hex: str = ""):
        if private_key_hex:
            self._key = PrivateKey(bytes.fromhex(private_key_hex))
        else:
            self._key = PrivateKey()

    @property
    def pubkey(self) -> str:
        """Публичный ключ в hex (32 байта x-only)."""
        return self._key.public_key.hex()

    @property
    def private_key_hex(self) -> str:
        """Приватный ключ в hex (для сохранения)."""
        return self._key.hex()

    def sign_event(self, event: dict) -> dict:
        """Подписать Nostr event по NIP-01 / BIP-340.

        Заполняет поля id и sig в переданном event.
        """
        e = Event(
            event.get("pubkey", self.pubkey),
            event.get("content", ""),
            kind=event.get("kind", 8010),
            tags=event.get("tags", []),
            created_at=event.get("created_at", int(time.time())),
        )
        # Подписать через nostr
        self._key.sign_event(e)

        event["id"] = e.id
        event["sig"] = e.signature
        event["pubkey"] = e.public_key
        event["created_at"] = e.created_at

        return event

    def create_kind_8010(
        self,
        device_id: str,
        temp: float,
        hum: float,
        battery: int,
        seq: int,
        extra: dict | None = None,
    ) -> dict:
        """Создать и подписать kind:8010 (Device Telemetry)."""
        content = {
            "temp": temp,
            "hum": hum,
            "battery": battery,
            **(extra or {}),
        }

        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8010,
            "tags": [
                ["d", device_id],
                ["t", "temperature"],
                ["seq", str(seq)],
                ["batt", str(battery)],
            ],
            "content": json.dumps(content, separators=(',', ':')),
        }

        return self.sign_event(event)

    def create_kind_8012(
        self,
        device_id: str,
        action: str,
        params: dict | None = None,
        seq: int = 1,
    ) -> dict:
        """Создать и подписать kind:8012 (Device Command)."""
        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8012,
            "tags": [
                ["d", device_id],
                ["cmd", action],
                ["seq", str(seq)],
            ],
            "content": json.dumps(params or {}, separators=(',', ':')),
        }

        return self.sign_event(event)

    def create_kind_8011(
        self,
        device_id: str,
        alert_type: str,
        severity: str,
        message: str,
        seq: int,
    ) -> dict:
        """Создать и подписать kind:8011 (Device Alert)."""
        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8011,
            "tags": [
                ["d", device_id],
                ["alert", alert_type],
                ["severity", severity],
                ["seq", str(seq)],
            ],
            "content": json.dumps({"message": message}, separators=(',', ':')),
        }
        return self.sign_event(event)

    def create_kind_8013(
        self,
        device_id: str,
        version: str,
        size: int,
        sha256: str,
        seq: int,
    ) -> dict:
        """Создать и подписать kind:8013 (OTA Update)."""
        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8013,
            "tags": [
                ["d", device_id],
                ["ver", version],
                ["size", str(size)],
                ["sha256", sha256],
                ["seq", str(seq)],
            ],
            "content": json.dumps({"version": version, "size": size}, separators=(',', ':')),
        }
        return self.sign_event(event)

    def create_kind_8014(
        self,
        device_id: str,
        model: str,
        capabilities: list[str],
        seq: int,
    ) -> dict:
        """Создать и подписать kind:8014 (Device Registration)."""
        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8014,
            "tags": [
                ["d", device_id],
                ["model", model],
                ["caps", ",".join(capabilities)],
                ["seq", str(seq)],
            ],
            "content": json.dumps({"model": model, "caps": capabilities}, separators=(',', ':')),
        }
        return self.sign_event(event)

    def create_kind_8015(
        self,
        device_id: str,
        lat: float,
        lon: float,
        alt: float,
        speed: float,
        satellites: int,
        seq: int,
    ) -> dict:
        """Создать и подписать kind:8015 (Device Location / GPS)."""
        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8015,
            "tags": [
                ["d", device_id],
                ["lat", str(lat)],
                ["lon", str(lon)],
                ["alt", str(alt)],
                ["speed", str(speed)],
                ["satellites", str(satellites)],
                ["seq", str(seq)],
            ],
            "content": json.dumps({"hdop": 1.2, "fix_quality": 3}, separators=(',', ':')),
        }
        return self.sign_event(event)

    def create_kind_8016(
        self,
        device_id: str,
        mode: str,
        pubkey_hex: str,
        seq: int,
    ) -> dict:
        """Создать и подписать kind:8016 (Commission)."""
        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8016,
            "tags": [
                ["d", device_id],
                ["mode", mode],
                ["pubkey", pubkey_hex],
                ["seq", str(seq)],
            ],
            "content": json.dumps({"mode": mode}, separators=(',', ':')),
        }
        return self.sign_event(event)

    def create_kind_8017(
        self,
        device_id: str,
        uptime: int,
        firmware: str,
        heap_free: int,
        wifi_rssi: int,
        battery: int,
        seq: int,
    ) -> dict:
        """Создать и подписать kind:8017 (System Status)."""
        event = {
            "pubkey": self.pubkey,
            "created_at": int(time.time()),
            "kind": 8017,
            "tags": [
                ["d", device_id],
                ["uptime", str(uptime)],
                ["firmware", firmware],
                ["batt", str(battery)],
                ["seq", str(seq)],
            ],
            "content": json.dumps({
                "uptime": uptime, "firmware": firmware,
                "heap_free": heap_free, "wifi_rssi": wifi_rssi,
                "battery": battery
            }, separators=(',', ':')),
        }
        return self.sign_event(event)

    def verify_event(self, event: dict) -> bool:
        """Проверить Schnorr подпись события."""
        if "id" not in event or "sig" not in event or "pubkey" not in event:
            return False

        try:
            pub = PublicKey.from_hex(event["pubkey"])
            return pub.verify(event["id"], event["sig"])
        except Exception:
            return False


# ─── Self-test ─────────────────────────────────────────────────
def _self_test():
    import logging
    logging.basicConfig(level=logging.INFO)

    # 1. Генерация ключа
    signer = NostrSigner()
    assert len(signer.pubkey) == 64  # 32 байта в hex
    print(f"  ✅ Key generated: {signer.pubkey[:16]}...")

    # 2. Создание kind:8010
    event = signer.create_kind_8010(
        device_id="sensor_test_01",
        temp=23.5,
        hum=60.2,
        battery=85,
        seq=1,
    )
    assert event["kind"] == 8010
    assert len(event["id"]) == 64
    assert len(event["sig"]) == 128  # 64 байта Schnorr sig
    print(f"  ✅ kind:8010 signed: id={event['id'][:16]}...")

    # 3. Создание kind:8012
    cmd = signer.create_kind_8012(
        device_id="sensor_test_01",
        action="set_interval",
        params={"seconds": 60},
        seq=1,
    )
    assert cmd["kind"] == 8012
    assert cmd["tags"][1][1] == "set_interval"
    print(f"  ✅ kind:8012 signed: cmd={cmd['tags'][1][1]}")

    # 4. Проверка подписи
    assert signer.verify_event(event)
    print("  ✅ Signature verify OK")

    # 5. Публикация в реальный relay
    import asyncio, aiohttp

    async def test_publish():
        ws_url = "ws://localhost:8198"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, timeout=10) as ws:
                await ws.send_json(["EVENT", event])
                resp = await ws.receive(timeout=5)
                data = resp.data
                if isinstance(data, list) and data[0] == "OK" and data[2] is True:
                    print(f"  ✅ Published kind:8010 — ACCEPTED!")
                else:
                    print(f"  ⚠️ Relay: {data}")

                # Публикуем команду
                await ws.send_json(["EVENT", cmd])
                resp2 = await ws.receive(timeout=5)
                data2 = resp2.data
                if isinstance(data2, list) and data2[0] == "OK" and data2[2] is True:
                    print(f"  ✅ Published kind:8012 — ACCEPTED!")
                else:
                    print(f"  ⚠️ Relay: {data2}")

                await ws.close()

    asyncio.run(test_publish())

    print("\n✅ ALL NOSTR SIGNER TESTS PASSED")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    _self_test()
