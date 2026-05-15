#!/usr/bin/env python3
"""SNIN ESP32 — Command Handler for kind:8012.

Парсит входящие команды от relay-v2, маршрутизирует по device_id.
Может работать на bridge (серверная часть) и на ESP32 (клиентская).

kind:8012 format:
  {
    "kind": 8012,
    "pubkey": "<dao_agent_pk>",
    "tags": [
      ["d", "<device_id>"],
      ["cmd", "<action>"],
      ["seq", "<sequence_number>"],
    ],
    "content": '{"param1": "val1", ...}'
  }

Actions:
  - set_gpio(pin, state)     — вкл/выкл GPIO
  - set_interval(seconds)     — смена интервала отправки
  - read_sensor(sensor_type)  — принудительное чтение
  - reboot()                  — перезагрузка ESP32
  - set_config(key, value)    — любой конфиг
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("snin.command")


class CommandAction(str, Enum):
    SET_GPIO = "set_gpio"
    SET_INTERVAL = "set_interval"
    READ_SENSOR = "read_sensor"
    REBOOT = "reboot"
    SET_CONFIG = "set_config"
    START_OTA = "start_ota"
    PAUSE = "pause"
    RESUME = "resume"


@dataclass
class DeviceCommand:
    """Одна команда ESP32."""
    device_id: str
    action: CommandAction
    params: dict = field(default_factory=dict)
    seq: int = 0
    source_pubkey: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "action": self.action.value,
            "params": self.params,
            "seq": self.seq,
            "source": self.source_pubkey,
            "ts": self.timestamp,
        }

    @classmethod
    def from_kind_8012(cls, event: dict) -> "DeviceCommand | None":
        """Парсинг Nostr kind:8012 в DeviceCommand."""
        try:
            tags = {t[0]: t[1] if len(t) > 1 else "" for t in event.get("tags", [])}
            device_id = tags.get("d", "")
            action_raw = tags.get("cmd", "")
            seq = int(tags.get("seq", 0))

            if not device_id or not action_raw:
                logger.warning("Missing d or cmd tag in event")
                return None

            try:
                action = CommandAction(action_raw)
            except ValueError:
                logger.warning(f"Unknown action: {action_raw}")
                return None

            content = event.get("content", "{}")
            params = json.loads(content) if isinstance(content, str) else content

            return cls(
                device_id=device_id,
                action=action,
                params=params if isinstance(params, dict) else {},
                seq=seq,
                source_pubkey=event.get("pubkey", ""),
                timestamp=time.time(),
            )

        except (KeyError, json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error(f"Failed to parse kind:8012: {e}")
            return None


class ActionRegistry:
    """Реестр действий: action -> функция-исполнитель.

    Позволяет регистрировать кастомные действия без наследования.
    """

    def __init__(self):
        self._actions: dict[CommandAction, Callable] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(CommandAction.SET_GPIO, self._action_set_gpio)
        self.register(CommandAction.SET_INTERVAL, self._action_set_interval)
        self.register(CommandAction.READ_SENSOR, self._action_read_sensor)
        self.register(CommandAction.REBOOT, self._action_reboot)
        self.register(CommandAction.SET_CONFIG, self._action_set_config)
        self.register(CommandAction.PAUSE, self._action_pause)
        self.register(CommandAction.RESUME, self._action_resume)

    def register(self, action: CommandAction, handler: Callable):
        self._actions[action] = handler

    def execute(self, command: DeviceCommand) -> dict:
        handler = self._actions.get(command.action)
        if not handler:
            return {"ok": False, "error": f"no handler for {command.action}"}
        try:
            return handler(command)
        except Exception as e:
            logger.exception(f"Action {command.action} failed")
            return {"ok": False, "error": str(e)}

    # --- Default actions (PC-симуляция) ---

    def _action_set_gpio(self, cmd: DeviceCommand) -> dict:
        pin = cmd.params.get("pin", 0)
        state = cmd.params.get("state", 0)
        logger.info(f"[SIM] GPIO {pin} -> {'HIGH' if state else 'LOW'}")
        return {"ok": True, "action": "set_gpio", "pin": pin, "state": state}

    def _action_set_interval(self, cmd: DeviceCommand) -> dict:
        seconds = cmd.params.get("seconds", 30)
        logger.info(f"[SIM] Interval -> {seconds}s")
        return {"ok": True, "action": "set_interval", "seconds": seconds}

    def _action_read_sensor(self, cmd: DeviceCommand) -> dict:
        sensor_type = cmd.params.get("sensor", "temperature")
        logger.info(f"[SIM] Read sensor: {sensor_type}")
        return {"ok": True, "action": "read_sensor", "sensor": sensor_type,
                "value": 23.5}  # симуляция

    def _action_reboot(self, cmd: DeviceCommand) -> dict:
        delay = cmd.params.get("delay_ms", 1000)
        logger.info(f"[SIM] Reboot in {delay}ms")
        return {"ok": True, "action": "reboot", "delay_ms": delay}

    def _action_set_config(self, cmd: DeviceCommand) -> dict:
        key = cmd.params.get("key", "")
        value = cmd.params.get("value", "")
        logger.info(f"[SIM] Config {key} = {value}")
        return {"ok": True, "action": "set_config", "key": key, "value": value}

    def _action_pause(self, cmd: DeviceCommand) -> dict:
        logger.info("[SIM] Paused")
        return {"ok": True, "action": "pause"}

    def _action_resume(self, cmd: DeviceCommand) -> dict:
        logger.info("[SIM] Resumed")
        return {"ok": True, "action": "resume"}


class CmdHandler:
    """Высокоуровневый обработчик команд ESP32.

    Принимает сырые events kind:8012, валидирует, исполняет.
    """

    def __init__(self, device_id: str | None = None):
        self.device_id = device_id
        self.registry = ActionRegistry()
        self._last_seq: dict[str, int] = {}  # device_id -> seq
        self._executed: list[dict] = []
        self._paused: set[str] = set()

    def handle(self, event: dict) -> dict:
        """Входная точка: принять kind:8012, выполнить."""
        cmd = DeviceCommand.from_kind_8012(event)
        if cmd is None:
            return {"ok": False, "error": "invalid command format"}

        # Фильтр: если задан device_id — только для него
        if self.device_id and cmd.device_id != self.device_id:
            return {"ok": False, "error": "not for this device"}

        # Anti-replay: seq строго возрастает
        last = self._last_seq.get(cmd.device_id, -1)
        if cmd.seq <= last:
            logger.warning(f"Replay detected: {cmd.device_id} seq={cmd.seq} <= {last}")
            return {"ok": False, "error": f"replay: seq {cmd.seq} <= {last}"}
        self._last_seq[cmd.device_id] = cmd.seq

        # Проверка паузы
        if cmd.device_id in self._paused and cmd.action != CommandAction.RESUME:
            return {"ok": False, "error": "device paused"}

        # Исполнение
        result = self.registry.execute(cmd)
        result["seq"] = cmd.seq
        result["device_id"] = cmd.device_id

        self._executed.append(cmd.to_dict())
        return result

    def stats(self) -> dict:
        return {
            "executed": len(self._executed),
            "devices": len(self._last_seq),
            "paused": list(self._paused),
            "last_seq_map": self._last_seq,
        }


# --- Self-test ---
def _self_test():
    logging.basicConfig(level=logging.INFO)

    handler = CmdHandler(device_id="sensor_01")

    # 1. Парсинг kind:8012
    event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "set_interval"], ["seq", "1"]],
        "content": json.dumps({"seconds": 60}),
    }
    cmd = DeviceCommand.from_kind_8012(event)
    assert cmd is not None
    assert cmd.action == CommandAction.SET_INTERVAL
    assert cmd.params["seconds"] == 60
    print("  ✅ Parse kind:8012")

    # 2. Исполнение
    result = handler.handle(event)
    assert result["ok"]
    print(f"  ✅ Execute set_interval: {result}")

    # 3. Anti-replay
    result2 = handler.handle(event)
    assert not result2["ok"]
    assert "replay" in result2["error"]
    print("  ✅ Anti-replay rejected duplicate seq")

    # 4. set_gpio
    gpio_event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "set_gpio"], ["seq", "2"]],
        "content": json.dumps({"pin": 4, "state": 1}),
    }
    result3 = handler.handle(gpio_event)
    assert result3["ok"]
    assert result3["state"] == 1
    print("  ✅ Execute set_gpio")

    # 5. read_sensor
    read_event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "read_sensor"], ["seq", "3"]],
        "content": json.dumps({"sensor": "temperature"}),
    }
    result4 = handler.handle(read_event)
    assert result4["ok"]
    print(f"  ✅ Execute read_sensor: {result4['value']}°C")

    # 6. Reboot
    reboot_event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "reboot"], ["seq", "4"]],
        "content": json.dumps({"delay_ms": 500}),
    }
    result5 = handler.handle(reboot_event)
    assert result5["ok"]
    print("  ✅ Execute reboot")

    # 7. Unknown action
    bad_event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "fly_to_moon"], ["seq", "5"]],
        "content": "{}",
    }
    result6 = handler.handle(bad_event)
    assert not result6["ok"]
    print("  ✅ Unknown action rejected")

    # 8. Pause/Resume
    handler._paused.add("sensor_01")
    pause_check = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "read_sensor"], ["seq", "6"]],
        "content": "{}",
    }
    result7 = handler.handle(pause_check)
    assert not result7["ok"]
    print("  ✅ Pause blocks commands")

    resume_event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "sensor_01"], ["cmd", "resume"], ["seq", "7"]],
        "content": "{}",
    }
    result8 = handler.handle(resume_event)
    assert result8["ok"]
    print("  ✅ Resume unblocks")

    # 9. Wrong device_id
    wrong_event = {
        "kind": 8012,
        "pubkey": "dao_agent_01",
        "tags": [["d", "other_sensor"], ["cmd", "reboot"], ["seq", "1"]],
        "content": "{}",
    }
    result9 = handler.handle(wrong_event)
    assert not result9["ok"]
    print("  ✅ Wrong device_id rejected")

    stats = handler.stats()
    assert stats["executed"] > 0
    print(f"\n  Stats: {stats['executed']} executed, {stats['devices']} devices")

    print("\n✅ ALL COMMAND TESTS PASSED")


if __name__ == "__main__":
    _self_test()
