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

# Try to import GPIO - will fail on non-Pi systems
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


# =============================================================================
# REAL VALVE CONTROLLER (GPIO)
# =============================================================================

class ValveController:
    """
    Controls irrigation valves via Raspberry Pi GPIO pins.
    
    Each zone has a solenoid valve connected via a relay module.
    GPIO HIGH = valve open, GPIO LOW = valve closed.
    """
    
    def __init__(self, zone_pins: Dict[str, int]):
        """
        Initialize valve controller.
        
        Args:
            zone_pins: Dict mapping zone_id to GPIO pin number
                       e.g., {"zone_1": 17, "zone_2": 18}
        """
        self.zone_pins = zone_pins
        self._logger = logging.getLogger('valves')
        self._open_valves: Set[str] = set()
        
        if not GPIO_AVAILABLE:
            self._logger.warning(
                "RPi.GPIO not available - valve control will be simulated. "
                "Install with: pip install RPi.GPIO (only works on Raspberry Pi)"
            )
            return
        
        # Initialize GPIO
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            for zone_id, pin in zone_pins.items():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)  # Start with all valves closed
                self._logger.debug(f"GPIO pin {pin} configured for {zone_id}")
            
            self._logger.info(f"Valve controller initialized for {len(zone_pins)} zones")
            
        except Exception as e:
            self._logger.error(f"GPIO initialization failed: {e}")
    
    def open_valve(self, zone_id: str) -> bool:
        """
        Open valve for a zone.
        
        Args:
            zone_id: Zone identifier
            
        Returns:
            True if successful, False otherwise
        """
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
        """
        Close valve for a zone.
        
        Args:
            zone_id: Zone identifier
            
        Returns:
            True if successful, False otherwise
        """
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
        """Emergency close all valves."""
        self._logger.warning("CLOSING ALL VALVES")
        
        for zone_id in list(self.zone_pins.keys()):
            self.close_valve(zone_id)
    
    def get_open_valves(self) -> Set[str]:
        """Get set of currently open valves."""
        return self._open_valves.copy()
    
    def is_open(self, zone_id: str) -> bool:
        """Check if a specific valve is open."""
        return zone_id in self._open_valves
    
    def cleanup(self):
        """Clean up GPIO on shutdown."""
        self._logger.info("Cleaning up valve controller")
        self.close_all()
        
        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup()
            except Exception as e:
                self._logger.error(f"GPIO cleanup error: {e}")


# =============================================================================
# MOCK VALVE CONTROLLER (For Testing)
# =============================================================================

class MockValveController(ValveController):
    """
    Mock valve controller for testing without GPIO hardware.
    
    Behaves identically to ValveController but doesn't touch GPIO.
    Useful for development on non-Pi machines and for demo mode.
    """
    
    def __init__(self, zone_pins: Dict[str, int]):
        """
        Initialize mock valve controller.
        
        Args:
            zone_pins: Dict mapping zone_id to GPIO pin number
        """
        self.zone_pins = zone_pins
        self._logger = logging.getLogger('valves')
        self._open_valves: Set[str] = set()
        
        self._logger.info(f"[MOCK] Valve controller initialized for {len(zone_pins)} zones")
    
    def open_valve(self, zone_id: str) -> bool:
        """Open valve (mock - just logs and tracks state)."""
        if zone_id not in self.zone_pins:
            self._logger.error(f"Unknown zone: {zone_id}")
            return False
        
        self._open_valves.add(zone_id)
        self._logger.info(f"[MOCK] Opened valve: {zone_id}")
        return True
    
    def close_valve(self, zone_id: str) -> bool:
        """Close valve (mock - just logs and tracks state)."""
        if zone_id not in self.zone_pins:
            self._logger.error(f"Unknown zone: {zone_id}")
            return False
        
        self._open_valves.discard(zone_id)
        self._logger.info(f"[MOCK] Closed valve: {zone_id}")
        return True
    
    def cleanup(self):
        """Clean up (mock - just closes all valves)."""
        self._logger.info("[MOCK] Cleaning up valve controller")
        self.close_all()


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_valve_controller(
    zone_pins: Dict[str, int],
    use_mock: bool = False
) -> ValveController:
    """
    Create appropriate valve controller based on environment.
    
    Args:
        zone_pins: Dict mapping zone_id to GPIO pin number
        use_mock: Force mock controller even if GPIO available
        
    Returns:
        ValveController or MockValveController instance
    """
    if use_mock or not GPIO_AVAILABLE:
        return MockValveController(zone_pins)
    return ValveController(zone_pins)


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    print("Valve Controller Test")
    print("=" * 50)
    print(f"GPIO Available: {GPIO_AVAILABLE}")
    
    # Test with mock controller
    zone_pins = {
        "zone_1": 17,
        "zone_2": 18,
        "zone_3": 27
    }
    
    controller = create_valve_controller(zone_pins, use_mock=True)
    
    print("\n--- Opening valves ---")
    controller.open_valve("zone_1")
    controller.open_valve("zone_2")
    print(f"Open valves: {controller.get_open_valves()}")
    
    print("\n--- Closing zone_1 ---")
    controller.close_valve("zone_1")
    print(f"Open valves: {controller.get_open_valves()}")
    
    print("\n--- Emergency close all ---")
    controller.close_all()
    print(f"Open valves: {controller.get_open_valves()}")
    
    print("\n--- Cleanup ---")
    controller.cleanup()
    
    print("\n✓ Valve controller working correctly")
