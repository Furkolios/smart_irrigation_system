import pytest
from unittest.mock import MagicMock, patch
import sys
import raspberry_pi.water.valve_controller as vc_module


@pytest.fixture
def valve_controller():
    # Patch GPIO_AVAILABLE to True and GPIO to a mock with create=True
    with (
        patch("raspberry_pi.water.valve_controller.GPIO_AVAILABLE", True),
        patch("raspberry_pi.water.valve_controller.GPIO", create=True) as mock_gpio,
    ):
        # Setup mock constants
        mock_gpio.BCM = "BCM"
        mock_gpio.OUT = "OUT"
        mock_gpio.LOW = 0
        mock_gpio.HIGH = 1

        controller = vc_module.ValveController(
            zone_pins={"zone_1": 17}, active_low=True
        )
        yield controller, mock_gpio


def test_valve_initialization(valve_controller):
    controller, mock_gpio = valve_controller
    mock_gpio.setmode.assert_called_with("BCM")
    mock_gpio.setup.assert_called_with(17, "OUT")
    # Initial state should be HIGH (OFF for active-low)
    mock_gpio.output.assert_called_with(17, 1)


def test_open_valve(valve_controller):
    controller, mock_gpio = valve_controller
    controller.open_valve("zone_1")
    # Active-low: Open = LOW
    mock_gpio.output.assert_called_with(17, 0)
    assert controller.is_open("zone_1")


def test_close_valve(valve_controller):
    controller, mock_gpio = valve_controller
    controller.open_valve("zone_1")
    controller.close_valve("zone_1")
    # Active-low: Close = HIGH
    mock_gpio.output.assert_called_with(17, 1)
    assert not controller.is_open("zone_1")


def test_active_high_logic():
    with (
        patch("raspberry_pi.water.valve_controller.GPIO_AVAILABLE", True),
        patch("raspberry_pi.water.valve_controller.GPIO", create=True) as mock_gpio,
    ):
        mock_gpio.BCM = "BCM"
        mock_gpio.OUT = "OUT"
        mock_gpio.LOW = 0
        mock_gpio.HIGH = 1

        vc = vc_module.ValveController(zone_pins={"zone_1": 17}, active_low=False)

        # Init: OFF = LOW
        mock_gpio.output.assert_called_with(17, 0)

        vc.open_valve("zone_1")
        # Open: ON = HIGH
        mock_gpio.output.assert_called_with(17, 1)
