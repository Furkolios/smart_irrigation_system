import cv2
import numpy as np
from collections import deque
from picamera2 import Picamera2
import time
import json
from datetime import datetime

# -----------------------
# TUNABLE SETTINGS
# -----------------------
ROI = None  # e.g. ROI = (200, 80, 800, 800)

# HSV thresholds for red
LOWER_RED = np.array([100, 120, 70])
UPPER_RED = np.array([125, 255, 255])

MIN_AREA = 50
KERNEL_SIZE = 7
HISTORY_N = 15
MAX_JUMP = 50

# Calibration values
Y_EMPTY = 600.0
Y_FULL = 200.0

# Performance settings
FRAME_SKIP = 0
RESIZE_FACTOR = 1.0

# Water level thresholds - SIMPLE!
LOW_WATER = 20.0      # Fill when below this
FULL_WATER = 70.0     # Stop filling at this

# Logging
LOG_FILE = "water_level.csv"

# -----------------------
# SIMPLE FUNCTIONS
# -----------------------

def save_calibration():
    config = {'ROI': ROI, 'Y_EMPTY': Y_EMPTY, 'Y_FULL': Y_FULL}
    with open('calibration.json', 'w') as f:
        json.dump(config, f)
    print("Calibration saved")

def load_calibration():
    global ROI, Y_EMPTY, Y_FULL
    try:
        with open('calibration.json', 'r') as f:
            config = json.load(f)
            ROI = tuple(config['ROI']) if config['ROI'] else None
            Y_EMPTY = config['Y_EMPTY']
            Y_FULL = config['Y_FULL']
        print(f"Calibration loaded: Y_FULL={Y_FULL}, Y_EMPTY={Y_EMPTY}")
        return True
    except FileNotFoundError:
        print("No calibration file found - please calibrate first")
        return False

def clamp(x, a, b):
    return max(a, min(b, x))

def compute_level_percent(cy, y_empty, y_full):
    denom = (y_empty - y_full)
    if abs(denom) < 1e-6:
        return None
    level = (y_empty - cy) / denom
    level = clamp(level, 0.0, 1.0)
    return 100.0 * level

def detect_red_floater(frame_bgr):
    if ROI is not None:
        x0, y0, w, h = ROI
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
        return None, mask
    
    M = cv2.moments(best)
    if M["m00"] == 0:
        return None, mask
    
    cx = int((M["m10"] / M["m00"]) * scale_back) + x0
    cy = int((M["m01"] / M["m00"]) * scale_back) + y0
    
    x, y, w, h = cv2.boundingRect(best)
    bbox = (int(x * scale_back) + x0, int(y * scale_back) + y0, 
            int(w * scale_back), int(h * scale_back))
    
    return (cx, cy, bbox, best_area / (RESIZE_FACTOR ** 2)), mask

# -----------------------
# CALIBRATION MODE
# -----------------------
def calibrate_mode():
    global Y_EMPTY, Y_FULL, ROI
    
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
    picam2.configure(config)
    picam2.start()
    
    print("\n" + "="*60)
    print("  CALIBRATION MODE")
    print("="*60)
    print("\n1. Select tank area (or press ESC to skip)")
    print("2. Position floater at FULL, click it")
    print("3. Position floater at EMPTY, click it")
    print("="*60 + "\n")
    
    time.sleep(1)
    
    # Step 1: ROI
    frame_rgb = picam2.capture_array()
    frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    
    roi_temp = cv2.selectROI("Select Tank Area", frame, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Select Tank Area")
    
    if roi_temp[2] > 0 and roi_temp[3] > 0:
        ROI = roi_temp
        print(f"✓ Tank area selected")
    else:
        ROI = None
        print("✓ Using full frame")
    
    # Step 2: FULL level
    print("\n[Step 2] Position floater at FULL level, then click it")
    full_y = None
    
    def click_full(event, x, y, flags, param):
        nonlocal full_y
        if event == cv2.EVENT_LBUTTONDOWN:
            full_y = y
            print(f"✓ FULL level set at Y={y}")
    
    cv2.namedWindow("Click at FULL Level")
    cv2.setMouseCallback("Click at FULL Level", click_full)
    
    while full_y is None:
        frame_rgb = picam2.capture_array()
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        det, _ = detect_red_floater(frame)
        
        display = frame.copy()
        
        if ROI is not None:
            x0, y0, w, h = ROI
            cv2.rectangle(display, (x0, y0), (x0+w, y0+h), (255, 255, 0), 2)
        
        if det:
            cx, cy, bbox, _ = det
            cv2.circle(display, (cx, cy), 10, (0, 255, 0), -1)
            cv2.putText(display, f"Y={cy}", (cx+20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
        
        cv2.putText(display, "Click at FULL water level", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,255,255), 2)
        if det:
            cv2.putText(display, "Or press SPACE", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
        
        cv2.imshow("Click at FULL Level", display)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' ') and det:
            full_y = cy
            print(f"✓ FULL level set at Y={cy}")
        elif key == ord('q'):
            cv2.destroyAllWindows()
            picam2.stop()
            return
    
    Y_FULL = float(full_y)
    time.sleep(0.5)
    
    # Step 3: EMPTY level
    print("\n[Step 3] Position floater at EMPTY level, then click it")
    empty_y = None
    
    def click_empty(event, x, y, flags, param):
        nonlocal empty_y
        if event == cv2.EVENT_LBUTTONDOWN:
            empty_y = y
            print(f"✓ EMPTY level set at Y={y}")
    
    cv2.destroyWindow("Click at FULL Level")
    cv2.namedWindow("Click at EMPTY Level")
    cv2.setMouseCallback("Click at EMPTY Level", click_empty)
    
    while empty_y is None:
        frame_rgb = picam2.capture_array()
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        det, _ = detect_red_floater(frame)
        
        display = frame.copy()
        
        if ROI is not None:
            x0, y0, w, h = ROI
            cv2.rectangle(display, (x0, y0), (x0+w, y0+h), (255, 255, 0), 2)
        
        cv2.line(display, (0, int(Y_FULL)), (display.shape[1], int(Y_FULL)), (0,255,255), 2)
        cv2.putText(display, "FULL", (10, int(Y_FULL)-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)
        
        if det:
            cx, cy, bbox, _ = det
            cv2.circle(display, (cx, cy), 10, (0, 0, 255), -1)
            cv2.putText(display, f"Y={cy}", (cx+20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
        
        cv2.putText(display, "Click at EMPTY water level", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 2)
        if det:
            cv2.putText(display, "Or press SPACE", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
        
        cv2.imshow("Click at EMPTY Level", display)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' ') and det:
            empty_y = cy
            print(f"✓ EMPTY level set at Y={cy}")
        elif key == ord('q'):
            cv2.destroyAllWindows()
            picam2.stop()
            return
    
    Y_EMPTY = float(empty_y)
    
    cv2.destroyAllWindows()
    picam2.stop()
    
    save_calibration()
    
    print("\n" + "="*60)
    print("  CALIBRATION COMPLETE!")
    print("="*60)
    print(f"Y_FULL:  {Y_FULL}")
    print(f"Y_EMPTY: {Y_EMPTY}")
    print("="*60 + "\n")

# -----------------------
# SIMPLE WATER LEVEL CLASS
# -----------------------
class WaterLevel:
    """Super simple water level reader"""
    
    def __init__(self):
        self.picam2 = None
        self.cy_hist = deque(maxlen=HISTORY_N)
        self.last_cy = None
        
    def start(self):
        """Start the camera"""
        load_calibration()
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
        self.picam2.configure(config)
        self.picam2.start()
        time.sleep(0.5)
        print("Camera started")
    
    def stop(self):
        """Stop the camera"""
        if self.picam2:
            self.picam2.stop()
            print("Camera stopped")
    
    def get_level(self):
        """
        Get current water level
        Returns: percentage (0-100) or None if not detected
        """
        if not self.picam2:
            print("ERROR: Camera not started. Call start() first")
            return None
        
        frame_rgb = self.picam2.capture_array()
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        det, _ = detect_red_floater(frame)
        
        if det is None:
            return None
        
        cx, cy, bbox, area = det
        
        # Smooth the reading
        if self.last_cy is None or abs(cy - self.last_cy) <= MAX_JUMP:
            self.cy_hist.append(cy)
            self.last_cy = cy
        
        if len(self.cy_hist) > 0:
            cy_smooth = float(np.median(np.array(self.cy_hist)))
            level = compute_level_percent(cy_smooth, Y_EMPTY, Y_FULL)
            return level
        
        return None
    
    def need_water(self):
        """
        Simple question: Do we need to add water?
        Returns: True if water needed, False otherwise
        """
        level = self.get_level()
        if level is None:
            return False  # Can't decide without detection
        return level < LOW_WATER
    
    def is_full(self):
        """
        Simple question: Is tank full enough?
        Returns: True if tank is full enough, False otherwise
        """
        level = self.get_level()
        if level is None:
            return False
        return level >= FULL_WATER

# -----------------------
# SIMPLE USAGE EXAMPLES
# -----------------------
def example_simple():
    """Simplest possible usage"""
    print("\n=== SIMPLE EXAMPLE ===\n")
    
    water = WaterLevel()
    water.start()
    
    # Just get the level
    level = water.get_level()
    
    if level is None:
        print("Cannot detect water level")
    else:
        print(f"Water level: {level:.1f}%")
        
        # Make a decision
        if water.need_water():
            print("→ ACTION: Fill water!")
        else:
            print("→ Water level OK")
    
    water.stop()

def example_loop():
    """Check water every 10 seconds"""
    print("\n=== MONITORING LOOP ===")
    print("Checking every 10 seconds. Press Ctrl+C to stop\n")
    
    water = WaterLevel()
    water.start()
    
    try:
        while True:
            level = water.get_level()
            
            if level is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  No detection")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Water: {level:.1f}%", end="")
                
                if water.need_water():
                    print(" → FILL NEEDED")
                    # activate_pump()  # Your pump code here
                else:
                    print(" → OK")
            
            time.sleep(10)
    
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        water.stop()

def example_fill_tank():
    """Example: Fill tank until full"""
    print("\n=== FILL TANK EXAMPLE ===\n")
    
    water = WaterLevel()
    water.start()
    
    try:
        if not water.need_water():
            print("Tank is already full enough")
            water.stop()
            return
        
        print("Starting fill...")
        # activate_pump()  # Turn on your pump
        
        while not water.is_full():
            level = water.get_level()
            if level:
                print(f"Filling... {level:.1f}%")
            time.sleep(2)
        
        print("Tank is full!")
        # deactivate_pump()  # Turn off your pump
    
    finally:
        water.stop()

# -----------------------
# MAIN WITH GUI
# -----------------------
def main():
    """Main function with visual display"""
    if not load_calibration():
        print("\nPlease run calibration first:")
        print("  python script.py calibrate")
        return
    
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
    picam2.configure(config)
    picam2.start()
    
    cy_hist = deque(maxlen=HISTORY_N)
    last_cy = None
    
    print("\n=== Water Level Monitor ===")
    print("Q - Quit")
    print("C - Calibrate")
    print("============================\n")
    
    try:
        while True:
            frame_rgb = picam2.capture_array()
            frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            
            det, mask = detect_red_floater(frame)
            level = None
            
            # Draw reference lines
            cv2.line(frame, (0, int(Y_FULL)), (frame.shape[1], int(Y_FULL)), (0,255,255), 1)
            cv2.putText(frame, "FULL", (5, int(Y_FULL)-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 1)
            cv2.line(frame, (0, int(Y_EMPTY)), (frame.shape[1], int(Y_EMPTY)), (0,0,255), 1)
            cv2.putText(frame, "EMPTY", (5, int(Y_EMPTY)+15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
            
            if det is not None:
                cx, cy, bbox, area = det
                x, y, bw, bh = bbox
                
                if last_cy is None or abs(cy - last_cy) <= MAX_JUMP:
                    cy_hist.append(cy)
                    last_cy = cy
                
                if len(cy_hist) > 0:
                    cy_smooth = float(np.median(np.array(cy_hist)))
                    level = compute_level_percent(cy_smooth, Y_EMPTY, Y_FULL)
                    
                    cv2.rectangle(frame, (x, y), (x+bw, y+bh), (0,255,0), 2)
                    cv2.circle(frame, (cx, int(cy_smooth)), 6, (0,255,0), -1)
            
            # Display level
            if level is not None:
                if level < LOW_WATER:
                    color = (0, 0, 255)  # Red
                    msg = "FILL NEEDED"
                elif level >= FULL_WATER:
                    color = (0, 255, 0)  # Green
                    msg = "FULL"
                else:
                    color = (0, 255, 255)  # Yellow
                    msg = "OK"
                
                cv2.putText(frame, f"{level:.1f}%", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 2.0, color, 3)
                cv2.putText(frame, msg, (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
            else:
                cv2.putText(frame, "NO DETECTION", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,0,255), 3)
            
            cv2.imshow("Water Level", frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord('q')):
                break
            elif key == ord('c'):
                cv2.destroyAllWindows()
                picam2.stop()
                calibrate_mode()
                picam2.start()
    
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        cv2.destroyAllWindows()
        picam2.stop()

# -----------------------
# RUN
# -----------------------
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'calibrate':
            calibrate_mode()
        
        elif cmd == 'simple':
            example_simple()
        
        elif cmd == 'loop':
            example_loop()
        
        elif cmd == 'fill':
            example_fill_tank()
        
        else:
            print("Commands:")
            print("  python script.py calibrate  # Setup")
            print("  python script.py simple     # Check level once")
            print("  python script.py loop       # Monitor continuously")
            print("  python script.py fill       # Fill tank example")
            print("  python script.py            # GUI mode")
    else:
        main()