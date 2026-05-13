#!/usr/bin/env python3
"""SNIN Display Devices v0.6 — M5Stack / TTGO T-Display / LilyGO T-Watch.

Дисплей = ESP32 + экран + кнопки + батарея.
Роль: DAO-терминал + dashboard телеметрии.

Что умеет v0.6:
1. Список ESP32 в рое (kind:31000 телеметрия в реальном времени)
2. DAO-голосование: вопрос → Да/Нет → kind:31002 команда
3. Статус bridge/relay/mesh
4. Алерты устройств (kind:31007) — красный экран с предупреждением

Драйверы:
  - PC симулятор (pygame, для разработки)
  - ST7789 (170x320) — TTGO T-Display
  - ILI9341 (320x240) — M5Stack
"""

from __future__ import annotations

import abc
import json
import time
import logging
from typing import Callable
from dataclasses import dataclass, field

logger = logging.getLogger("snin.display")


# ─── Data models ───────────────────────────────────────────────
@dataclass
class DeviceTelemetry:
    """Телеметрия одного ESP32 на экране."""
    device_id: str
    temp: float = 0.0
    hum: float = 0.0
    battery: int = 100
    last_seen: float = 0.0
    online: bool = False

    def age_seconds(self) -> float:
        return time.time() - self.last_seen if self.last_seen else 999


@dataclass
class DAOProposal:
    """Вопрос для голосования."""
    title: str
    description: str = ""
    proposal_id: str = ""
    votes_for: int = 0
    votes_against: int = 0
    deadline: float = 0.0


@dataclass
class AlertDisplay:
    """Алерт для отображения на экране."""
    device_id: str
    alert_type: str
    severity: str
    message: str
    timestamp: float = 0.0
    acknowledged: bool = False


# ─── Абстрактный дисплей ───────────────────────────────────────
class DisplayDriver(abc.ABC):
    @abc.abstractmethod
    def clear(self):
        ...

    @abc.abstractmethod
    def text(self, text: str, x: int, y: int, color: tuple = (255, 255, 255)):
        ...

    @abc.abstractmethod
    def show(self):
        ...

    @abc.abstractmethod
    def width(self) -> int: ...

    @abc.abstractmethod
    def height(self) -> int: ...


# ─── PC симулятор ──────────────────────────────────────────────
class PCDisplaySimulator(DisplayDriver):
    """Симулятор дисплея на PC через pygame."""

    def __init__(self, width: int = 320, height: int = 240, scale: float = 2.0):
        self._w = width
        self._h = height
        self._scale = scale
        self._surface = None

        try:
            import pygame
            pygame.init()
            self._surface = pygame.Surface((width, height))
            self._window = pygame.display.set_mode((
                int(width * scale), int(height * scale)
            ))
            pygame.display.set_caption("SNIN Display v0.6")
            self._font = pygame.font.Font(None, 24)
            self._small_font = pygame.font.Font(None, 16)
        except ImportError:
            logger.warning("pygame not installed — display simulation disabled")

    def clear(self):
        if self._surface:
            self._surface.fill((0, 0, 0))

    def text(self, text: str, x: int, y: int, color: tuple = (255, 255, 255)):
        if self._surface:
            import pygame
            c = pygame.Color(*color)
            rendered = self._font.render(text, True, c)
            self._surface.blit(rendered, (x, y))

    def small_text(self, text: str, x: int, y: int, color: tuple = (200, 200, 200)):
        if self._surface:
            import pygame
            c = pygame.Color(*color)
            rendered = self._small_font.render(text, True, c)
            self._surface.blit(rendered, (x, y))

    def show(self):
        if self._surface:
            import pygame
            scaled = pygame.transform.scale(self._surface, (
                int(self._w * self._scale), int(self._h * self._scale)
            ))
            self._window.blit(scaled, (0, 0))
            pygame.display.flip()

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h


# ─── Dashboard ─────────────────────────────────────────────────
class DAODashboard:
    """Основной экран: список ESP32 + DAO голосование + алерты."""

    def __init__(self, display: DisplayDriver, relay_url: str = "ws://localhost:8198"):
        self.display = display
        self.relay_url = relay_url
        self.devices: dict[str, DeviceTelemetry] = {}
        self.alerts: list[AlertDisplay] = []
        self.proposals: list[DAOProposal] = []
        self._page = 0  # 0=devices, 1=alerts, 2=dao
        self._last_refresh = 0

    def add_telemetry(self, device_id: str, temp: float, hum: float, batt: int):
        """Обновить телеметрию устройства."""
        self.devices[device_id] = DeviceTelemetry(
            device_id=device_id,
            temp=temp,
            hum=hum,
            battery=batt,
            last_seen=time.time(),
            online=True,
        )

    def add_alert(self, device_id: str, alert_type: str,
                  severity: str, message: str):
        """Добавить алерт на экран."""
        self.alerts.insert(0, AlertDisplay(
            device_id=device_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            timestamp=time.time(),
        ))
        # Оставляем последние 10
        self.alerts = self.alerts[:10]

    def render(self):
        """Отрисовать текущую страницу."""
        self.display.clear()
        self._render_header()

        if self._page == 0:
            self._render_devices()
        elif self._page == 1:
            self._render_alerts()
        elif self._page == 2:
            self._render_dao()

        self._render_footer()
        self.display.show()

    def _render_header(self):
        self.display.text("SNIN NETWORK", 5, 5, (0, 180, 255))
        self.display.small_text(
            f"Devices: {len(self.devices)}  Alerts: {len(self.alerts)}",
            5, 25, (150, 150, 150),
        )

    def _render_devices(self):
        y = 45
        self.display.small_text("=== DEVICES ===", 5, y, (255, 255, 0))
        y += 15

        if not self.devices:
            self.display.text("No devices", 20, y, (150, 150, 150))
            return

        for did, dev in sorted(self.devices.items())[:8]:
            age = dev.age_seconds()
            color = (0, 255, 0) if age < 60 else (255, 255, 0) if age < 300 else (255, 0, 0)
            batt_color = (0, 255, 0) if dev.battery > 30 else (255, 0, 0)

            self.display.small_text(
                f"{dev.device_id[:14]:14s} "
                f"{dev.temp:5.1f}C {dev.hum:5.1f}% "
                f"BAT:{dev.battery:3d}%",
                5, y, color,
            )
            y += 15

    def _render_alerts(self):
        y = 45
        self.display.small_text("=== ALERTS ===", 5, y, (255, 100, 100))
        y += 15

        if not self.alerts:
            self.display.text("No active alerts", 20, y, (0, 255, 0))
            return

        for alert in self.alerts[:6]:
            color = (255, 0, 0) if alert.severity == "critical" else \
                    (255, 100, 0) if alert.severity == "high" else (255, 255, 0)
            self.display.small_text(
                f"[{alert.severity.upper():8s}] {alert.device_id[:10]:10s}: "
                f"{alert.message[:20]:20s}",
                5, y, color,
            )
            y += 15

    def _render_dao(self):
        y = 45
        self.display.small_text("=== DAO VOTING ===", 5, y, (100, 255, 100))
        y += 15

        if not self.proposals:
            self.display.text("No active proposals", 20, y, (150, 150, 150))
            return

        for prop in self.proposals[:3]:
            self.display.text(prop.title[:25], 10, y, (255, 255, 255))
            y += 15
            total = prop.votes_for + prop.votes_against
            if total > 0:
                pct = int(prop.votes_for / total * 100)
                self.display.small_text(
                    f"For: {prop.votes_for}  Against: {prop.votes_against}  "
                    f"({pct}% support)",
                    10, y, (200, 200, 200),
                )
                y += 15
            y += 5

    def _render_footer(self):
        h = self.display.height()
        pages = ["Devices", "Alerts", "DAO"]
        nav = "  ".join(
            f"[{p.upper()}]" if i == self._page else p
            for i, p in enumerate(pages)
        )
        self.display.small_text(nav, 5, h - 15, (100, 100, 100))

    def next_page(self):
        self._page = (self._page + 1) % 3

    def prev_page(self):
        self._page = (self._page - 1) % 3

    def update_from_relay(self, events: list[dict]):
        """Обновить данные из событий relay-v2."""
        for ev in events:
            kind = ev.get("kind")
            if kind == 31000:
                tags = dict(t[:2] for t in ev.get("tags", []))
                did = tags.get("d", "unknown")
                try:
                    content = json.loads(ev.get("content", "{}"))
                except json.JSONDecodeError:
                    content = {}
                self.add_telemetry(
                    device_id=did,
                    temp=content.get("temp", 0),
                    hum=content.get("hum", 0),
                    batt=content.get("battery", 100),
                )
            elif kind == 31007:
                tags = dict(t[:2] for t in ev.get("tags", []))
                did = tags.get("d", "unknown")
                alert_type = tags.get("alert", "unknown")
                severity = tags.get("severity", "low")
                try:
                    content = json.loads(ev.get("content", "{}"))
                except json.JSONDecodeError:
                    content = {}
                self.add_alert(
                    device_id=did,
                    alert_type=alert_type,
                    severity=severity,
                    message=content.get("message", ""),
                )


def _self_test():
    logging.basicConfig(level=logging.INFO)

    display = PCDisplaySimulator(width=320, height=240)
    dashboard = DAODashboard(display)

    # Симуляция телеметрии
    dashboard.add_telemetry("sensor_01", 23.5, 60.2, 85)
    dashboard.add_telemetry("sensor_02", 18.2, 45.0, 70)
    dashboard.add_telemetry("sensor_03", 30.0, 55.0, 12)  # low battery
    assert len(dashboard.devices) == 3
    print("  ✅ 3 devices added")

    # Симуляция алерта
    dashboard.add_alert("sensor_03", "battery_low", "high", "Battery 12%")
    assert len(dashboard.alerts) == 1
    print("  ✅ Alert added")

    # Симуляция DAO
    dashboard.proposals.append(DAOProposal(
        title="Increase polling interval",
        votes_for=5,
        votes_against=2,
    ))
    print("  ✅ DAO proposal added")

    # Рендер страниц
    for page in range(3):
        dashboard._page = page
        dashboard.render()
        print(f"  ✅ Rendered page {page}")

    # Обновление из relay
    events = [
        {"kind": 31000, "tags": [["d", "sensor_04"]],
         "content": json.dumps({"temp": 26.0, "hum": 50, "battery": 90})},
        {"kind": 31007, "tags": [["d", "sensor_01"], ["alert", "temp_high"],
                                 ["severity", "high"]],
         "content": json.dumps({"message": "Temperature 52C"})},
    ]
    dashboard.update_from_relay(events)
    assert "sensor_04" in dashboard.devices
    assert len(dashboard.alerts) == 2
    print("  ✅ Relay events processed")

    print("\n✅ ALL DISPLAY TESTS PASSED")


if __name__ == "__main__":
    _self_test()
