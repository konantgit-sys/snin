"""
Пример 3: BLE-мост — ESP32 отправляет данные на телефон.

Когда нужно видеть датчики на телефоне без интернета.
ESP32 работает как BLE GATT сервер, телефон подключается и читает.

BLE Service:
  UUID: 6e400001-b5a3-f393-e0a9-e50e24dcca9e
  TX:   6e400002-b5a3-f393-e0a9-e50e24dcca9e (ESP32 -> Phone)
  RX:   6e400003-b5a3-f393-e0a9-e50e24dcca9e (Phone -> ESP32)
"""

import asyncio
from hardware.esp32.ble.ble_phy import BLECommandHandler


async def demo_commands():
    """Демо: обработка BLE-команд от телефона."""

    handler = BLECommandHandler(device_id="bridge_01")
    handler.set_sensor_data({"temp": 23.5, "hum": 60.2})

    # Телефон прислал "poll" — запрос показаний
    resp = await handler._handle_poll({"payload": {}})
    print("Poll:", resp)

    # Телефон прислал "register" — регистрация
    resp = await handler._handle_register({"device_id": "new_sensor_02"})
    print("Register:", resp)

    # Телефон прислал "config" — смена интервала
    resp = await handler._handle_config({"interval": 30, "threshold": 25.0})
    print("Config:", resp)

    # Телефон прислал "status"
    resp = await handler._handle_status({})
    print("Status:", resp)


if __name__ == "__main__":
    asyncio.run(demo_commands())
    print("\n-- BLE demo OK --")
