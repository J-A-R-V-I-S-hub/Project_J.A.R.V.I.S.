from __future__ import annotations

import httpx

WEATHER_CODES = {
    0: "sereno",
    1: "prevalentemente sereno",
    2: "parzialmente nuvoloso",
    3: "nuvoloso",
    45: "nebbia",
    48: "nebbia con brina",
    51: "pioviggine debole",
    53: "pioviggine",
    55: "pioviggine intensa",
    61: "pioggia debole",
    63: "pioggia",
    65: "pioggia forte",
    71: "neve debole",
    73: "neve",
    75: "neve forte",
    80: "rovesci deboli",
    81: "rovesci",
    82: "rovesci violenti",
    95: "temporale",
    96: "temporale con grandine",
    99: "temporale forte con grandine",
}


def _describe(code: int | None) -> str:
    return WEATHER_CODES.get(int(code or 0), "condizioni variabili")


def get_weather(
    location: str = "Casteggio",
    latitude: float | None = None,
    longitude: float | None = None,
    timezone: str = "Europe/Rome",
) -> str:
    """Meteo attuale e previsione di oggi per una località (Open-Meteo, senza chiave API)."""
    try:
        with httpx.Client(timeout=12) as client:
            resolved_name = location
            if latitude is None or longitude is None:
                geo = client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1, "language": "it", "format": "json"},
                )
                geo.raise_for_status()
                results = geo.json().get("results") or []
                if not results:
                    return f"Non ho trovato la località '{location}'."
                place = results[0]
                latitude = place["latitude"]
                longitude = place["longitude"]
                resolved_name = ", ".join(
                    part for part in (place.get("name"), place.get("admin1"), place.get("country")) if part
                )

            forecast = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": timezone,
                    "forecast_days": 1,
                },
            )
            forecast.raise_for_status()
            data = forecast.json()
    except Exception as exc:  # network / API errors must not break the bot
        return f"Non riesco a recuperare il meteo: {exc}"

    current = data.get("current") or {}
    daily = data.get("daily") or {}
    max_temp = (daily.get("temperature_2m_max") or [None])[0]
    min_temp = (daily.get("temperature_2m_min") or [None])[0]
    rain = (daily.get("precipitation_probability_max") or [None])[0]

    lines = [
        f"🌤️ **Meteo — {resolved_name}**",
        (
            f"Adesso: {current.get('temperature_2m')}°C (percepiti {current.get('apparent_temperature')}°C), "
            f"{_describe(current.get('weather_code'))}, vento {current.get('wind_speed_10m')} km/h."
        ),
    ]
    if max_temp is not None and min_temp is not None:
        lines.append(f"Oggi: min {min_temp}°C / max {max_temp}°C.")
    if rain is not None:
        lines.append(f"Probabilità di precipitazioni: {rain}%.")
    return "\n".join(lines)
