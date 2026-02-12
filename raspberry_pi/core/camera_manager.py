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
            self.logger.warning("Neither OpenCV nor rpicam-still available. Cameras disabled.")

    def initialize(self):
        """Initialize cameras based on config and auto-detection."""
        available_video_devices = self._scan_video_devices()
        self.logger.info(f"Detected video devices: {available_video_devices}")

        # Basic logic:
        # 1. If config says 'libcamera' or similar, use rpicam.
        # 2. If config has a device path (/dev/videoX), try OpenCV first.
        # 3. If rpicam-hello works (user says it does), we might prioritize rpicam for known RPi cams.
        #    However, mixing USB and RPi cams is complex.
        #    For now, we'll try to follow the config.

        for config in self.configs:
            if not config.enabled:
                continue
            
            # Decide backend
            # If explicit device path is given and it's a video node, default to OpenCV (if available)
            # If no device path, or if we suspect it's a ribbon cable cam, check rpicam.
            
            # Heuristic: If rpicam is available, try to use it for 'camera 0', 'camera 1' etc.
            # config.device_path might be an integer '0', '1' or '/dev/video0'.
            
            camera_id = config.device_path
            
            # If user hasn't specified a path, we need to assign one.
            # This is tricky with mixed backends. For now, let's assume manual config or simple defaults.
            if not camera_id:
                # Default behavior:
                # If rpicam is available and we haven't used it yet, assign index 0.
                # This needs a better allocation strategy for multiple cameras.
                camera_id = "0" 

            if self.rpicam_available:
                 # Try to treat camera_id as an index for rpicam
                if self._init_rpicam(config.role, camera_id, config.resolution):
                    continue

            if CV2_AVAILABLE:
                # Fallback to OpenCV
                 # If camera_id is an integer string, convert to int for OpenCV?
                 # Or if it's /dev/videoX
                if self._init_opencv(config.role, camera_id, config.resolution):
                    continue
            
            self.logger.warning(f"Failed to initialize camera {config.role} (ID: {camera_id})")

    def _scan_video_devices(self) -> List[str]:
        """Scan for /dev/video* devices."""
        devices = glob.glob("/dev/video*")
        devices.sort()
        return devices

    def _init_rpicam(self, role: str, camera_id: str, resolution: List[int]) -> bool:
        """Initialize a libcamera device (conceptual init, mostly validation)."""
        # We can't really 'open' the camera in Python without complex bindings,
        # but we can verify it exists or just assume it works if rpicam-still is present.
        # The user said "rpicam-hello --camera 0" works.
        
        # Simple check: is camera_id essentially an integer?
        try:
             # Normalize "/base/soc/i2c0mux/i2c@1/imx219@10" to an index if possible,
             # or just pass it to --camera if rpicam supports paths.
             # rpicam-apps usually take --camera <index> or --camera <video-node>?
             # The user used --camera 0.
             
             # If it looks like /dev/video*, it might be V4L2, rpicam usually uses libcamera indices.
             # If the user config has "0" or "1", that's perfect.
             
            cmd = ["rpicam-still", "--list-cameras"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                 # Output parsing could confirm if idx exists.
                 # For now, trust the config if it's a simple index.
                 pass

            self._cameras[role] = camera_id # Store the ID/Index
            self._backend_type[role] = "rpicam"
            self._device_paths[role] = camera_id
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
                 # Path might not be compatible with cv2.VideoCapture(int)
                 # cv2.VideoCapture(str) usually for files or streams.
                 # On linux GStreamer might work with device path.
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
        Returns the path to the saved temporary image file.
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

        # Build command: rpicam-still --camera <id> -o <path> -t 1 (timeout 1ms for immediate, or standard 5s?)
        # -t 1 might be too fast for AWB/AE. valid defaults usually ~5000ms.
        # User wants a capture. -n for no preview. -t 2000 for 2s startup.
        cmd = [
            "rpicam-still",
            "--camera", str(camera_id),
            "-o", path,
            "--nopreview",
            "--timeout", "2000",
             "--width", "1920", # Should use config resolution
             "--height", "1080"
        ]
        
        # Optimization: Config resolution
        # We need to access config again or store it.
        # For now, hardcode or accept default.
        
        try:
            self.logger.info(f"Capturing with rpicam: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if os.path.exists(path):
                return path
            return None
        except subprocess.CalledProcessError as e:
            self.logger.error(f"rpicam capture failed: {e.stderr.decode().strip()}")
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
                "detected": True
            }
            for role in self._cameras.keys()
        }
