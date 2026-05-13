# SNIN Architecture

## Слои

```
APPLICATION      Sensor read / DAO vote / Display render
────────────────────────────────────────────────────────
AGENT LAYER      AgentMesh (emit/listen/capabilities)
────────────────────────────────────────────────────────
TRANSPORT        TCP | HTTP | IPFS | ESP-NOW
────────────────────────────────────────────────────────
CRYPTO           Ed25519 (ucrypto / cryptography)
────────────────────────────────────────────────────────
BRIDGE           ESP-NOW → UART → bridge.py → AgentMesh
                 WAL, anti-replay, Ed25519 verify
────────────────────────────────────────────────────────
RELAY-V2         Nostr kinds 31000-31002
                 Device Telemetry | Registration | Command
────────────────────────────────────────────────────────
HARDWARE         ESP32 | Arduino | RPi | M5Stack | TTGO
```

## Поток данных (один для всех платформ)

```
1. DHT22 читает температуру на ESP32
2. ESP32 подписывает Ed25519, шлёт ESP-NOW (250 байт)
3. Bridge принимает, верифицирует, шлёт в AgentMesh
4. AgentMesh публикует в relay-v2 (kind:31000)
5. DAO Pilot видит событие, может голосовать
6. DAO → kind:31002 → bridge → ESP-NOW → ESP32
```

## Транспорты

| Тип | Дальность | Пропускная | Пакет | Платформы |
|-----|-----------|-----------|-------|-----------|
| ESP-NOW | ~200m | 250 байт | ESP-NOW фрейм | ESP32, ESP8266 |
| TCP | ∞ | ∞ | поток | RPi, сервер |
| HTTP | ∞ | ∞ | JSON | RPi, сервер |
| IPFS | ∞ | ∞ | GossipSub | RPi, сервер |

## Криптография

- Подпись: Ed25519 (32 байта ключ, 64 байта подпись)
- Совместимость: ucrypto (ESP32) ↔ cryptography (Python)
- Anti-replay: sequence number + window
- Хранилище ключей: config.py на ESP32

## Релеи (Nostr)

| Kind | Название | Назначение |
|------|----------|-----------|
| 31000 | Device Telemetry | Температура, влажность, батарея |
| 31001 | Device Registration | Регистрация нового ESP32 |
| 31002 | Device Command | Команда от DAO к ESP32 |
