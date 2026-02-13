import pytest
from unittest.mock import MagicMock, patch
import numpy as np

# Mock dependencies before import
mock_picamera = MagicMock()
mock_cv2 = MagicMock()
mock_cv2.COLOR_RGB2BGR = 1
mock_cv2.COLOR_BGR2HSV = 2
mock_cv2.MORPH_ELLIPSE = 3
mock_cv2.MORPH_OPEN = 4
mock_cv2.MORPH_CLOSE = 5
mock_cv2.RETR_EXTERNAL = 6
mock_cv2.CHAIN_APPROX_SIMPLE = 7

with patch.dict(
    "sys.modules", {"picamera2": mock_picamera, "cv2": mock_cv2, "numpy": np}
):
    from raspberry_pi.sensors.tank_sensor import get_tank_level, cleanup


def test_tank_sensor_no_camera():
    # Simulate import error
    with patch("raspberry_pi.sensors.tank_sensor.CAMERA_AVAILABLE", False):
        level = get_tank_level()
        assert level == 0.0


@patch("raspberry_pi.sensors.tank_sensor.CAMERA_AVAILABLE", True)
@patch("raspberry_pi.sensors.tank_sensor._picam2")
@patch("raspberry_pi.sensors.tank_sensor.cv2")
def test_tank_sensor_reading(mock_cv_local, mock_picam_instance):
    # Setup mock image capture
    mock_picam_instance.capture_array.return_value = np.zeros(
        (100, 100, 3), dtype=np.uint8
    )

    # Mock cv2 functions to return a detection
    # contourArea, momnets, boundingrect
    mock_cv_local.cvtColor.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_cv_local.inRange.return_value = np.ones((100, 100), dtype=np.uint8)
    mock_cv_local.getStructuringElement.return_value = np.ones((3, 3), dtype=np.uint8)
    mock_cv_local.morphologyEx.return_value = np.ones((100, 100), dtype=np.uint8)

    # Return one dummy contour
    mock_contour = MagicMock()
    mock_cv_local.findContours.return_value = ([mock_contour], None)
    mock_cv_local.contourArea.return_value = 1000.0  # Big enough

    # Moments for centroid
    mock_cv_local.moments.return_value = {
        "m00": 1000.0,
        "m10": 50000.0,
        "m01": 400000.0,
    }  # cy = 400

    # Bounding rect (x, y, w, h)
    mock_cv_local.boundingRect.return_value = (50, 400, 20, 20)

    # We need to ensure _Y_EMPTY and _Y_FULL are set defaults or we patch them
    # By default _Y_EMPTY=600, _Y_FULL=200
    # cy=400 is midpoint -> 50%
    # 50L capacity -> 25L

    level = get_tank_level()

    # First reading might just be stored in history, need loop to stabilize or check if returns immediately
    # Code says: if _last_cy is None ... _cy_hist.append(cy) ... if len > 0 ... return liters

    assert level > 20.0 and level < 30.0

    cleanup()
