import pytest
from unittest.mock import patch, MagicMock
import os
from raspberry_pi.api.plant_api import PlantAPI


@patch("raspberry_pi.api.plant_api.os.getenv")
def test_plant_api_init_no_key(mock_getenv):
    mock_getenv.return_value = None
    with pytest.raises(ValueError):
        PlantAPI()


def test_plant_api_init_with_key():
    api = PlantAPI(api_key="test_key")
    assert api.api_key == "test_key"


@patch("raspberry_pi.api.plant_api.requests.get")
def test_search_plants(mock_get):
    api = PlantAPI(api_key="test_key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "id": 1,
                "common_name": "Tomato",
                "scientific_name": ["Solanum lycopersicum"],
            }
        ]
    }
    mock_get.return_value = mock_response

    results = api.search_plants_simple("tomato")

    assert len(results) == 1
    assert results[0]["name"] == "Tomato"
    assert results[0]["scientific_name"] == "Solanum lycopersicum"


@patch("raspberry_pi.api.plant_api.requests.get")
def test_get_irrigation_data(mock_get):
    api = PlantAPI(api_key="test_key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": 1,
        "common_name": "Fern",
        "watering": "Frequent",
        "watering_general_benchmark": {"value": "2-3", "unit": "days"},
        "sunlight": ["part_shade"],
    }
    mock_get.return_value = mock_response

    data = api.get_irrigation_data(1)

    assert data["watering"] == "Frequent"
    assert data["watering_general_benchmark"]["value"] == "2-3"
