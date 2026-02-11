"""
Image Sender Module
===================
Handles multipart image uploads to the Smart Irrigation API.

Endpoint: POST /api/v1/external-devices/{device_id}/images

Fulfills Section 3.2 of the Technical Manual.
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any


class ImageSender:
    """
    Sends captured images to the dashboard server using multipart/form-data.
    """

    def __init__(
        self,
        device_id: str,
        server_ip: Optional[str] = None,
        server_port: int = 8000,
        timeout: int = 15,  # Images need more time
    ):
        self.device_id = device_id
        self.server_ip = server_ip or os.getenv("DASHBOARD_SERVER_IP", "127.0.0.1")
        self.server_port = server_port
        self.timeout = timeout
        self.url = f"http://{self.server_ip}:{self.server_port}/api/v1/external-devices/{self.device_id}/images"
        self.logger = logging.getLogger("image_sender")

    def upload_image(
        self,
        image_path: str,
        image_type: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Uploads an image file to the server.
        """
        if not os.path.exists(image_path):
            self.logger.error(f"Image file not found: {image_path}")
            return False

        try:
            with open(image_path, "rb") as f:
                files = {"image_file": (os.path.basename(image_path), f, "image/jpeg")}
                data = {
                    "image_type": image_type,
                    "captured_at": datetime.now().isoformat(),
                }
                if metadata:
                    data["metadata_json"] = json.dumps(metadata)

                self.logger.info(f"Uploading image {image_path} to {self.url}")
                response = requests.post(
                    self.url, files=files, data=data, timeout=self.timeout
                )
                response.raise_for_status()
                self.logger.info("Image upload successful")
                return True

        except Exception as e:
            self.logger.error(f"Image upload failed: {e}")
            return False


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.DEBUG)
    # sender = ImageSender(device_id="mock-id")
    # sender.upload_image("test_image.jpg", image_type="plant")
