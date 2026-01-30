"""
Perenual Plant API Module
-------------------------
A module to fetch plant data from the Perenual API for the smart agricultural system.
Uses environment variables for secure API key management.

API Documentation: https://perenual.com/docs/api
"""

import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class PlantAPI:
    """
    A class to interact with the Perenual Plant API.
    
    Provides methods to:
    - Search for plants by name
    - Get detailed plant information (watering, sunlight, hardiness, etc.)
    - Fetch pest/disease information
    """
    
    def __init__(self, api_key: str = None):
        """
        Initialize the Perenual API client.
        
        Args:
            api_key: Optional API key. If not provided, reads from PERENUAL_API_KEY env variable.
        """
        self.api_key = api_key or os.getenv('PERENUAL_API_KEY')
        if not self.api_key:
            raise ValueError(
                "API key not found. Either pass api_key parameter or "
                "set PERENUAL_API_KEY in your .env file"
            )
        
        self.base_url = "https://www.perenual.com/api/v2"
        self.timeout = 10  # seconds
    
    def _make_request(self, endpoint: str, params: dict = None) -> dict | None:
        """
        Make a GET request to the Perenual API.
        
        Args:
            endpoint: API endpoint (e.g., 'species-list', 'species/details/1')
            params: Additional query parameters
            
        Returns:
            JSON response as dictionary, or None if request failed
        """
        url = f"{self.base_url}/{endpoint}"
        
        # Always include the API key
        request_params = {'key': self.api_key}
        if params:
            request_params.update(params)
        
        try:
            response = requests.get(url, params=request_params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            print(f"Error: Request timed out after {self.timeout} seconds")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            return None
        except ValueError as e:
            print(f"Error parsing JSON response: {e}")
            return None
    
    def search_plants(self, query: str, page: int = 1, **filters) -> dict | None:
        """
        Search for plants by name or keyword.
        
        Args:
            query: Search term (plant name)
            page: Page number for pagination (default: 1)
            **filters: Additional filters:
                - watering: 'frequent', 'average', 'minimum', 'none'
                - sunlight: 'full_shade', 'part_shade', 'sun-part_shade', 'full_sun'
                - cycle: 'perennial', 'annual', 'biennial', 'biannual'
                - edible: True/False
                - poisonous: True/False
                - indoor: True/False
                - hardiness: '1-13' (e.g., '5-7' for zones 5-7)
                
        Returns:
            Dictionary with plant data and pagination info
        """
        params = {
            'q': query,
            'page': page
        }
        
        # Add optional filters
        for key, value in filters.items():
            if value is not None:
                # Convert booleans to 1/0 for API
                if isinstance(value, bool):
                    params[key] = 1 if value else 0
                else:
                    params[key] = value
        
        return self._make_request('species-list', params)
    
    def search_plants_simple(self, query: str, max_results: int = 10) -> list[dict] | None:
        """
        Search for plants and return a simplified list for UI dropdowns.
        
        Args:
            query: Search term (plant name)
            max_results: Maximum number of results to return (default: 10)
            
        Returns:
            List of dictionaries with basic plant info:
            [
                {'id': 1, 'name': 'European Silver Fir', 'scientific_name': 'Abies alba'},
                ...
            ]
            Returns None if request failed.
        """
        results = self.search_plants(query)
        
        if not results or 'data' not in results:
            return None
        
        simplified = []
        for plant in results['data'][:max_results]:
            scientific = plant.get('scientific_name', [])
            simplified.append({
                'id': plant.get('id'),
                'name': plant.get('common_name', 'Unknown'),
                'scientific_name': scientific[0] if scientific else None
            })
        
        return simplified
    
    def get_plant_details(self, plant_id: int) -> dict | None:
        """
        Get detailed information about a specific plant.
        
        Args:
            plant_id: The Perenual species ID
            
        Returns:
            Dictionary with detailed plant information including:
            - watering requirements
            - sunlight needs
            - hardiness zones
            - growth rate
            - care level
            - and much more
        """
        return self._make_request(f'species/details/{plant_id}')
    
    def get_pest_diseases(self, query: str = None, page: int = 1) -> dict | None:
        """
        Get information about plant pests and diseases.
        
        Args:
            query: Optional search term
            page: Page number for pagination
            
        Returns:
            Dictionary with pest/disease data
        """
        # Note: pest-disease endpoint uses v1-style URL (no /v2/)
        url = "https://www.perenual.com/api/pest-disease-list"
        
        params = {'key': self.api_key, 'page': page}
        if query:
            params['q'] = query
        
        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching pest/disease data: {e}")
            return None
    
    def get_irrigation_data(self, plant_id: int) -> dict | None:
        """
        Extract irrigation-relevant data from plant details.
        
        This is a convenience method that fetches plant details and returns
        only the data relevant for irrigation decisions.
        
        Args:
            plant_id: The Perenual species ID
            
        Returns:
            Dictionary with irrigation-relevant fields:
            - watering: general watering level
            - watering_general_benchmark: recommended watering frequency
            - drought_tolerant: boolean
            - hardiness: temperature zones
            - sunlight: light requirements (affects water needs)
        """
        details = self.get_plant_details(plant_id)
        
        if not details:
            return None
        
        # Extract irrigation-relevant fields
        irrigation_data = {
            'id': details.get('id'),
            'common_name': details.get('common_name'),
            'scientific_name': details.get('scientific_name'),
            'watering': details.get('watering'),
            'watering_general_benchmark': details.get('watering_general_benchmark'),
            'drought_tolerant': details.get('drought_tolerant'),
            'hardiness': details.get('hardiness'),
            'sunlight': details.get('sunlight'),
            'soil': details.get('soil'),
            'growth_rate': details.get('growth_rate'),
            'care_level': details.get('care_level'),
            'indoor': details.get('indoor'),
        }
        
        # Clean up watering benchmark value (API sometimes returns extra quotes)
        benchmark = irrigation_data.get('watering_general_benchmark')
        if benchmark and 'value' in benchmark:
            benchmark['value'] = str(benchmark['value']).strip('"\'')
        
        return irrigation_data
    
    def display_plant_info(self, plant_id: int) -> None:
        """
        Fetch and display plant information in a readable format.
        
        Args:
            plant_id: The Perenual species ID
        """
        data = self.get_plant_details(plant_id)
        
        if not data:
            print("Could not fetch plant data.")
            return
        
        print(f"\n{'='*60}")
        print(f"Plant Information: {data.get('common_name', 'Unknown')}")
        print(f"{'='*60}")
        print(f"Scientific Name: {data.get('scientific_name', ['N/A'])[0] if data.get('scientific_name') else 'N/A'}")
        print(f"Type: {data.get('type', 'N/A')}")
        print(f"Cycle: {data.get('cycle', 'N/A')}")
        print(f"\n--- Care Requirements ---")
        print(f"Watering: {data.get('watering', 'N/A')}")
        
        # Watering benchmark
        benchmark = data.get('watering_general_benchmark')
        if benchmark:
            print(f"Watering Frequency: Every {benchmark.get('value', 'N/A')} {benchmark.get('unit', 'days')}")
        
        # Sunlight
        sunlight = data.get('sunlight', [])
        print(f"Sunlight: {', '.join(sunlight) if sunlight else 'N/A'}")
        
        # Soil
        soil = data.get('soil', [])
        print(f"Soil Type: {', '.join(soil) if soil else 'N/A'}")
        
        print(f"\n--- Plant Characteristics ---")
        print(f"Growth Rate: {data.get('growth_rate', 'N/A')}")
        print(f"Care Level: {data.get('care_level', 'N/A')}")
        print(f"Maintenance: {data.get('maintenance', 'N/A')}")
        
        # Hardiness zones
        hardiness = data.get('hardiness', {})
        if hardiness:
            print(f"Hardiness Zones: {hardiness.get('min', '?')}-{hardiness.get('max', '?')}")
        
        print(f"\n--- Other Info ---")
        print(f"Drought Tolerant: {'Yes' if data.get('drought_tolerant') else 'No'}")
        print(f"Indoor Plant: {'Yes' if data.get('indoor') else 'No'}")
        print(f"Edible: {'Yes' if data.get('edible_fruit') or data.get('edible_leaf') else 'No'}")
        print(f"Poisonous to Pets: {'Yes' if data.get('poisonous_to_pets') else 'No'}")
        print(f"{'='*60}\n")


# Example usage and testing
if __name__ == "__main__":
    # Initialize the API client
    # Make sure you have PERENUAL_API_KEY in your .env file
    try:
        plant_api = PlantAPI()
    except ValueError as e:
        print(f"Setup Error: {e}")
        print("\nTo use this module:")
        print("1. Create a .env file in your project directory")
        print("2. Add: PERENUAL_API_KEY=your_api_key_here")
        print("3. Get your API key from: https://perenual.com/user/developer")
        exit(1)
    
    # Example 1: Simple search for dropdown (what your dashboard will use)
    print("\n--- Simple search for 'tomato' (for dropdown) ---")
    options = plant_api.search_plants_simple('tomato')
    if options:
        for plant in options:
            print(f"  {plant['id']}: {plant['name']} ({plant['scientific_name']})")
    
    # Example 2: Get irrigation data after user selects a plant
    print("\n--- Getting irrigation data for selected plant ---")
    if options:
        selected_id = options[0]['id']  # Simulating user selection
        irrigation = plant_api.get_irrigation_data(selected_id)
        if irrigation:
            print(f"Plant: {irrigation['common_name']}")
            print(f"Watering Level: {irrigation['watering']}")
            
            # Format the watering benchmark nicely
            benchmark = irrigation['watering_general_benchmark']
            if benchmark:
                print(f"Watering Frequency: Every {benchmark['value']} {benchmark['unit']}")
            
            print(f"Drought Tolerant: {irrigation['drought_tolerant']}")
            
            # Show what the raw data looks like (for debugging)
            print("\n--- Raw irrigation data (for database) ---")
            for key, value in irrigation.items():
                print(f"  {key}: {value}")
