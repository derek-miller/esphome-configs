#!/usr/bin/env python3
"""Get a brief weather report using OpenAI and the free Open-Meteo API."""

import json
import sys
import urllib.parse
import urllib.request

import usaddress
from openai import OpenAI


def _nominatim(query):
    """Try Nominatim (OpenStreetMap) geocoding."""
    encoded = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=1&countrycodes=us"
    req = urllib.request.Request(url, headers={"User-Agent": "esphome-weather/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", query).split(",")[0]
    return None


def geocode(query):
    """Convert an address/city/zip to lat/lon using usaddress parser + Nominatim."""
    # Try full query first
    result = _nominatim(query)
    if result:
        return result

    # Parse the address and extract city/state/zip
    try:
        tagged, _ = usaddress.tag(query)
        parts = []
        for key in ("PlaceName", "StateName", "ZipCode"):
            if key in tagged:
                parts.append(tagged[key])
        if parts:
            result = _nominatim(" ".join(parts))
            if result:
                return result
    except usaddress.RepeatedLabelError:
        pass

    print(f"Error: could not geocode '{query}'", file=sys.stderr)
    sys.exit(1)


def get_weather(lat: float, lon: float):
    """Fetch current weather from Open-Meteo (no API key needed)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&forecast_days=1&timezone=auto"
    )
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def summarize(weather_data, location_name):
    """Use OpenAI to turn raw weather data into a natural 1-2 sentence report."""
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a concise weather announcer. Given weather data, produce a 1-2 sentence spoken weather report that mentions the city name. No greetings, no sign-offs. Just the weather. Use natural language, not numbers like 'temperature_2m'.",
            },
            {"role": "user", "content": f"Location: {location_name}\n\n{json.dumps(weather_data, indent=2)}"},
        ],
        max_tokens=100,
    )
    return response.choices[0].message.content.strip()


if __name__ == "__main__":
    lat, lon, name = geocode(query = " ".join(sys.argv[1:]))
    print(f"Location: {name} ({lat}, {lon})", file=sys.stderr)
    weather = get_weather(lat, lon)
    report = summarize(weather, name)
    print(report)