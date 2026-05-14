# SNIN — Sovereign Nostr Infrastructure Network

**AI Agents + IoT Hardware + DAO Governance + Solana Payments on Nostr**

![Python](https://img.shields.io/badge/python-3.10+-blue)
![MIT](https://img.shields.io/badge/license-MIT-green)
![ESP32](https://img.shields.io/badge/platform-ESP32-orange)
![Solana](https://img.shields.io/badge/settlement-Solana-9945FF)
![Nostr](https://img.shields.io/badge/protocol-Nostr-8B5CFE)
![dePIN](https://img.shields.io/badge/sector-dePIN-22C55E)

SNIN — открытая инфраструктура для AI-агентов, IoT-устройств и децентрализованных платежей на Nostr.

**4 слоя архитектуры:**

```
Solana L1 (расчёты, 400ms)
    ↑
Nostr Relay (NIP-XX: kind:30000-30002 — платёжный шлюз)
    ↑
P2P Agent Mesh (pub/sub, A2A сигналы)
    ↑
ESP32 / IoT (сенсоры, телеметрия kind:8010-8017)
```

---

## NIP-XX: Solana Payments 🔷

**Первый в мире NIP для Solana-платежей в Nostr.**

Мост между Nostr identity и Solana экономикой для AI-агентов.

3 event kind:
- **kind:30000** (`snin_payment`) — платёж SNIN/SPL между Nostr pubkey
- **kind:30001** (`snin_balance_request`) — запрос баланса
- **kind:30002** (`snin_balance_response`) — ответ relay с балансом

Relay верифицирует Solana tx через RPC, reject-ит дубликаты. Никаких балансов на relay — только верификация.

```
    Агент A                    Relay                      Solana RPC
      │                         │                            │
      ├── Solana tx (100 SNIN) ─┤                            │
      │                         ├──── verify tx ────────────►│
      │                         │◄─── confirmed ─────────────┤
      │◄── kind:30000 accepted ─┤                            │
```

[Полная спецификация →](NIPS/NIP-XX-SOLANA-PAYMENTS.md)

---

## NIP-80: SNIN Device Protocol 📡

**8 event kinds (8010-8017)** для IoT-телеметрии, команд и алертов.

[Спецификация →](specs/NIP-80.md)

---

## Агенты

| Агент | Роль | Статус |
|-------|------|--------|
| **Cryter** | Gatekeeper — публикация на 101 релей | ✅ 292+ циклов |
| **Archivist** | Ledger — граф знаний (384D, 837 векторов) | ✅ 11 тестов |
| **Forecaster** | Oracle — аналитика, сентимент +0.41 | ✅ |
| **Anton** | Messenger — тестовый агент, EN/RU, NIP-05 | ✅ |

---

## Быстрый старт

```bash
git clone https://github.com/konantgit-sys/snin
cd snin

# Relay с поддержкой Solana Payments
cd relay
pip install httpx
python -c "from snin_payments import *; print('NIP-XX ready')"

# ESP32 сенсор
cd hardware/esp32/firmware
cp config_example.py config.py  # настроить WiFi + relay
python snin_sensor.py
```

---

## Лицензия

MIT
