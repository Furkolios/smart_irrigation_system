from raspberry_pi.api.telemetry import TelemetrySender
from raspberry_pi.api.weather_api import WeatherAPI
from unittest.mock import patch, MagicMock
from datetime import datetime


def test_telemetry_payload_construction():
    sensor_map = {"zone_1": "uuid-1"}
    sender = TelemetrySender(device_id="dev-123", sensor_map=sensor_map)

    sensor_data = {
        "zone_1": {
            "soil_moisture_percent": 45.5,
            "temperature_c": 22.0,
            "humidity_percent": 60.0,
        }
    }

    with patch.object(sender, "_post_request") as mock_post:
        mock_post.return_value = True
        sender.send_telemetry(sensor_data)

        # Verify payload structure
        args, kwargs = mock_post.call_args
        payload = args[1]

        assert "readings" in payload
        assert len(payload["readings"]) == 1
        reading = payload["readings"][0]
        assert reading["sensorId"] == "uuid-1"
        assert reading["type"] == "humidity"
        assert reading["unit"] == "%"
        assert reading["value"] == 45.5
        assert "metadata" not in reading


@patch("requests.get")
def test_weather_api_parsing(mock_get):
    # Mock response from OpenWeatherMap (which WeatherAPI expects)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "list": [
            {
                "dt": int(datetime.now().timestamp()),  # Use real timestamp
                "main": {
                    "temp": 20.0,
                    "temp_min": 15.0,
                    "temp_max": 25.0,
                    "humidity": 60.0,
                },
                "rain": {"3h": 5.0},
                "wind": {"speed": 2.0},
                "clouds": {"all": 50},
            }
        ],
        "city": {"coord": {"lat": 48.8566, "lon": 2.3522}},
    }
    mock_get.return_value = mock_response

    api = WeatherAPI(api_key="fake-key", cache_enabled=False)

    data = api.get_irrigation_data(city="Paris")

    # Use the first date in results
    date_str = list(data.keys())[0] if data else None
    assert date_str is not None
    assert data[date_str]["rain"]["total_mm"] == 5.0


def test_image_sender_payload_construction(tmp_path):
    from raspberry_pi.images.image_sender import ImageSender

    sender = ImageSender(device_id="dev-123")

    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake-image-data")

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        sender.upload_image(str(img_path), image_type="plant")

        # Verify post was called
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        # In ImageSender.upload_image, the key is 'file' (external-devices contract)
        assert "file" in kwargs["files"]
        assert "image/jpeg" in kwargs["files"]["file"][2]
