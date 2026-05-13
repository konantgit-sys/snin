#!/usr/bin/env python3
"""SNIN ESP32 — GPS Tracker Module.

Для LilyGO T-Watch, ESP32 + NEO-6M/GPS модулей.

Публикует kind:8015 (Device Location) в relay-v2.

Поток:
  GPS (NMEA) → ESP32 → kind:8015 → relay-v2 → DAO Pilot / Dashboard
                                       ↓
                              kind:8012 (geofence command)

kind:8015 format:
  {
    "kind": 8015,
    "pubkey": "<bridge_pk>",
    "tags": [
      ["d", "<device_id>"],
      ["lat", "<latitude>"],
      ["lon", "<longitude>"],
      ["alt", "<altitude_m>"],
      ["speed", "<kmh>"],
      ["satellites", "<count>"],
      ["seq", "<seq>"],
    ],
    "content": '{"hdop": 1.2, "fix_quality": 3}'
  }
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("snin.gps")


@dataclass
class GPSFix:
    """GPS координаты."""
    lat: float = 0.0           # широта (десятичные градусы)
    lon: float = 0.0           # долгота
    altitude: float = 0.0      # метры над уровнем моря
    speed: float = 0.0         # км/ч
    heading: float = 0.0       # курс (градусы)
    satellites: int = 0        # количество спутников
    hdop: float = 99.9         # горизонтальная точность (<2 = отлично)
    fix_quality: int = 0       # 0=no fix, 1=GPS, 2=DGPS
    timestamp: float = 0.0

    @property
    def has_fix(self) -> bool:
        return self.fix_quality > 0 and self.lat != 0.0

    @property
    def accuracy(self) -> str:
        if self.hdop < 2: return "excellent"
        elif self.hdop < 5: return "good"
        elif self.hdop < 10: return "fair"
        else: return "poor"


class GeofenceZone:
    """Геозона: круг радиусом N метров вокруг точки."""

    def __init__(self, name: str, lat: float, lon: float, radius_m: float = 100):
        self.name = name
        self.lat = lat
        self.lon = lon
        self.radius = radius_m

    def contains(self, fix: GPSFix) -> bool:
        """Проверить, находится ли точка внутри зоны."""
        if not fix.has_fix:
            return False
        dist = self._haversine(self.lat, self.lon, fix.lat, fix.lon)
        return dist <= self.radius

    def distance_to(self, fix: GPSFix) -> float:
        """Дистанция до центра зоны в метрах."""
        if not fix.has_fix:
            return float('inf')
        return self._haversine(self.lat, self.lon, fix.lat, fix.lon)

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Дистанция между двумя точками в метрах."""
        R = 6371000  # радиус Земли в метрах
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


class GPSTracker:
    """GPS трекер. На PC — симуляция. На ESP32 — NEO-6M через UART."""

    def __init__(self, device_id: str = "gps_tracker_01"):
        self.device_id = device_id
        self._last_fix = GPSFix()
        self._zones: list[GeofenceZone] = []
        self._in_zone: set[str] = set()
        self._seq = 0

        try:
            import pynmea2
            self._has_nmea = True
        except ImportError:
            self._has_nmea = False
            logger.info("pynmea2 not available — using GPS simulation")

    def add_geofence(self, zone: GeofenceZone):
        self._zones.append(zone)

    def read_gps(self) -> GPSFix:
        """Читает GPS. Симуляция на PC, NEO-6M на ESP32."""
        if self._has_nmea:
            try:
                return self._read_serial_gps()
            except Exception as e:
                logger.warning(f"GPS read error: {e}")

        return self._simulate_gps()

    def _read_serial_gps(self) -> GPSFix:
        """Чтение NMEA с UART (для ESP32 / RPi с GPS модулем)."""
        import pynmea2
        import serial

        with serial.Serial('/dev/ttyS0', 9600, timeout=2) as ser:
            line = ser.readline().decode('ascii', errors='replace').strip()
            if line.startswith('$GPGGA'):
                msg = pynmea2.parse(line)
                self._last_fix = GPSFix(
                    lat=msg.latitude,
                    lon=msg.longitude,
                    altitude=msg.altitude,
                    satellites=int(msg.num_sats),
                    hdop=float(msg.horizontal_dil) if msg.horizontal_dil else 99.9,
                    fix_quality=int(msg.gps_qual),
                    timestamp=time.time(),
                )
            elif line.startswith('$GPRMC'):
                msg = pynmea2.parse(line)
                if self._last_fix.lat == 0 and msg.latitude:
                    self._last_fix.lat = msg.latitude
                    self._last_fix.lon = msg.longitude
                self._last_fix.speed = msg.spd_over_grnd_kmph or 0
                self._last_fix.heading = msg.true_course or 0
                self._last_fix.timestamp = time.time()

        return self._last_fix

    def _simulate_gps(self) -> GPSFix:
        """Симуляция GPS для тестов на PC."""
        import random
        # Симулируем движение вокруг SNIN HQ (55.7558°N, 37.6173°E)
        base_lat, base_lon = 55.7558, 37.6173
        drift = time.time() * 0.00001  # медленный дрейф

        self._last_fix = GPSFix(
            lat=base_lat + math.sin(drift) * 0.001,
            lon=base_lon + math.cos(drift * 1.1) * 0.001,
            altitude=random.uniform(140, 160),
            speed=random.uniform(0, 5),
            heading=random.uniform(0, 360),
            satellites=random.randint(8, 15),
            hdop=random.uniform(0.8, 2.5),
            fix_quality=3 if random.random() > 0.1 else 1,
            timestamp=time.time(),
        )
        return self._last_fix

    def check_geofence(self) -> list[str]:
        """Проверить пересечение геозон."""
        fix = self._last_fix
        events = []

        for zone in self._zones:
            inside = zone.contains(fix)
            key = zone.name

            if inside and key not in self._in_zone:
                self._in_zone.add(key)
                events.append(f"enter:{key}")
                logger.info(f"Geofence ENTER: {key}")
            elif not inside and key in self._in_zone:
                self._in_zone.discard(key)
                events.append(f"exit:{key}")
                logger.info(f"Geofence EXIT: {key}")

        return events

    def to_kind_8015(self) -> dict:
        """Создать kind:8015 (Device Location) событие."""
        fix = self._last_fix
        self._seq += 1

        return {
            "kind": 8015,
            "pubkey": self.device_id,
            "tags": [
                ["d", self.device_id],
                ["lat", f"{fix.lat:.6f}"],
                ["lon", f"{fix.lon:.6f}"],
                ["alt", f"{fix.altitude:.1f}"],
                ["speed", f"{fix.speed:.1f}"],
                ["satellites", str(fix.satellites)],
                ["seq", str(self._seq)],
            ],
            "content": json.dumps({
                "hdop": fix.hdop,
                "fix_quality": fix.fix_quality,
                "accuracy": fix.accuracy,
            }),
        }

    def stats(self) -> dict:
        fix = self._last_fix
        return {
            "device_id": self.device_id,
            "has_fix": fix.has_fix,
            "lat": fix.lat,
            "lon": fix.lon,
            "satellites": fix.satellites,
            "accuracy": fix.accuracy,
            "geofence_zones": len(self._zones),
            "in_zone": list(self._in_zone),
        }


def _self_test():
    logging.basicConfig(level=logging.INFO)

    # 1. GPS симуляция
    tracker = GPSTracker(device_id="gps_tracker_01")
    fix = tracker.read_gps()
    assert fix.has_fix
    assert fix.lat != 0
    print(f"  ✅ GPS fix: {fix.lat:.4f}, {fix.lon:.4f} ({fix.satellites} sats)")

    # 2. kind:8015
    event = tracker.to_kind_8015()
    assert event["kind"] == 8015
    assert event["tags"][1][1] is not None
    print(f"  ✅ kind:8015: lat={event['tags'][1][1]} lon={event['tags'][2][1]}")

    # 3. Geofence
    tracker.add_geofence(GeofenceZone(
        name="home", lat=55.7558, lon=37.6173, radius_m=500,
    ))
    events = tracker.check_geofence()
    print(f"  ✅ Geofence events: {events}")

    # 4. Haversine
    dist = GeofenceZone._haversine(55.7558, 37.6173, 55.7558, 37.6173)
    assert dist < 1  # та же точка
    print(f"  ✅ Haversine: {dist:.1f}m (same point)")

    dist2 = GeofenceZone._haversine(55.7558, 37.6173, 55.7600, 37.6200)
    assert 300 < dist2 < 500  # ~400 метров
    print(f"  ✅ Haversine: {dist2:.1f}m (~400m)")

    print("\n✅ ALL GPS TESTS PASSED")


if __name__ == "__main__":
    _self_test()
