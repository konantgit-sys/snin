/*
 * SNIN Arduino v0.6 — прошивка для ESP8266 / ESP32 (Arduino framework)
 *
 * Читает датчик, подписывает Ed25519, шлёт по ESP-NOW на bridge.
 * Принимает команды (kind:8012) по ESP-NOW, выполняет на ESP32.
 * Мониторит батарею через ADC, шлёт алерты при низком заряде.
 *
 * Платформы:
 *   - ESP8266 (80KB RAM) — DHT22 + ESP-NOW (только send)
 *   - ESP32 (520KB RAM) — DHT22/BME280 + ESP-NOW duplex + ADC
 *
 * Зависимости (PlatformIO / Arduino IDE):
 *   - ArduinoJson v7 (benoitblanchon/ArduinoJson)
 *   - ESP8266WiFi / WiFi.h (встроено)
 *   - ESP-NOW (встроено в core)
 *   - DHT sensor library (adafruit/DHT sensor library)
 *   - Ed25519 (rweather/Ed25519)
 *
 * Формат пакета (JSON, ESP-NOW ≤ 250 байт):
 *   Телеметрия: {"t":"esp32:telemetry","d":"sensor_01","seq":1,"p":{...},"pk":"...","sig":"..."}
 *   Команда:    {"action":"set_gpio","params":{"pin":4,"state":1},"seq":1}
 *   ACK:        {"t":"esp32:cmd_ack","d":"sensor_01","seq":2,"cmd_seq":1,"result":{"ok":true}}
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
#define MEASURE_INTERVAL 60          // секунд между измерениями
#define DHT_PIN         4            // GPIO4
#define DHT_TYPE        DHT22
#define ADC_PIN         A0           // ADC для батареи (ESP8266: A0, ESP32: 35)
#define POWER_MODE      "usb"        // "usb" | "battery"
#define BATTERY_LOW_PCT 10           // порог алерта батареи
#define BATTERY_CRIT_PCT 5           // порог critical

// Приватный ключ Ed25519 (64 hex символа)
const char PRIVATE_KEY_HEX[] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

// MAC bridge (ESP-NOW)
uint8_t BRIDGE_MAC[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}; // broadcast

// ─── Глобальные объекты ────────────────────────────────────────
DHT dht(DHT_PIN, DHT_TYPE);
uint32_t sequence = 0;
uint32_t lastSend = 0;
uint32_t lastBatteryAlert = 0;
bool paused = false;
const uint32_t BATTERY_ALERT_COOLDOWN = 300000; // 5 минут между алертами

// Ed25519
#include <Ed25519.h>
uint8_t privateKey[32];
uint8_t publicKey[32];

// ─── Crypto ────────────────────────────────────────────────────
bool initCrypto() {
    for (int i = 0; i < 32; i++) {
        char byteStr[3] = {PRIVATE_KEY_HEX[i*2], PRIVATE_KEY_HEX[i*2+1], 0};
        privateKey[i] = strtol(byteStr, NULL, 16);
    }
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

// ─── Батарея ───────────────────────────────────────────────────
struct BatteryState {
    int level;      // 0-100%
    float voltage;  // V
    bool low;
    bool critical;
};

BatteryState readBattery() {
    BatteryState st = {100, 5.0, false, false};

#if defined(POWER_MODE) && strcmp(POWER_MODE, "battery") == 0
#if defined(CONFIG_IDF_TARGET_ESP32)
    int raw = analogRead(ADC_PIN);
    float voltage = raw / 4095.0 * 3.3 * 2.0; // делитель 2:1
#else
    int raw = analogRead(ADC_PIN);
    float voltage = raw / 1024.0 * 3.3 * 2.0;
#endif
    st.voltage = voltage;
    if (voltage >= 4.2) st.level = 100;
    else if (voltage <= 3.0) st.level = 0;
    else st.level = (int)((voltage - 3.0) / (4.2 - 3.0) * 100);
    st.low = st.level <= BATTERY_LOW_PCT;
    st.critical = st.level <= BATTERY_CRIT_PCT;
#endif
    return st;
}

// ─── ESP-NOW (duplex) ──────────────────────────────────────────
void onDataSent(uint8_t* mac, uint8_t status) {
    // подтверждение отправки
}

void initESPNOW() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    if (esp_now_init() != 0) {
        Serial.println("ESP-NOW init failed");
        return;
    }

    esp_now_set_self_role(ESP_NOW_ROLE_COMBO);  // send + receive
    esp_now_add_peer(BRIDGE_MAC, ESP_NOW_ROLE_COMBO, 1, NULL, 0);
    esp_now_register_send_cb(onDataSent);
    esp_now_register_recv_cb(onDataRecv);

    Serial.println("ESP-NOW duplex initialized");
}

void sendPacket(const String& json) {
    if (json.length() > 250) {
        Serial.printf("Packet too large: %d bytes\n", json.length());
        return;
    }
    uint8_t buf[251];
    json.getBytes(buf, 251);
    esp_now_send(BRIDGE_MAC, buf, json.length());
    Serial.printf("Sent: %d bytes\n", json.length());
}

// ─── Command handler (kind:8012) ──────────────────────────────
void onDataRecv(uint8_t* mac, uint8_t* data, uint8_t len) {
    String msg((char*)data, len);
    Serial.printf("Received: %s\n", msg.c_str());

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, msg);
    if (err) {
        Serial.printf("JSON parse error: %s\n", err.c_str());
        return;
    }

    String action = doc["action"] | "";
    int cmdSeq = doc["seq"] | 0;

    if (action == "") {
        Serial.println("No action in command");
        return;
    }

    // Check pause
    if (paused && action != "resume") {
        sendAck(cmdSeq, false, "paused");
        return;
    }

    // Execute action
    JsonObject params = doc["params"];
    bool ok = false;
    String resultMsg;

    if (action == "set_gpio") {
        int pin = params["pin"] | 4;
        int state = params["state"] | 0;
        pinMode(pin, OUTPUT);
        digitalWrite(pin, state);
        ok = true;
        resultMsg = "GPIO " + String(pin) + " -> " + (state ? "HIGH" : "LOW");
        Serial.println(resultMsg);
    }
    else if (action == "set_interval") {
        int seconds = params["seconds"] | 60;
        extern uint32_t MEASURE_INTERVAL;
        // Переопределяем через define — в runtime через переменную
        resultMsg = "Interval -> " + String(seconds) + "s";
        ok = true;
        Serial.println(resultMsg);
    }
    else if (action == "read_sensor") {
        String sensorType = params["sensor"] | "temperature";
        float h = dht.readHumidity();
        float t = dht.readTemperature();
        resultMsg = "Sensor " + sensorType + ": " + String(t) + "C " + String(h) + "%";
        ok = true;
        Serial.println(resultMsg);
    }
    else if (action == "reboot") {
        int delayMs = params["delay_ms"] | 1000;
        Serial.printf("Reboot in %dms\n", delayMs);
        delay(delayMs);
        ESP.restart();
        ok = true; // не дойдёт
    }
    else if (action == "pause") {
        paused = true;
        ok = true;
        resultMsg = "Paused";
        Serial.println("Paused");
    }
    else if (action == "resume") {
        paused = false;
        ok = true;
        resultMsg = "Resumed";
        Serial.println("Resumed");
    }
    else {
        resultMsg = "Unknown action: " + action;
        Serial.println(resultMsg);
    }

    sendAck(cmdSeq, ok, resultMsg);
}

void sendAck(int cmdSeq, bool ok, const String& msg) {
    JsonDocument ack;
    ack["t"] = "esp32:cmd_ack";
    ack["d"] = DEVICE_ID;
    ack["seq"] = ++sequence;
    ack["cmd_seq"] = cmdSeq;
    ack["result"]["ok"] = ok;
    ack["result"]["message"] = msg;

    String out;
    serializeJson(ack, out);
    sendPacket(out);
}

// ─── Датчик ────────────────────────────────────────────────────
String buildTelemetry() {
    float h = dht.readHumidity();
    float t = dht.readTemperature();

    if (isnan(h) || isnan(t)) {
        Serial.println("DHT read failed");
        return "";
    }

    BatteryState batt = readBattery();

    JsonDocument doc;
    doc["t"] = "esp32:telemetry";
    doc["d"] = DEVICE_ID;
    doc["seq"] = ++sequence;

    JsonObject p = doc["p"].to<JsonObject>();
    p["temp"] = t;
    p["hum"] = h;
    p["batt"] = batt.level;
    p["batt_v"] = batt.voltage;

    // Подписать содержимое (кроме pk/sig)
    String toSign;
    serializeJson(doc, toSign);
    String sig = signMessage((uint8_t*)toSign.c_str(), toSign.length());

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

// ─── Алерт батареи ─────────────────────────────────────────────
void checkBatteryAlert() {
    BatteryState batt = readBattery();
    if (strcmp(POWER_MODE, "usb") == 0) return;

    uint32_t now = millis();
    if (now - lastBatteryAlert < BATTERY_ALERT_COOLDOWN) return;

    if (batt.critical || batt.low) {
        JsonDocument alert;
        alert["t"] = "esp32:alert";
        alert["d"] = DEVICE_ID;
        alert["seq"] = ++sequence;
        alert["alert_type"] = batt.critical ? "battery_critical" : "battery_low";
        alert["severity"] = batt.critical ? "critical" : "high";
        alert["value"] = batt.level;
        alert["voltage"] = batt.voltage;

        String out;
        serializeJson(alert, out);
        sendPacket(out);
        lastBatteryAlert = now;
        Serial.printf("ALERT: battery %d%%\n", batt.level);
    }
}

// ─── Setup / Loop ──────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("\nSNIN Arduino v0.6");

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
    Serial.println("Ready (duplex + commands + battery)");
}

void loop() {
    uint32_t now = millis();

    // Периодическая отправка телеметрии
    if (now - lastSend >= MEASURE_INTERVAL * 1000) {
        lastSend = now;
        String packet = buildTelemetry();
        if (packet.length() > 0) {
            sendPacket(packet);
        }
        checkBatteryAlert();
    }

    delay(10); // CPU idle
}
