/*
 * SNIN Arduino — прошивка для ESP8266 / ESP32 (Arduino framework)
 *
 * Читает датчик, подписывает Ed25519, шлёт по ESP-NOW.
 * Совместимо с bridge.py на серверной стороне.
 *
 * Платформы:
 *   - ESP8266 (80KB RAM, 4MB flash) — DHT22 + ESP-NOW
 *   - ESP32 (520KB RAM) — DHT22/BME280 + ESP-NOW + дисплей (опционально)
 *
 * Зависимости (Arduino IDE / PlatformIO):
 *   - ArduinoJson v7 (benoitblanchon/ArduinoJson)
 *   - ESP8266WiFi / WiFi.h (встроено)
 *   - ESP-NOW (встроено в ESP8266/ESP32 core)
 *   - DHT sensor library (adafruit/DHT sensor library)
 *   - Ed25519 (rweather/Ed25519 или micro-ecc)
 *
 * Прошивка:
 *   1. Установить PlatformIO или Arduino IDE
 *   2. Скопировать platformio.ini / настроить board
 *   3. Задать CONFIG в начале файла
 *   4. Скомпилировать и залить
 *
 * Формат пакета (JSON, ESP-NOW ≤ 250 байт):
 *   {"t":"esp32:telemetry","d":"sensor_01","seq":1,"p":{"temp":23.5},"pk":"...","sig":"..."}
 *
 * Совместимость подписей:
 *   Arduino (Ed25519 lib) → Python (cryptography) — одинаковые кривые
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266WiFi.h>   // ESP32: заменить на <WiFi.h>
#include <espnow.h>         // ESP32: заменить на <esp_now.h>
#include <DHT.h>            // Adafruit DHT sensor library

// ─── Конфигурация ──────────────────────────────────────────────
#define DEVICE_ID       "arduino_sensor_01"
#define SENSOR_TYPE     "temperature"
#define WIFI_SSID       "SNIN_MESH"
#define WIFI_PASS       ""
#define MEASURE_INTERVAL 60          // секунд
#define DHT_PIN         4            // GPIO4
#define DHT_TYPE        DHT22

// Приватный ключ Ed25519 (32 байта, hex)
// Сгенерировать однократно, сохранить
const char PRIVATE_KEY_HEX[] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

// MAC bridge (ESP-NOW)
uint8_t BRIDGE_MAC[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}; // broadcast

// ─── Глобальные объекты ────────────────────────────────────────
DHT dht(DHT_PIN, DHT_TYPE);
uint32_t sequence = 0;
uint32_t lastSend = 0;

// ─── Ed25519 (через rweather/Ed25519) ──────────────────────────
// Для ESP8266 — библиотека rweather/Ed25519
// Для ESP32 — micro-ecc или port of crypto_sign
#include <Ed25519.h>  // rweather/Ed25519 — sign/verify/keygen

uint8_t privateKey[32];
uint8_t publicKey[32];

bool initCrypto() {
    // Из hex-строки в байты
    for (int i = 0; i < 32; i++) {
        char byteStr[3] = {PRIVATE_KEY_HEX[i*2], PRIVATE_KEY_HEX[i*2+1], 0};
        privateKey[i] = strtol(byteStr, NULL, 16);
    }
    // Вычислить публичный ключ из приватного
    Ed25519::derivePublicKey(publicKey, privateKey);
    return true;
}

String signMessage(const uint8_t* msg, size_t len) {
    uint8_t signature[64];
    Ed25519::sign(signature, privateKey, publicKey, msg, len);
    
    char hex[129];
    for (int i = 0; i < 64; i++) {
        sprintf(hex + i*2, "%02x", signature[i]);
    }
    hex[128] = 0;
    return String(hex);
}

// ─── ESP-NOW ───────────────────────────────────────────────────
void initESPNOW() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    // ESP-NOW работает даже без подключения к роутеру
    // WiFi.disconnect() — если не нужно подключаться

    if (esp_now_init() != 0) {
        Serial.println("ESP-NOW init failed");
        return;
    }
    
    esp_now_set_self_role(ESP_NOW_ROLE_CONTROLLER);
    esp_now_add_peer(BRIDGE_MAC, ESP_NOW_ROLE_SLAVE, 1, NULL, 0);
    Serial.println("ESP-NOW initialized");
}

void sendPacket(const String& json) {
    if (json.length() > 250) {
        Serial.printf("Packet too large: %d bytes\n", json.length());
        return;
    }
    
    uint8_t buf[251];
    json.getBytes(buf, 251);
    esp_now_send(BRIDGE_MAC, buf, json.length());
    Serial.printf("Sent: %d bytes | %s\n", json.length(), json.c_str());
}

// ─── Датчик ────────────────────────────────────────────────────
String readSensor() {
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    
    if (isnan(h) || isnan(t)) {
        Serial.println("DHT read failed");
        return "";
    }
    
    // JSON: {"t":"esp32:telemetry","d":"arduino_01","seq":1,"p":{"temp":23.5,"hum":60.2}}
    JsonDocument doc;
    doc["t"] = "esp32:telemetry";
    doc["d"] = DEVICE_ID;
    doc["seq"] = ++sequence;
    
    JsonObject payload = doc["p"].to<JsonObject>();
    payload["temp"] = t;
    payload["hum"] = h;
    
    // Подписать
    String toSign;
    serializeJson(doc, toSign);
    String sig = signMessage((uint8_t*)toSign.c_str(), toSign.length());
    
    // Публичный ключ
    char pkHex[65];
    for (int i = 0; i < 32; i++) {
        sprintf(pkHex + i*2, "%02x", publicKey[i]);
    }
    pkHex[64] = 0;
    
    doc["pk"] = pkHex;
    doc["sig"] = sig;
    
    String result;
    serializeJson(doc, result);
    return result;
}

// ─── Setup / Loop ──────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("\nSNIN Arduino Sensor v0.1");
    
    dht.begin();
    
    if (!initCrypto()) {
        Serial.println("Crypto init failed!");
        return;
    }
    
    char pkHex[65];
    for (int i = 0; i < 32; i++) {
        sprintf(pkHex + i*2, "%02x", publicKey[i]);
    }
    Serial.printf("Pubkey: %s\n", pkHex);
    
    initESPNOW();
    Serial.println("Ready");
}

void loop() {
    uint32_t now = millis();
    
    if (now - lastSend >= MEASURE_INTERVAL * 1000) {
        lastSend = now;
        
        String packet = readSensor();
        if (packet.length() > 0) {
            sendPacket(packet);
        }
    }
    
    // Энергосбережение: ESP.deepSleep(MEASURE_INTERVAL * 1000000);
    delay(100);
}
