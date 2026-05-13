```
NIP-XX
------

SNIN Device Events

`draft` `optional`

This NIP defines event kinds for SNIN IoT devices on Nostr.

## Kinds

| Kind | Name | Description |
|------|------|-------------|
| 31000 | Device Telemetry | Sensor readings (temp, hum, battery) |
| 31001 | Device Registration | Device identity and capabilities |
| 31002 | Device Command | DAO-to-device command |
| 31003 | Device OTA Update | Firmware update payload |
| 31004 | Device Log | Diagnostic log entry |
| 31005 | Device Config | Remote configuration |
| 31006 | Device Location | GPS coordinates |

## Event format (kind:31000)

```json
{
  "kind": 31000,
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
DAO agents subscribe to kind:31000 and may respond with kind:31002.
