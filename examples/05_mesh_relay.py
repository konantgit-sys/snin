"""
Пример 5: relay-v2 интеграция — полный цикл от ESP32 до Nostr.

Показывает, как ESP32 -> Bridge -> AgentMesh -> relay-v2 -> Nostr.
Вся цепочка kind:8010 (Telemetry) -> kind:8012 (Command).
"""

import json
from hardware.esp32.relay.device_handler import (
    ESP32DeviceHandler, DeviceRegistry
)


def demo_telemetry():
    """Демо: обработка телеметрии от ESP32."""

    handler = ESP32DeviceHandler()

    # ESP32 прислал telemetry (kind:8010)
    event = {
        "kind": 8010,
        "pubkey": "a1b2c3d4e5f6",
        "tags": [["d", "sensor_kitchen_01"], ["t", "temperature"],
                 ["seq", "42"], ["batt", "85"]],
        "content": json.dumps({"temp": 23.5, "hum": 60.2}),
    }

    # handler принимает, проверяет, сохраняет
    result = handler.handle_telemetry(event)
    print(f"Telemetry handled: {result}")

    # Проверка температуры: если > 30 — команда
    payload = json.loads(event["content"])
    if payload["temp"] > 30.0:
        command = handler.build_command(
            device_id="sensor_kitchen_01",
            action="activate_fan",
            params={"fan_speed": 80, "duration": 300},
        )
        print(f"Command: kind={command['kind']}")

    print(f"Device stats: {handler.stats()}")


if __name__ == "__main__":
    demo_telemetry()
    print("\n-- relay-v2 demo OK --")
