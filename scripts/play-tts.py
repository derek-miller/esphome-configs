#!/usr/bin/env python3
"""Play text-to-speech on an ESPHome media player device.

Uses OpenAI's TTS API to generate audio, serves it locally,
and tells the ESPHome device to play it.

Requires OPENAI_API_KEY environment variable.
"""

import asyncio
import io
import os
import socket
import struct
import sys
import threading
import time
import wave
from http.server import HTTPServer, SimpleHTTPRequestHandler

from aioesphomeapi import APIClient, MediaPlayerInfo
from aioesphomeapi.core import APIConnectionError, ReadFailedAPIError
from openai import OpenAI


def get_local_ip(device_ip):
    """Get local IP address reachable by the device."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((device_ip, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def resample_wav(wav_data, target_rate=16000):
    """Resample WAV data to target sample rate."""
    with wave.open(io.BytesIO(wav_data), "rb") as src:
        src_rate = src.getframerate()
        n_channels = src.getnchannels()
        sampwidth = src.getsampwidth()
        frames = src.readframes(src.getnframes())

    if src_rate == target_rate:
        return wav_data

    # Simple linear resampling
    n_samples = len(frames) // (sampwidth * n_channels)
    ratio = target_rate / src_rate
    new_n_samples = int(n_samples * ratio)

    fmt = f"<{n_samples}h" if sampwidth == 2 else f"<{n_samples}b"
    samples = struct.unpack(fmt, frames)

    new_samples = []
    for i in range(new_n_samples):
        src_idx = i / ratio
        idx = int(src_idx)
        if idx >= n_samples - 1:
            new_samples.append(samples[-1])
        else:
            frac = src_idx - idx
            val = int(samples[idx] * (1 - frac) + samples[idx + 1] * frac)
            new_samples.append(val)

    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(target_rate)
        dst.writeframes(struct.pack(f"<{len(new_samples)}h", *new_samples))

    return out.getvalue()


def generate_tts(text, voice="alloy"):
    """Generate WAV audio from text using OpenAI TTS API."""
    client = OpenAI()
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        response_format="wav",
    )
    raw = response.read()
    # Resample to 16kHz mono which the ESP32 handles well
    return resample_wav(raw, 16000)


def serve_wav(wav_data, port=8123):
    """Serve WAV data on a temporary HTTP server."""

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", len(wav_data))
            self.end_headers()
            try:
                self.wfile.write(wav_data)
            except BrokenPipeError:
                print("  HTTP: client closed stream early")

        def log_message(self, format, *args):
            print(f"  HTTP: {self.requestline}")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def play(host, text, voice="alloy", port=6053):
    """Connect to ESPHome device and play TTS audio."""
    local_ip = get_local_ip(host)
    serve_port = 8123

    print(f"Generating TTS: \"{text}\"")
    wav_data = generate_tts(text, voice)
    print(f"Got {len(wav_data)} bytes of audio")

    server = serve_wav(wav_data, serve_port)
    url = f"http://{local_ip}:{serve_port}/tts-{int(time.time())}.wav"

    try:
        print(f"Connecting to {host}:{port}...")
        client = APIClient(host, port, password="")
        await client.connect(login=True)

        entities = await client.list_entities_services()
        media_players = [e for e in entities[0] if isinstance(e, MediaPlayerInfo)]

        if not media_players:
            print("Error: no media player entities found on device")
            return

        mp = media_players[0]
        print(f"Playing on: {mp.name}")

        # Reset the speaker pipeline in case the previous stream left I2S busy.
        client.media_player_command(mp.key, command=2)  # STOP
        await asyncio.sleep(0.5)
        client.media_player_command(mp.key, volume=0.35)
        await asyncio.sleep(0.2)
        client.media_player_command(mp.key, media_url=url)

        # Keep server alive — estimate duration from file size
        # 16-bit mono 16kHz = ~32KB/s
        duration = max(len(wav_data) / 32000, 5) + 2
        await asyncio.sleep(duration)
        print("Done.")
        try:
            await client.disconnect()
        except (APIConnectionError, ReadFailedAPIError, ConnectionResetError) as exc:
            print(f"Disconnect warning: {exc}")
    finally:
        server.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <device-ip> <text> [voice]")
        print(f"Voices: alloy, echo, fable, onyx, nova, shimmer")
        sys.exit(1)

    host = sys.argv[1]
    text = sys.argv[2]
    voice = sys.argv[3] if len(sys.argv) > 3 else "alloy"
    asyncio.run(play(host, text, voice))
