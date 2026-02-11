import uuid
import logging
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


class DeviceProvisioner:
    """
    Handles the bootstrapping workflow for a new device.
    Fulfills Section 2.1 of the Technical Manual.
    """

    def __init__(self, server_ip: str, server_port: int = 8000):
        self.server_ip = server_ip
        self.server_port = server_port
        self.url = f"http://{server_ip}:{server_port}/api/v1/devices/provision"
        self.logger = logging.getLogger("provisioner")

    def get_hardware_id(self) -> str:
        """
        Returns a unique hardware ID for this device (MAC address).
        """
        # Format MAC address from uuid.getnode()
        mac = ":".join(
            ["{:02x}".format((uuid.getnode() >> i) & 0xFF) for i in range(0, 48, 8)][
                ::-1
            ]
        )
        return mac

    def provision(self, capabilities: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Sends a provisioning request to the server.
        """
        payload = {
            "hardwareId": self.get_hardware_id(),
            "firmware": "1.0.0",  # Could be read from a file
            "capabilities": capabilities,
        }

        self.logger.info(f"Sending provisioning request to {self.url}")
        self.logger.debug(f"Payload: {payload}")

        try:
            response = requests.post(self.url, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()
            self.logger.info("Provisioning successful")
            return data

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Provisioning failed: {e}")
            if hasattr(e, "response") and e.response is not None:
                self.logger.error(f"Server response: {e.response.text}")
            return None


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.DEBUG)
    # Using a dummy server IP for the local test
    p = DeviceProvisioner("127.0.0.1")
    print(f"Hardware ID: {p.get_hardware_id()}")

    # Example capabilities matching main_controller.py DEFAULT_CONFIG
    caps = {
        "sensors": [{"localName": "zone_1", "type": "humidity"}],
        "cameras": ["main_view"],
    }
    # This will fail unless a server is running, which is expected for a standalone test run
    # p.provision(caps)
