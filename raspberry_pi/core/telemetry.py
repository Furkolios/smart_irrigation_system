import json
import logging
import os
import requests
from queue import Queue, Empty
from threading import Thread
from typing import Dict, Any
from datetime import datetime

from ..config.models import ServerConfig


class TelemetryManager:
    """
    Manages sending telemetry, logs, and heartbeats to the server.
    Implements a store-and-forward mechanism for offline resilience.
    """

    def __init__(self, config: ServerConfig):
        self.config = config
        self.logger = logging.getLogger("telemetry")

        # In-memory queue for immediate sending
        self.queue = Queue()
        self._running = False
        self._worker_thread = None

        # Local storage for failed messages
        self.backlog_file = "data/telemetry_backlog.jsonl"
        os.makedirs(os.path.dirname(self.backlog_file), exist_ok=True)

        if self.config.enabled:
            self.start()

    def start(self):
        self._running = True
        self._worker_thread = Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        self.logger.info("Telemetry Manager started")

    def stop(self):
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)

    def send_telemetry(self, sensor_data: Dict[str, Any]):
        """Queue sensor data for sending."""
        payload = {
            "type": "telemetry",
            "deviceId": self.config.device_id,
            "timestamp": datetime.now().isoformat(),
            "data": sensor_data,
        }
        self.queue.put(payload)

    def send_log(self, level: str, message: str):
        """Queue log message."""
        payload = {
            "type": "log",
            "deviceId": self.config.device_id,
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
        }
        self.queue.put(payload)

    def send_heartbeat(self):
        """Queue heartbeat."""
        payload = {
            "type": "heartbeat",
            "deviceId": self.config.device_id,
            "timestamp": datetime.now().isoformat(),
        }
        self.queue.put(payload)

    def _worker_loop(self):
        """Main sender loop."""
        while self._running:
            # 1. Process new messages from queue
            try:
                # Wait up to 1s for new message
                payload = self.queue.get(timeout=1.0)
                if not self._send_to_server(payload):
                    self._save_to_backlog(payload)
                self.queue.task_done()
            except Empty:
                pass

            # 2. Retry backlog periodically (if queue is empty or low load)
            if self.queue.empty():
                self._process_backlog()

    def _send_to_server(self, payload: Dict[str, Any]) -> bool:
        """Attempt to send payload to server."""
        if not self.config.base_url:
            return False

        endpoint_map = {
            "telemetry": "/api/v1/telemetry",
            "log": "/api/v1/logs",
            "heartbeat": "/api/v1/heartbeat",
        }

        msg_type = payload.get("type")
        endpoint = endpoint_map.get(msg_type)
        if not endpoint:
            return True  # Unknown type, "success" to discard

        url = f"{self.config.base_url}{endpoint}"

        try:
            # Remove internal 'type' field before sending if API doesn't expect it
            data_to_send = {k: v for k, v in payload.items() if k != "type"}

            response = requests.post(url, json=data_to_send, timeout=5)
            if response.status_code in [200, 201, 202]:
                return True
            else:
                self.logger.warning(
                    f"Server returned {response.status_code} for {msg_type}"
                )
                return False
        except Exception as e:
            self.logger.warning(f"Connection failed ({msg_type}): {e}")
            return False

    def _save_to_backlog(self, payload: Dict[str, Any]):
        """Save failed message to local file."""
        try:
            with open(self.backlog_file, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            self.logger.error(f"Failed to save to backlog: {e}")

    def _process_backlog(self):
        """Try to send failed messages from backlog."""
        if not os.path.exists(self.backlog_file):
            return

        # Rename current backlog to process it safely
        processing_file = self.backlog_file + ".processing"
        try:
            os.rename(self.backlog_file, processing_file)
        except OSError:
            # File might represent no data or locked
            return

        failed_again = []
        sent_count = 0

        try:
            with open(processing_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        if self._send_to_server(payload):
                            sent_count += 1
                        else:
                            failed_again.append(line)
                    except json.JSONDecodeError:
                        pass  # discard corrupt
        except Exception as e:
            self.logger.error(f"Error processing backlog: {e}")
            # Ensure we don't lose everything if read fails
            # (Simple implementation: might lose some data if crash here)

        # Write back failed messages
        if failed_again:
            try:
                with open(self.backlog_file, "a") as f:
                    for line in failed_again:
                        f.write(line + "\n")
            except Exception:
                pass

        # Cleanup processed file
        try:
            os.remove(processing_file)
        except OSError:
            pass

        if sent_count > 0:
            self.logger.info(f"Recovered {sent_count} messages from backlog")
