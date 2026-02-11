import logging
import time
import os
import glob
from typing import Dict, Optional, List, Any
from ..config.models import CameraConfig


# Try importing OpenCV
try:
    import cv2

    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


class CameraManager:
    """
    Manages camera devices.
    - Enumerates /dev/video* devices.
    - validation of cameras.
    - Captures images.
    """

    def __init__(self, configs: List[CameraConfig]):
        self.configs = configs
        self.logger = logging.getLogger("camera_manager")
        self._cameras: Dict[str, cv2.VideoCapture] = {}  # role -> VideoCapture
        self._device_paths: Dict[str, str] = {}  # role -> /dev/videoX

        if not CV2_AVAILABLE:
            self.logger.warning("OpenCV not available. Camera functionality disabled.")

    def initialize(self):
        """Initialize cameras based on config and auto-detection."""
        if not CV2_AVAILABLE:
            return

        available_devices = self._scan_devices()
        self.logger.info(f"detected video devices: {available_devices}")

        used_devices = set()

        for config in self.configs:
            if not config.enabled:
                continue

            device_path = config.device_path

            # Auto-assign if not specified
            if not device_path:
                for dev in available_devices:
                    if dev not in used_devices:
                        device_path = dev
                        break

            if device_path:
                if self._init_camera(config.role, device_path, config.resolution):
                    used_devices.add(device_path)
            else:
                self.logger.warning(f"No available device found for role {config.role}")

    def _scan_devices(self) -> List[str]:
        """Scan for /dev/video* devices."""
        devices = glob.glob("/dev/video*")
        # Sort to prioritize video0, video1
        devices.sort()
        return devices

    def _init_camera(self, role: str, device_path: str, resolution: List[int]) -> bool:
        """Initialize a specific camera."""
        try:
            # OpenCV index is usually the integer X from /dev/videoX
            index = int(device_path.replace("/dev/video", ""))

            cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            if not cap.isOpened():
                self.logger.error(f"Failed to open camera {device_path} for {role}")
                return False

            # Set resolution
            width, height = resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

            # Validate read
            ret, frame = cap.read()
            if not ret:
                self.logger.error(f"Failed to read frame from {device_path} for {role}")
                cap.release()
                return False

            self._cameras[role] = cap
            self._device_paths[role] = device_path
            self.logger.info(
                f"Camera {role} initialized on {device_path} ({width}x{height})"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error initializing camera {device_path}: {e}")
            return False

    def capture_image(self, role: str) -> Optional[str]:
        """
        Capture an image from the specified camera role.
        Returns the path to the saved temporary image file.
        """
        if role not in self._cameras:
            self.logger.warning(f"Camera role {role} not available")
            return None

        cap = self._cameras[role]
        if not cap.isOpened():
            # Try re-init?
            return None

        # Flush buffer (grab a few frames)
        for _ in range(5):
            cap.grab()

        ret, frame = cap.read()
        if ret:
            timestamp = int(time.time())
            filename = f"capture_{role}_{timestamp}.jpg"
            # Ensure images dir exists
            os.makedirs("data/images", exist_ok=True)
            path = os.path.join("data/images", filename)
            cv2.imwrite(path, frame)
            return path
        else:
            self.logger.error(f"Failed to capture from {role}")
            return None

    def release(self):
        """Release all cameras."""
        for role, cap in self._cameras.items():
            cap.release()
        self._cameras.clear()
        self.logger.info("Cameras released")

    def get_status(self) -> Dict[str, Any]:
        return {
            role: {"device": self._device_paths.get(role, "unknown"), "detected": True}
            for role in self._cameras.keys()
        }
