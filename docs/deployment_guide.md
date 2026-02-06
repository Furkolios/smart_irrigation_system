# Deployment & Testing Guide: Raspberry Pi Initialization

This guide outlines the steps to deploy the device code to a Raspberry Pi and verify the initialization, provisioning, and telemetry flow with a local server.

## 1. Prerequisites

- **Raspberry Pi**: Set up with Raspberry Pi OS (Standard or Lite).
- **Network**: Raspberry Pi and the computer running the server must be on the **same local network**.
- **Server**: The Smart Irrigation API should be running on your local computer.

## 2. Server Configuration

1.  **Find your Computer's Local IP**:
    - On macOS/Linux: Run `ifconfig` or `ip addr`. Look for `inet 192.168.x.x`.
    - On Windows: Run `ipconfig`.
2.  **Ensure the Server is listening on `0.0.0.0`**:
    - Your API server should be started with `--host 0.0.0.0` to allow external connections from the Pi.

## 3. Device Setup (on Raspberry Pi)

1.  **Clone the Repository**:
    ```bash
    git clone <your-repo-url>
    cd smart_irrigation_system/raspberry_pi
    ```
2.  **Install Dependencies**:
    ```bash
    pip install requests python-dotenv
    ```
3.  **Configure Environment**:
    Create a `.env` file in the `raspberry_pi` folder:
    ```bash
    DASHBOARD_SERVER_IP=192.168.x.x  # Replace with your computer's IP
    ```

## 4. Initialization & Testing Flow

### Step 1: Initial Boot & Provisioning
Run the controller for the first time. The system will detect it is not provisioned and start the bootstrapping flow.

```bash
# Run with mock sensors to test without Arduino hardware
python main_controller.py --once --mock
```

**Verification**:
- Check the console output: Look for `✓ Communication initialized (DeviceID: ...)`.
- Check for a new file: `device_internal_config.json`. It should contain the `deviceId` and `sensorMap` assigned by the server.

### Step 2: Periodic Telemetry
Start the main control loop. The device will send data every cycle.

```bash
python main_controller.py --mock
```

**Verification**:
- **Logs**: The console will show `Sending telemetry: X readings` every 10 minutes (or based on your config).
- **Heartbeat**: If the server is momentarily unreachable, the device will continue to try and log successes/failures.
- **Server Side**: Check your server logs to see the incoming `POST` requests to `/api/v1/external-devices/.../telemetry`.

### Step 3: Image Upload (Visual Verification)
If you have a camera attached:

```bash
# Capture and send image once
python main_controller.py --once
```

**Verification**:
- Verify that `tank_capture.jpg` is created and then deleted after upload.
- Check the server's storage/logs for the received image.

## 5. Troubleshooting

- **Connection Error**: Ensure there is no firewall on your computer blocking port 8000.
- **"Device ID missing"**: Delete `device_internal_config.json` to force a re-provisioning if you change server databases.
- **Time Sync**: Ensure the Pi has the correct time (NTP) for accurate `sentAt` timestamps.
- **Unused Sensors**: If the server responds with fewer sensors than expected, check the server-side device configuration.
