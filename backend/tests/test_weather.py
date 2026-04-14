import pytest
from fastmcp.exceptions import ToolError


@pytest.mark.asyncio
async def test_weather_get_current_weather_no_api_key(mcp_client, user):
    """Weather tools should raise ToolError without an API key."""
    with pytest.raises(
        ToolError,
        match="No weather credentials configured. Use PUT /api/config/weather to add your API keys.",
    ):
        await mcp_client.call_tool(
            "weather_get_current_weather", {"_user_id": user, "city": "London"}
        )


@pytest.mark.asyncio
async def test_weather_get_weather_forecast_no_api_key(mcp_client, user):
    """Weather tools should raise ToolError without an API key."""
    with pytest.raises(
        ToolError,
        match="No weather credentials configured. Use PUT /api/config/weather to add your API keys.",
    ):
        await mcp_client.call_tool(
            "weather_get_weather_forecast", {"_user_id": user, "city": "London"}
        )
