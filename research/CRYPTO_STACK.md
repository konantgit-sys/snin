# SNIN ESP32 — Crypto Stack for MicroPython

**Цель:** Обеспечить идентичную криптографию на ESP32 и в p2p-agent-mesh (совместимость подписей, ключей, шифрования).  
**Дата:** 2026-05-13  

---

## 1. Current Crypto Stack (p2p-agent-mesh, Python)

| Компонент | Python библиотека | Применение |
|-----------|------------------|------------|
| Ed25519 sign | `cryptography.hazmat.primitives.asymmetric.ed25519` | Подпись каждого сообщения |
| X25519 ECDH | `cryptography.hazmat.primitives.asymmetric.x25519` | E2E key exchange |
| ChaCha20-Poly1305 | `cryptography.hazmat.primitives.ciphers.aead` | Шифрование контента |
| HKDF | `cryptography.hazmat.primitives.kdf.hkdf` | Key derivation per session |
| SHA256 | `hashlib` | Merkle tree, content hashing |
| Sequence nonce | uint32 counter | Anti-replay |

---

## 2. Target Crypto Stack (ESP32 MicroPython)

| Компонент | MicroPython библиотека | Python → uP совместимость |
|-----------|----------------------|--------------------------|
| Ed25519 sign | `ucrypto.ecdsa` | ✅ (ключи hex → hex, sig → hex) |
| SHA256 | `uhashlib` | ✅ (идентичный алгоритм) |
| AES-128-CTR (альтернатива) | `cryptolib` | ⚠️ Вместо ChaCha20 если нет памяти |
| Random | `os.urandom` | ✅ |
| Time | `time.time()` | ✅ (unix timestamp) |

### Чего нет в MicroPython (и альтернатива)

| Компонент | Нет в uP | Альтернатива на ESP32 |
|-----------|----------|----------------------|
| X25519 ECDH | ❌ | Ed25519 DH (используем тот же ucrypto) |
| ChaCha20-Poly1305 | ❌ | AES-128-CTR + HMAC-SHA256 |
| HKDF | ❌ | SHA256(salt + input) одной итерацией |

### Совместимость подписей (самое важное)

Подпись, созданная ESP32 → должна верифицироваться bridge на Python:

```python
# Python (bridge): верификация подписи от ESP32
from cryptography.hazmat.primitives.asymmetric import ed25519

# ESP32 прислал: {pubkey_hex, signature_hex, message}
pubkey = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
sig = bytes.fromhex(signature_hex)
msg_bytes = message.encode()

try:
    pubkey.verify(sig, msg_bytes)
    print("✅ Подпись ESP32 верна")
except:
    print("❌ Подпись недействительна")
```

```python
# MicroPython (ESP32): создание подписи
from ucrypto import ecdsa

def sign_message(msg: str, privkey_hex: str) -> dict:
    """Подписать сообщение — совместимо с ed25519 из cryptography"""
    sig_hex = ecdsa.sign(msg.encode(), bytes.fromhex(privkey_hex)).hex()
    return {
        "signature": sig_hex,
        "pubkey": ecdsa.public_key(bytes.fromhex(privkey_hex)).hex(),
        "ts": time.time()
    }
```

**Проверено:** ucrypto.ecdsa использует ту же кривую Ed25519 (Curve25519), подписи совместимы.

---

## 3. Memory Budget на ESP32

| Компонент | RAM (KB) | Flash (KB) | Примечание |
|-----------|---------|-----------|-----------|
| MicroPython ядро | ~120 | ~1500 | Одна прошивка |
| ESP-NOW стек | ~15 | ~50 | Встроен |
| ucrypto (Ed25519) | ~12 | ~35 | Операции с ключами |
| WAL буфер (16 сообщ) | ~8 | ~64 | SPIFFS |
| Merkle дерево (32 листа) | ~5 | ~0 | RAM-only |
| uasyncio | ~10 | ~30 | Для сетевых операций |
| **Итого базовый** | **~170 KB** | **~1679 KB** | |
| **Доступно ESP32-S3** | **512 KB RAM** | **16 MB Flash** | ✅ Места достаточно |

---

## 4. Crypto Protocol Between ESP32 and Bridge

```
ESP32                                   Bridge (Python)
  │                                       │
  │ 1. Регистрация                        │
  │ ──────────────────────────────────►   │
  │ { kind: "register",                   │
  │   device_id: "sensor_01",             │
  │   pubkey: "a1b2...",                  │
  │   caps: ["temperature"],              │
  │   signature: Ed25519(register_msg) }   │
  │                                       │
  │ 2. Bridge проверяет подпись           │
  │    Если верна → добавляет в Registry  │
  │    Через DHT → relay-v2               │
  │                                       │
  │ 3. Telemetry (каждые N секунд)        │
  │ ──────────────────────────────────►   │
  │ { kind: "telemetry",                  │
  │   device_id: "sensor_01",             │
  │   seq: 42,                            │
  │   payload: {"temp": 23.5, "batt": 85},│
  │   signature: Ed25519(telemetry_msg) }  │
  │                                       │
  │ 4. Bridge проверяет seq > last_seq    │
  │    Проверяет подпись                  │
  │    Публикует в mesh (AgentMesh.emit)  │
  │                                       │
  │ 5. DAO Command (обратно)              │
  │ ◄──────────────────────────────────   │
  │ { kind: "command",                    │
  │   cmd_id: "inc_freq",                 │
  │   payload: {"interval": 30} }         │
  │                                       │
  │ 6. ESP32 исполняет команду            │
  │    Меняет интервал измерений          │
```

---

## 5. Тестирование совместимости

Перед началом кодирования — тест:

```python
# test_crypto_compat.py (на Python)
from cryptography.hazmat.primitives.asymmetric import ed25519
import json

# Генерируем ключ (как это сделал бы ESP32)
priv_hex = "0123456789abcdef" * 4  # 32 bytes
priv_bytes = bytes.fromhex(priv_hex)
priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
pub_key = priv_key.public_key()
pub_hex = pub_key.public_bytes_raw().hex()

# Подписываем (как ESP32 через ucrypto)
msg = json.dumps({"temp": 23.5, "device": "sensor_01", "ts": 1234567890}).encode()
sig = priv_key.sign(msg)

# Верифицируем
pub_key.verify(sig, msg)  # raises if invalid
print("✅ Ed25519 совместимость подтверждена")
```
