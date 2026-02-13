import pytest
from unittest.mock import MagicMock, patch
from raspberry_pi.core.state_manager import StateManager, SystemState
from raspberry_pi.core.hardware import HardwareManager, ArduinoManager
from raspberry_pi.core.system import SystemOrchestrator
from raspberry_pi.config.models import SystemConfig, SystemMode

# --- StateManager Tests ---


def test_state_manager_transitions():
    sm = StateManager()
    assert sm.current_state == SystemState.BOOTING

    sm.transition_to(SystemState.READY)
    assert sm.current_state == SystemState.READY

    sm.transition_to(SystemState.RUNNING)
    assert sm.current_state == SystemState.RUNNING


def test_state_manager_error():
    sm = StateManager()
    sm.report_error("Something went wrong")

    # Non-critical error leads to DEGRADED by default if not already ERROR
    assert sm.current_state == SystemState.DEGRADED

    status = sm.get_status()
    assert status["active_errors"] == 1
    assert "Something went wrong" in status["recent_errors"][0]


# --- HardwareManager Tests ---


@patch("raspberry_pi.core.hardware.ValveController")
@patch("raspberry_pi.core.hardware.MockValveController")
@patch("raspberry_pi.core.hardware.CameraManager")
def test_hardware_manager_init_main(mock_camera, mock_mock_valves, mock_valves):
    config = SystemConfig()
    config.system_mode = SystemMode.MAIN

    # Use spec=True (or class) to ensure Mock resembles the real class
    with patch(
        "raspberry_pi.core.hardware.ArduinoManager", spec=ArduinoManager
    ) as mock_arduino:
        hm = HardwareManager(config)

        # Should use real components
        mock_valves.assert_called()
        mock_arduino.assert_called()
        mock_mock_valves.assert_not_called()

        # Verify strict mocking: simulate_irrigation should NOT exist on ArduinoManager instance
        # Since we use spec=ArduinoManager, accessing unknown attributes might verify this
        # But hasattr on a Mock with spec usually works correctly for non-existing attributes
        assert not hasattr(hm.sensor_provider, "simulate_irrigation")


def test_hardware_manager_init_demo():
    config = SystemConfig()
    config.system_mode = SystemMode.DEMO

    # Mock MockSensorProvider
    with patch(
        "raspberry_pi.sensors.sensor_providers.MockSensorProvider"
    ) as mock_sensor_prov:
        hm = HardwareManager(config)

        # Should use mock components
        # Verify MockSensorProvider was initialized
        mock_sensor_prov.assert_called()


# --- SystemOrchestrator Tests ---


@patch("raspberry_pi.core.system.ConfigManager")
@patch("raspberry_pi.core.system.HardwareManager")
@patch("raspberry_pi.core.system.TelemetryManager")
def test_orchestrator_init(mock_telemetry, mock_hardware, mock_config_cls):
    # Setup mocks
    mock_config_instance = MagicMock()
    mock_config_instance.config = SystemConfig(system_mode=SystemMode.TEST)
    mock_config_cls.return_value = mock_config_instance

    orch = SystemOrchestrator(config_path="dummy.yaml")

    assert orch.config.system_mode == SystemMode.TEST
    mock_hardware.assert_called()
    # Telemetry is initialized during `start()` (after provisioning), not in `__init__`
    mock_telemetry.assert_not_called()
    assert orch.telemetry is None
    assert orch.decision_engine is not None
