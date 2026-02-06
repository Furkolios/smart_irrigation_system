import os
import json
import pytest
import responses
from unittest.mock import MagicMock, patch
from pathlib import Path

# Adjust path to import from parent directory
import sys

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "raspberry_pi"))
)

from config_manager import ConfigManager
from provisioning import DeviceProvisioner
from telemetry import TelemetrySender
from image_sender import ImageSender

# =============================================================================
# ConfigManager Tests
# =============================================================================


class TestConfigManager:
    @pytest.fixture
    def config_file(self, tmp_path):
        return str(tmp_path / "test_config.json")

    def test_initialization_empty(self, config_file):
        cm = ConfigManager(config_file)
        assert cm.is_provisioned() is False
        assert cm.device_id is None
        assert cm.sensor_map == {}

    def test_save_and_load(self, config_file):
        cm = ConfigManager(config_file)
        cm.device_id = "test-uuid"
        cm.sensor_map = {"zone_1": "sensor-uuid"}

        # Load new instance from same file
        cm2 = ConfigManager(config_file)
        assert cm2.device_id == "test-uuid"
        assert cm2.sensor_map == {"zone_1": "sensor-uuid"}

    def test_update_from_provisioning(self, config_file):
        cm = ConfigManager(config_file)
        data = {
            "deviceId": "new-uuid",
            "sensors": [
                {"localName": "soil_1", "sensorId": "s-1"},
                {"localName": "soil_2", "sensorId": "s-2"},
            ],
            "polling": {"telemetryIntervalSec": 100, "heartbeatIntervalSec": 50},
        }
        cm.update_from_provisioning(data)
        assert cm.device_id == "new-uuid"
        assert cm.sensor_map == {"soil_1": "s-1", "soil_2": "s-2"}
        assert cm.intervals["telemetryIntervalSec"] == 100


# =============================================================================
# DeviceProvisioner Tests
# =============================================================================


class TestDeviceProvisioner:
    @responses.activate
    def test_provision_success(self):
        dp = DeviceProvisioner("127.0.0.1")
        responses.add(
            responses.POST,
            dp.url,
            json={"deviceId": "assigned-id", "sensors": []},
            status=200,
        )

        result = dp.provision({"sensors": []})
        assert result["deviceId"] == "assigned-id"
        assert len(responses.calls) == 1

    @responses.activate
    def test_provision_failure(self):
        dp = DeviceProvisioner("127.0.0.1")
        responses.add(responses.POST, dp.url, status=500)

        result = dp.provision({"sensors": []})
        assert result is None


# =============================================================================
# TelemetrySender Tests
# =============================================================================


class TestTelemetrySender:
    @pytest.fixture
    def sender(self):
        return TelemetrySender(device_id="dev-123", sensor_map={"zone_1": "uuid-1"})

    @responses.activate
    def test_send_telemetry_success(self, sender):
        responses.add(responses.POST, sender.telemetry_url, status=200)

        data = {"zone_1": {"soil_moisture_percent": 30.0}}
        success = sender.send_telemetry(data)

        assert success is True
        payload = json.loads(responses.calls[0].request.body)
        assert payload["readings"][0]["sensorId"] == "uuid-1"
        assert payload["readings"][0]["value"] == 30.0

    @responses.activate
    def test_send_log(self, sender):
        responses.add(responses.POST, sender.log_url, status=201)
        success = sender.send_log("info", "Hello world")
        assert success is True

        payload = json.loads(responses.calls[0].request.body)
        assert payload["level"] == "info"
        assert payload["message"] == "Hello world"


# =============================================================================
# ImageSender Tests
# =============================================================================


class TestImageSender:
    @responses.activate
    def test_upload_image(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake-image-data")

        sender = ImageSender(device_id="dev-123")
        responses.add(responses.POST, sender.url, status=200)

        success = sender.upload_image(str(img_path), image_type="plant")
        assert success is True
        assert (
            "multipart/form-data" in responses.calls[0].request.headers["Content-Type"]
        )
