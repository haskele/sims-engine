"""Weather data fetcher using Open-Meteo (free, no key required)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)


async def get_weather_forecast(
    lat: float,
    lon: float,
    target_date: date | None = None,
) -> dict[str, Any]:
    """Fetch hourly weather forecast for a stadium location.

    Parameters
    ----------
    lat, lon : float
        Stadium coordinates.
    target_date : date, optional
        Defaults to today.

    Returns
    -------
    dict
        Raw Open-Meteo API response with hourly data arrays.
    """
    if target_date is None:
        target_date = date.today()

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,windspeed_10m,winddirection_10m,precipitation_probability",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "temperature_unit": "fahrenheit",
        "windspeed_unit": "mph",
        "timezone": "America/New_York",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(settings.open_meteo_url, params=params)
        resp.raise_for_status()
        data = resp.json()
    logger.info("Weather fetched for (%.2f, %.2f) on %s", lat, lon, target_date)
    return data


def extract_game_time_weather(
    forecast: dict[str, Any],
    game_hour: int = 19,
) -> dict[str, float | None]:
    """Extract weather values for a specific hour from an Open-Meteo response.

    Parameters
    ----------
    forecast : dict
        Raw Open-Meteo response (from ``get_weather_forecast``).
    game_hour : int
        Hour of the day (0-23, local time) to extract.  Defaults to 19 (7 PM).

    Returns
    -------
    dict with keys: temperature, wind_speed, wind_dir, precip_pct
    """
    hourly = forecast.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    winds = hourly.get("windspeed_10m", [])
    dirs_ = hourly.get("winddirection_10m", [])
    precip = hourly.get("precipitation_probability", [])

    # Find the index matching the target hour
    idx = None
    for i, t in enumerate(times):
        try:
            hour = datetime.fromisoformat(t).hour
        except (ValueError, TypeError):
            continue
        if hour == game_hour:
            idx = i
            break

    if idx is None:
        logger.warning("Could not find hour=%d in forecast times", game_hour)
        return {
            "temperature": None,
            "wind_speed": None,
            "wind_dir": None,
            "precip_pct": None,
        }

    return {
        "temperature": temps[idx] if idx < len(temps) else None,
        "wind_speed": winds[idx] if idx < len(winds) else None,
        "wind_dir": dirs_[idx] if idx < len(dirs_) else None,
        "precip_pct": precip[idx] if idx < len(precip) else None,
    }
