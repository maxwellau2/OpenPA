from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import requests
from tools.credentials import get_creds

mcp = FastMCP("weather")


@mcp.tool()
async def get_current_weather(_user_id: int, city: str) -> dict:
    """
    Get the current weather for a specific city.

    Args:
        _user_id: User ID (injected automatically)
        city: The name of the city.
    """
    creds = await get_creds(_user_id, "weather")
    api_key = creds.get("api_key")
    if not api_key:
        raise ToolError("No OpenWeatherMap API key found. Please set it in settings.")

    base_url = "http://api.openweathermap.org/data/2.5/weather?"
    complete_url = f"{base_url}q={city}&appid={api_key}&units=metric"

    response = requests.get(complete_url)
    data = response.json()

    if data.get("cod") == 200:
        main = data["main"]
        weather_description = data["weather"][0]["description"]
        temperature = main["temp"]
        humidity = main["humidity"]

        return {
            "city": city,
            "temperature": temperature,
            "humidity": humidity,
            "description": weather_description,
        }
    else:
        error_message = data.get("message", f"City '{city}' not found.")
        raise ToolError(f"Error fetching weather: {error_message}")


@mcp.tool()
async def get_weather_forecast(_user_id: int, city: str, days: int = 3) -> dict:
    """
    Get the weather forecast for a specific city for the next few days.

    Args:
        _user_id: User ID (injected automatically)
        city: The name of the city.
        days: The number of days for the forecast (default is 3).
    """
    creds = await get_creds(_user_id, "weather")
    api_key = creds.get("api_key")
    if not api_key:
        raise ToolError("No OpenWeatherMap API key found. Please set it in settings.")

    base_url = "http://api.openweathermap.org/data/2.5/forecast?"
    complete_url = f"{base_url}q={city}&appid={api_key}&units=metric"

    response = requests.get(complete_url)
    data = response.json()

    if data.get("cod") == 200:
        forecast_list = data["list"]
        daily_forecast = {}

        for forecast in forecast_list:
            date = forecast["dt_txt"].split(" ")[0]
            if date not in daily_forecast:
                daily_forecast[date] = {"temperatures": [], "descriptions": []}
            daily_forecast[date]["temperatures"].append(forecast["main"]["temp"])
            daily_forecast[date]["descriptions"].append(
                forecast["weather"][0]["description"]
            )

        formatted_forecast = []
        for i, (date, values) in enumerate(daily_forecast.items()):
            if i >= days:
                break
            avg_temp = sum(values["temperatures"]) / len(values["temperatures"])
            most_common_description = max(
                set(values["descriptions"]), key=values["descriptions"].count
            )
            formatted_forecast.append(
                {
                    "date": date,
                    "average_temperature": round(avg_temp, 2),
                    "description": most_common_description,
                }
            )

        return {"city": city, "forecast": formatted_forecast}
    else:
        error_message = data.get("message", f"City '{city}' not found.")
        raise ToolError(f"Error fetching weather: {error_message}")
