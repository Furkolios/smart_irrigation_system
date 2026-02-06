"""
Telemetry Module
================
Sends sensor and system data to the dashboard server via HTTP POST.

This module:
    1. Collects all sensor/system data into a single dictionary
    2. Prints it formatted in the console (for debugging)
    3. Sends it as an HTTP POST request to the dashboard server

Endpoint: http://<server_ip>:8000/api/v1/telemetry

Usage:
    from telemetry import TelemetrySender

    sender = TelemetrySender(server_ip="192.168.1.50")
    sender.send(sensor_data, tank_level, weather_data, decision_result)
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any

from dotenv import load_dotenv

load_dotenv()


# =============================================================================
# TELEMETRY SENDER
# =============================================================================

class TelemetrySender:
    """
    Collects system data and sends it to the dashboard server.

    The server receives a JSON payload with all the information
    the frontend needs to display the current system state.
    """

    def __init__(
        self,
        server_ip: Optional[str] = None,
        server_port: int = 8000,
        timeout: int = 5
    ):
        """
        Initialize the telemetry sender.

        Args:
            server_ip: Dashboard server IP address.
                       If not provided, reads from DASHBOARD_SERVER_IP env variable.
            server_port: Server port (default: 8000)
            timeout: HTTP request timeout in seconds
        """
        self.server_ip = server_ip or os.getenv('DASHBOARD_SERVER_IP', '127.0.0.1')
        self.server_port = server_port
        self.timeout = timeout

        self.url = f"http://{self.server_ip}:{self.server_port}/api/v1/telemetry"

        self._logger = logging.getLogger('telemetry')
        self._logger.info(f"Telemetry endpoint: {self.url}")

    # =========================================================================
    # STEP 1: Build the data dictionary
    # =========================================================================

    def build_payload(
        self,
        sensor_data: Dict[str, Dict[str, float]],
        tank_level_liters: float,
        tank_capacity_liters: float,
        weather_data: Optional[Dict[str, Any]] = None,
        decision_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build the telemetry payload dictionary from all data sources.

        Args:
            sensor_data: Sensor readings per zone from sensor_providers.
                         Format: {"zone_1": {"soil_moisture_percent": 45.0, ...}, ...}
            tank_level_liters: Current water tank level in liters
            tank_capacity_liters: Total tank capacity in liters
            weather_data: Weather forecast from weather_api (optional)
            decision_result: Last decision from decision_engine as dict (optional)

        Returns:
            Complete telemetry dictionary ready to send
        """
        # -- Zones --
        zones = []
        for zone_id, readings in sensor_data.items():
            zones.append({
                'zone_id': zone_id,
                'soil_moisture_percent': round(readings.get('soil_moisture_percent', 0), 1),
                'temperature_c': round(readings.get('temperature_c', 0), 1),
                'humidity_percent': round(readings.get('humidity_percent', 0), 1),
            })

        # -- Tank --
        tank_percent = (tank_level_liters / tank_capacity_liters * 100) if tank_capacity_liters > 0 else 0
        tank = {
            'level_liters': round(tank_level_liters, 1),
            'capacity_liters': round(tank_capacity_liters, 1),
            'level_percent': round(tank_percent, 1),
        }

        # -- Weather (include if available) --
        weather = None
        if weather_data:
            today = datetime.now().strftime('%Y-%m-%d')
            today_weather = weather_data.get(today, {})
            weather = {
                'rain_mm': today_weather.get('rain', {}).get('total_mm', 0),
                'will_rain': today_weather.get('rain', {}).get('will_rain', False),
                'temp_min': today_weather.get('temperature', {}).get('day_min'),
                'temp_max': today_weather.get('temperature', {}).get('day_max'),
                'et_mm': today_weather.get('et', {}).get('et_mm', 0),
            }

        # -- Assemble payload --
        payload = {
            'timestamp': datetime.now().isoformat(),
            'zones': zones,
            'tank': tank,
        }

        if weather is not None:
            payload['weather'] = weather

        if decision_result is not None:
            payload['last_decision'] = decision_result

        return payload

    # =========================================================================
    # STEP 2: Print formatted in the console
    # =========================================================================

    def print_payload(self, payload: Dict[str, Any]) -> None:
        """
        Print the telemetry payload in a readable format for debugging.

        Args:
            payload: The telemetry dictionary to display
        """
        print(f"\n{'='*50}")
        print(f"  TELEMETRY DATA - {payload['timestamp']}")
        print(f"{'='*50}")

        # Tank
        tank = payload['tank']
        print(f"\n  Tank: {tank['level_liters']}L / {tank['capacity_liters']}L ({tank['level_percent']}%)")

        # Zones
        print(f"\n  Zones:")
        for zone in payload['zones']:
            print(
                f"    {zone['zone_id']}: "
                f"moisture={zone['soil_moisture_percent']}% | "
                f"temp={zone['temperature_c']}°C | "
                f"humidity={zone['humidity_percent']}%"
            )

        # Weather
        if 'weather' in payload:
            w = payload['weather']
            rain_str = f"{w['rain_mm']}mm" if w['will_rain'] else "no rain"
            print(f"\n  Weather: {rain_str}, {w['temp_min']}–{w['temp_max']}°C, ET={w['et_mm']}mm")

        # Decision
        if 'last_decision' in payload:
            dec = payload['last_decision']
            if dec.get('should_irrigate'):
                n = len(dec.get('commands', []))
                total = dec.get('total_water_liters', 0)
                print(f"\n  Decision: Irrigate {n} zone(s), {total}L total")
            else:
                print(f"\n  Decision: No irrigation — {dec.get('delay_reason', 'not needed')}")

        print(f"{'='*50}\n")

    # =========================================================================
    # STEP 3: Send HTTP POST request
    # =========================================================================

    def post_payload(self, payload: Dict[str, Any]) -> bool:
        """
        Send the telemetry payload to the dashboard server via HTTP POST.

        Args:
            payload: The telemetry dictionary to send

        Returns:
            True if the request was successful, False otherwise
        """
        try:
            response = requests.post(
                self.url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            self._logger.info(f"Telemetry sent successfully (status {response.status_code})")
            return True

        except requests.exceptions.ConnectionError:
            self._logger.warning(f"Cannot reach server at {self.url}")
            return False
        except requests.exceptions.Timeout:
            self._logger.warning(f"Request timed out after {self.timeout}s")
            return False
        except requests.exceptions.HTTPError as e:
            self._logger.warning(f"Server error: {e}")
            return False
        except Exception as e:
            self._logger.error(f"Unexpected error sending telemetry: {e}")
            return False

    # =========================================================================
    # CONVENIENCE: All 3 steps in one call
    # =========================================================================

    def send(
        self,
        sensor_data: Dict[str, Dict[str, float]],
        tank_level_liters: float,
        tank_capacity_liters: float,
        weather_data: Optional[Dict[str, Any]] = None,
        decision_result: Optional[Dict[str, Any]] = None,
        print_to_console: bool = True
    ) -> bool:
        """
        Build, print, and send telemetry data in one call.

        Args:
            sensor_data: Sensor readings per zone
            tank_level_liters: Current tank level
            tank_capacity_liters: Tank capacity
            weather_data: Weather forecast (optional)
            decision_result: Last decision as dict (optional)
            print_to_console: Whether to print formatted output (default: True)

        Returns:
            True if POST was successful, False otherwise
        """
        # Step 1: Build dict
        payload = self.build_payload(
            sensor_data, tank_level_liters, tank_capacity_liters,
            weather_data, decision_result
        )

        # Step 2: Print formatted
        if print_to_console:
            self.print_payload(payload)

        # Step 3: POST to server
        success = self.post_payload(payload)

        if not success:
            self._logger.warning("Telemetry send failed — data was printed but not delivered")

        return success


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # --- Example with mock data ---
    print("Telemetry Module — Test Run")
    print("=" * 40)

    sender = TelemetrySender(server_ip="127.0.0.1")

    # Simulated sensor data (same format as sensor_providers output)
    mock_sensors = {
        "zone_1": {
            "soil_moisture_percent": 32.5,
            "temperature_c": 23.0,
            "humidity_percent": 58.0
        },
        "zone_2": {
            "soil_moisture_percent": 51.0,
            "temperature_c": 23.0,
            "humidity_percent": 58.0
        },
    }

    # Simulated weather (same format as weather_api output)
    today = datetime.now().strftime('%Y-%m-%d')
    mock_weather = {
        today: {
            'rain': {'total_mm': 2.0, 'will_rain': True, 'by_period': {}},
            'temperature': {'day_min': 14.0, 'day_max': 26.0, 'by_period': {}},
            'et': {'et_mm': 3.5},
            'water_balance_mm': -1.5
        }
    }

    # Build and print (skip actual POST for testing)
    payload = sender.build_payload(
        sensor_data=mock_sensors,
        tank_level_liters=35.0,
        tank_capacity_liters=50.0,
        weather_data=mock_weather
    )

    sender.print_payload(payload)

    # Show raw JSON
    print("Raw JSON payload:")
    print(json.dumps(payload, indent=2))

    # Try sending (will fail if no server running — that's OK)
    print("\nAttempting POST to server...")
    success = sender.post_payload(payload)
    print(f"Result: {'✓ Sent' if success else '✗ Server not reachable (expected in test)'}")
