"""
Tank Sensor Module
==================
Simple module for reading water tank level.

For the classroom demo, this returns a random value.
For production, implement actual ultrasonic sensor reading.

Usage:
    from tank_sensor import get_tank_level
    
    level = get_tank_level()  # Returns liters (0-50)
"""

import random

def get_tank_level() -> float:
    """
    Get current tank water level in liters.
    
    Returns:
        Random float between 0 and 50 liters.
        
    Note:
        For production, replace this with actual sensor reading
        (e.g., HC-SR04 ultrasonic sensor via GPIO).
    """
    return random.uniform(0, 50)

# =============================================================================
# FOR PRODUCTION: Implement actual sensor reading
# =============================================================================

if __name__ == "__main__":
    # Quick test
    print("Tank Sensor Test")
    print("=" * 30)
    for i in range(5):
        level = get_tank_level()
        print(f"  Reading {i+1}: {level:.1f} liters")
