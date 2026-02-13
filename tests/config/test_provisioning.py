import pytest
from unittest.mock import patch, MagicMock
from raspberry_pi.config.provisioning import DeviceProvisioner
from requests.exceptions import RequestException


def test_get_hardware_id():
    provisioner = DeviceProvisioner("127.0.0.1")
    hw_id = provisioner.get_hardware_id()
    assert isinstance(hw_id, str)
    assert len(hw_id.split(":")) == 6


@patch("raspberry_pi.config.provisioning.requests.post")
def test_provision_success(mock_post):
    provisioner = DeviceProvisioner("127.0.0.1")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"device_id": "uuid-123", "zones": []}
    mock_post.return_value = mock_response

    result = provisioner.provision({})
    assert result is not None
    assert result["device_id"] == "uuid-123"


@patch("raspberry_pi.config.provisioning.requests.post")
def test_provision_failure(mock_post):
    provisioner = DeviceProvisioner("127.0.0.1")

    # Needs to handle exception inside provision method
    mock_post.side_effect = RequestException("Connection Error")

    result = provisioner.provision({})
    assert result is None
