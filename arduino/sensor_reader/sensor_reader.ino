/*
 * Smart Irrigation - Arduino Sensor Reader (Single Zone)
 * ======================================================
 * Reads soil moisture, DHT20 (temp/humidity), and luminosity
 * for ONE zone. Sends JSON over serial to Raspberry Pi.
 *
 * Each Arduino handles one zone. Two Arduinos connect to the
 * Raspberry Pi via separate USB ports.
 *
 * Hardware per Arduino:
 *   - DHT20 sensor (I2C) for temperature and humidity
 *   - 1x Capacitive soil moisture sensor
 *   - 1x Photoresistor (LDR) for luminosity
 *
 * Output format (JSON):
 *   {"zone_1":{"moisture":45.2,"lux":23500},"temp":22.5,"humidity":60.0}
 *
 * Setup:
 *   1. Set ZONE_ID below to match your config.json ("zone_1" or "zone_2")
 *   2. Calibrate moisture: note airValue (dry) and waterValue (in water)
 *   3. Upload to Arduino and connect to Raspberry Pi USB port
 */

#include <Wire.h>
#include "DHT20.h"

// =============================================================================
// ZONE CONFIGURATION - Edit for each Arduino
// =============================================================================

// IMPORTANT: Change this to match the zone this Arduino is responsible for.
// Arduino 1 → "zone_1", Arduino 2 → "zone_2"
const char* ZONE_ID = "zone_1";

// Soil moisture sensor
const int MOISTURE_PIN = A0;
const int AIR_VALUE = 620;    // Calibration: raw reading in dry air (~600-650)
const int WATER_VALUE = 310;  // Calibration: raw reading in water (~300-350)

// Luminosity sensor (photoresistor / LDR)
const int LDR_PIN = A1;
const int LDR_RESISTOR_OHMS = 10000;  // Value of the voltage divider resistor

// =============================================================================
// TIMING
// =============================================================================

const unsigned long READ_INTERVAL = 2000;  // ms between readings

// =============================================================================
// GLOBALS
// =============================================================================

DHT20 dht20;
unsigned long lastReadTime = 0;

// =============================================================================
// SETUP
// =============================================================================

void setup() {
  Serial.begin(9600);
  Wire.begin();
  dht20.begin();

  // Wait for sensors to stabilize
  delay(1000);

  // Startup message
  Serial.print("Smart Irrigation Sensor Ready - Zone: ");
  Serial.println(ZONE_ID);
}

// =============================================================================
// MAIN LOOP
// =============================================================================

void loop() {
  unsigned long currentTime = millis();

  if (currentTime - lastReadTime >= READ_INTERVAL) {
    lastReadTime = currentTime;
    sendSensorData();
  }
}

// =============================================================================
// SENSOR FUNCTIONS
// =============================================================================

float readMoisture() {
  int raw = analogRead(MOISTURE_PIN);
  float percent = (raw / 1023.0) * 100.0;

  // Clamp to 0-100

  return percent;
}

float readLuminosity() {
  /*
   * Reads the photoresistor (LDR) through a voltage divider and converts
   * the analog reading to an approximate lux value.
   *
   * Circuit:
   *   5V ──┤LDR├──┬──┤10kΩ├── GND
   *                │
   *               A1 (analog read)
   *
   * The LDR resistance decreases with more light.
   * This approximation assumes a typical GL5528 LDR.
   */
  int raw = analogRead(LDR_PIN);

  // Avoid division by zero
  if (raw == 0) raw = 1;

  // Calculate LDR resistance from voltage divider
  // V_out = V_in * R_fixed / (R_ldr + R_fixed)
  // R_ldr = R_fixed * (1023 - raw) / raw
  float ldrResistance = (float)LDR_RESISTOR_OHMS * (1023.0 - raw) / raw;

  // Approximate lux from resistance (empirical formula for GL5528)
  // lux ≈ 500000 / R_ldr^1.2 (rough approximation)
  float lux = 0;
  if (ldrResistance > 0) {
    lux = 500000.0 / pow(ldrResistance, 1.2);
  }

  // Clamp to reasonable range
  if (lux < 0) lux = 0;
  if (lux > 100000) lux = 100000;

  return lux;
}

// =============================================================================
// OUTPUT
// =============================================================================

void sendSensorData() {
  // Read DHT20
  int status = dht20.read();
  float temperature = 20.0;  // Default fallback
  float humidity = 50.0;     // Default fallback

  if (status == DHT20_OK) {
    temperature = dht20.getTemperature();
    humidity = dht20.getHumidity();
  }

  // Read sensors
  float moisture = readMoisture();
  float lux = readLuminosity();

  // Build JSON output
  // Format: {"zone_1":{"moisture":45.2,"lux":23500.0},"temp":22.5,"humidity":60.0}
  Serial.print("{\"");
  Serial.print(ZONE_ID);
  Serial.print("\":{\"moisture\":");
  Serial.print(moisture, 1);
  Serial.print(",\"lux\":");
  Serial.print(lux, 1);
  Serial.print("},\"temp\":");
  Serial.print(temperature, 1);
  Serial.print(",\"humidity\":");
  Serial.print(humidity, 1);
  Serial.println("}");
}
