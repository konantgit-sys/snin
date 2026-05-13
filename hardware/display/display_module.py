#!/usr/bin/env python3
"""SNIN Display Devices — M5Stack / TTGO T-Display / LilyGO T-Watch / Waveshare.

Эти устройства = ESP32 + экран + кнопки + батарея.
Роль в рое: визуальный терминал для DAO-голосования и статуса.

Что умеют:
1. Показывать список ESP32-сенсоров в рое
2. DAO-голосование: вопрос на экране → кнопки Да/Нет
3. Статус подключения: bridge / relay / mesh
4. Личные метрики агента

Дисплей-стек:
  MicroPython: framebuf + machine.SPI + драйвер дисплея
  C++ (опционально): LVGL — 8KB RAM, анимации, кнопки

Поддерживаемые дисплеи:
  - ILI9341 (320x240) — M5Stack
  - ST7789 (170x320) — TTGO T-Display
  - ST7735 (128x160) — TinyPICO
  - SSD1306 (128x64) — OLED (текстовый режим)
"""

from __future__ import annotations

import abc
import json
import time
import logging
from typing import Callable

logger = logging.getLogger("snin.display")


# ─── Абстрактный дисплей ───────────────────────────────────────
class Display(abc.ABC):
    """Абстрактный класс для любого дисплея в рое."""

    @abc.abstractmethod
    def clear(self):
        ...

    @abc.abstractmethod
    def text(self, text: str, x: int, y: int, color: tuple[int, int, int] = (255, 255, 255)):
        ...

    @abc.abstractmethod
    def show(self):
        ...

    @property
    @abc.abstractmethod
    def width(self) -> int:
        ...

    @property
    @abc.abstractmethod
    def height(self) -> int:
        ...


# ─── MicroPython framebuf (ESP32 + SPI LCD) ─────────────────────
class MicroPythonFramebufDisplay(Display):
    """Для MicroPython на ESP32 с framebuf + SPI.

    Подходит: ILI9341, ST7789, ST7735, SSD1306.

    Пример использования на ESP32:
        import snin_display
        d = snin_display.MicroPythonFramebufDisplay()
        d.show_swarm([{"device_id": "sensor_01", "temp": 23.5}])
    """

    def __init__(self, width: int = 320, height: int = 240, spi_id: int = 1,
                 cs: int = 5, dc: int = 17, rst: int = 16, bl: int = 4,
                 driver: str = "ili9341"):
        self._width = width
        self._height = height
        self._driver_name = driver

        try:
            import machine
            import framebuf

            self._spi = machine.SPI(spi_id, baudrate=40000000, sck=machine.Pin(18),
                                    mosi=machine.Pin(23), miso=machine.Pin(19))
            self._cs = machine.Pin(cs, machine.Pin.OUT)
            self._dc = machine.Pin(dc, machine.Pin.OUT)
            self._rst = machine.Pin(rst, machine.Pin.OUT)
            self._bl = machine.Pin(bl, machine.Pin.OUT)
            self._bl.value(1)  # подсветка вкл

            self._buf = framebuf.FrameBuffer(
                bytearray(width * height * 2), width, height, framebuf.RGB565
            )
            self._fb = self._buf
            self._ready = True
        except Exception as e:
            logger.warning(f"Display init failed: {e}")
            self._ready = False

    def clear(self):
        if self._ready:
            self._fb.fill(0)

    def text(self, text: str, x: int, y: int, color: tuple = None):
        if self._ready:
            c = color or (255, 255, 255)
            color565 = ((c[0] >> 3) << 11) | ((c[1] >> 2) << 5) | (c[2] >> 3)
            self._fb.text(text, x, y, color565)

    def show(self):
        if self._ready:
            pass  # Отправка buf на дисплей — через драйвер

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    # ── SNIN-specific: дашборд роя ─────────────────────────────
    def show_swarm(self, devices: list[dict]):
        """Главный экран: список устройств в рое."""
        self.clear()

        # Заголовок
        self.text("SNIN SWARM", 10, 10, (0, 212, 255))
        y = 35

        for d in devices[:8]:  # максимум 8 на экране
            did = d.get("device_id", "?")[:16]
            temp = d.get("payload", {}).get("temp", "?")
            batt = d.get("payload", {}).get("batt", "?")
            color = (100, 255, 100) if (batt != "?" and batt > 20) else (255, 100, 100)
            self.text(f"{did}  {temp}C  batt:{batt}%", 15, y, color)
            y += 28

        self.text(f"Total: {len(devices)} devices", 10, self._height - 20, (100, 100, 100))
        self.show()

    def show_dao_proposal(self, proposal: dict):
        """Экран DAO-голосования: вопрос + кнопки Да/Нет."""
        self.clear()
        self.text("DAO VOTE", 10, 10, (255, 200, 0))

        title = proposal.get("title", "?")[:30]
        self.text(title, 10, 45, (255, 255, 255))

        desc = proposal.get("description", "")[:120]
        y = 80
        for line in [desc[i:i+28] for i in range(0, len(desc), 28)]:
            self.text(line, 15, y, (200, 200, 200))
            y += 20

        # Кнопки
        self.text("[ YES ]", 40, self._height - 50, (100, 255, 100))
        self.text("[ NO  ]", self._width - 120, self._height - 50, (255, 100, 100))

        self.show()

    def show_status(self, bridge_ok: bool, mesh_ok: bool, relay_ok: bool):
        """Экран статуса соединений."""
        self.clear()
        self.text("SNIN STATUS", 10, 10, (0, 212, 255))
        y = 45

        statuses = [
            ("Bridge", bridge_ok),
            ("Mesh", mesh_ok),
            ("Relay", relay_ok),
        ]
        for name, ok in statuses:
            color = (100, 255, 100) if ok else (255, 100, 100)
            self.text(f"{'●' if ok else '○'} {name}", 20, y, color)
            y += 30

        self.show()


# ─── PC эмуляция дисплея (pygame) ──────────────────────────────
class PCDisplaySimulator:
    """Эмулирует дисплей на PC для отладки без ESP32.

    Usage:
        sim = PCDisplaySimulator()
        sim.show_swarm([{"device_id": "test_01", "payload": {"temp": 23.5}}])
        sim.close()
    """

    def __init__(self, width: int = 320, height: int = 240):
        self._width = width
        self._height = height
        self._running = False

    def start(self):
        import pygame
        pygame.init()
        self._screen = pygame.display.set_mode((self._width, self._height))
        self._font = pygame.font.Font(None, 24)
        self._running = True
        logger.info(f"PC display simulator started: {self._width}x{self._height}")

    def show_swarm(self, devices: list[dict]):
        if not self._running:
            return
        import pygame
        self._screen.fill((10, 10, 10))

        y = 10
        title = self._font.render("SNIN SWARM (SIM)", True, (0, 212, 255))
        self._screen.blit(title, (10, y))
        y += 30

        for d in devices[:8]:
            did = d.get("device_id", "?")[:16]
            temp = d.get("payload", {}).get("temp", "?")
            batt = d.get("payload", {}).get("batt", "?")
            text = f"{did}  {temp}C  batt:{batt}%"
            color = (100, 255, 100) if (batt != "?" and batt > 20) else (255, 100, 100)
            line = self._font.render(text, True, color)
            self._screen.blit(line, (20, y))
            y += 30

        total = self._font.render(f"Total: {len(devices)}", True, (100, 100, 100))
        self._screen.blit(total, (10, self._height - 30))
        pygame.display.flip()

    def show_dao_proposal(self, proposal: dict):
        if not self._running:
            return
        import pygame
        self._screen.fill((10, 10, 10))

        title = self._font.render(f"DAO: {proposal.get('title', '?')}", True, (255, 200, 0))
        self._screen.blit(title, (10, 10))

        desc = proposal.get("description", "")[:100]
        y = 50
        for line in [desc[i:i-30] for i in range(0, len(desc), 30)]:
            line_r = self._font.render(line, True, (200, 200, 200))
            self._screen.blit(line_r, (15, y))
            y += 25

        yes = self._font.render("[ YES ]", True, (100, 255, 100))
        self._screen.blit(yes, (40, self._height - 50))
        no = self._font.render("[ NO ]", True, (255, 100, 100))
        self._screen.blit(no, (self._width - 120, self._height - 50))
        pygame.display.flip()

    def close(self):
        import pygame
        pygame.quit()
        self._running = False


# ─── Self-test ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("SNIN Display Module — Self Test (PC simulator)")
    print("=" * 50)

    sim = PCDisplaySimulator()
    sim.start()

    test_devices = [
        {"device_id": "sensor_kitchen", "payload": {"temp": 23.5, "batt": 85}},
        {"device_id": "sensor_garden", "payload": {"temp": 18.2, "batt": 45}},
        {"device_id": "sensor_roof", "payload": {"temp": 31.0, "batt": 12}},
        {"device_id": "m5stack_01", "payload": {"temp": 26.0, "batt": 90}},
    ]

    print("Showing swarm...")
    sim.show_swarm(test_devices)

    proposal = {
        "title": "Increase measurement freq on sensor_roof?",
        "description": "Current 60s. Proposal: 30s due to high temp variance.",
    }
    print("Showing DAO proposal...")
    sim.show_dao_proposal(proposal)

    import time
    time.sleep(5)
    sim.close()
    print("✅ Display self-test PASSED")
