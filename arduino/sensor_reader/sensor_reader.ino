/*
 * Smart Irrigation - Arduino Sensor Reader
 * =========================================
 * Reads soil moisture sensors and DHT20 (temp/humidity) for the 
 * smart irrigation system. Sends JSON over serial to Raspberry Pi.
 *
 * Hardware:
 *   - DHT20 sensor (I2C) for temperature and humidity
 *   - Capacitive soil moisture sensors (one per zone)
 *
 * Output format (JSON):
 *   {"zone_1":{"moisture":45.2},"zone_2":{"moisture":52.1},"temp":22.5,"humidity":60.0}
 *
 * Calibration:
 *   1. Note the raw value with sensor in dry air (airValue)
 *   2. Note the raw value with sensor in water (waterValue)
 *   3. Update the ZONES array below with your values
 */

#include <Wire.h>
#include "DHT20.h"

// =============================================================================
// ZONE CONFIGURATION - Edit this section for your setup
// =============================================================================

struct ZoneConfig {
  const char* id;      // Zone identifier (must match Raspberry Pi config)
  int pin;             // Analog pin for moisture sensor
  int airValue;        // Calibration: raw reading in dry air (~600-650)
  int waterValue;      // Calibration: raw reading in water (~300-350)
};

// Define your zones here - add or remove as needed
const ZoneConfig ZONES[] = {
  {"zone_1", A0, 620, 310},
  {"zone_2", A1, 620, 310},
  // {"zone_3", A2, 620, 310},
};

const int NUM_ZONES = sizeof(ZONES) / sizeof(ZONES[0]);

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
  Serial.print("Smart Irrigation Sensor Ready - ");
  Serial.print(NUM_ZONES);
  Serial.println(" zone(s)");
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

float readMoisture(int zoneIndex) {
  const ZoneConfig& zone = ZONES[zoneIndex];
  int raw = analogRead(zone.pin);
  return rawToPercent(raw, zone.airValue, zone.waterValue);
}

float rawToPercent(int raw, int airValue, int waterValue) {
  float percent = (float)(airValue - raw) / (airValue - waterValue) * 100.0;
  
  // Clamp to 0-100
  if (percent < 0) percent = 0;
  if (percent > 100) percent = 100;
  
  return percent;
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

  // Build JSON output
  Serial.print("{");

  // Zone moisture readings
  for (int i = 0; i < NUM_ZONES; i++) {
    Serial.print("\"");
    Serial.print(ZONES[i].id);
    Serial.print("\":{\"moisture\":");
    Serial.print(readMoisture(i), 1);
    Serial.print("}");
    
    if (i < NUM_ZONES - 1) {
      Serial.print(",");
    }
  }

  // Temperature and humidity
  Serial.print(",\"temp\":");
  Serial.print(temperature, 1);
  Serial.print(",\"humidity\":");
  Serial.print(humidity, 1);

  Serial.println("}");
}
