"""
Valve Controller Module
=======================
Controls irrigation valves via Raspberry Pi GPIO.

Supports both active-HIGH and active-LOW relay modules:
- active_low=True  (default): For HW-482 and similar optocoupled relays
  where GPIO LOW triggers the relay ON.
- active_low=False: For relay modules where GPIO HIGH triggers the relay ON.

This module contains:
- ValveController: Real GPIO-based valve control
- MockValveController: For testing without hardware

Usage:
    from valve_controller import ValveController, MockValveController

    # For production with HW-482 relay (active-LOW, default)
    controller = ValveController(zone_pins={"zone_1": 17, "zone_2": 18})

    # For active-HIGH relay modules
    controller = ValveController(zone_pins={"zone_1": 17}, active_low=False)

    # For testing
    controller = MockValveController(zone_pins={"zone_1": 17, "zone_2": 18})

    # Control valves
    controller.open_valve("zone_1")
    controller.close_valve("zone_1")
    controller.close_all()
"""

import logging
from typing import Dict, Set

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


class ValveController:
    """
    Controls irrigation valves via Raspberry Pi GPIO pins.

    Args:
        zone_pins: Mapping of zone_id to BCM GPIO pin number.
        active_low: If True (default), the relay triggers on LOW
                    (HW-482 and most optocoupled modules). If False,
                    the relay triggers on HIGH.
    """

    def __init__(self, zone_pins: Dict[str, int], active_low: bool = True):
        self.zone_pins = zone_pins
        self.active_low = active_low
        self._logger = logging.getLogger('valves')
        self._open_valves: Set[str] = set()

        if not GPIO_AVAILABLE:
            self._logger.warning(
                "RPi.GPIO not available - valve control will be simulated. "
                "Install with: pip install RPi.GPIO (only works on Raspberry Pi)"
            )
            return

        # Determine GPIO states based on relay type
        # For active-LOW:  idle = HIGH (relay off), trigger = LOW (relay on)
        # For active-HIGH: idle = LOW  (relay off), trigger = HIGH (relay on)
        self._state_on = GPIO.LOW if active_low else GPIO.HIGH
        self._state_off = GPIO.HIGH if active_low else GPIO.LOW

        relay_type = "active-LOW (HW-482)" if active_low else "active-HIGH"
        self._logger.info(f"Relay mode: {relay_type}")

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for zone_id, pin in zone_pins.items():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, self._state_off)  # Start with all valves closed
                self._logger.debug(f"GPIO pin {pin} configured for {zone_id}")
            self._logger.info(f"Valve controller initialized for {len(zone_pins)} zones")
        except Exception as e:
            self._logger.error(f"GPIO initialization failed: {e}")

    def open_valve(self, zone_id: str) -> bool:
        if zone_id not in self.zone_pins:
            self._logger.error(f"Unknown zone: {zone_id}")
            return False
        pin = self.zone_pins[zone_id]
        self._logger.info(f"Opening valve for {zone_id} (GPIO {pin})")
        if GPIO_AVAILABLE:
            try:
                GPIO.output(pin, self._state_on)
            except Exception as e:
                self._logger.error(f"Failed to open valve: {e}")
                return False
        self._open_valves.add(zone_id)
        return True

    def close_valve(self, zone_id: str) -> bool:
        if zone_id not in self.zone_pins:
            self._logger.error(f"Unknown zone: {zone_id}")
            return False
        pin = self.zone_pins[zone_id]
        self._logger.info(f"Closing valve for {zone_id} (GPIO {pin})")
        if GPIO_AVAILABLE:
            try:
                GPIO.output(pin, self._state_off)
            except Exception as e:
                self._logger.error(f"Failed to close valve: {e}")
                return False
        self._open_valves.discard(zone_id)
        return True

    def close_all(self):
        self._logger.warning("CLOSING ALL VALVES")
        for zone_id in list(self.zone_pins.keys()):
            self.close_valve(zone_id)

    def get_open_valves(self) -> Set[str]:
        return self._open_valves.copy()

    def is_open(self, zone_id: str) -> bool:
        return zone_id in self._open_valves

    def cleanup(self):
        self._logger.info("Cleaning up valve controller")
        self.close_all()
        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup()
            except Exception as e:
                self._logger.error(f"GPIO cleanup error: {e}")


class MockValveController(ValveController):
    """Mock valve controller for testing without GPIO hardware."""

    def __init__(self, zone_pins: Dict[str, int], active_low: bool = True):
        self.zone_pins = zone_pins
        self.active_low = active_low
        self._logger = logging.getLogger('valves')
        self._open_valves: Set[str] = set()
        self._logger.info(f"[MOCK] Valve controller initialized for {len(zone_pins)} zones")

    def open_valve(self, zone_id: str) -> bool:
        if zone_id not in self.zone_pins:
            self._logger.error(f"Unknown zone: {zone_id}")
            return False
        self._open_valves.add(zone_id)
        self._logger.info(f"[MOCK] Opened valve: {zone_id}")
        return True

    def close_valve(self, zone_id: str) -> bool:
        if zone_id not in self.zone_pins:
            self._logger.error(f"Unknown zone: {zone_id}")
            return False
        self._open_valves.discard(zone_id)
        self._logger.info(f"[MOCK] Closed valve: {zone_id}")
        return True

    def cleanup(self):
        self._logger.info("[MOCK] Cleaning up valve controller")
        self.close_all()


def create_valve_controller(
    zone_pins: Dict[str, int],
    use_mock: bool = False,
    active_low: bool = True
) -> ValveController:
    """
    Create appropriate valve controller based on environment.

    Args:
        zone_pins: Mapping of zone_id to BCM GPIO pin number.
        use_mock: Force mock controller (for testing).
        active_low: If True, relay triggers on LOW (HW-482 default).
    """
    if use_mock or not GPIO_AVAILABLE:
        return MockValveController(zone_pins, active_low=active_low)
    return ValveController(zone_pins, active_low=active_low)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    print("Valve Controller Test")
    print("=" * 50)
    zone_pins = {"zone_1": 17, "zone_2": 18}
    controller = create_valve_controller(zone_pins, use_mock=True, active_low=True)
    print(f"Relay mode: active-LOW (HW-482)")
    controller.open_valve("zone_1")
    controller.open_valve("zone_2")
    print(f"Open valves: {controller.get_open_valves()}")
    controller.close_valve("zone_1")
    print(f"Open valves: {controller.get_open_valves()}")
    controller.close_all()
    controller.cleanup()
    print("\n✓ Valve controller working correctly")
