# SNIN Quickstart

## За 30 секунд: симуляция ESP32 в рое

```bash
git clone https://github.com/konantgit-sys/snin.git
cd snin
pip install cryptography aiohttp

# Self-test всей цепочки (без железа)
cd hardware/esp32
python3 test_smoke.py
```

## За 5 минут: реальный ESP32 в рое

### 1. Прошивка сенсора (ESP32 + DHT22)

```bash
# 1. Скопировать config
cp firmware/config_example.py firmware/config.py
# 2. Сгенерировать Ed25519 ключ (один раз)
python3 -c "from sdk.crypto import gen_keypair; print(gen_keypair())"
# 3. Записать ключ в config.py
# 4. Залить на ESP32 через mip
mip install hardware/esp32/firmware/snin_sensor.py
```

### 2. Bridge (RPi или сервер)

```bash
python3 bridge/bridge.py --port 9090
```

### 3. relay-v2

```bash
# В p2p-agent-mesh
python3 relay/relay_server.py --port 2025
```

## Доступные транспорты

| Транспорт | Дальность | Когда использовать |
|-----------|-----------|-------------------|
| ESP-NOW | ~200m | Датчики в доме/дворе |
| LoRa | 2-15km | Датчики в поле/лесу |
| BLE | ~10m | T-Watch, телефон рядом |
| TCP | ∞ | Bridge → relay-v2 |
| mDNS | LAN | ESP32 ищет bridge автоматически |
