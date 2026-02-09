# Hardware Wiring Guide — Smart Irrigation System

This guide covers how to physically wire all circuit components for the smart irrigation system. The system uses **two Arduinos** (one per zone), each with its own soil moisture sensor, DHT20, and luminosity sensor, connected to a single Raspberry Pi that controls valves via an HW-482 relay module.

---

## 1. Components List

### Microcontrollers
| Component | Quantity | Notes |
|---|---|---|
| Arduino Uno/Nano | **2** | One per zone — each reads its own sensors |
| Raspberry Pi 3B+ or newer | 1 | Decision controller — runs Python, controls valves |

### Sensors (Per Arduino)
| Component | Qty per Arduino | Notes |
|---|---|---|
| Capacitive soil moisture sensor (v1.2 or v2.0) | 1 | **Must be capacitive**, not resistive |
| DHT20 temperature/humidity sensor | 1 | I²C interface (SDA/SCL) |
| Photoresistor (LDR) — GL5528 or similar | 1 | For luminosity readings (data sent to server, not used in irrigation decisions) |
| 10kΩ resistor | 1 | Voltage divider for the LDR |

### Valve & Relay Hardware
| Component | Quantity | Notes |
|---|---|---|
| 12V solenoid valve (normally closed) | 2 | One per zone |
| **HW-482 v2.0.1** 2-channel relay module | 1 | Active-LOW, optocoupled, 5V coil |
| 1N4007 flyback diode | 2 | One per valve — protects against solenoid back-EMF |
| 12V DC power supply | 1 | Powers both solenoid valves |

### Tank Level (Optional — Camera-Based)
| Component | Quantity | Notes |
|---|---|---|
| Raspberry Pi Camera Module | 1 | For red-floater water level detection |
| Red floater ball | 1 | Detected via OpenCV in `tank_sensor.py` |

### Wiring Supplies
| Component | Notes |
|---|---|
| USB-A to USB-B cable × 2 (or Mini-USB for Nano) | Arduino 1 & 2 → Raspberry Pi |
| Jumper wires (male-to-male, male-to-female) | General connections |
| Breadboard × 2 | One per Arduino for prototyping |
| 10kΩ pull-up resistors × 2 per Arduino | Only if DHT20 breakout lacks built-in I²C pull-ups |

---

## 2. Arduino Wiring (Per Arduino)

Each Arduino handles **one zone** and reads three sensors: soil moisture, DHT20, and an LDR luminosity sensor. The only difference between the two Arduinos is the `ZONE_ID` constant in the firmware (`"zone_1"` vs `"zone_2"`).

### 2.1 Capacitive Soil Moisture Sensor

| Sensor Pin | Arduino Pin | Notes |
|---|---|---|
| AOUT | **A0** | Analog signal |
| VCC | **5V** | Power |
| GND | **GND** | Ground |

**No extra resistors needed** — capacitive sensors output a 0–3V analog signal read directly by the Arduino.

### 2.2 DHT20 Temperature & Humidity Sensor (I²C)

| DHT20 Pin | Arduino Pin | Notes |
|---|---|---|
| VCC | **5V** | Can also run on 3.3V |
| GND | **GND** | |
| SDA | **A4** | I²C data (hardware SDA on Uno) |
| SCL | **A5** | I²C clock (hardware SCL on Uno) |

> **Pull-up resistors:** Most DHT20 breakout boards include 10kΩ pull-ups on SDA and SCL. If yours does not, add **10kΩ resistors from SDA → 5V** and **SCL → 5V**.

### 2.3 Photoresistor (LDR) — Luminosity Sensor

The LDR is connected via a voltage divider circuit. The Arduino reads the voltage at the midpoint to estimate light intensity in lux.

**Circuit:**

```
5V ───┤ LDR ├───┬───┤ 10kΩ ├─── GND
                │
               A1  (analog read)
```

| Connection | Arduino Pin |
|---|---|
| LDR one leg | **5V** |
| LDR other leg + 10kΩ resistor | **A1** (junction point) |
| 10kΩ other leg | **GND** |

> The LDR resistance decreases with more light. The 10kΩ resistor forms a voltage divider — in bright light, A1 reads a higher voltage; in darkness, it reads lower. The firmware converts this to approximate lux.

> **Note:** Luminosity data is sent to the dashboard server for monitoring but is **not used** in the irrigation decision logic.

### 2.4 Single Arduino Wiring Diagram

Both Arduinos are wired identically. Only the `ZONE_ID` in the firmware differs.

```
Arduino (Zone 1 or Zone 2)
┌──────────────────────────────────┐
│                                  │
│  A0 ◄── Soil Moisture Sensor (AOUT)
│                                  │
│  A1 ◄── LDR + 10kΩ voltage divider
│                                  │
│  A4 (SDA) ◄──► DHT20 SDA
│  A5 (SCL) ◄──► DHT20 SCL
│                                  │
│  5V  ────► Sensor VCC + LDR top
│  GND ────► Sensor GND + 10kΩ bottom
│                                  │
│  USB ════► Raspberry Pi USB port
│                                  │
└──────────────────────────────────┘
```

### 2.5 Firmware Configuration

Upload `sensor_reader.ino` to **each** Arduino, changing only the `ZONE_ID`:

**Arduino 1:**
```cpp
const char* ZONE_ID = "zone_1";
```

**Arduino 2:**
```cpp
const char* ZONE_ID = "zone_2";
```

Also calibrate the moisture sensor values (`AIR_VALUE` and `WATER_VALUE`) individually for each sensor, as they may differ slightly.

Each Arduino outputs JSON like:
```json
{"zone_1":{"moisture":45.2,"lux":23500.0},"temp":22.5,"humidity":60.0}
```

---

## 3. Raspberry Pi Wiring

The Pi connects to both Arduinos via USB and controls both valves via the HW-482 relay.

### 3.1 Serial Connections to Arduinos

Connect each Arduino to a separate USB port on the Raspberry Pi. They appear as separate serial devices:

| Arduino | USB Port | Serial Device | Zone |
|---|---|---|---|
| Arduino 1 | USB port 1 | `/dev/ttyACM0` | zone_1 |
| Arduino 2 | USB port 2 | `/dev/ttyACM1` | zone_2 |

> **Port assignment tip:** USB device numbering can change on reboot. To get stable names, you can create udev rules based on each Arduino's serial number:
> ```bash
> # Find serial numbers
> udevadm info -a /dev/ttyACM0 | grep serial
> udevadm info -a /dev/ttyACM1 | grep serial
>
> # Create rule in /etc/udev/rules.d/99-arduino.rules
> SUBSYSTEM=="tty", ATTRS{serial}=="ARDUINO1_SERIAL", SYMLINK+="arduino_zone1"
> SUBSYSTEM=="tty", ATTRS{serial}=="ARDUINO2_SERIAL", SYMLINK+="arduino_zone2"
> ```
> Then use `/dev/arduino_zone1` and `/dev/arduino_zone2` in your config.

**Baud rate:** 9600 for both (must match Arduino sketch).

### 3.2 HW-482 Relay Module Overview

The HW-482 v2.0.1 is a **2-channel, active-LOW** relay module — perfect for our 2-zone setup.

- **Active-LOW**: The relay triggers when the input pin goes **LOW**. The `valve_controller.py` handles this with `active_low=True` (default).
- **2 channels**: One for each zone — matches our 2-Arduino, 2-valve setup exactly.
- **Built-in coil flyback diodes**: Protects relay coils, but you still need **external 1N4007 diodes across the solenoid valves**.

#### HW-482 Pin Layout

```
HW-482 v2.0.1
┌─────────────────────────────────────────┐
│                                         │
│  Input Side (low-voltage)               │
│  ┌─────┬─────┬─────┬──────┐            │
│  │ GND │ IN1 │ IN2 │ VCC  │            │
│  └─────┴─────┴─────┴──────┘            │
│                                         │
│  [JD-VCC jumper]                        │
│                                         │
│  Output Side (high-voltage)             │
│  ┌──────┬────┬────┐  ┌──────┬────┬────┐│
│  │ COM1 │ NO1│ NC1│  │ COM2 │ NO2│ NC2││
│  └──────┴────┴────┘  └──────┴────┴────┘│
└─────────────────────────────────────────┘
```

### 3.3 JD-VCC Jumper Configuration

**Option A — Jumper ON (default, simpler):**
- VCC and JD-VCC are bridged. Relay coil and optocoupler both run from Pi's 5V.
- No electrical isolation. **Fine for this project.**

**Option B — Jumper OFF (full isolation):**
- Remove jumper. Connect **VCC** to Pi's 3.3V/5V (optocoupler only).
- Connect **JD-VCC** to a separate external 5V supply (relay coils).
- Connect external supply GND to relay board GND.

### 3.4 Pi → HW-482 Connections

| HW-482 Pin | Connect To | Purpose |
|---|---|---|
| VCC | Raspberry Pi **5V** (Pin 2 or 4) | Power |
| GND | Raspberry Pi **GND** (Pin 6, 9, etc.) | Ground |
| IN1 | **GPIO 17** (Pin 11) | Zone 1 valve control |
| IN2 | **GPIO 18** (Pin 12) | Zone 2 valve control |

> GPIO pins can be changed in `config.json` under each zone's `valve_pin` field. The code uses **BCM numbering**.

> **Active-LOW logic:** `open_valve()` sends GPIO LOW (relay ON), `close_valve()` sends GPIO HIGH (relay OFF). On startup, all pins are initialized HIGH (valves closed).

### 3.5 HW-482 → Solenoid Valve Connections

Use the **NO (Normally Open)** terminal so valves stay closed when the system is off (fail-safe).

```
12V Power Supply (+) ──► COM1 and COM2
                         NO1 ──► Solenoid Valve 1 (+)
                         NO2 ──► Solenoid Valve 2 (+)
                         Valve 1 (−) ──► 12V Power Supply (−)
                         Valve 2 (−) ──► 12V Power Supply (−)
```

### 3.6 External Flyback Diodes

The HW-482's built-in diodes protect the **relay coils** only. You must still install a **1N4007 diode across each solenoid valve** to suppress back-EMF:

```
Solenoid Valve
┌─────────┐
│  (+)  (−) │
└──┬────┬──┘
   │    │
   │  ┌─┴─┐
   │  │ ◄ │  1N4007 diode
   │  └─┬─┘  (cathode band toward +)
   │    │
   └────┘
```

### 3.7 Complete Wiring Diagram

```
Raspberry Pi                  HW-482 Relay Module
┌──────────┐                 ┌─────────────────┐
│          │                 │   Input Side     │
│ GPIO 17  ├──── IN1 ───────►│                 │
│ GPIO 18  ├──── IN2 ───────►│                 │
│ 5V       ├──── VCC         │  [JD-VCC on]    │
│ GND      ├──── GND         │                 │
│          │                 │   Output Side    │
│          │                 │                 │      ┌──────────┐
│          │                 │  COM1 ◄── 12V+ ─┼──────┤ 12V PSU  │
│          │                 │  NO1  ──────────┼──►(+) Valve 1   │
│          │                 │                 │   (−)──► 12V GND │
│          │                 │                 │    ↕ 1N4007      │
│          │                 │                 │                  │
│          │                 │  COM2 ◄── 12V+ ─┼──────┤(same PSU)│
│          │                 │  NO2  ──────────┼──►(+) Valve 2   │
│          │                 │                 │   (−)──► 12V GND │
│          │                 └─────────────────┘    ↕ 1N4007      │
│          │                                       └──────────────┘
│          │
│  USB 1 ══╪════► Arduino 1 (zone_1)
│  USB 2 ══╪════► Arduino 2 (zone_2)
│          │
│  CSI  ───┼───► Pi Camera (optional)
└──────────┘
```

Each Arduino (identical wiring):
```
Arduino
┌────────────────────────────┐
│  A0 ◄── Soil Moisture Sensor
│  A1 ◄── LDR + 10kΩ divider
│  A4 ◄──► DHT20 SDA
│  A5 ◄──► DHT20 SCL
│  5V ──► Sensors + LDR
│  GND ──► Sensors + 10kΩ
│  USB ══► Raspberry Pi
└────────────────────────────┘
```

---

## 4. Software Configuration

### 4.1 config.json

```json
{
  "location": {
    "city": "Paris",
    "elevation_m": 35
  },
  "tank": {
    "capacity_liters": 50.0
  },
  "arduinos": {
    "/dev/ttyACM0": "zone_1",
    "/dev/ttyACM1": "zone_2"
  },
  "zones": [
    {
      "zone_id": "zone_1",
      "name": "Tomato Bed",
      "plant_id": 285,
      "area_m2": 2.0,
      "valve_pin": 17,
      "moisture_threshold_low": 35.0,
      "moisture_threshold_target": 65.0
    },
    {
      "zone_id": "zone_2",
      "name": "Herb Garden",
      "plant_id": null,
      "area_m2": 1.0,
      "valve_pin": 18,
      "moisture_threshold_low": 25.0,
      "moisture_threshold_target": 50.0
    }
  ],
  "server": {
    "ip": "192.168.1.50",
    "port": 8000,
    "enabled": true
  }
}
```

The `arduinos` field maps serial port → zone_id. The `MultiArduinoSensorProvider` reads from both ports and merges the data.

### 4.2 Luminosity Data Flow

Luminosity is collected by each Arduino and flows through the system as follows:

1. **Arduino** reads LDR on pin A1, converts to approximate lux, includes it in the JSON output.
2. **`MultiArduinoSensorProvider`** passes `luminosity_lux` through in each zone's reading dict.
3. **Decision engine** ignores it — irrigation decisions are based only on moisture, weather, and plant data.
4. **Telemetry** attaches luminosity as metadata in the telemetry payload sent to the dashboard server.
5. **Dashboard** can display luminosity trends, correlate with irrigation patterns, etc.

---

## 5. Pi Camera (Tank Level Sensor — Optional)

1. Connect the **Raspberry Pi Camera Module** via the CSI ribbon cable.
2. Enable the camera: `sudo raspi-config` → Interface Options → Camera → Enable.
3. Place a **red floater ball** in the water tank.
4. Calibrate: `python water_level3_VF.py calibrate`.

---

## 6. Power Considerations

### Arduinos
- Both powered via USB from the Raspberry Pi. No separate supplies needed.
- The Pi's USB ports can supply ~500mA each — more than enough for an Arduino + sensors.

### Raspberry Pi
- Use a quality **5V 3A** power supply.
- Total USB current draw: ~150mA × 2 Arduinos + ~70mA × 2 relay channels = ~440mA from the 5V rail. Well within spec.

### Solenoid Valves
- Dedicated **12V DC power supply**. Typical: 300–500mA per valve → a 12V 1.5A supply handles both.
- **Never power solenoids from the Pi or Arduino.**

### Common Ground
All grounds must be connected together: Pi GND, HW-482 GND, and 12V supply GND.

---

## 7. Calibration Checklist

1. **Soil moisture sensors** — Calibrate each sensor individually. Record `AIR_VALUE` (dry air) and `WATER_VALUE` (submerged in water) in each Arduino's firmware. Values may differ between sensors.

2. **DHT20** — No calibration needed. Verify via serial monitor.

3. **LDR luminosity** — No precise calibration needed. The approximate lux conversion in firmware works well enough for trend monitoring. For more accuracy, compare readings against a known lux meter and adjust the formula constants.

4. **Serial ports** — Verify both Arduinos are detected:
   ```bash
   ls /dev/ttyACM*
   ```
   Expected: `/dev/ttyACM0` and `/dev/ttyACM1`. Update `config.json` if different. Consider udev rules for stable naming (see Section 3.1).

5. **Valve test** — Test both relay channels:
   ```bash
   python main_controller.py --test valves
   ```
   Listen for both relay clicks on the HW-482.

6. **Full sensor test** — Read from both Arduinos:
   ```bash
   python main_controller.py --test sensors
   ```

7. **Tank camera** (if used):
   ```bash
   python water_level3_VF.py calibrate
   ```

---

## 8. Safety Notes

- **Never connect 12V to the Arduino or Raspberry Pi GPIO** — permanent damage.
- **Always install flyback diodes on solenoid valves** — the HW-482's built-in diodes only protect relay coils.
- **Active-LOW means HIGH = safe** — GPIO HIGH keeps relays off. The code initializes all pins HIGH on startup.
- **Waterproof outdoor connections** — use enclosures or heat-shrink tubing on all sensor cable joints, especially the soil moisture sensors.
- **Capacitive sensors only** — resistive sensors corrode within weeks in soil.
- **Test without water first** — verify relay clicks and software logic before connecting to actual water lines.
- **Label your Arduinos** — mark which Arduino is zone_1 and which is zone_2 to avoid confusion during maintenance.
