# SNIN Publication Checklist

> Тон публикации: сухо, точно, без маркетинга.
> Каждый пункт — проверяемый. Если не проверено — не написано.

---

## ⬜ Pre-push (перед каждым коммитом)

- [ ] `git status` — нет случайных файлов (pycache, .env, *ключи*)
- [ ] `git diff --stat` — объём изменений адекватен коммиту
- [ ] В коммит не попали:
  - приватные ключи Ed25519
  - реальные IP/домены кроме *.v2.site
  - токены доступа
  - __pycache__ / .pyc / .egg-info
- [ ] Сообщение коммита по схеме: `vMAJOR.MINOR — Краткое описание`

---

## ⬜ Self-test (обязательно)

- [ ] `PYTHONPATH=. python3 hardware/esp32/test_smoke.py` — ALL TESTS PASSED
- [ ] `PYTHONPATH=. python3 hardware/esp32/sim/sim_sensor.py --self-test` — PASSED
- [ ] `python3 hardware/esp32/lora/lora_phy.py` — ALL LORA TESTS PASSED
- [ ] `python3 hardware/esp32/ble/ble_phy.py` — ALL BLE TESTS PASSED
- [ ] Импорт mDNS + Raspberry + Display — без ошибок
- [ ] p2p-agent-mesh импорт — `from sdk.agent import AgentMesh` — без ошибок

---

## ⬜ README (визитка репозитория)

- [ ] Название проекта + 1 строка что это
- [ ] Схема архитектуры (ASCII или ссылка)
- [ ] Быстрый старт: `pip install`, `python3 test_smoke.py`
- [ ] Таблица модулей / файлов
- [ ] Статус фаз разработки
- [ ] Ссылки на связанные репозитории
- [ ] Лицензия

---

## ⬜ GitHub metadata

- [ ] Topics (20 шт): nostr, esp32, iot, arduino, raspberry-pi, sensors, p2p, mesh-network, ed25519, decentralized, agent, m5stack, lora, ble, mdns, iot-framework, smart-home, dePIN, sove-identity
- [ ] Description в репозитории: ~120 символов
- [ ] Website URL (если есть): https://snin.v2.site
- [ ] README рендерится корректно (нет битых ссылок)

---

## ⬜ Код (стиль)

- [ ] Python: snake_case, type hints, docstrings (что делает, как использовать)
- [ ] C++ (Arduino): camelCase, комментарии к конфигурации
- [ ] JSON: одинарные кавычки только где обязательно
- [ ] Нет `print()` в production коде (только `logging`)
- [ ] `if __name__ == "__main__":` — самодокументированный self-test

---

## ⬜ Архитектура (связность)

- [ ] Каждый модуль импортируется без циклических зависимостей
- [ ] `transport.py` — единственная точка входа для всех транспортов
- [ ] relay-v2 handler не зависит от bridge (plug-in)
- [ ] Симулятор не требует реального ESP32
- [ ] Тесты не требуют интернета (кроме mDNS)

---

## ⬜ Безопасность

- [ ] `config_example.py` — реальный config.py в .gitignore
- [ ] Никаких хардкоженных ключей в *.py
- [ ] SHA256/Ed25519 — только через библиотеки, не самописные
- [ ] ESP-NOW broadcast отключён по умолчанию

---

## ⬜ Для уникальности (чем SNIN отличается от других)

Что уже есть и чего нет у аналогов:
- [ ] **AgentMesh поверх ESP32** — ни у кого больше
- [ ] **ESP-NOW + Nostr relay** — Linux P2P mesh + ESP-NOW LoRa в одной архитектуре
- [ ] **DAO голосование на экране M5Stack/TTGO** — hardware DAO terminal
- [ ] **101 Nostr relay** — в p2p-agent-mesh
- [ ] **Ed25519 от ESP32 до relay-v2** — end-to-end, bridge не расшифровывает
- [ ] **1 протокол для 10 платформ** — ESP32, Arduino, RPi, M5Stack, T-Watch и др.

Чего не хватает:
- [ ] Документация на английском (сейчас RU-heavy)
- [ ] CI/CD тесты в GitHub Actions
- [ ] Package на PyPI (`pip install snin-hardware`)
- [ ] Arduino library в PlatformIO registry
- [ ] Примеров для copy-paste (5 штук минимум)
