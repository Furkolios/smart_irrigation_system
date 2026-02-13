import pytest
from pathlib import Path
from raspberry_pi.config.config_manager import ConfigManager
from raspberry_pi.config.models import SystemConfig, SystemMode


def test_config_manager_load_defaults(tmp_path):
    # Non-existent file should load defaults
    config_file = tmp_path / "non_existent.yaml"
    manager = ConfigManager(config_path=str(config_file))

    assert isinstance(manager.config, SystemConfig)
    assert manager.config.system_mode == SystemMode.MAIN
    # Check default irrigation setting
    assert manager.config.irrigation.loop_interval_seconds == 60


def test_config_manager_load_valid_file(tmp_path):
    config_file = tmp_path / "test_config.yaml"
    yaml_content = """
    system_mode: "test"
    irrigation:
      loop_interval_seconds: 120
    """
    config_file.write_text(yaml_content)

    manager = ConfigManager(config_path=str(config_file))
    assert manager.config.system_mode == SystemMode.TEST
    assert manager.config.irrigation.loop_interval_seconds == 120


def test_config_manager_save(tmp_path):
    config_file = tmp_path / "save_config.yaml"
    manager = ConfigManager(config_path=str(config_file))

    # Modify and save
    manager.config.system_mode = SystemMode.DEMO
    manager.save_config()

    # Reload
    new_manager = ConfigManager(config_path=str(config_file))
    assert new_manager.config.system_mode == SystemMode.DEMO


def test_config_manager_update_server(tmp_path):
    config_file = tmp_path / "server_config.yaml"
    manager = ConfigManager(config_path=str(config_file))

    manager.update_server_config(device_id="new-uuid", base_url="http://test.com")

    assert manager.config.server.device_id == "new-uuid"
    assert manager.config.server.base_url == "http://test.com"

    # Verify persistence
    new_manager = ConfigManager(config_path=str(config_file))
    assert new_manager.config.server.device_id == "new-uuid"
