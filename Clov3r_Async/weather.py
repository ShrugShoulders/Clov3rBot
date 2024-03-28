import requests
import json
import asyncio

class WeatherSnag:
    def __init__(self):
        self.api_key = ""
        self.user_agent = "Clov3r_forecast, your@email.com"

    async def geocode_location(self, location):
        # If the location is empty, return None
        if not location:
            return None, None

        try:
            # Make a request to retrieve the latitude and longitude for the location
            response = requests.get(f"https://geocode.maps.co/search?q={location}&api_key={self.api_key}")
            print("Geocoding response status code:", response.status_code)
            print("Geocoding response content:", response.content)
            
            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                # Parse the JSON response
                data = response.json()
                
                # Extract latitude and longitude from the first place_id
                if data:
                    first_place = data[0]
                    latitude = round(float(first_place["lat"]), 4)
                    longitude = round(float(first_place["lon"]), 4)
                    return latitude, longitude

            # If unable to get latitude and longitude from the location
            print("Unable to geocode the location:", location)
            return None, None
            
        except Exception as e:
            print("An error occurred while geocoding:", e)
            return None, None

    async def get_weather(self, location, channel):
        # Set your user agent
        #user_agent = "Clov3r_forecast, connorkim.kim3@gmail.com"

        # Get latitude and longitude from geocoding
        lat, lon = await self.geocode_location(location)

        # If unable to geocode the location, respond accordingly
        if lat is None or lon is None:
            response = f"PRIVMSG {channel} :Unable to get latitude and longitude for the location: {location}."
            #await self.send(response)
            return response

        # Get the forecast data for the given latitude and longitude
        try:
            # Make a request to retrieve the weather forecast data
            response = requests.get(f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}", headers={"User-Agent": self.user_agent})
            print("Response status code:", response.status_code)
            print("Response content:", response.content)
            
            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                # Parse the JSON response
                data = response.json()
                
                # Extract relevant weather information
                timeseries = data.get("properties", {}).get("timeseries", [])
                
                if timeseries:
                    # Get the current forecast (first entry in timeseries)
                    current_forecast = timeseries[0]
                    print("Current forecast:", current_forecast)
                    
                    # Extract data from the current forecast
                    instant_details = current_forecast.get("data", {}).get("instant", {}).get("details", {})
                    print("Instant details:", instant_details)
                    next_1_hours_summary = current_forecast.get("data", {}).get("next_1_hours", {}).get("summary", {})
                    print("Next 1 hour summary:", next_1_hours_summary)
                    next_6_hours_summary = current_forecast.get("data", {}).get("next_6_hours", {}).get("summary", {})
                    print("Next 6 hours summary:", next_6_hours_summary)

                    # Calculate temperature in Fahrenheit
                    celsius_temp = instant_details.get('air_temperature')
                    fahrenheit_temp = (celsius_temp * 9/5) + 32
                    
                    # Construct weather forecast message
                    forecast_message = f"[\x0311{location}\x03]:" #, lat={lat}, lon={lon}
                    temp_message = f"Current temperature: {celsius_temp}C/{fahrenheit_temp}F"
                    cloud_message = f"Cloud coverage: {instant_details.get('cloud_area_fraction')}%"
                    humidity_message = f"Humidity: {instant_details.get('relative_humidity')}%"
                    wind_direction = f"Wind Direction: {instant_details.get('wind_from_direction')}"
                    wind_speed = f"Wind Speed: {instant_details.get('wind_speed')}"
                    nxt1hr_message = f"Next 1 hour: {next_1_hours_summary.get('symbol_code', 'N/A')}"
                    nxt6hr_message = f"Next 6 hours: {next_6_hours_summary.get('symbol_code', 'N/A')}"
                    
                    # Send weather forecast to the channel
                    response = f"PRIVMSG {channel} :{forecast_message} " + f"{temp_message} " + f"{cloud_message} " + f"{humidity_message} " + f"{wind_speed} " + f"{wind_direction} " + f"{nxt1hr_message} " + f"{nxt6hr_message} "
                    #await self.send(response)
                    return response
                
            # If no forecast available
            response = f"PRIVMSG {channel} :No forecast available for location: {location}."
            #await self.send(response)
            return response
            
        except Exception as e:
            print("An error occurred:", e)
            response = f"PRIVMSG {channel} :An error occurred while fetching weather information."
            #await self.send(response)
            return response
