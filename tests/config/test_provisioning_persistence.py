import yaml

from raspberry_pi.config.config_manager import ConfigManager


def test_update_from_provisioning_persists_device_and_mapping(tmp_path):
    cfg_path = tmp_path / "system_config.yaml"
    cfg_path.write_text("server:\n  enabled: true\n  base_url: \"http://localhost:8000\"\n")

    cm = ConfigManager(str(cfg_path))
    provision_data = {
        "deviceId": "dev-abc",
        "sensors": [{"localName": "zone_1", "sensorId": "sensor-1"}],
        "polling": {"telemetryIntervalSec": 12, "heartbeatIntervalSec": 3},
    }

    assert cm.update_from_provisioning(provision_data) is True

    # Re-read file to ensure it's persisted
    raw = yaml.safe_load(cfg_path.read_text())
    assert raw["server"]["device_id"] == "dev-abc"
    assert raw["server"]["sensor_map"]["zone_1"] == "sensor-1"
    assert raw["server"]["telemetry_interval_seconds"] == 12
    assert raw["server"]["heartbeat_interval_seconds"] == 3

