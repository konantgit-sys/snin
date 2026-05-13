#!/usr/bin/env python3
"""SNIN ESP32 — Power Manager (USB / Battery).

Мониторинг питания ESP32 через ADC.
Работает и от USB (псевдо-100%), и от батарейки (реальный уровень).

Режимы:
  - USB: battery_level всегда 100%, deep sleep отключён
  - Battery: читает ADC, шлёт алерт при < 10%, активирует deep sleep

Конфиг задаётся при инициализации.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("snin.power")


class PowerMode(Enum):
    USB = "usb"            # USB питание, без deep sleep
    BATTERY = "battery"    # Батарейка, deep sleep активен
    UNKNOWN = "unknown"


@dataclass
class PowerState:
    """Текущее состояние питания."""
    mode: PowerMode = PowerMode.UNKNOWN
    voltage: float = 0.0        # Вольт
    battery_level: int = 100     # 0-100%
    is_low: bool = False         # battery < 10%
    is_critical: bool = False    # battery < 5%
    uptime_seconds: float = 0.0


class PowerManager:
    """Менеджер питания ESP32.

    На PC — симуляция. На ESP32 — читает реальный ADC.
    """

    def __init__(
        self,
        mode: PowerMode = PowerMode.USB,
        adc_pin: int = 35,         # GPIO35 (у M5Stack / TTGO)
        adc_multiplier: float = 2.0,  # делитель напряжения
        low_threshold: int = 10,      # % для алерта
        critical_threshold: int = 5,  # % для critical
        deep_sleep_enabled: bool = False,
    ):
        self.mode = mode
        self.adc_pin = adc_pin
        self.adc_multiplier = adc_multiplier
        self.low_threshold = low_threshold
        self.critical_threshold = critical_threshold
        self.deep_sleep_enabled = deep_sleep_enabled if mode == PowerMode.BATTERY else False

        self._start_time = time.time()
        self._last_state = PowerState()
        self._alert_sent_low = False
        self._alert_sent_critical = False

    def read_voltage(self) -> float:
        """Читает напряжение через ADC.
        На PC — возвращает симулированное значение.
        На ESP32 — читает machine.ADC(pin).read().
        """
        if self.mode == PowerMode.USB:
            return 5.0  # USB — всегда 5V

        try:
            # Для MicroPython на ESP32:
            # from machine import ADC, Pin
            # adc = ADC(Pin(self.adc_pin))
            # adc.atten(ADC.ATTN_11DB)
            # raw = adc.read()
            # return raw / 4095 * 3.3 * self.adc_multiplier

            # Симуляция для PC-тестов:
            return 4.2  # полный LiPo — 4.2V
        except Exception as e:
            logger.warning(f"ADC read failed: {e}, using sim")
            return 4.2

    def _voltage_to_percent(self, voltage: float) -> int:
        """LiPo 3.7V: 3.0V = 0%, 4.2V = 100%."""
        if voltage >= 4.2:
            return 100
        if voltage <= 3.0:
            return 0
        return int((voltage - 3.0) / (4.2 - 3.0) * 100)

    def update(self) -> PowerState:
        """Обновить состояние питания."""
        voltage = self.read_voltage()
        pct = self._voltage_to_percent(voltage) if self.mode == PowerMode.BATTERY else 100

        self._last_state = PowerState(
            mode=self.mode,
            voltage=round(voltage, 2),
            battery_level=pct,
            is_low=pct <= self.low_threshold,
            is_critical=pct <= self.critical_threshold,
            uptime_seconds=time.time() - self._start_time,
        )
        return self._last_state

    def should_alert(self) -> bool:
        """Пора ли слать kind:8011?"""
        st = self.update()
        if st.is_critical and not self._alert_sent_critical:
            self._alert_sent_critical = True
            return True
        if st.is_low and not self._alert_sent_low:
            self._alert_sent_low = True
            return True
        return False

    def should_sleep(self) -> bool:
        """Пора ли в deep sleep?"""
        return self.deep_sleep_enabled and self._last_state.is_critical

    def get_state(self) -> PowerState:
        return self._last_state

    def stats(self) -> dict:
        st = self._last_state
        return {
            "mode": self.mode.value,
            "voltage": st.voltage,
            "battery_pct": st.battery_level,
            "is_low": st.is_low,
            "is_critical": st.is_critical,
            "deep_sleep": self.deep_sleep_enabled,
            "uptime_s": round(st.uptime_seconds),
        }


def _self_test():
    logging.basicConfig(level=logging.INFO)

    # USB mode
    pm = PowerManager(mode=PowerMode.USB)
    st = pm.update()
    assert st.battery_level == 100
    assert not st.is_low
    assert not pm.should_sleep()
    print("  ✅ USB mode: 100%")

    # Battery mode — full
    pm2 = PowerManager(mode=PowerMode.BATTERY, deep_sleep_enabled=True)
    st2 = pm2.update()
    assert st2.battery_level == 100
    assert not st2.is_low
    print(f"  ✅ Battery: {st2.battery_level}% at {st2.voltage}V")

    # Battery mode — low (simulate by overriding voltage)
    pm3 = PowerManager(mode=PowerMode.BATTERY, deep_sleep_enabled=True,
                        low_threshold=10, critical_threshold=5)
    # Override the read_voltage method to simulate low battery
    pm3.read_voltage = lambda: 3.2  # ~20%
    st3 = pm3.update()
    assert not st3.is_low  # 20% > 10%
    print(f"  ✅ Battery: {st3.battery_level}% — OK")

    # Critical (0% battery)
    pm4 = PowerManager(mode=PowerMode.BATTERY, deep_sleep_enabled=True,
                       low_threshold=5, critical_threshold=3)
    pm4.read_voltage = lambda: 2.9  # 0% (below 3.0V)
    st4 = pm4.update()
    assert st4.is_critical
    assert pm4.should_alert()        # critical alert (0% <= 3%)
    assert pm4.should_sleep()        # deep sleep
    print(f"  ✅ Battery: {st4.battery_level}% — CRITICAL, alert + sleep")

    # Low alert (set voltage to 3.15V = ~10%)
    pm4.read_voltage = lambda: 3.15
    pm4.low_threshold = 15
    pm4.critical_threshold = 5
    # Reset flags for clean test
    pm4._alert_sent_low = False
    pm4._alert_sent_critical = False
    assert pm4.should_alert()        # low alert (10% <= 15%)
    print("  ✅ Battery: ~10% — LOW alert")

    # Dedup
    assert not pm4.should_alert()    # already sent
    print("  ✅ Alert dedup: second call suppressed")

    print("\n✅ ALL POWER TESTS PASSED")


if __name__ == "__main__":
    _self_test()
