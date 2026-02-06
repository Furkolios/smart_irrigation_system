"""
Tank Sensor Module
==================
Module for reading water tank level using camera-based floater detection.
Uses red floater detection and calibrated boundaries to determine water level.

Usage:
    from tank_sensor import get_tank_level
    level = get_tank_level()  # Returns liters (0-50)
"""

import json
from collections import deque

# Camera/CV dependencies — only available on Raspberry Pi with camera
try:
    import cv2
    import numpy as np
    from picamera2 import Picamera2
    import time
    CAMERA_AVAILABLE = True
except ImportError:
    CAMERA_AVAILABLE = False

# -----------------------
# CONFIGURATION
# -----------------------
TANK_CAPACITY_LITERS = 50.0

# HSV thresholds for red floater
LOWER_RED = None
UPPER_RED = None

# Detection parameters
MIN_AREA = 50
KERNEL_SIZE = 7
HISTORY_N = 15
MAX_JUMP = 50
RESIZE_FACTOR = 1.0

# Global variables for camera and calibration
_picam2 = None
_ROI = None
_Y_EMPTY = 600.0
_Y_FULL = 200.0
_cy_hist = None
_last_cy = None

if CAMERA_AVAILABLE:
    LOWER_RED = np.array([100, 120, 70])
    UPPER_RED = np.array([125, 255, 255])
    _cy_hist = deque(maxlen=HISTORY_N)


# -----------------------
# HELPER FUNCTIONS
# -----------------------

def _load_calibration():
    """Load calibration from file"""
    global _ROI, _Y_EMPTY, _Y_FULL
    try:
        with open('calibration.json', 'r') as f:
            config = json.load(f)
            _ROI = tuple(config['ROI']) if config['ROI'] else None
            _Y_EMPTY = config['Y_EMPTY']
            _Y_FULL = config['Y_FULL']
        return True
    except FileNotFoundError:
        print("Warning: No calibration file found. Using default values.")
        return False


def _clamp(x, a, b):
    return max(a, min(b, x))


def _compute_level_percent(cy, y_empty, y_full):
    denom = (y_empty - y_full)
    if abs(denom) < 1e-6:
        return None
    level = (y_empty - cy) / denom
    level = _clamp(level, 0.0, 1.0)
    return 100.0 * level


def _detect_red_floater(frame_bgr):
    """Detect red floater in frame"""
    if _ROI is not None:
        x0, y0, w, h = _ROI
        img = frame_bgr[y0:y0+h, x0:x0+w]
    else:
        x0, y0 = 0, 0
        img = frame_bgr

    if RESIZE_FACTOR != 1.0:
        img = cv2.resize(img, None, fx=RESIZE_FACTOR, fy=RESIZE_FACTOR)
        scale_back = 1.0 / RESIZE_FACTOR
    else:
        scale_back = 1.0

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOWER_RED, UPPER_RED)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (KERNEL_SIZE, KERNEL_SIZE))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_area = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < MIN_AREA * (RESIZE_FACTOR ** 2):
            continue
        if area > best_area:
            best_area = area
            best = c

    if best is None:
        return None

    M = cv2.moments(best)
    if M["m00"] == 0:
        return None

    cx = int((M["m10"] / M["m00"]) * scale_back) + x0
    cy = int((M["m01"] / M["m00"]) * scale_back) + y0

    x, y, w, h = cv2.boundingRect(best)
    bbox = (int(x * scale_back) + x0, int(y * scale_back) + y0,
            int(w * scale_back), int(h * scale_back))

    return (cx, cy, bbox, best_area / (RESIZE_FACTOR ** 2))


def _initialize_camera():
    """Initialize camera if not already started"""
    global _picam2
    if _picam2 is None:
        _load_calibration()
        _picam2 = Picamera2()
        config = _picam2.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
        _picam2.configure(config)
        _picam2.start()
        import time
        time.sleep(0.5)


# -----------------------
# PUBLIC API
# -----------------------

def get_tank_level() -> float:
    """
    Get current tank water level in liters.
    
    Returns:
        float: Water level in liters (0 to TANK_CAPACITY_LITERS).
               Returns 0.0 if camera is not available or floater cannot be detected.
    
    Note:
        Uses camera-based red floater detection with calibrated boundaries.
        First call initializes the camera (may take ~0.5 seconds).
        Returns 0.0 on systems without picamera2/cv2 (use mock_tank_level instead).
    """
    global _last_cy, _cy_hist

    if not CAMERA_AVAILABLE:
        return 0.0

    try:
        _initialize_camera()
        
        frame_rgb = _picam2.capture_array()
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        
        det = _detect_red_floater(frame)
        
        if det is None:
            return 0.0
        
        cx, cy, bbox, area = det
        
        if _last_cy is None or abs(cy - _last_cy) <= MAX_JUMP:
            _cy_hist.append(cy)
            _last_cy = cy
        
        if len(_cy_hist) > 0:
            cy_smooth = float(np.median(np.array(_cy_hist)))
            level_percent = _compute_level_percent(cy_smooth, _Y_EMPTY, _Y_FULL)
            
            if level_percent is not None:
                liters = (level_percent / 100.0) * TANK_CAPACITY_LITERS
                return liters
        
        return 0.0

    except Exception as e:
        print(f"Error reading tank level: {e}")
        return 0.0


def cleanup():
    """Stop the camera and cleanup resources."""
    global _picam2
    if _picam2 is not None:
        _picam2.stop()
        _picam2 = None
        print("Camera stopped")


if __name__ == "__main__":
    if not CAMERA_AVAILABLE:
        print("Camera not available — tank_sensor requires Raspberry Pi with picamera2 and cv2.")
        print("In --mock mode, use mock_tank_level parameter instead.")
    else:
        import time
        print("Tank Sensor Test")
        print("=" * 30)
        try:
            for i in range(5):
                level = get_tank_level()
                percent = (level / TANK_CAPACITY_LITERS) * 100
                print(f"  Reading {i+1}: {level:.1f} liters ({percent:.1f}%)")
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nTest interrupted")
        finally:
            cleanup()
            print("Done")
