#!/usr/bin/env python3
"""SNIN ESP32 — Alert Handler for kind:8011.

Генерирует и обрабатывает алерты устройств.

kind:8011 format:
  {
    "kind": 8011,
    "pubkey": "<device_pk>",
    "tags": [
      ["d", "<device_id>"],
      ["alert", "<alert_type>"],
      ["severity", "low|medium|high|critical"],
      ["seq", "<seq>"],
    ],
    "content": '{"message": "...", "value": 42}'
  }

Alert types:
  - battery_low         — батарея < 10%
  - battery_critical    — батарея < 5%
  - temp_high           — температура > 50°C
  - sensor_fail         — сенсор не отвечает
  - offline             — устройство не выходило на связь > N минут
  - tamper              — физическое вскрытие корпуса
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("snin.alert")


class AlertType(str, Enum):
    BATTERY_LOW = "battery_low"
    BATTERY_CRITICAL = "battery_critical"
    TEMP_HIGH = "temp_high"
    SENSOR_FAIL = "sensor_fail"
    OFFLINE = "offline"
    TAMPER = "tamper"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_MAP = {
    AlertType.BATTERY_LOW: Severity.HIGH,
    AlertType.BATTERY_CRITICAL: Severity.CRITICAL,
    AlertType.TEMP_HIGH: Severity.HIGH,
    AlertType.SENSOR_FAIL: Severity.MEDIUM,
    AlertType.OFFLINE: Severity.LOW,
    AlertType.TAMPER: Severity.CRITICAL,
}


@dataclass
class Alert:
    device_id: str
    alert_type: AlertType
    severity: Severity
    message: str
    value: float | None = None
    seq: int = 0
    timestamp: float = 0.0

    def to_kind_8011(self) -> dict:
        return {
            "kind": 8011,
            "pubkey": self.device_id,
            "tags": [
                ["d", self.device_id],
                ["alert", self.alert_type.value],
                ["severity", self.severity.value],
                ["seq", str(self.seq)],
            ],
            "content": json.dumps({
                "message": self.message,
                "value": self.value,
                "ts": self.timestamp,
            }),
        }


class AlertManager:
    """Менеджер алертов: генерация, дедупликация, хранение истории."""

    def __init__(self, cooldown_seconds: float = 300.0):
        self.cooldown = cooldown_seconds
        self._last_sent: dict[str, float] = {}  # alert_key -> timestamp
        self._history: list[Alert] = []
        self._seq: int = 0

    def _alert_key(self, device_id: str, alert_type: AlertType) -> str:
        return f"{device_id}:{alert_type.value}"

    def can_send(self, device_id: str, alert_type: AlertType) -> bool:
        """Проверка кулдауна: не чаще 1 раза в N секунд."""
        key = self._alert_key(device_id, alert_type)
        last = self._last_sent.get(key, 0.0)
        return (time.time() - last) >= self.cooldown

    def send(self, device_id: str, alert_type: AlertType,
             message: str, value: float | None = None) -> Alert | None:
        """Создать алерт. Возвращает None если кулдаун не прошёл."""
        if not self.can_send(device_id, alert_type):
            logger.debug(f"Alert suppressed by cooldown: {device_id} {alert_type.value}")
            return None

        self._seq += 1
        severity = SEVERITY_MAP.get(alert_type, Severity.LOW)

        alert = Alert(
            device_id=device_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            value=value,
            seq=self._seq,
            timestamp=time.time(),
        )

        key = self._alert_key(device_id, alert_type)
        self._last_sent[key] = time.time()
        self._history.append(alert)

        logger.warning(f"ALERT [{severity.value}] {device_id}: {message}")
        return alert

    def get_history(self, limit: int = 20) -> list[dict]:
        return [a.to_kind_8011() for a in self._history[-limit:]]

    def stats(self) -> dict:
        return {
            "total_alerts": len(self._history),
            "active_cooldowns": sum(
                1 for t in self._last_sent.values()
                if (time.time() - t) < self.cooldown
            ),
            "by_severity": {
                s.value: sum(1 for a in self._history if a.severity == s)
                for s in Severity
            },
        }


def _self_test():
    logging.basicConfig(level=logging.INFO)

    mgr = AlertManager(cooldown_seconds=1.0)  # короткий кулдаун для теста

    # 1. Battery low
    a1 = mgr.send("sensor_01", AlertType.BATTERY_LOW, "Battery 8%", value=8.0)
    assert a1 is not None
    assert a1.severity == Severity.HIGH
    assert a1.device_id == "sensor_01"
    print(f"  ✅ {a1.alert_type.value} [{a1.severity.value}]: {a1.message}")

    # 2. Cooldown suppression
    a2 = mgr.send("sensor_01", AlertType.BATTERY_LOW, "Battery 7%", value=7.0)
    assert a2 is None
    print("  ✅ Cooldown suppresses duplicate")

    # 3. Different type — OK
    a3 = mgr.send("sensor_01", AlertType.TEMP_HIGH, "Temperature 52°C", value=52.0)
    assert a3 is not None
    print(f"  ✅ {a3.alert_type.value}: {a3.message}")

    # 4. Different device — OK
    a4 = mgr.send("sensor_02", AlertType.BATTERY_LOW, "Battery 9%", value=9.0)
    assert a4 is not None
    print(f"  ✅ {a4.device_id} {a4.alert_type.value}")

    # 5. Critical battery
    a5 = mgr.send("sensor_01", AlertType.BATTERY_CRITICAL, "Battery 3%", value=3.0)
    assert a5 is not None
    assert a5.severity == Severity.CRITICAL
    print(f"  ✅ {a5.alert_type.value} [{a5.severity.value}]: {a5.message}")

    # 6. kind:8011 format
    event = a5.to_kind_8011()
    assert event["kind"] == 8011
    assert event["tags"][1][1] == "battery_critical"
    print(f"  ✅ kind:8011 format: {event['tags'][1][1]}")

    # 7. Stats
    stats = mgr.stats()
    assert stats["total_alerts"] == 4
    assert stats["by_severity"]["high"] == 3  # battery_low x2 + temp_high
    print(f"  ✅ Stats: {stats['total_alerts']} total, {stats['by_severity']}")

    print("\n✅ ALL ALERT TESTS PASSED")


if __name__ == "__main__":
    _self_test()
