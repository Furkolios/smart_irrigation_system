# Smart Irrigation Weather API

Weather data provider for smart irrigation systems, designed for Raspberry Pi integration.

## Features

- **Rain Predictions** - Rainfall forecasts in mm, organized by time period
- **Temperature Predictions** - Min/max/avg temperature forecasts
- **Evapotranspiration (ET₀)** - Calculated using the Simplified Penman method
- **Response Caching** - Reduces API calls, saves bandwidth
- **Configurable Logging** - File, console, or silent modes

---

## Quick Start

### 1. Install Dependencies

```bash
pip install requests python-dotenv
```

### 2. Get an API Key

1. Create a free account at [OpenWeatherMap](https://openweathermap.org/api)
2. Copy your API key from the dashboard

### 3. Setup Environment

Create a `.env` file in your project directory:

```
WEATHER_API_KEY=your_api_key_here
```

### 4. Basic Usage

```python
from smart_irrigation_weather_api import SmartIrrigationWeatherAPI
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize API
api = SmartIrrigationWeatherAPI(
    api_key=os.getenv('WEATHER_API_KEY')
)

# Get all irrigation data
data = api.get_irrigation_data("Paris", max_days=3, elevation=35)

# Access the data
for date, info in data.items():
    print(f"{date}:")
    print(f"  Rain: {info['rain']['total_mm']} mm")
    print(f"  ET:   {info['et']['et_mm']} mm")
    print(f"  Net:  {info['water_balance_mm']} mm")
```

---

## API Methods

### `get_irrigation_data(city, max_days, elevation)`

Returns combined weather data for irrigation decisions.

```python
data = api.get_irrigation_data("Istanbul", max_days=3, elevation=40)
```

**Returns:**
```python
{
    "2025-01-21": {
        "rain": {
            "total_mm": 5.2,
            "will_rain": True,
            "by_period": {
                "morning": {"rain_mm": 2.1, "will_rain": True},
                "afternoon": {"rain_mm": 3.1, "will_rain": True},
                ...
            }
        },
        "temperature": {
            "day_min": 8.0,
            "day_max": 15.0,
            "by_period": {
                "morning": {"temp_avg": 10.2, "temp_min": 8.0, "temp_max": 12.5},
                ...
            }
        },
        "et": {
            "et_mm": 2.45,
            "temp_avg": 12.5,
            "humidity_avg": 65.0,
            "wind_avg": 3.2,
            "cloud_cover_avg": 40.0
        },
        "water_balance_mm": 2.75  # rain - ET (positive = surplus, negative = deficit)
    },
    ...
}
```

### Individual Data Methods

```python
# Rain only
rain = api.get_rain_predictions("Paris", max_days=3)

# Temperature only
temp = api.get_temperature_predictions("Paris", max_days=3)

# ET only
et = api.get_et_predictions("Paris", max_days=3, elevation=35)

# Current weather
current = api.get_current_weather("Paris")
```

---

## Configuration Options

### Full Initialization

```python
api = SmartIrrigationWeatherAPI(
    api_key="your_key",           # Required
    cache_enabled=True,           # Enable/disable caching
    cache_dir="~/.my_cache",      # Custom cache directory
    cache_duration_minutes=30,    # How long cache is valid
    log_level=logging.DEBUG,      # DEBUG, INFO, WARNING, ERROR
    log_file="weather.log",       # Log to file (None = console only)
    silent=False                  # True = disable all logging
)
```

### Quick Setup (Convenience Function)

```python
from smart_irrigation_weather_api import create_api

# Loads API key from .env automatically
api = create_api(
    cache_enabled=True,
    log_file="weather.log",
    silent=False
)
```

---

## Caching

The API caches responses to reduce network calls. This is especially useful on Raspberry Pi to save bandwidth and handle intermittent connectivity.

**Default settings:**
- **Location:** `~/.smart_irrigation_cache/`
- **Duration:** 30 minutes

**Cache operations:**
```python
# Clear all cache
api.clear_cache()

# Disable caching entirely
api = SmartIrrigationWeatherAPI(api_key=key, cache_enabled=False)
```

---

## Logging

Logs are useful for debugging and monitoring your irrigation system.

### Log Levels

| Level | Description |
|-------|-------------|
| `DEBUG` | All operations including cache hits/misses |
| `INFO` | Normal operations (default) |
| `WARNING` | Potential issues |
| `ERROR` | Failures only |

### Log Destinations

```python
import logging

# Console only (default)
api = SmartIrrigationWeatherAPI(api_key=key)

# Console + File
api = SmartIrrigationWeatherAPI(api_key=key, log_file="/var/log/irrigation.log")

# Silent (no output)
api = SmartIrrigationWeatherAPI(api_key=key, silent=True)

# Debug level
api = SmartIrrigationWeatherAPI(api_key=key, log_level=logging.DEBUG)
```

### Example Log Output

```
2025-01-21 14:30:15 - smart_irrigation - INFO - Cache enabled: ~/.smart_irrigation_cache (30min)
2025-01-21 14:30:15 - smart_irrigation - INFO - Rain predictions retrieved for Paris: 3 days
2025-01-21 14:30:15 - smart_irrigation - INFO - Temperature predictions retrieved for Paris: 3 days
2025-01-21 14:30:16 - smart_irrigation - INFO - ET predictions retrieved for Paris: 3 days
2025-01-21 14:30:16 - smart_irrigation - INFO - Irrigation data compiled for Paris: 3 days
```

---

## Integration Example

Here's how your irrigation controller might use this API:

```python
# irrigation_controller.py

from smart_irrigation_weather_api import SmartIrrigationWeatherAPI
import os
from dotenv import load_dotenv

load_dotenv()

class IrrigationController:
    def __init__(self):
        self.weather_api = SmartIrrigationWeatherAPI(
            api_key=os.getenv('WEATHER_API_KEY'),
            cache_enabled=True,
            log_file="/var/log/irrigation_weather.log",
            silent=False
        )
        self.city = "Paris"
        self.elevation = 35  # meters
    
    def get_weather_data(self):
        """Fetch weather data for irrigation decisions."""
        return self.weather_api.get_irrigation_data(
            city=self.city,
            max_days=3,
            elevation=self.elevation
        )
    
    def should_irrigate_today(self):
        """Determine if irrigation is needed based on weather."""
        data = self.get_weather_data()
        
        if not data:
            return None  # API failed, handle accordingly
        
        # Get today's date string
        today = list(data.keys())[0]
        today_data = data[today]
        
        # Your irrigation logic here
        # Example: Don't irrigate if rain is coming
        if today_data['rain']['will_rain']:
            return False
        
        # Example: Irrigate if water balance is negative
        if today_data['water_balance_mm'] < 0:
            return True
        
        return False

# Usage
controller = IrrigationController()
weather = controller.get_weather_data()

if weather:
    for date, info in weather.items():
        print(f"\n{date}")
        print(f"  Rain expected: {info['rain']['will_rain']}")
        print(f"  Water balance: {info['water_balance_mm']:+.1f} mm")
```

---

## Time Periods

The API organizes data into 4 time periods:

| Period | Hours |
|--------|-------|
| `night` | 00:00 - 06:00 |
| `morning` | 06:00 - 12:00 |
| `afternoon` | 12:00 - 18:00 |
| `evening` | 18:00 - 24:00 |

---

## Evapotranspiration (ET) Calculation

The API uses the **Simplified Penman method** to calculate reference evapotranspiration (ET₀):

```
ET₀ = (Δ/(Δ+γ)) × (Rn/λ) + (γ/(Δ+γ)) × f(u) × (es-ea)
```

Where:
- **Δ** = Slope of saturation vapor pressure curve
- **γ** = Psychrometric constant
- **Rn** = Net radiation
- **λ** = Latent heat of vaporization
- **f(u)** = Wind function
- **(es-ea)** = Vapor pressure deficit

**Note:** ET values represent water loss from a reference grass crop. Actual crop water needs may vary based on crop type and growth stage.

---

## Error Handling

The API returns `None` when requests fail. Always check for this:

```python
data = api.get_irrigation_data("Paris")

if data is None:
    # Handle error - maybe use cached data or default values
    print("Failed to fetch weather data")
else:
    # Process data normally
    pass
```

### Test Connection

```python
if api.test_connection():
    print("API connection OK")
else:
    print("Connection failed - check internet/API key")
```

---

## File Structure

```
your_project/
├── smart_irrigation_weather_api.py    # This API
├── irrigation_controller.py           # Your controller code
├── .env                               # API key (don't commit!)
├── .gitignore                         # Add .env here
└── logs/
    └── irrigation_weather.log         # Log file (if configured)
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ValueError: API key is required` | Set `WEATHER_API_KEY` in `.env` file |
| `Connection error` | Check internet connection |
| `HTTP Error 401` | Invalid API key |
| `HTTP Error 429` | Rate limited - enable caching |
| No data returned | Check city name spelling |

---

## Dependencies

- `requests` - HTTP requests
- `python-dotenv` - Environment variable loading
- Python 3.7+

---

## Authors

IDS Smart Irrigation Project Team - Galatasaray University / Mines Paris

## License

MIT License
