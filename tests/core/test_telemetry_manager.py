import pytest
import json
import os
import time
from unittest.mock import MagicMock, patch
from raspberry_pi.core.telemetry import TelemetryManager
from raspberry_pi.config.models import ServerConfig


@pytest.fixture
def telemetry_manager(tmp_path):
    config = ServerConfig(
        enabled=True, base_url="http://test-server", device_id="dev-123"
    )
    # Patch the backlog file location to use tmp_path
    with (
        patch("raspberry_pi.core.telemetry.TelemetryManager.start"),
        patch("raspberry_pi.core.telemetry.os.rename"),
        patch("raspberry_pi.core.telemetry.os.path.exists"),
        patch("raspberry_pi.core.telemetry.os.remove"),
    ):
        manager = TelemetryManager(config)
        manager.backlog_file = str(tmp_path / "backlog.jsonl")
        return manager


def test_telemetry_queueing(telemetry_manager):
    data = {"temp": 25}
    telemetry_manager.send_telemetry(data)

    assert not telemetry_manager.queue.empty()
    item = telemetry_manager.queue.get()
    assert item["type"] == "telemetry"
    assert item["data"] == data


@patch("raspberry_pi.core.telemetry.requests.post")
def test_send_to_server_success(mock_post, telemetry_manager):
    mock_post.return_value.status_code = 200

    payload = {"type": "heartbeat", "deviceId": "dev-123"}
    success = telemetry_manager._send_to_server(payload)

    assert success is True
    mock_post.assert_called_once()
    assert mock_post.call_args[0][0] == "http://test-server/api/v1/heartbeat"


@patch("raspberry_pi.core.telemetry.requests.post")
def test_send_to_server_failure(mock_post, telemetry_manager):
    mock_post.return_value.status_code = 500

    payload = {"type": "heartbeat"}
    success = telemetry_manager._send_to_server(payload)

    assert success is False


def test_save_to_backlog(telemetry_manager):
    payload = {"type": "log", "message": "test"}
    telemetry_manager._save_to_backlog(payload)

    with open(telemetry_manager.backlog_file, "r") as f:
        line = f.readline()
        saved = json.loads(line)
        assert saved["type"] == "log"
        assert saved["message"] == "test"
