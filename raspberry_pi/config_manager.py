import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    """
    Handles local persistence of device configuration.
    This includes the server-assigned deviceId and sensor mappings.
    """

    def __init__(self, config_file: str = "device_internal_config.json"):
        self.config_path = Path(config_file)
        self.logger = logging.getLogger("config_manager")
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load config from disk or return empty dict if not found."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load internal config: {e}")
        return {}

    def save(self):
        """Save the current data to disk."""
        try:
            with open(self.config_path, "w") as f:
                json.dump(self._data, f, indent=2)
            self.logger.debug(f"Saved internal config to {self.config_path}")
        except Exception as e:
            self.logger.error(f"Failed to save internal config: {e}")

    @property
    def device_id(self) -> Optional[str]:
        return self._data.get("deviceId")

    @device_id.setter
    def device_id(self, value: str):
        self._data["deviceId"] = value
        self.save()

    @property
    def sensor_map(self) -> Dict[str, str]:
        """Returns mapping from localName to sensorId."""
        return self._data.get("sensorMap", {})

    @sensor_map.setter
    def sensor_map(self, value: Dict[str, str]):
        self._data["sensorMap"] = value
        self.save()

    @property
    def intervals(self) -> Dict[str, int]:
        return self._data.get(
            "intervals", {"telemetryIntervalSec": 60, "heartbeatIntervalSec": 30}
        )

    @intervals.setter
    def intervals(self, value: Dict[str, int]):
        self._data["intervals"] = value
        self.save()

    def is_provisioned(self) -> bool:
        return bool(self.device_id)

    def update_from_provisioning(self, response_data: Dict[str, Any]):
        """Update local config with data from the server's provisioning response."""
        self.device_id = response_data.get("deviceId")

        # Map localName -> sensorId
        sensor_map = {}
        for s in response_data.get("sensors", []):
            if "localName" in s and "sensorId" in s:
                sensor_map[s["localName"]] = s["sensorId"]
        self.sensor_map = sensor_map

        # Polling intervals
        if "polling" in response_data:
            self.intervals = response_data["polling"]

        self.save()
        self.logger.info("Configuration updated from server provisioning response")


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.DEBUG)
    cm = ConfigManager("test_config.json")
    print(f"Is provisioned: {cm.is_provisioned()}")
    cm.device_id = "test-uuid"
    print(f"New ID: {cm.device_id}")
    os.remove("test_config.json")
