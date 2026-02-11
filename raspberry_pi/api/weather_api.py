"""
Smart Irrigation Weather API
=============================
Weather data provider for smart irrigation systems.

Provides:
- Rain predictions (mm per time period)
- Temperature predictions (°C)
- Evapotranspiration (ET₀) rate using Simplified Penman method

Designed for Raspberry Pi integration with:
- Configurable logging (file/console/silent)
- Response caching to reduce API calls
- Clean data interface for irrigation controllers

Usage:
    from smart_irrigation_weather_api import SmartIrrigationWeatherAPI
    
    api = SmartIrrigationWeatherAPI(api_key="your_key")
    data = api.get_irrigation_data("Paris", max_days=3)
"""

import requests 
import os
import math
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, Union

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CACHE_DIR = Path.home() / ".smart_irrigation_cache"
DEFAULT_CACHE_DURATION_MINUTES = 30
DEFAULT_FORECAST_DAYS = 3


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logger(
    name: str = "smart_irrigation",
    level: int = logging.INFO,
    log_file: Optional[Union[str, Path]] = None,
    silent: bool = False
) -> logging.Logger:
    """Configure and return a logger instance."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers = []
    
    if silent:
        logger.addHandler(logging.NullHandler())
        return logger
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# =============================================================================
# CACHE MANAGER
# =============================================================================

class CacheManager:
    """Simple file-based cache for API responses."""
    
    def __init__(self, cache_dir=DEFAULT_CACHE_DIR, duration_minutes=DEFAULT_CACHE_DURATION_MINUTES, logger=None):
        self.cache_dir = Path(cache_dir)
        self.duration = timedelta(minutes=duration_minutes)
        self.logger = logger or logging.getLogger("cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() else "_" for c in key)
        return self.cache_dir / f"{safe_key}.json"
    
    def get(self, key: str) -> Optional[dict]:
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None
        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)
            cached_time = datetime.fromisoformat(cached['timestamp'])
            if datetime.now() - cached_time > self.duration:
                cache_path.unlink()
                return None
            return cached['data']
        except (json.JSONDecodeError, KeyError):
            return None
    
    def set(self, key: str, data: dict) -> bool:
        cache_path = self._get_cache_path(key)
        try:
            cache_entry = {'timestamp': datetime.now().isoformat(), 'data': data}
            with open(cache_path, 'w') as f:
                json.dump(cache_entry, f)
            return True
        except Exception:
            return False
    
    def clear(self) -> int:
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1
        return count


# =============================================================================
# MAIN API CLASS
# =============================================================================

class WeatherAPI:
    """
    Weather API for Smart Irrigation Systems.
    
    Provides rain predictions, temperature forecasts, and evapotranspiration
    calculations using the Simplified Penman method.
    """
    
    def __init__(self, api_key, cache_enabled=True, cache_dir=DEFAULT_CACHE_DIR,
                 cache_duration_minutes=DEFAULT_CACHE_DURATION_MINUTES,
                 log_level=logging.INFO, log_file=None, silent=False):
        if not api_key:
            raise ValueError("API key is required. Set OPENWEATHER_API_KEY environment variable or pass directly.")
        
        self.api_key = api_key
        self.base_weather_url = "https://api.openweathermap.org/data/2.5/weather"
        self.base_forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
        
        self.logger = setup_logger(name="smart_irrigation", level=log_level, log_file=log_file, silent=silent)
        
        if cache_enabled:
            self.cache = CacheManager(cache_dir=cache_dir, duration_minutes=cache_duration_minutes, logger=self.logger)
        else:
            self.cache = None
        
        self._location_cache: Dict[str, Tuple[float, float]] = {}

    def _fetch_data(self, url, params, cache_key=None):
        if cache_key and self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                return cached
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if cache_key and self.cache:
                self.cache.set(cache_key, data)
            return data
        except requests.exceptions.Timeout:
            self.logger.error("Request timed out")
        except requests.exceptions.ConnectionError:
            self.logger.error("Connection error - check internet")
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP Error: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        return None

    def _get_time_period(self, hour):
        if 6 <= hour < 12: return "morning"
        elif 12 <= hour < 18: return "afternoon"
        elif 18 <= hour < 24: return "evening"
        else: return "night"

    def _date_to_string(self, date):
        return date.isoformat()

    def get_current_weather(self, city):
        params = {'q': city, 'appid': self.api_key, 'units': 'metric'}
        data = self._fetch_data(self.base_weather_url, params, f"current_{city.lower()}")
        if data and 'coord' in data:
            self._location_cache[city.lower()] = (data['coord']['lat'], data['coord']['lon'])
        return data

    def get_forecast(self, city):
        params = {'q': city, 'appid': self.api_key, 'units': 'metric'}
        data = self._fetch_data(self.base_forecast_url, params, f"forecast_{city.lower()}")
        if data and 'city' in data:
            self._location_cache[city.lower()] = (data['city']['coord']['lat'], data['city']['coord']['lon'])
        return data

    def get_rain_predictions(self, city, max_days=DEFAULT_FORECAST_DAYS):
        data = self.get_forecast(city)
        if not data:
            return None
        today = datetime.now().date()
        rain_forecast = {}
        for entry in data['list']:
            dt = datetime.fromtimestamp(entry['dt'])
            forecast_date = dt.date()
            days_ahead = (forecast_date - today).days
            if days_ahead < 0 or days_ahead >= max_days:
                continue
            date_str = self._date_to_string(forecast_date)
            period = self._get_time_period(dt.hour)
            if date_str not in rain_forecast:
                rain_forecast[date_str] = {}
            if period not in rain_forecast[date_str]:
                rain_forecast[date_str][period] = {'rain_mm': 0.0, 'will_rain': False}
            rain_mm = entry.get('rain', {}).get('3h', 0)
            rain_forecast[date_str][period]['rain_mm'] += rain_mm
            if rain_mm > 0:
                rain_forecast[date_str][period]['will_rain'] = True
        return rain_forecast

    def get_temperature_predictions(self, city, max_days=DEFAULT_FORECAST_DAYS):
        data = self.get_forecast(city)
        if not data:
            return None
        today = datetime.now().date()
        temp_data = {}
        for entry in data['list']:
            dt = datetime.fromtimestamp(entry['dt'])
            forecast_date = dt.date()
            days_ahead = (forecast_date - today).days
            if days_ahead < 0 or days_ahead >= max_days:
                continue
            date_str = self._date_to_string(forecast_date)
            period = self._get_time_period(dt.hour)
            temp = entry['main']['temp']
            temp_min = entry['main']['temp_min']
            temp_max = entry['main']['temp_max']
            if date_str not in temp_data:
                temp_data[date_str] = {}
            if period not in temp_data[date_str]:
                temp_data[date_str][period] = {'temps': [], 'temp_min': temp_min, 'temp_max': temp_max}
            temp_data[date_str][period]['temps'].append(temp)
            temp_data[date_str][period]['temp_min'] = min(temp_data[date_str][period]['temp_min'], temp_min)
            temp_data[date_str][period]['temp_max'] = max(temp_data[date_str][period]['temp_max'], temp_max)
        result = {}
        for date_str, periods in temp_data.items():
            result[date_str] = {}
            for period, pdata in periods.items():
                result[date_str][period] = {
                    'temp_avg': round(sum(pdata['temps']) / len(pdata['temps']), 1),
                    'temp_min': round(pdata['temp_min'], 1),
                    'temp_max': round(pdata['temp_max'], 1)
                }
        return result

    # =========================================================================
    # EVAPOTRANSPIRATION CALCULATIONS (SIMPLIFIED PENMAN)
    # =========================================================================

    def _calc_saturation_vapor_pressure(self, temp_c):
        return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
    
    def _calc_slope_vapor_pressure_curve(self, temp_c):
        es = self._calc_saturation_vapor_pressure(temp_c)
        return (4098 * es) / ((temp_c + 237.3) ** 2)
    
    def _calc_actual_vapor_pressure(self, temp_c, humidity):
        es = self._calc_saturation_vapor_pressure(temp_c)
        return es * (humidity / 100)
    
    def _calc_extraterrestrial_radiation(self, latitude, day_of_year):
        Gsc = 0.0820
        lat_rad = latitude * math.pi / 180
        dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
        delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
        ws = math.acos(-math.tan(lat_rad) * math.tan(delta))
        Ra = (24 * 60 / math.pi) * Gsc * dr * (
            ws * math.sin(lat_rad) * math.sin(delta) +
            math.cos(lat_rad) * math.cos(delta) * math.sin(ws)
        )
        return Ra
    
    def _calc_net_radiation(self, Ra, temp_c, ea, cloud_cover):
        Rs = Ra * (0.25 + 0.50 * (1 - cloud_cover))
        Rso = 0.75 * Ra
        Rns = (1 - 0.23) * Rs
        temp_k = temp_c + 273.16
        sigma = 4.903e-9
        cloud_factor = 1.35 * (Rs / Rso) - 0.35 if Rso > 0 else 0.5
        cloud_factor = max(0.05, min(1.0, cloud_factor))
        vapor_factor = 0.34 - 0.14 * math.sqrt(ea)
        Rnl = sigma * (temp_k ** 4) * vapor_factor * cloud_factor
        return max(0, Rns - Rnl)

    def calculate_et(self, temp_c, humidity, wind_speed, latitude, day_of_year, cloud_cover=0.5, elevation=0):
        """Calculate Reference Evapotranspiration (ET₀) using Simplified Penman."""
        lambda_v = 2.45
        P = 101.3 * ((293 - 0.0065 * elevation) / 293) ** 5.26
        gamma = 0.665e-3 * P
        delta = self._calc_slope_vapor_pressure_curve(temp_c)
        es = self._calc_saturation_vapor_pressure(temp_c)
        ea = self._calc_actual_vapor_pressure(temp_c, humidity)
        vpd = es - ea
        Ra = self._calc_extraterrestrial_radiation(latitude, day_of_year)
        Rn = self._calc_net_radiation(Ra, temp_c, ea, cloud_cover)
        f_u = 0.27 * (1 + 0.864 * wind_speed)
        weight_rad = delta / (delta + gamma)
        weight_wind = gamma / (delta + gamma)
        ET_rad = weight_rad * (Rn / lambda_v)
        ET_wind = weight_wind * f_u * vpd
        return max(0, ET_rad + ET_wind)

    def get_et_predictions(self, city, max_days=DEFAULT_FORECAST_DAYS, elevation=0):
        data = self.get_forecast(city)
        if not data:
            return None
        latitude = data['city']['coord']['lat']
        today = datetime.now().date()
        daily_data = {}
        for entry in data['list']:
            dt = datetime.fromtimestamp(entry['dt'])
            forecast_date = dt.date()
            days_ahead = (forecast_date - today).days
            if days_ahead < 0 or days_ahead >= max_days:
                continue
            date_str = self._date_to_string(forecast_date)
            if date_str not in daily_data:
                daily_data[date_str] = {
                    'temps': [], 'humidity': [], 'wind_speed': [], 'cloud_cover': [],
                    'day_of_year': forecast_date.timetuple().tm_yday
                }
            daily_data[date_str]['temps'].append(entry['main']['temp'])
            daily_data[date_str]['humidity'].append(entry['main']['humidity'])
            daily_data[date_str]['wind_speed'].append(entry['wind']['speed'])
            daily_data[date_str]['cloud_cover'].append(entry.get('clouds', {}).get('all', 50) / 100)
        result = {}
        for date_str, values in daily_data.items():
            temp_avg = sum(values['temps']) / len(values['temps'])
            humidity_avg = sum(values['humidity']) / len(values['humidity'])
            wind_avg = sum(values['wind_speed']) / len(values['wind_speed'])
            cloud_avg = sum(values['cloud_cover']) / len(values['cloud_cover'])
            et = self.calculate_et(temp_c=temp_avg, humidity=humidity_avg, wind_speed=wind_avg,
                                   latitude=latitude, day_of_year=values['day_of_year'],
                                   cloud_cover=cloud_avg, elevation=elevation)
            result[date_str] = {
                'et_mm': round(et, 2), 'temp_avg': round(temp_avg, 1),
                'humidity_avg': round(humidity_avg, 1), 'wind_avg': round(wind_avg, 1),
                'cloud_cover_avg': round(cloud_avg * 100, 1)
            }
        return result

    def get_irrigation_data(self, city, max_days=DEFAULT_FORECAST_DAYS, elevation=0):
        """Get all weather data needed for irrigation decisions."""
        rain = self.get_rain_predictions(city, max_days)
        temp = self.get_temperature_predictions(city, max_days)
        et = self.get_et_predictions(city, max_days, elevation)
        if not all([rain, temp, et]):
            return None
        result = {}
        for date_str in rain.keys():
            daily_rain = sum(p['rain_mm'] for p in rain[date_str].values())
            will_rain = any(p['will_rain'] for p in rain[date_str].values())
            temp_periods = temp.get(date_str, {})
            all_mins = [p['temp_min'] for p in temp_periods.values()]
            all_maxs = [p['temp_max'] for p in temp_periods.values()]
            et_data = et.get(date_str, {'et_mm': 0})
            result[date_str] = {
                'rain': {'total_mm': round(daily_rain, 1), 'will_rain': will_rain, 'by_period': rain[date_str]},
                'temperature': {'day_min': min(all_mins) if all_mins else None, 'day_max': max(all_maxs) if all_maxs else None, 'by_period': temp_periods},
                'et': et_data,
                'water_balance_mm': round(daily_rain - et_data.get('et_mm', 0), 2)
            }
        return result

    def clear_cache(self):
        if self.cache:
            return self.cache.clear()
        return 0

    def test_connection(self):
        try:
            data = self.get_current_weather("London")
            return data is not None
        except Exception:
            return False


def create_api(api_key=None, cache_enabled=True, log_file=None, silent=False):
    """Convenience function to create API instance."""
    from dotenv import load_dotenv
    load_dotenv()
    key = api_key or os.getenv('OPENWEATHER_API_KEY')
    return WeatherAPI(api_key=key, cache_enabled=cache_enabled, log_file=log_file, silent=silent)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    weather_api = WeatherAPI(
        api_key=os.getenv('OPENWEATHER_API_KEY'),
        cache_enabled=True, log_file="irrigation_weather.log", silent=False
    )
    
    print("Testing connection...")
    if weather_api.test_connection():
        print("✓ Connection successful\n")
    else:
        print("✗ Connection failed")
        exit(1)
    
    city = "Paris"
    data = weather_api.get_irrigation_data(city, max_days=3, elevation=35)
    if data:
        print(f"\n{'='*50}")
        print(f"IRRIGATION DATA - {city.upper()}")
        print(f"{'='*50}")
        for date_str, info in sorted(data.items()):
            print(f"\n📅 {date_str}")
            print(f"   Rain: {info['rain']['total_mm']} mm")
            print(f"   ET:   {info['et']['et_mm']} mm")
            print(f"   Net:  {info['water_balance_mm']:+.2f} mm")
