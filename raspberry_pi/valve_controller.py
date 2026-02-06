"""
Valve Controller Module
=======================
Controls irrigation valves via Raspberry Pi GPIO.

This module contains:
- ValveController: Real GPIO-based valve control
- MockValveController: For testing without hardware

Usage:
    from valve_controller import ValveController, MockValveController
    
    # For production (on Raspberry Pi)
    controller = ValveController(zone_pins={"zone_1": 17, "zone_2": 18})
    
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
    """Controls irrigation valves via Raspberry Pi GPIO pins."""
    
    def __init__(self, zone_pins: Dict[str, int]):
        self.zone_pins = zone_pins
        self._logger = logging.getLogger('valves')
        self._open_valves: Set[str] = set()
        
        if not GPIO_AVAILABLE:
            self._logger.warning(
                "RPi.GPIO not available - valve control will be simulated. "
                "Install with: pip install RPi.GPIO (only works on Raspberry Pi)"
            )
            return
        
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for zone_id, pin in zone_pins.items():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
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
                GPIO.output(pin, GPIO.HIGH)
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
                GPIO.output(pin, GPIO.LOW)
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
    
    def __init__(self, zone_pins: Dict[str, int]):
        self.zone_pins = zone_pins
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


def create_valve_controller(zone_pins: Dict[str, int], use_mock: bool = False) -> ValveController:
    """Create appropriate valve controller based on environment."""
    if use_mock or not GPIO_AVAILABLE:
        return MockValveController(zone_pins)
    return ValveController(zone_pins)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    print("Valve Controller Test")
    print("=" * 50)
    zone_pins = {"zone_1": 17, "zone_2": 18, "zone_3": 27}
    controller = create_valve_controller(zone_pins, use_mock=True)
    controller.open_valve("zone_1")
    controller.open_valve("zone_2")
    print(f"Open valves: {controller.get_open_valves()}")
    controller.close_valve("zone_1")
    print(f"Open valves: {controller.get_open_valves()}")
    controller.close_all()
    controller.cleanup()
    print("\n✓ Valve controller working correctly")
