import pytest
import sys
from unittest.mock import patch, MagicMock

# Mock serial module before importing sensor_providers
mock_serial_module = MagicMock()
sys.modules["serial"] = mock_serial_module

from raspberry_pi.sensors.sensor_providers import (
    MockSensorProvider,
    ArduinoSensorProvider,
)
from tests.mocks.sensor_mocks import MockSerial, get_sample_sensor_data


def test_mock_sensor_provider():
    zone_ids = ["zone_1", "zone_2"]
    provider = MockSensorProvider(zone_ids=zone_ids, initial_moisture=50.0)

    readings = provider.get_sensor_readings()

    assert len(readings) == 2
    for zone_id in zone_ids:
        assert zone_id in readings
        assert 10 <= readings[zone_id]["soil_moisture_percent"] <= 100
        assert "temperature_c" in readings[zone_id]
        assert "humidity_percent" in readings[zone_id]


def test_mock_sensor_irrigation_simulation():
    provider = MockSensorProvider(zone_ids=["zone_1"], initial_moisture=30.0)

    # Simulate 10L irrigation on 1m2 area
    provider.simulate_irrigation("zone_1", 10.0, 1.0)

    readings = provider.get_sensor_readings()
    # 30 + (10/1)*2 = 50.0 (plus some random noise +/- 1 in Provider)
    assert 48.0 <= readings["zone_1"]["soil_moisture_percent"] <= 52.0


@patch("serial.Serial")
def test_arduino_sensor_provider_parsing(mock_serial_class):
    # Setup mock serial
    mock_serial = MockSerial(port="/dev/test", baudrate=9600, timeout=1.0)
    mock_serial_class.return_value = mock_serial

    provider = ArduinoSensorProvider(port="/dev/test")

    # Inject mock data
    sample_data = get_sample_sensor_data("zone_1")
    mock_serial.set_next_data(sample_data)

    readings = provider.get_sensor_readings()

    assert "zone_1" in readings
    assert readings["zone_1"]["soil_moisture_percent"] == 45.0
    assert readings["zone_1"]["temperature_c"] == 22.5
    assert readings["zone_1"]["humidity_percent"] == 60.0
