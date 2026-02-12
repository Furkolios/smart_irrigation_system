import json
import logging
import os
from datetime import datetime
from queue import Queue, Empty
from threading import Thread
from typing import Dict, Any, Optional

import requests

from ..config.models import ServerConfig


class TelemetryManager:
    """
    Device → Server telemetry transport with store-and-forward buffering.

    Matches `docs/device_technical_manual.md` endpoints:
      - POST /api/v1/external-devices/{device_id}/telemetry
      - POST /api/v1/external-devices/{device_id}/logs
      - POST /api/v1/external-devices/{device_id}/images (multipart)
      - GET  /api/v1/external-devices/{device_id}/status
    """

    def __init__(self, config: ServerConfig):
        self.config = config
        self.logger = logging.getLogger("telemetry")

        # In-memory queue for immediate sending
        self.queue: "Queue[Dict[str, Any]]" = Queue()
        self._running = False
        self._worker_thread: Optional[Thread] = None

        # Local storage for failed messages
        self.backlog_file = "data/telemetry_backlog.jsonl"
        os.makedirs(os.path.dirname(self.backlog_file), exist_ok=True)

        if self._is_enabled():
            self.start()
        else:
            self.logger.info("Telemetry disabled (missing server config or deviceId)")

    def _is_enabled(self) -> bool:
        return bool(
            self.config.enabled and self.config.base_url and self.config.device_id
        )

    @property
    def device_id(self) -> Optional[str]:
        return self.config.device_id

    def start(self):
        self._running = True
        self._worker_thread = Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        self.logger.info("Telemetry Manager started")

    def stop(self):
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)

    # =========================================================================
    # Public enqueue API
    # =========================================================================

    def send_telemetry(self, sensor_data: Dict[str, Dict[str, Any]]):
        """
        Queue telemetry built from raw sensor data.

        Input format:
          { "zone_1": { "soil_moisture_percent": 45.0, "temperature_c": 22.1, ... }, ... }
        """
        now_iso = datetime.now().isoformat()
        readings = []

        # External devices guide requires: sensorId, type, value, unit (and optionally readingAt)
        # We send one or more readings per zone depending on what is mapped in `server.sensor_map`.
        for zone_id, values in (sensor_data or {}).items():
            # 1) Soil moisture (represented as humidity %; sensorId must exist server-side)
            soil_sensor_id = (self.config.sensor_map or {}).get(zone_id)
            soil_value = (values or {}).get("soil_moisture_percent")
            if soil_sensor_id and soil_value is not None:
                readings.append(
                    {
                        "sensorId": soil_sensor_id,
                        "type": "humidity",
                        "value": round(float(soil_value), 2),
                        "unit": "%",
                        "readingAt": now_iso,
                    }
                )
            elif soil_value is not None:
                self.logger.warning(f"No sensorId found for localName: {zone_id}")

            # 2) Temperature (optional)
            temp_local = f"{zone_id}_temperature"
            temp_sensor_id = (self.config.sensor_map or {}).get(temp_local)
            temp_value = (values or {}).get("temperature_c")
            if temp_sensor_id and temp_value is not None:
                readings.append(
                    {
                        "sensorId": temp_sensor_id,
                        "type": "temperature",
                        "value": round(float(temp_value), 2),
                        "unit": "C",
                        "readingAt": now_iso,
                    }
                )

            # 3) Air humidity (optional) — kept separate from soil moisture via sensorId/localName
            hum_local = f"{zone_id}_humidity"
            hum_sensor_id = (self.config.sensor_map or {}).get(hum_local)
            hum_value = (values or {}).get("humidity_percent")
            if hum_sensor_id and hum_value is not None:
                readings.append(
                    {
                        "sensorId": hum_sensor_id,
                        "type": "humidity",
                        "value": round(float(hum_value), 2),
                        "unit": "%",
                        "readingAt": now_iso,
                    }
                )

        payload = {
            "type": "telemetry",
            "sentAt": now_iso,
            "readings": readings,
        }
        self.queue.put(payload)

    def send_log(self, level: str, message: str):
        payload = {
            "type": "log",
            "level": str(level).lower(),
            "message": str(message),
            "recordedAt": datetime.now().isoformat(),
        }
        self.queue.put(payload)

    def send_heartbeat(self):
        payload = {"type": "heartbeat", "timestamp": datetime.now().isoformat()}
        self.queue.put(payload)

    def send_health(self, health: Dict[str, Any]):
        """
        Best-effort health reporting (implemented as a structured log).
        """
        payload = {
            "type": "health",
            "recordedAt": datetime.now().isoformat(),
            "health": health,
        }
        self.queue.put(payload)

    def send_image(
        self,
        image_path: str,
        image_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        delete_on_success: bool = False,
    ):
        payload = {
            "type": "image",
            "image_path": image_path,
            "image_type": image_type,
            "captured_at": datetime.now().isoformat(),
            "metadata": metadata or {},
            "delete_on_success": bool(delete_on_success),
        }
        self.queue.put(payload)

    # =========================================================================
    # Worker / transport
    # =========================================================================

    def _worker_loop(self):
        while self._running:
            try:
                payload = self.queue.get(timeout=1.0)
                if not self._send_to_server(payload):
                    self._save_to_backlog(payload)
                self.queue.task_done()
            except Empty:
                pass

            if self.queue.empty():
                self._process_backlog()

    def _base(self) -> str:
        return str(self.config.base_url).rstrip("/")

    def _device_base(self) -> str:
        return f"{self._base()}/api/v1/external-devices/{self.config.device_id}"

    def _send_to_server(self, payload: Dict[str, Any]) -> bool:
        if not self._is_enabled():
            return False

        msg_type = payload.get("type")
        try:
            if msg_type == "telemetry":
                url = f"{self._device_base()}/telemetry"
                data = {k: v for k, v in payload.items() if k != "type"}
                resp = requests.post(url, json=data, timeout=5)
                return resp.status_code in (200, 201, 202)

            if msg_type == "log":
                url = f"{self._device_base()}/logs"
                data = {k: v for k, v in payload.items() if k != "type"}
                resp = requests.post(url, json=data, timeout=5)
                return resp.status_code in (200, 201, 202)

            if msg_type == "health":
                url = f"{self._device_base()}/logs"
                health = payload.get("health") or {}
                data = {
                    "level": "info",
                    "message": json.dumps({"type": "health", "data": health}),
                    "recordedAt": payload.get("recordedAt") or datetime.now().isoformat(),
                }
                resp = requests.post(url, json=data, timeout=5)
                return resp.status_code in (200, 201, 202)

            if msg_type == "heartbeat":
                url = f"{self._device_base()}/status"
                resp = requests.get(url, timeout=5)
                return resp.status_code in (200, 204)

            if msg_type == "image":
                image_path = payload.get("image_path")
                if not image_path or not os.path.exists(image_path):
                    self.logger.warning(f"Image missing, dropping: {image_path}")
                    return True

                url = f"{self._device_base()}/images"
                data = {
                    # Must match `docs/external-devices.md` form fields
                    "type": payload.get("image_type") or "general",
                    "captured_at": payload.get("captured_at") or datetime.now().isoformat(),
                }
                metadata = payload.get("metadata") or {}
                if metadata:
                    data["metadata"] = json.dumps(metadata)

                with open(image_path, "rb") as f:
                    files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
                    resp = requests.post(url, files=files, data=data, timeout=15)
                    ok = resp.status_code in (200, 201, 202)

                if ok and payload.get("delete_on_success"):
                    try:
                        os.remove(image_path)
                    except OSError:
                        pass

                return ok

            # Unknown message type: drop
            return True
        except Exception as e:
            self.logger.warning(f"Connection failed ({msg_type}): {e}")
            return False

    def _save_to_backlog(self, payload: Dict[str, Any]):
        try:
            with open(self.backlog_file, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            self.logger.error(f"Failed to save to backlog: {e}")

    def _process_backlog(self):
        if not os.path.exists(self.backlog_file):
            return

        processing_file = self.backlog_file + ".processing"
        try:
            os.rename(self.backlog_file, processing_file)
        except OSError:
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
                            # If it's an image and file vanished, don't keep retrying
                            if payload.get("type") == "image" and not os.path.exists(
                                payload.get("image_path") or ""
                            ):
                                continue
                            failed_again.append(line)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            self.logger.error(f"Error processing backlog: {e}")

        if failed_again:
            try:
                with open(self.backlog_file, "a") as f:
                    for line in failed_again:
                        f.write(line + "\n")
            except Exception:
                pass

        try:
            os.remove(processing_file)
        except OSError:
            pass

        if sent_count > 0:
            self.logger.info(f"Recovered {sent_count} messages from backlog")
