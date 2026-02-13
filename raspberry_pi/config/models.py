from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, validator


class SystemMode(str, Enum):
    MAIN = "main"
    DEMO = "demo"
    TEST = "test"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ArduinoConfig(BaseModel):
    # Optional manual port override. If not set, auto-detection logic applies.
    port: Optional[str] = None
    baud_rate: int = 9600
    timeout: float = 2.0


class CameraConfig(BaseModel):
    enabled: bool = True
    # "tank" or "plant"
    role: str
    # Optional device path override (e.g. /dev/video0)
    device_path: Optional[str] = None
    resolution: List[int] = [640, 480]


class ValveConfig(BaseModel):
    zone_id: str
    pin: int
    name: str
    # Flow rate in liters per minute
    flow_rate_lpm: float = 2.0


class HardwareConfig(BaseModel):
    max_arduinos: int = 2
    max_cameras: int = 2
    global_arduino_config: ArduinoConfig = Field(default_factory=ArduinoConfig)
    cameras: List[CameraConfig] = []
    valves: List[ValveConfig] = []


class ServerConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://localhost:8000"
    device_id: Optional[str] = None
    # Provisioning response: mapping from local sensor names (e.g. "zone_1") to server sensor UUIDs
    sensor_map: Dict[str, str] = Field(default_factory=dict)
    telemetry_interval_seconds: int = 60
    image_interval_seconds: int = 3600
    heartbeat_interval_seconds: int = 30
    health_interval_seconds: int = 300
    retry_policy: Dict[str, Any] = {"max_retries": 5, "backoff_factor": 1.5}


class IrrigationConfig(BaseModel):
    # Global check interval for the main loop
    loop_interval_seconds: int = 60
    default_moisture_threshold: float = 30.0
    default_water_amount_liters: float = 1.0


class LoggingConfig(BaseModel):
    level: LogLevel = LogLevel.INFO
    file_path: str = "irrigation.log"
    max_size_mb: int = 5
    backup_count: int = 3


class SystemConfig(BaseModel):
    system_mode: SystemMode = SystemMode.MAIN
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    irrigation: IrrigationConfig = Field(default_factory=IrrigationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Location for weather data
    location: Dict[str, Any] = {"city": "Paris", "elevation_m": 35.0}
