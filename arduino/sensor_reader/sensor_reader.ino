/*
 * Smart Irrigation - Arduino Sensor Reader (Dynamic Zones)
 * ========================================================
 * Reads sensors for multiple irrigation zones from a single Arduino.
 * Sends data as JSON over serial to Raspberry Pi.
 *
 * CONFIGURATION:
 *   Edit the ZONE CONFIGURATION section below to add/remove zones.
 *   When adding a multiplexer later, only modify the readMoisture() function.
 *
 * Hardware:
 *   - DHT20 sensor (I2C) for temperature and humidity (shared)
 *   - Capacitive soil moisture sensors (one per zone)
 *   - Optional: Ultrasonic sensor (HC-SR04) for tank level
 */

#include "DHT20.h"

// =============================================================================
// ZONE CONFIGURATION - Edit this section to add/remove zones
// =============================================================================

struct ZoneConfig {
  const char* id;      // Zone identifier (e.g., "zone_1")
  int pin;             // Analog pin for moisture sensor
  int airValue;        // Calibration: sensor reading in dry air
  int waterValue;      // Calibration: sensor reading in water
};

// Define your zones here - add or remove as needed
const ZoneConfig ZONES[] = {
  {"zone_1", A0, 620, 310},
  {"zone_2", A1, 620, 310},
  // Add more zones here:
  // {"zone_3", A2, 620, 310},
  // {"zone_4", A3, 620, 310},
};

const int NUM_ZONES = sizeof(ZONES) / sizeof(ZONES[0]);

// =============================================================================
// TIMING CONFIGURATION
// =============================================================================

const unsigned long READ_INTERVAL = 2000;  // ms between readings

// =============================================================================
// GLOBALS - Don't modify
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
// SENSOR READING FUNCTIONS
// =============================================================================

/*
 * Read moisture for a specific zone.
 *
 * MULTIPLEXER NOTE: When adding a multiplexer, modify this function
 * to select the appropriate channel before reading. The rest of the
 * code will work unchanged.
 */
float readMoisture(int zoneIndex) {
  const ZoneConfig& zone = ZONES[zoneIndex];

  // Direct analog read - replace this section for multiplexer
  int raw = analogRead(zone.pin);

  // Convert to percentage
  return rawToPercent(raw, zone.airValue, zone.waterValue);
}

float rawToPercent(int raw, int airValue, int waterValue) {
  float percent = (float)(airValue - raw) / (airValue - waterValue) * 100.0;

  // Clamp to valid range
  if (percent < 0) percent = 0;
  if (percent > 100) percent = 100;

  return percent;
}

// =============================================================================
// DATA OUTPUT
// =============================================================================

void sendSensorData() {
  // Read shared sensors
  dht20.read();
  float temperature = dht20.getTemperature();
  float humidity = dht20.getHumidity();

  // Start JSON object
  Serial.print("{");

  // Loop through all zones
  for (int i = 0; i < NUM_ZONES; i++) {
    float moisture = readMoisture(i);

    Serial.print("\"");
    Serial.print(ZONES[i].id);
    Serial.print("\":{\"moisture\":");
    Serial.print(moisture, 1);
    Serial.print("}");

    // Add comma if not last zone
    if (i < NUM_ZONES - 1) {
      Serial.print(",");
    }
  }

  // Add shared temperature and humidity
  Serial.print(",\"temp\":");
  Serial.print(temperature, 1);
  Serial.print(",\"humidity\":");
  Serial.print(humidity, 1);

  // End JSON object
  Serial.println("}");
}
