# Device Technical Manual: Communication & Behavior

This manual defines the expected behavior, communication protocols, and configuration requirements for external devices (Raspberry Pi, etc.) interacting with the **Smart Irrigation API**.

---

## 1. Overview & Data Philosophy

The system separates concerns into four planes:
1.  **Control Plane**: Identity and mapping (Server-owned).
2.  **Data Plane**: Raw facts (Telemetry, Images, Logs).
3.  **Analytics Plane**: Processing facts into meaning.
4.  **Read Plane**: Dashboard consumption.

**Rule Zero**: Devices describe reality (facts). The server creates meaning.

---

## 2. Device Identity & Provisioning

A device must be registered before it can send telemetry.

### 2.1 Bootstrapping Flow
1.  **First Boot**: Device has no UUID. It knows its MAC address/Serial and its hardware capabilities (e.g., "I have 2 humidity sensors").
2.  **Provisioning Request**: Device calls `POST /api/v1/devices/provision`.
    ```json
    {
      "hardwareId": "unique-mac-or-serial",
      "firmware": "1.0.0",
      "capabilities": {
        "sensors": [
          { "localName": "soil_1", "type": "humidity" },
          { "localName": "tank_level", "type": "water-level" }
        ],
        "cameras": ["main_view"]
      }
    }
    ```
3.  **Server Response**: The server returns the authoritative configuration.
    ```json
    {
      "deviceId": "uuid-assigned-by-server",
      "sensors": [
        { "localName": "soil_1", "sensorId": "uuid-1" },
        { "localName": "tank_level", "sensorId": "uuid-2" }
      ],
      "polling": {
        "telemetryIntervalSec": 60,
        "heartbeatIntervalSec": 30
      }
    }
    ```

### 2.2 Local Storage Requirements
The device **MUST** persist the following parameters locally (e.g., in NVS or EEPROM):
- `deviceId` (UUID)
- Mapping between `localName` and `sensorId` (UUID)
- `telemetryIntervalSec`
- `heartbeatIntervalSec`

---

## 3. Communication Protocols

### 3.1 Telemetry (Periodic Facts)
Sent via `POST /api/v1/external-devices/{device_id}/telemetry`.

- **Format**: JSON
- **Frequency**: Defined by `telemetryIntervalSec`.
- **Payload**:
  ```json
  {
    "sentAt": "Iso8601Timestamp",
    "readings": [
      {
        "sensorId": "uuid-1",
        "value": 45.2,
        "readingAt": "Iso8601Timestamp"
      }
    ]
  }
  ```

### 3.2 Image Capture (Visual Proof)
Sent via `POST /api/v1/external-devices/{device_id}/images`.

- **Format**: `multipart/form-data`
- **Fields**:
  - `image_file`: Binary JPG file.
  - `image_type`: String (e.g., `plant`, `tank`, `zone`).
  - `captured_at`: Iso8601Timestamp.
  - `metadata_json`: (Optional) Additional JSON info.

### 3.3 Diagnostic Logs
Sent via `POST /api/v1/external-devices/{device_id}/logs`.

- **Format**: JSON
- **Level**: `info`, `warning`, `error`, `critical`.
- **Payload**:
  ```json
  {
    "level": "error",
    "message": "WiFi Signal dropped to -90dBm",
    "recordedAt": "Iso8601Timestamp"
  }
  ```

---

## 4. Status & Heartbeats

The server marks a device as "Offline" if no interaction occurs within **5 minutes**.

- **Heartbeat**: Any request to the server (Telemetry, Logs, or a simple `GET /api/v1/external-devices/{device_id}/status`) updates the `last_seen_at` timestamp.
- **Auto-Registration**: If a known `device_id` calls the API, its status is automatically updated to `is_online = true`.

---

## 5. Failure Handling & Best Practices

1.  **Network Loss**:
    - **Buffering**: Devices should attempt to buffer telemetry locally if the server is unreachable.
    - **Backoff**: Use exponential backoff for reconnection attempts to avoid DDOSing the server after a power outage.
2.  **Clock Sync**: Devices **MUST** use NTP to ensure `readingAt` timestamps are accurate. If NTP fails, do not send telemetry or mark it with a "invalid time" flag if the protocol allows.
3.  **Efficiency**:
    - Use `multipart/form-data` for images.
    - Batch multiple sensor readings into a single Telemetry request.
