import logging
import time
import os
import glob
import subprocess
import shutil
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
    Supports:
    - OpenCV (Legacy / USB cameras)
    - rpicam-apps (libcamera for new RPi cameras)
    """

    def __init__(self, configs: List[CameraConfig]):
        self.configs = configs
        self.logger = logging.getLogger("camera_manager")
        self._cameras: Dict[str, Any] = {}  # role -> backend object or identifier
        self._backend_type: Dict[str, str] = {}  # role -> 'opencv' or 'rpicam'
        self._device_paths: Dict[str, str] = {}  # role -> /dev/videoX or index

        # Check for rpicam-still availability
        self.rpicam_available = shutil.which("rpicam-still") is not None
        if not CV2_AVAILABLE and not self.rpicam_available:
            self.logger.warning(
                "Neither OpenCV nor rpicam-still available. Cameras disabled."
            )

    def initialize(self):
        """Initialize cameras based on config and auto-detection."""
        available_video_devices = self._scan_video_devices()
        self.logger.info(f"Detected video devices: {available_video_devices}")

        used_devices = set()

        for config in self.configs:
            if not config.enabled:
                continue

            camera_id = config.device_path

            # Auto-assign if not specified
            if not camera_id:
                if self.rpicam_available:
                    # Try to find an unused index (0, 1, 2...)
                    for i in range(10):
                        idx = str(i)
                        if idx not in used_devices:
                            camera_id = idx
                            break
                elif available_video_devices:
                    # Try to find an unused /dev/videoX
                    for dev in available_video_devices:
                        if dev not in used_devices:
                            camera_id = dev
                            break

            if not camera_id:
                self.logger.warning(f"No available device found for role {config.role}")
                continue

            # Try rpicam first if available
            if self.rpicam_available:
                if self._init_rpicam(config.role, camera_id, config.resolution):
                    used_devices.add(camera_id)
                    continue

            # Fallback to OpenCV
            if CV2_AVAILABLE:
                if self._init_opencv(config.role, camera_id, config.resolution):
                    used_devices.add(camera_id)
                    continue

            self.logger.warning(
                f"Failed to initialize camera {config.role} (ID: {camera_id})"
            )

    def _scan_video_devices(self) -> List[str]:
        """Scan for /dev/video* devices."""
        devices = glob.glob("/dev/video*")
        devices.sort()
        return devices

    def _init_rpicam(self, role: str, camera_id: str, resolution: List[int]) -> bool:
        """Initialize a libcamera device."""
        try:
            # We can use rpicam-still --list-cameras to check if ID exists
            # but for simplicity and since the user said it works, we'll trust it
            # if it's a digit.
            if not camera_id.isdigit() and not camera_id.startswith("/dev/video"):
                # rpicam-still usually takes index or video node
                return False

            self._cameras[role] = camera_id
            self._backend_type[role] = "rpicam"
            self._device_paths[role] = camera_id
            # Store resolution for capture
            if not hasattr(self, "_resolutions"):
                self._resolutions = {}
            self._resolutions[role] = resolution

            self.logger.info(f"Initialized rpicam for {role} (ID: {camera_id})")
            return True

        except Exception as e:
            self.logger.error(f"Error initializing rpicam for {role}: {e}")
            return False

    def _init_opencv(self, role: str, device_path: str, resolution: List[int]) -> bool:
        """Initialize a specific camera using OpenCV."""
        try:
            # OpenCV index is usually the integer X from /dev/videoX
            if device_path.startswith("/dev/video"):
                index = int(device_path.replace("/dev/video", ""))
            elif device_path.isdigit():
                index = int(device_path)
            else:
                return False

            cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            if not cap.isOpened():
                return False

            # Set resolution
            width, height = resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

            # Validate read
            ret, _ = cap.read()
            if not ret:
                cap.release()
                return False

            self._cameras[role] = cap
            self._backend_type[role] = "opencv"
            self._device_paths[role] = device_path
            self.logger.info(
                f"Camera {role} initialized on {device_path} ({width}x{height}) via OpenCV"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error initializing OpenCV camera {device_path}: {e}")
            return False

    def capture_image(self, role: str) -> Optional[str]:
        """
        Capture an image from the specified camera role.
        """
        if role not in self._cameras:
            self.logger.warning(f"Camera role {role} not available")
            return None

        backend = self._backend_type.get(role)
        if backend == "rpicam":
            return self._capture_rpicam(role)
        elif backend == "opencv":
            return self._capture_opencv(role)
        else:
            self.logger.error(f"Unknown backend {backend} for {role}")
            return None

    def _capture_rpicam(self, role: str) -> Optional[str]:
        camera_id = self._cameras[role]
        timestamp = int(time.time())
        filename = f"capture_{role}_{timestamp}.jpg"
        os.makedirs("data/images", exist_ok=True)
        path = os.path.join("data/images", filename)

        resolution = getattr(self, "_resolutions", {}).get(role, [1920, 1080])
        width, height = resolution

        cmd = [
            "rpicam-still",
            "--camera",
            str(camera_id),
            "-o",
            path,
            "--nopreview",
            "--timeout",
            "2000",
            "--width",
            str(width),
            "--height",
            str(height),
        ]

        try:
            self.logger.info(f"Capturing with rpicam: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and os.path.exists(path):
                return path
            else:
                self.logger.error(f"rpicam capture failed: {result.stderr}")
                return None
        except Exception as e:
            self.logger.error(f"rpicam capture exception: {e}")
            return None

    def _capture_opencv(self, role: str) -> Optional[str]:
        cap = self._cameras[role]
        if not cap.isOpened():
            return None

        # Flush buffer
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
        for role, backend in self._backend_type.items():
            if backend == "opencv":
                self._cameras[role].release()

        self._cameras.clear()
        self._backend_type.clear()
        self.logger.info("Cameras released")

    def get_status(self) -> Dict[str, Any]:
        return {
            role: {
                "device": self._device_paths.get(role, "unknown"),
                "backend": self._backend_type.get(role, "unknown"),
                "detected": True,
            }
            for role in self._cameras.keys()
        }
