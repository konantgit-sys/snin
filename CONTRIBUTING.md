# Contributing to SNIN

## Структура коммитов

```
vMAJOR.MINOR — Краткое описание
- Список изменений построчно
- Каждый пункт — глагол в прошедшем времени
```

## Self-test перед push

```bash
cd hardware/esp32
python3 test_smoke.py          # ALL TESTS PASSED
python3 sim/sim_sensor.py --self-test  # Self test PASSED
python3 lora/lora_phy.py       # ALL LORA TESTS PASSED
python3 ble/ble_phy.py         # ALL BLE TESTS PASSED
```

## Что принимается

- Новые транспорты (LoRa, BLE, Zigbee, CAN)
- Прошивки для новых платформ
- Улучшения документации
- Баг-фиксы
- CI/CD конфигурация

## Что НЕ принимается

- Код с хардкоженными ключами/токенами
- Без self-test
- С сant-спамингом
- Рефакторинг без тестов
