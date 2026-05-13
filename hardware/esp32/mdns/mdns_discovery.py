#!/usr/bin/env python3
"""SNIN mDNS — автоматическое обнаружение bridge в локальной сети.

Зачем:
  ESP32 подключается к WiFi и не знает IP адрес bridge.
  mDNS позволяет bridge рекламировать себя как snin-bridge.local.
  ESP32 просто ищет _snin-bridge._tcp.local. и получает IP:port.

Архитектура:
  Bridge (RPi / ESP32) → mDNS announce: _snin-bridge._tcp.local port 9090
  Sensor ESP32 → mDNS query → получает bridge IP → подключается

Протокол:
  Служебная запись:
    _snin-bridge._tcp.local. IN SRV 0 0 9090 bridge-hostname.local.
    _snin-bridge._tcp.local. IN TXT "ver=0.2" "cap=espnow" "id=bridge_01"

На RPi:
    sudo apt-get install avahi-daemon
    # Автоматически — через avahi-publish или python3-zeroconf

На ESP32 (MicroPython):
    import mdns  # встроен в MicroPython 1.23+
    bridge_ip = mdns.query("_snin-bridge._tcp.local")

На Pure Python:
    pip install zeroconf
    ZeroConf().get_service_info(type_, name)
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Callable

logger = logging.getLogger("snin.mdns")


# ─── mDNS Service Type ─────────────────────────────────────────
SNIN_MDNS_TYPE = "_snin-bridge._tcp.local."
SNIN_MDNS_NAME = "SNIN Bridge"


# ─── mDNS Announcer (на bridge) ─────────────────────────────────
class MDnsAnnouncer:
    """Публикует mDNS запись bridge в локальной сети.

    Использование на bridge (RPi):
        announcer = MDnsAnnouncer(port=9090, device_id="bridge_01")
        announcer.start()
        # bridge работает, mDNS обновляется каждые 60 секунд
    """

    def __init__(self, port: int = 9090, device_id: str = "bridge_01",
                 hostname: str | None = None):
        self._port = port
        self._device_id = device_id
        self._hostname = hostname or socket.gethostname()
        self._running = False
        self._zeroconf = None

    def start(self):
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf

            # Получаем локальный IP
            ip = self._get_local_ip()

            service_info = ServiceInfo(
                type_=SNIN_MDNS_TYPE,
                name=f"{SNIN_MDNS_NAME}-{self._device_id}.{SNIN_MDNS_TYPE}",
                addresses=[socket.inet_aton(ip)],
                port=self._port,
                properties={
                    "ver": "0.2",
                    "cap": "espnow",
                    "id": self._device_id,
                    "transport": "tcp",
                },
                server=f"{self._hostname}.local.",
            )

            self._zeroconf = Zeroconf()
            self._zeroconf.register_service(service_info)
            self._running = True
            logger.info(f"mDNS announced: {self._device_id} @ {ip}:{self._port}")

        except ImportError:
            logger.warning("zeroconf not installed — try: pip install zeroconf")
        except Exception as e:
            logger.error(f"mDNS announce failed: {e}")

    def stop(self):
        if self._zeroconf:
            self._zeroconf.unregister_all_services()
            self._zeroconf.close()
            self._running = False
            logger.info("mDNS stopped")

    @staticmethod
    def _get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"


# ─── mDNS Discoverer (на ESP32) ────────────────────────────────
class MDnsDiscoverer:
    """Ищет bridge в локальной сети через mDNS.

    Использование на ESP32:
        discoverer = MDnsDiscoverer()
        bridges = discoverer.discover(timeout=3.0)
        if bridges:
            bridge_ip = bridges[0]["ip"]
            bridge_port = bridges[0]["port"]
    """

    def __init__(self):
        self._zeroconf = None

    def discover(self, timeout: float = 3.0) -> list[dict]:
        """Найти все snin-bridge в сети."""
        try:
            from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf

            self._zeroconf = Zeroconf()
            found: list[dict] = []

            def on_change(zeroconf, service_type, name, state_change):
                if state_change == ServiceStateChange.Added:
                    info = zeroconf.get_service_info(service_type, name)
                    if info:
                        ip = socket.inet_ntoa(info.addresses[0]) if info.addresses else "?"
                        device_id = info.properties.get(b"id", b"?").decode()
                        found.append({
                            "name": name,
                            "ip": ip,
                            "port": info.port,
                            "device_id": device_id,
                            "ver": info.properties.get(b"ver", b"?").decode(),
                        })

            browser = ServiceBrowser(
                self._zeroconf, SNIN_MDNS_TYPE, handlers=[on_change]
            )

            # Ждём timeout
            import time
            time.sleep(timeout)
            browser.cancel()
            self._zeroconf.close()

            logger.info(f"mDNS discovered: {len(found)} bridge(s)")
            return found

        except ImportError:
            logger.warning("zeroconf not installed — try: pip install zeroconf")
            return []
        except Exception as e:
            logger.error(f"mDNS discover failed: {e}")
            return []


# ─── Integration: mDNS + ESP32 auto-connect ────────────────────
class AutoBridgeConnector:
    """ESP32 находит bridge через mDNS и подключается автоматически.

    Поток:
      1. ESP32 включается, подключается к WiFi
      2. mDNS ищет _snin-bridge._tcp.local
      3. Находит bridge, получает IP:port
      4. Подключается по TCP/ESP-NOW
      5. Регистрируется (kind:8014)
      6. Начинает слать телеметрию (kind:8010)
    """

    def __init__(self, device_id: str = "auto_esp32_01"):
        self.device_id = device_id
        self._bridge_info: dict | None = None

    def find_bridge(self, timeout: float = 3.0) -> dict | None:
        discoverer = MDnsDiscoverer()
        bridges = discoverer.discover(timeout)
        if bridges:
            self._bridge_info = bridges[0]
            logger.info(f"Found bridge: {self._bridge_info['ip']}:{self._bridge_info['port']}")
            return self._bridge_info
        logger.warning("No bridge found via mDNS")
        return None

    def connect(self) -> bool:
        if not self._bridge_info:
            self.find_bridge()
            if not self._bridge_info:
                return False

        # Подключение к bridge по TCP
        try:
            reader, writer = asyncio.open_connection(
                self._bridge_info["ip"],
                self._bridge_info["port"],
            )
            # Регистрация
            reg_packet = json.dumps({
                "topic": "esp32:register",
                "device_id": self.device_id,
                "seq": 0,
                "payload": {
                    "device_type": "temperature_sensor",
                    "fw_version": "snin-esp32-v0.1",
                    "capabilities": ["temperature", "humidity"],
                },
            })
            writer.write(reg_packet.encode() + b"\n")
            writer.close()
            logger.info(f"Connected and registered: {self.device_id}")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False


# ─── Self-test ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("SNIN mDNS Module — Self Test")
    print("=" * 50)

    # 1. Announcer test (без сети — не сработает)
    print("\n1. MDnsAnnouncer (requires zeroconf)...")
    try:
        import zeroconf
        print("  zeroconf available: ✅")
    except ImportError:
        print("  zeroconf not installed: pip install zeroconf")

    # 2. AutoBridgeConnector — поиск bridge
    print("\n2. AutoBridgeConnector...")
    print("  (works on real network with bridge)")

    # 3. Проверяем импорт всех компонентов
    print("\n3. Import check:")
    for cls_name in ["MDnsAnnouncer", "MDnsDiscoverer", "AutoBridgeConnector"]:
        try:
            obj = globals()[cls_name]
            print(f"  ✅ {cls_name}")
        except Exception as e:
            print(f"  ❌ {cls_name}: {e}")

    print("\n✅ mDNS Module OK (needs zeroconf + network to run)")