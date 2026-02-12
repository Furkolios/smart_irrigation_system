# External Devices Behavior Documentation

This document describes the current state, behavior, and data flow of the **External Devices** component in the Smart Irrigation API.

## Overview

The `external-devices` module provides a set of endpoints designed for peripheral hardware (e.g., ESP32, Arduino, Raspberry Pi) to communicate with the system. It handles telemetry data, operational logs, device images, and liveness monitoring.

## Base path and conventions

- **Router prefix**: `/external-devices`
- **Path parameter**: `device_id` is a UUID (example: `2b7d2c3f-7d4b-4e1f-9f0a-4c1b3c9c7b2a`)
- **Date/time fields**: use ISO-8601 (example: `2026-02-12T12:34:56Z`)
- **JSON field naming**:
  - Request/response models for telemetry and logs use camelCase aliases (example: `sentAt`, `recordedAt`).
  - They also accept snake_case input (example: `sent_at`, `recorded_at`) because the schemas allow population by field name.

## Core Entities & Models

### 1. Device (`DeviceModel`)
Represents a physical device in the field.
- **Attributes**: `id` (UUID), `name`, `description`, `is_active`.
- **Liveness**: Tracks `last_seen_at`, `is_online`, and `uptime`.
- **Behavior**: Any interaction with the `/external-devices` endpoints automatically registers a new device or updates the `last_seen_at` timestamp for an existing one.

### 2. Device Logs (`DeviceLogModel`)
Stores diagnostic messages from the hardware.
- **Attributes**: `level` (info, warning, error, critical), `message`, `recorded_at`.
- **Purpose**: Helps in remote debugging of connectivity or hardware failures without physical access to the device.

### 3. Device Images (`DeviceImageModel`)
Stores references to images captured by the device.
- **Attributes**: `image_url` (local path), `type` (plant, tank, zone), `captured_at`, `metadata`.
- **Storage**: Physical images are saved in `uploads/devices/{id}/{type}.jpg`.
- **Behavior**: The system keeps the most recent image for each `type` per device (Upsert logic).

### 4. Telemetry & Sensor Readings
While not a dedicated "external device" model, telemetry ingestion is a primary function.
- **Data Flow**: `TelemetryRequest` -> `save_telemetry` -> `SensorReadingModel`.
- **Validation**: Incoming telemetry only saves data for `sensor_id`s that already exist in the `sensors` table.

## Endpoint reference (expected params/bodies)

### `POST /external-devices/{device_id}/telemetry`

**Content-Type**: `application/json`  
**Path params**:
- **device_id**: UUID

**Body** (`TelemetryRequest`):
- **sentAt** (datetime, required): when the device sent this payload
- **readings** (array, required): list of sensor readings
  - **sensorId** (string, required): device-local or provisioned sensor identifier (stored as string)
  - **type** (string enum, required): one of `humidity`, `temperature`, `flow`, `water-level`, `air-quality`
  - **value** (number, required)
  - **unit** (string, required)
  - **readingAt** (datetime, optional): timestamp for the specific reading (if omitted, backend may use `sentAt`/server time depending on service logic)

Example JSON:
```json
{
  "sentAt": "2024-02-04T12:00:00Z",
  "readings": [
    {
      "sensorId": "uuid-here",
      "type": "humidity",
      "value": 45.2,
      "unit": "%",
      "readingAt": "2024-02-04T11:59:00Z"
    }
  ]
}
```

Example `curl`:

```bash
curl -X POST "$BASE_URL/api/v1/external-devices/$DEVICE_ID/telemetry" \
  -H "Content-Type: application/json" \
  -d '{"sentAt":"2026-02-12T12:00:00Z","readings":[{"sensorId":"soil-1","type":"humidity","value":45.2,"unit":"%","readingAt":"2026-02-12T11:59:00Z"}]}'
```

**Response** (`TelemetryResponse`, 201):
- **id** (UUID)
- **deviceId** (string)
- **status** (string, default `accepted`)
- **processedCount** (int)

### `POST /external-devices/{device_id}/logs`

**Content-Type**: `application/json`  
**Path params**:
- **device_id**: UUID

**Body** (`DeviceLogCreate`):
- **level** (string, required)
- **message** (string, required)
- **recordedAt** (datetime, optional)

Example JSON:
```json
{
  "level": "error",
  "message": "Wifi reconnection failed 3 times",
  "recordedAt": "2024-02-04T12:05:00Z"
}
```

Example `curl`:

```bash
curl -X POST "$BASE_URL/api/v1/external-devices/$DEVICE_ID/logs" \
  -H "Content-Type: application/json" \
  -d '{"level":"error","message":"Wifi reconnection failed 3 times","recordedAt":"2026-02-12T12:05:00Z"}'
```

**Response** (`DeviceLogResponse`, 201):
- **id** (UUID)
- **deviceId** (UUID)
- **level** (string)
- **message** (string)
- **recordedAt** (datetime)

### `POST /external-devices/{device_id}/images`

**Content-Type**: `multipart/form-data`  
**Path params**:
- **device_id**: UUID

**Form fields**:
- **file** (file, required): the image file upload
- **type** (string, required): image category (free-form string; commonly `plant`, `tank`, `zone`)
- **captured_at** (datetime, required): when the image was captured
- **plant_id** (UUID, optional): associate the image to a plant
- **zone_id** (UUID, optional): associate the image to a zone
- **metadata** (string, optional): JSON-encoded string; will be parsed with `json.loads` (must be valid JSON if provided)

Example `curl`:

```bash
curl -X POST "$BASE_URL/api/v1/external-devices/$DEVICE_ID/images" \
  -H "Accept: application/json" \
  -F "file=@./image.jpg" \
  -F "type=plant" \
  -F "captured_at=2026-02-12T12:00:00Z" \
  -F "plant_id=$PLANT_ID" \
  -F 'metadata={"source":"esp32-cam","exposure":0.2}'
```

**Response** (`DeviceImageResponse`, 201):
- **id** (UUID)
- **deviceId** (UUID)
- **plantId** (UUID | null)
- **zoneId** (UUID | null)
- **imageUrl** (string)
- **type** (string)
- **capturedAt** (datetime)

### `GET /external-devices/{device_id}/status`

**Path params**:
- **device_id**: UUID

Example `curl`:

```bash
curl -X GET "$BASE_URL/api/v1/external-devices/$DEVICE_ID/status"
```

**Response** (`DeviceStatusResponse`, 200):
- **deviceId** (UUID)
- **name** (string)
- **isOnline** (bool)
- **lastSeenAt** (datetime | null)
- **uptime** (float | null)

## Database Impact

1. **Device Upsert**: Every call to these endpoints ensures the device exists in the `devices` table and marks it as `is_online` (within a 5-minute window).
2. **Persistence**:
   - Telemetry -> `sensor_readings` table.
   - Logs -> `device_logs` table.
   - Images -> `device_images` table + File System storage.

## What to do with this data? (Future Usage)

The data collected in the database serves several critical purposes:

### 1. Visualization & Monitoring
- **Dashboards**: Use `sensor_readings` to plot historical humidity, temperature, and water level charts for a zone, plant, sensor, water views.
