```
NIP-XX
------

SNIN Device Events

`draft` `optional`

This NIP defines event kinds for SNIN IoT devices on Nostr.

## Kinds

| Kind | Name | Description |
|------|------|-------------|
| 8010 | Device Telemetry | Sensor readings (temp, hum, battery) |
| 8014 | Device Registration | Device identity and capabilities |
| 8012 | Device Command | DAO-to-device command |
| 8013 | Device OTA Update | Firmware update payload |
| 31004 | Device Log | Diagnostic log entry |
| 31005 | Device Config | Remote configuration |
| 8015 | Device Location | GPS coordinates |

## Event format (kind:8010)

```json
{
  "kind": 8010,
  "pubkey": "hex_pubkey",
  "tags": [
    ["d", "sensor_kitchen_01"],
    ["t", "temperature"],
    ["seq", "42"],
    ["batt", "85"]
  ],
  "content": "{\"temp\": 23.5, \"hum\": 60.2}"
}
```

## Transport

ESP32 sends 250-byte ESP-NOW packets to a bridge node.
Bridge verifies Ed25519 signature and publishes to relay-v2.
DAO agents subscribe to kind:8010 and may respond with kind:8012.
