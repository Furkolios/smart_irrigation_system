from raspberry_pi.config.config_manager import ConfigManager
from raspberry_pi.config.provisioning import DeviceProvisioner
from unittest.mock import patch, MagicMock


def test_config_manager_provisioning_state(tmp_path):
    # Use a temporary file for config
    config_file = str(tmp_path / "device_config.json")

    manager = ConfigManager(config_file=config_file)
    assert manager.is_provisioned() is False

    # Simulate provisioning update
    provision_data = {
        "deviceId": "test-uuid",
        "sensors": [
            {"sensorId": "s1", "localName": "zone_1"},
            {"sensorId": "s2", "localName": "zone_2"},
        ],
    }
    manager.update_from_provisioning(provision_data)

    assert manager.is_provisioned() is True
    assert manager.device_id == "test-uuid"
    assert manager.sensor_map["zone_1"] == "s1"


def test_device_provisioner_hardware_id():
    provisioner = DeviceProvisioner(server_ip="127.0.0.1")
    hw_id = provisioner.get_hardware_id()

    # MAC address format check (6 groups of 2 hex digits)
    assert len(hw_id.split(":")) == 6
    for group in hw_id.split(":"):
        assert len(group) == 2
        int(group, 16)  # Should not raise ValueError


@patch("requests.post")
def test_device_provisioner_success(mock_post):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"deviceId": "new-id", "sensors": []}
    mock_post.return_value = mock_response

    provisioner = DeviceProvisioner(server_ip="127.0.0.1")
    result = provisioner.provision({"sensors": []})

    assert result["deviceId"] == "new-id"
    mock_post.assert_called_once()
