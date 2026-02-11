"""
Hardware Testing Utility
========================
Test individual hardware components (sensors and/or valves).
"""

import os
import time
import logging
from typing import Optional, Dict, Any

from sensors.sensor_providers import (
    MockSensorProvider,
    ArduinoSensorProvider,
    MultiArduinoSensorProvider,
)
from water.valve_controller import create_valve_controller, GPIO_AVAILABLE
from api.telemetry import TelemetrySender
from config.config_manager import ConfigManager


def run_tests(args):
    """
    Test individual hardware components (sensors and/or valves).
    Sensor tests also send telemetry if the device is provisioned.
    """
    from core.main_controller import load_config

    config = load_config(args.config)
    zone_configs = config.get("zones", [])

    print("\n" + "=" * 60)
    print("SMART IRRIGATION - TEST MODE")
    print(f"Testing: {args.type.upper()}")
    print("=" * 60)

    # Build telemetry sender for sensor tests (reuses provisioning data)
    telemetry = None
    if args.type in ("sensors", "both") and not getattr(args, "no_telemetry", False):
        telemetry = _build_telemetry(config, getattr(args, "server_ip", None))

    if args.type in ("sensors", "both"):
        _test_sensors(zone_configs, use_mock=args.mock, telemetry=telemetry)

    if args.type in ("valves", "both"):
        _test_valves(zone_configs, use_mock=args.mock)

    print("\n" + "=" * 60)
    print("Tests complete")
    print("=" * 60)


def _build_telemetry(
    config: Dict[str, Any], cli_server_ip: Optional[str] = None
) -> Optional[TelemetrySender]:
    """Create a TelemetrySender from provisioning data if available."""
    internal_config = ConfigManager()
    if not internal_config.is_provisioned():
        print("[Telemetry] Device not provisioned - telemetry disabled")
        return None

    server_config = config.get("server", {})
    server_ip = (
        cli_server_ip
        or server_config.get("ip")
        or os.getenv("DASHBOARD_SERVER_IP", "127.0.0.1")
    )
    server_port = server_config.get("port", 8000)

    try:
        sender = TelemetrySender(
            device_id=internal_config.device_id,
            sensor_map=internal_config.sensor_map,
            server_ip=server_ip,
            server_port=server_port,
        )
        print(f"[Telemetry] Enabled -> {sender.telemetry_url}")
        return sender
    except Exception as e:
        print(f"[Telemetry] Setup failed: {e}")
        return None


def _test_sensors(
    zone_configs: list,
    use_mock: bool = False,
    telemetry: Optional[TelemetrySender] = None,
):
    """Read and display sensor data for all zones, optionally sending telemetry."""
    zone_ids = [z["zone_id"] for z in zone_configs]

    if use_mock:
        provider = MockSensorProvider(zone_ids)
        print("\n[Sensors] Using MOCK provider")
    else:
        try:
            # Check if multi-arduino config exists in the context of run_tests call
            # For simplicity in test mode, we try Multi if configured, otherwise single
            # This is a bit simplified compared to main() logic but sufficient for test tool
            provider = ArduinoSensorProvider()
            print("\n[Sensors] Using REAL Arduino connection")
        except Exception as e:
            print(f"\n[Sensors] Cannot connect to Arduino: {e}")
            return

    print(f"[Sensors] Reading {len(zone_ids)} zone(s)...\n")

    try:
        for i in range(3):
            readings = provider.get_sensor_readings()

            if not readings:
                print(f"  Reading {i + 1}: No data received")
            else:
                print(f"  Reading {i + 1}:")
                for zone_id, data in sorted(readings.items()):
                    name = next(
                        (
                            z.get("name", zone_id)
                            for z in zone_configs
                            if z["zone_id"] == zone_id
                        ),
                        zone_id,
                    )
                    print(
                        f"    {name}: "
                        f"moisture={data['soil_moisture_percent']:.1f}% | "
                        f"temp={data['temperature_c']:.1f}C | "
                        f"humidity={data['humidity_percent']:.1f}%"
                    )

                if telemetry:
                    ok = telemetry.send_telemetry(readings, print_to_console=False)
                    tag = "sent" if ok else "FAILED"
                    print(f"    [Telemetry] {tag}")

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n  Sensor test interrupted")
    finally:
        if hasattr(provider, "close"):
            provider.close()

    print("\n[Sensors] Done")


def _test_valves(zone_configs: list, use_mock: bool = False, duration: float = 3.0):
    """Open each valve briefly to verify operation."""
    zone_pins = {z["zone_id"]: z["valve_pin"] for z in zone_configs if "valve_pin" in z}

    if not zone_pins:
        print("\n[Valves] No valve pins configured - skipping")
        return

    try:
        controller = create_valve_controller(zone_pins, use_mock=use_mock)
    except Exception as e:
        print(f"\n[Valves] Cannot initialize valve controller: {e}")
        return

    label = "MOCK" if use_mock or not GPIO_AVAILABLE else "REAL GPIO"
    print(f"\n[Valves] Using {label} controller")
    print(f"[Valves] Testing {len(zone_pins)} valve(s), {duration:.0f}s each...\n")

    try:
        for zone_id, pin in zone_pins.items():
            name = next(
                (
                    z.get("name", zone_id)
                    for z in zone_configs
                    if z["zone_id"] == zone_id
                ),
                zone_id,
            )
            print(f"  {name} (GPIO {pin}): opening...", end="", flush=True)
            controller.open_valve(zone_id)
            time.sleep(duration)
            controller.close_valve(zone_id)
            print(" closed")

    except KeyboardInterrupt:
        print("\n  Valve test interrupted - closing all valves")
    finally:
        controller.cleanup()

    print("\n[Valves] Done")
