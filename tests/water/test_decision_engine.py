import pytest
from datetime import datetime
from raspberry_pi.water.decision_engine import (
    IrrigationDecisionEngine,
    ZoneConfig,
    SensorReading,
    TankStatus,
    DecisionResult,
)
from unittest.mock import patch


def test_decision_engine_basic_irrigation():
    zones = [
        ZoneConfig(
            zone_id="zone_1",
            name="Zone 1",
            area_m2=1.0,
            moisture_threshold_low=30.0,
            moisture_threshold_target=60.0,
        )
    ]
    engine = IrrigationDecisionEngine(zones=zones)

    # Critical moisture (20%)
    sensor_data = {
        "zone_1": SensorReading(
            zone_id="zone_1",
            soil_moisture_percent=20.0,
            temperature_c=25.0,
            humidity_percent=40.0,
        )
    }

    # No rain, enough water
    weather_data = {
        datetime.now().strftime("%Y-%m-%d"): {
            "rain": {"total_mm": 0, "will_rain": False},
            "temperature": {"day_min": 15, "day_max": 25},
            "et": {"et_mm": 3.0},
        }
    }

    tank_status = TankStatus(current_level_liters=50.0, capacity_liters=50.0)

    # Force=True to bypass time-of-day check
    result = engine.make_decisions(sensor_data, weather_data, tank_status, force=True)

    assert result.should_irrigate is True
    assert len(result.commands) == 1
    assert result.commands[0].zone_id == "zone_1"
    assert result.total_water_liters > 0


def test_decision_engine_tank_constraint():
    zones = [
        ZoneConfig(
            zone_id="zone_1", name="Zone 1", area_m2=10.0, moisture_threshold_low=30.0
        )
    ]
    engine = IrrigationDecisionEngine(zones=zones)

    # Very dry
    sensor_data = {
        "zone_1": SensorReading(
            zone_id="zone_1",
            soil_moisture_percent=10.0,
            temperature_c=25.0,
            humidity_percent=40.0,
        )
    }

    # Tank is almost empty (2L left, capacity 50L)
    # Reserve is 10% (5L), Emergency is 5% (2.5L)
    tank_status = TankStatus(current_level_liters=2.0, capacity_liters=50.0)

    weather_data = {
        datetime.now().strftime("%Y-%m-%d"): {
            "rain": {"total_mm": 0, "will_rain": False},
            "temperature": {"day_min": 15, "day_max": 25},
        }
    }

    result = engine.make_decisions(sensor_data, weather_data, tank_status, force=True)

    # Should not irrigate because of tank level
    assert result.should_irrigate is False
    assert result.total_water_liters == 0


def test_decision_engine_rain_delay():
    zones = [
        ZoneConfig(
            zone_id="zone_1", name="Zone 1", area_m2=1.0, moisture_threshold_low=30.0
        )
    ]
    engine = IrrigationDecisionEngine(zones=zones)

    sensor_data = {
        "zone_1": SensorReading(
            zone_id="zone_1",
            soil_moisture_percent=20.0,
            temperature_c=25.0,
            humidity_percent=40.0,
        )
    }

    # Build a fake "now" that is NOT midday to avoid midday evaporation delay
    # e.g. 8:00 AM
    fixed_now = datetime.now().replace(hour=8, minute=0)

    # Heavy rain forecast (10mm)
    weather_data = {
        fixed_now.strftime("%Y-%m-%d"): {
            "rain": {"total_mm": 10.0, "will_rain": True},
            "temperature": {"day_min": 15, "day_max": 25},
        }
    }

    tank_status = TankStatus(current_level_liters=50.0, capacity_liters=50.0)

    with patch("raspberry_pi.water.decision_engine.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        mock_datetime.strftime = datetime.strftime

        result = engine.make_decisions(
            sensor_data, weather_data, tank_status, force=False
        )

        assert result.should_irrigate is False
        assert "Rain expected" in result.delay_reason
