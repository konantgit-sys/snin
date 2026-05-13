# SNIN Phase Plan — Итог + Фазы

## Что уже сделано (Итог за 1 день)

| Компонент | Статус |
|-----------|--------|
| Transport Abstraction (TCP/HTTP/IPFS/ESP-NOW) | ✅ 290 строк |
| Bridge ESP-NOW → AgentMesh + Ed25519 + WAL | ✅ 288 строк |
| relay-v2 plugin (kind:8010-8012) | ✅ 241 строка |
| ESP32 прошивка (DHT22 + подпись + ESP-NOW) | ✅ 256 строк |
| ESP32 bridge прошивка (ESP-NOW → UART) | ✅ 188 строк |
| Симулятор ESP32 + self-test | ✅ 300 строк |
| Raspberry Pi модуль (3 роли) | ✅ 312 строк |
| Arduino C++ прошивка (ESP8266) | ✅ 162 строки |
| Display модуль (M5Stack/TTGO/LilyGO) | ✅ 254 строки |
| Спецификация 10 платформ | ✅ |
| Stack Optimization + Gap Analysis | ✅ |
| **Код с нуля: ~350 строк уникального** | ✅ |
| **Остальное: порты из p2p-agent-mesh** | ✅ |
| **Тесты: все проходят** | ✅ |

---

## 5 фаз развития

### Фаза 0 — Transport Abstraction ✅ (СДЕЛАНО)

**Что:** `sdk/transport.py` — TCP/HTTP/IPFS/ESP-NOW через единый интерфейс.
**Зачем:** AgentMesh теперь не привязан к одному транспорту.

---

### Фаза 1 — Device Bridge ✅ (СДЕЛАНО)

**Что:** `bridge/bridge.py` + `relay/device_handler.py` + прошивки + симулятор.
**Зачем:** ESP32 шлёт телеметрию → bridge → AgentMesh → relay-v2.

---

### Фаза 2 — Multi-Platform ✅ (СДЕЛАНО)

**Что:** Arduino (C++), Raspberry Pi (Python), Display (M5Stack/TTGO/LilyGO).
**Зачем:** 1 протокол для всех железок.

---

### Фаза 3 — Transport Expansion (1-2 дня)

**Что добавить:**
- **LoRa** (SX1278) — дальность >2km
- **BLE** — LilyGO T-Watch, телефон
- **mDNS Discovery** — ESP32 сам находит bridge
- **OTA Update** — обновление прошивок по воздуху
- **Device Command Loop (kind:8012)** — DAO → ESP32

**Зачем:** 70% use-cases без этого не работают (поле, лес, носимые устройства).

---

### Фаза 4 — Когнитивный Рой (3-5 дней)

**Что добавить:**
- Task Scheduler — распределение задач между агентами
- GPS Tracker — привязка телеметрии к координатам
- Edge AI — TensorFlow Lite Micro на ESP32 (числа/текст)
- Camera Agent — ESP32 + OV2640, отправка изображений
- Power Manager — глубокий сон, батарея 6+ мес

**Зачем:** рой становится автономным, а не просто сенсорная сеть.

---

### Фаза 5 — DePIN Production (1-2 недели)

**Что:**
- Порт ESP32 кода на C (ESP-IDF) — для >100 устройств
- Миграция WAL на InfluxDB/TimescaleDB
- Grafana dashboard для роя
- Load testing: 1000 ESP32 → 1 bridge
- Документация и GitHub Actions CI

**Зачем:** из прототипа в продакшен.

---

## Резюме

Сейчас на **Фазе 1-2**. 3 следующих шага:

1. **LoRa + BLE** — закрыть транспортные дыры
2. **OTA + mDNS** — чтобы прошивки обновлялись сами
3. **Device Command (8012)** — чтобы DAO мог управлять ESP32

После этого — Фаза 4 (рой сам принимает решения).
