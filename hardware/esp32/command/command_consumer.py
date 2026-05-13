#!/usr/bin/env python3
"""SNIN ESP32 — Command Consumer для bridge.

bridge подписывается на kind:8012 в relay-v2,
получает команды, маршрутизирует на ESP32.

Поток:
  relay-v2 ── kind:8012 ──→ command_consumer
                                │
                          ┌─────┴──────┐
                          │  ESP-NOW   │  → ESP32
                          │  UART      │  → ESP32 (через USB)
                          │  LoRa      │  → ESP32 (дальняя связь)
                          │  BLE       │  → T-Watch / телефон
                          └────────────┘
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable

from hardware.esp32.command.cmd_handler import CmdHandler, DeviceCommand, CommandAction

logger = logging.getLogger("snin.command_consumer")


class TransportType:
    ESP_NOW = "esp_now"
    UART = "uart"
    LORA = "lora"
    BLE = "ble"


class CommandConsumer:
    """Подписывается на kind:8012, отправляет команды на ESP32.

    В режиме PC-симуляции — логирует и сохраняет.
    В режиме bridge — реально отправляет ESP32 через выбранный транспорт.
    """

    def __init__(
        self,
        device_id: str = "bridge_01",
        transport: str = TransportType.ESP_NOW,
        send_callback: Callable | None = None,
    ):
        self.device_id = device_id
        self.transport = transport
        self.send_callback = send_callback  # пользовательский метод отправки
        self.cmd_handler = CmdHandler()
        self._received: list[dict] = []

    async def handle_event(self, event: dict) -> dict:
        """Обработка входящего kind:8012 от relay-v2."""
        # Парсим команду
        cmd = DeviceCommand.from_kind_8012(event)
        if cmd is None:
            return {"ok": False, "error": "parse failed"}

        logger.info(
            f"Command: {cmd.device_id} {cmd.action.value} seq={cmd.seq}"
        )

        # Исполняем локально (логика команды)
        result = self.cmd_handler.handle(event)
        if not result["ok"]:
            return result

        # Отправляем на ESP32 (если есть callback)
        if self.send_callback:
            try:
                delivery = self.send_callback(cmd)
                result["delivery"] = delivery
            except Exception as e:
                logger.error(f"Send to ESP32 failed: {e}")
                result["delivery"] = {"ok": False, "error": str(e)}
        else:
            # Симуляция отправки
            logger.info(f"[SIM] Sending {cmd.action.value} → {cmd.device_id} via {self.transport}")
            result["delivery"] = {
                "ok": True,
                "transport": self.transport,
                "simulated": True,
            }

        self._received.append({
            "ts": time.time(),
            "device_id": cmd.device_id,
            "action": cmd.action.value,
            "seq": cmd.seq,
        })

        return result

    def stats(self) -> dict:
        base = self.cmd_handler.stats()
        base["received"] = len(self._received)
        base["transport"] = self.transport
        return base


# --- Relay-v2 subscription helper ---

async def subscribe_to_commands(
    relay_url: str,
    consumer: CommandConsumer,
    poll_interval: float = 5.0,
):
    """Подписка на kind:8012 через polling (для совместимости с relay-v2).

    В production relay-v2 поддерживает subscription push.
    Здесь — fallback polling.
    """
    import aiohttp

    url = f"{relay_url.rstrip('/')}/events"
    params = {"kind": 8012, "limit": 10}

    last_id = ""

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        events = await resp.json()
                        if isinstance(events, list):
                            for ev in events:
                                if ev.get("id", "") > last_id:
                                    await consumer.handle_event(ev)
                                    last_id = ev["id"]
                    else:
                        logger.debug(f"Poll returned {resp.status}")
        except asyncio.TimeoutError:
            logger.debug("Poll timeout")
        except Exception as e:
            logger.error(f"Poll error: {e}")

        await asyncio.sleep(poll_interval)


def _self_test():
    logging.basicConfig(level=logging.INFO)

    consumer = CommandConsumer(device_id="bridge_01", transport=TransportType.ESP_NOW)

    event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "set_interval"], ["seq", "1"]],
        "content": json.dumps({"seconds": 60}),
    }

    import asyncio
    result = asyncio.run(consumer.handle_event(event))

    assert result["ok"]
    assert result["delivery"]["simulated"]
    print(f"  ✅ Command received: {result['action']}")
    print(f"  ✅ Delivery: {result['delivery']['transport']} (simulated)")

    stats = consumer.stats()
    assert stats["received"] == 1
    assert stats["transport"] == "esp_now"
    print(f"  ✅ Stats: {stats['received']} received")

    print("\n✅ ALL CONSUMER TESTS PASSED")


if __name__ == "__main__":
    _self_test()
