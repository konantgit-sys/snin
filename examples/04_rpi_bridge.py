"""
Пример 4: Raspberry Pi — хаб для роя ESP32.

RPi — центральный узел. На нём работают:
  1. Bridge (ESP-NOW -> AgentMesh)
  2. Agent (подписан на kind:31000, публикует решения)
  3. mDNS announcer (чтобы ESP32 сами находили RPi)
  4. HDMI dashboard (опционально)

Требуется:
  - Raspberry Pi 4/5, Pi Zero 2W
  - ESP32 на USB (как ESP-NOW адаптер) — опционально
  - display (HDMI или TFT) — опционально
"""

from hardware.raspberry.raspberry_node import RPiNode
from hardware.esp32.mdns.mdns_discovery import MDnsAnnouncer


def demo_rpi_hub():
    """Демо: инициализация RPi-хаба для роя ESP32."""

    # Инициализация RPi-узла
    node = RPiNode(
        node_id="rpi_hub_01",
        roles=["bridge"],
        transport_type="tcp",
    )
    print(f"RPi node created: {node.node_id}")

    # mDNS: пусть ESP32 сами находят RPi
    announcer = MDnsAnnouncer(
        port=9090,
        device_id="rpi_hub_01",
    )
    announcer.start()
    print(f"mDNS announced: _snin-bridge._tcp.local on port 9090")

    # Статистика (без запуска — GPIO нет)
    print(f"Role: bridge")
    print(f"Transport: TCP")


if __name__ == "__main__":
    demo_rpi_hub()
    print("\n-- RPi bridge demo OK --")
