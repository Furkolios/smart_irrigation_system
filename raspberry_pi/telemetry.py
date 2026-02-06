"""
Telemetry & Logging Module
==========================
Handles communication with the Smart Irrigation API for telemetry,
diagnostic logs, and heartbeats.

Endpoints:
    - Telemetry: POST /api/v1/external-devices/{device_id}/telemetry
    - Logs:      POST /api/v1/external-devices/{device_id}/logs
    - Status:    GET  /api/v1/external-devices/{device_id}/status

Fulfills Sections 3.1, 3.3, and 4 of the Technical Manual.
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any

from dotenv import load_dotenv

load_dotenv()


class TelemetrySender:
    """
    Sends sensor readings and diagnostic logs to the dashboard server.
    """

    def __init__(
        self,
        device_id: str,
        sensor_map: Dict[str, str],
        server_ip: Optional[str] = None,
        server_port: int = 8000,
        timeout: int = 5,
    ):
        """
        Initialize the telemetry sender.

        Args:
            device_id: UUID assigned by the server.
            sensor_map: Mapping from localName to sensorId (UUID).
            server_ip: Dashboard server IP address.
            server_port: Server port (default: 8000)
            timeout: HTTP request timeout in seconds
        """
        self.device_id = device_id
        self.sensor_map = sensor_map
        self.server_ip = server_ip or os.getenv("DASHBOARD_SERVER_IP", "127.0.0.1")
        self.server_port = server_port
        self.timeout = timeout

        self.base_url = f"http://{self.server_ip}:{self.server_port}/api/v1/external-devices/{self.device_id}"
        self.telemetry_url = f"{self.base_url}/telemetry"
        self.log_url = f"{self.base_url}/logs"
        self.status_url = f"{self.base_url}/status"

        self._logger = logging.getLogger("telemetry")
        self._logger.info(f"Telemetry initialized for device {self.device_id}")

    # =========================================================================
    # TELEMETRY (Section 3.1)
    # =========================================================================

    def send_telemetry(
        self, sensor_data: Dict[str, Dict[str, float]], print_to_console: bool = True
    ) -> bool:
        """
        Assemble and send telemetry payload.

        Args:
            sensor_data: Raw sensor readings from providers.
                         Format: {"zone_1": {"soil_moisture_percent": 45.0, ...}, ...}
        """
        now_iso = datetime.now().isoformat()
        readings = []

        for local_name, values in sensor_data.items():
            sensor_id = self.sensor_map.get(local_name)
            if not sensor_id:
                self._logger.warning(f"No sensorId found for localName: {local_name}")
                continue

            # In the current system, we send the primary value (moisture)
            # but we could expand this to send all sub-readings if needed.
            # Assuming 'soil_moisture_percent' is the primary 'value'.
            value = values.get("soil_moisture_percent")
            if value is not None:
                readings.append(
                    {
                        "sensorId": sensor_id,
                        "value": round(float(value), 2),
                        "readingAt": now_iso,
                    }
                )

        payload = {"sentAt": now_iso, "readings": readings}

        if print_to_console:
            self._logger.info(f"Sending telemetry: {len(readings)} readings")
            if len(readings) > 0:
                self._logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

        return self._post_request(self.telemetry_url, payload)

    # =========================================================================
    # DIAGNOSTIC LOGS (Section 3.3)
    # =========================================================================

    def send_log(self, level: str, message: str) -> bool:
        """
        Send a diagnostic log to the server.
        Levels: info, warning, error, critical.
        """
        payload = {
            "level": level.lower(),
            "message": message,
            "recordedAt": datetime.now().isoformat(),
        }
        return self._post_request(self.log_url, payload)

    # =========================================================================
    # HEARTBEAT (Section 4)
    # =========================================================================

    def send_heartbeat(self) -> bool:
        """
        Simple heartbeat to update 'last_seen_at'.
        """
        try:
            response = requests.get(self.status_url, timeout=self.timeout)
            response.raise_for_status()
            return True
        except Exception as e:
            self._logger.warning(f"Heartbeat failed: {e}")
            return False

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _post_request(self, url: str, payload: Dict[str, Any]) -> bool:
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return True
        except Exception as e:
            self._logger.error(f"POST to {url} failed: {e}")
            return False


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.DEBUG)
    mock_id = "00000000-0000-0000-0000-000000000000"
    mock_map = {"zone_1": "11111111-1111-1111-1111-111111111111"}

    sender = TelemetrySender(device_id=mock_id, sensor_map=mock_map)

    test_data = {"zone_1": {"soil_moisture_percent": 42.5}}

    print("Testing build logic (will fail POST without server)...")
    sender.send_telemetry(test_data)
    sender.send_log("info", "Test log message")
