import os
import sys
import json
import argparse
import logging
from pathlib import Path

# =============================================================================
# VIRTUAL ENVIRONMENT CHECK
# =============================================================================


def check_venv():
    """Ensure the script is running inside the virtual environment."""
    is_venv = sys.prefix != sys.base_prefix
    # Also check if venv directory exists in the project root
    root_path = Path(__file__).parent.parent
    venv_exists = (root_path / "venv").exists()

    if not is_venv:
        print("\n" + "!" * 60)
        print("ERROR: Virtual environment not active.")
        print("-" * 60)
        print("Please activate the environment before running this script:")
        print("    source venv/bin/activate")
        print("!" * 60 + "\n")
        sys.exit(1)


# Run check immediately
check_venv()

# =============================================================================
# IMPORTS (after venv check)
# =============================================================================

# Add current directory to path so we can import modules correctly
sys.path.append(str(Path(__file__).parent))

from core.main_controller import (
    IrrigationController,
    load_config,
    run_demo_mode,
    run_tests,
    WEATHER_API_AVAILABLE,
    PLANT_API_AVAILABLE,
)

# Optional API imports
try:
    from api.weather_api import create_api as create_weather_api

    WEATHER_API_AVAILABLE = True
except ImportError:
    WEATHER_API_AVAILABLE = False

try:
    from api.plant_api import PlantAPI

    PLANT_API_AVAILABLE = True
except ImportError:
    PLANT_API_AVAILABLE = False

from sensors.sensor_providers import MockSensorProvider, MultiArduinoSensorProvider

# =============================================================================
# CLI WRAPPER
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Smart Irrigation System - Unified CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run main irrigation cycle (production)
  python %(prog)s run
  
  # Run once in mock mode
  python %(prog)s run --mock --once
  
  # Run demo mode
  python %(prog)s demo --scenario critical
  
  # Test hardware
  python %(prog)s test both
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # --- RUN COMMAND ---
    run_parser = subparsers.add_parser("run", help="Run the irrigation controller")
    run_parser.add_argument("--config", type=str, help="Path to config file")
    run_parser.add_argument("--once", action="store_true", help="Run once and exit")
    run_parser.add_argument("--force", action="store_true", help="Force irrigation")
    run_parser.add_argument("--status", action="store_true", help="Print system status")
    run_parser.add_argument("--mock", action="store_true", help="Use mock sensors/tank")
    run_parser.add_argument("--server-ip", type=str, help="Dashboard server IP")
    run_parser.add_argument(
        "--no-telemetry", action="store_true", help="Disable telemetry"
    )

    # --- DEMO COMMAND ---
    demo_parser = subparsers.add_parser("demo", help="Run in demo/simulation mode")
    demo_parser.add_argument(
        "--scenario",
        type=str,
        default="normal",
        choices=["normal", "critical", "rain", "healthy", "low_tank", "mixed"],
        help="Demo scenario",
    )
    demo_parser.add_argument("--zones", type=int, default=3, help="Number of zones")
    demo_parser.add_argument(
        "--once", action="store_true", help="Run single cycle output"
    )
    demo_parser.add_argument("--server-ip", type=str, help="Dashboard server IP")

    # --- TEST COMMAND ---
    test_parser = subparsers.add_parser("test", help="Test hardware components")
    test_parser.add_argument(
        "type", choices=["sensors", "valves", "both"], help="What to test"
    )
    test_parser.add_argument("--mock", action="store_true", help="Use mock components")
    test_parser.add_argument("--config", type=str, help="Path to config file")
    test_parser.add_argument("--server-ip", type=str, help="Dashboard server IP")
    test_parser.add_argument(
        "--no-telemetry", action="store_true", help="Disable telemetry"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Handle commands
    if args.command == "demo":
        # Adapting args for core.main_controller.run_demo_mode
        # which expects argparse.Namespace with demo=True
        args.demo = True
        run_demo_mode(args)

    elif args.command == "test":
        # Adapting args for core.main_controller.run_tests
        # which expects argparse.Namespace with test=type
        args.test = args.type
        run_tests(args)

    elif args.command == "run":
        # Direct implementation of run logic from core/main_controller.py
        config = load_config(args.config)

        if args.server_ip:
            config.setdefault("server", {})["ip"] = args.server_ip
        if args.no_telemetry:
            config.setdefault("server", {})["enabled"] = False

        weather_api = None
        plant_api = None

        if WEATHER_API_AVAILABLE:
            try:
                weather_api = create_weather_api(silent=True)
            except:
                pass

        if PLANT_API_AVAILABLE:
            try:
                plant_api = PlantAPI()
            except:
                pass

        zone_ids = [z["zone_id"] for z in config.get("zones", [])]
        mock_tank = None
        sensor_provider = None

        if args.mock:
            capacity = config.get("tank", {}).get("capacity_liters", 50.0)
            mock_tank = capacity * 0.8
            sensor_provider = MockSensorProvider(zone_ids)
        else:
            arduino_map = config.get("arduinos", {})
            if arduino_map:
                try:
                    sensor_provider = MultiArduinoSensorProvider(
                        port_zone_map=arduino_map
                    )
                except Exception as e:
                    print(f"Arduino setup failed: {e}. Falling back to mock.")
                    sensor_provider = MockSensorProvider(zone_ids)
                    mock_tank = (
                        config.get("tank", {}).get("capacity_liters", 50.0) * 0.8
                    )

        controller = IrrigationController(
            config=config,
            sensor_provider=sensor_provider,
            weather_api=weather_api,
            plant_api=plant_api,
            mock_tank_level=mock_tank,
        )

        if args.status:
            print(json.dumps(controller.get_status(), indent=2))
        elif args.once:
            result = controller.run_once(force=args.force)
            print(json.dumps(result.to_dict(), indent=2))
        else:
            controller.run()


if __name__ == "__main__":
    main()
