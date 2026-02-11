import yaml
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import ValidationError

from .models import SystemConfig


class ConfigManager:
    """
    Manages loading, validation, and access to system configuration.
    """

    def __init__(self, config_path: str = "config/system_config.yaml"):
        self.config_path = Path(config_path)
        self.logger = logging.getLogger("config_manager")
        self._config: SystemConfig = self._load_config()

    def _load_config(self) -> SystemConfig:
        """
        Load configuration from YAML file.
        If file doesn't exist or is invalid, falls back to defaults (with warning).
        """
        if not self.config_path.exists():
            self.logger.warning(
                f"Config file {self.config_path} not found. Using defaults."
            )
            return SystemConfig()

        try:
            with open(self.config_path, "r") as f:
                raw_config = yaml.safe_load(f) or {}

            # Validate with Pydantic
            config = SystemConfig(**raw_config)
            self.logger.info(f"Configuration loaded from {self.config_path}")
            return config

        except ValidationError as e:
            self.logger.error(f"Configuration validation failed: {e}")
            self.logger.warning("Using default configuration due to validation errors.")
            return SystemConfig()
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return SystemConfig()

    @property
    def config(self) -> SystemConfig:
        """Get the current configuration object."""
        return self._config

    def get_hardware_config(self):
        return self._config.hardware

    def get_server_config(self):
        return self._config.server

    def save_config(self):
        """Save current configuration back to YAML file."""
        try:
            # Create directory if it doesn't exist
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, "w") as f:
                # model_dump (v2) or dict (v1)
                data = self._config.model_dump(mode="json")
                yaml.dump(data, f, default_flow_style=False)
            self.logger.info(f"Configuration saved to {self.config_path}")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    def update_server_config(self, **kwargs):
        """Update server configuration values."""
        current_data = self._config.server.model_dump()
        current_data.update(kwargs)
        self._config.server = self._config.server.__class__(**current_data)
        self.save_config()


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    cm = ConfigManager("system_config.yaml")
    print(f"System Mode: {cm.config.system_mode}")
    print(f"Valves: {len(cm.config.hardware.valves)}")
