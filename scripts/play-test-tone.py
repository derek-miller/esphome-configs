#!/usr/bin/env python3
"""Play a test tone on an ESPHome media player device.

Generates a WAV tone in memory, serves it via a temporary HTTP server,
and tells the ESPHome device to play it.
"""

import asyncio
import io
import socket
import struct
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler

from aioesphomeapi import APIClient, MediaPlayerInfo
from aioesphomeapi.core import APIConnectionError, ReadFailedAPIError


def get_local_ip(device_ip):
    """Get local IP address reachable by the device."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((device_ip, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def generate_wav(freq=440, duration=5, sample_rate=16000, volume=0.25):
    """Generate a sine wave WAV file in memory."""
    import math

    num_samples = sample_rate * duration
    buf = io.BytesIO()

    # WAV header
    data_size = num_samples * 2  # 16-bit mono
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))

    for i in range(num_samples):
        sample = volume * math.sin(2 * math.pi * freq * i / sample_rate)
        buf.write(struct.pack("<h", int(sample * 32767)))

    buf.seek(0)
    return buf.read()


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


async def play(host, port=6053):
    """Connect to ESPHome device and play the test tone."""
    local_ip = get_local_ip(host)
    serve_port = 8123
    wav_data = generate_wav()

    print(f"Generating 440Hz test tone (3s)...")
    server = serve_wav(wav_data, serve_port)
    url = f"http://{local_ip}:{serve_port}/tone-{int(time.time())}.wav"

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
        print(f"Found media player: {mp.name} (key={mp.key})")
        print(f"Playing {url} ...")

        # Stop any previous playback first to reset I2S state
        client.media_player_command(mp.key, command=2)  # STOP
        await asyncio.sleep(0.5)
        client.media_player_command(mp.key, volume=0.35)
        await asyncio.sleep(0.2)

        client.media_player_command(mp.key, media_url=url)

        # Keep server alive while audio plays
        await asyncio.sleep(5)

        print("Stopping playback...")
        client.media_player_command(mp.key, command=2)  # STOP

        await asyncio.sleep(0.5)
        print("Done.")
        try:
            await client.disconnect()
        except (APIConnectionError, ReadFailedAPIError, ConnectionResetError) as exc:
            print(f"Disconnect warning: {exc}")
    finally:
        server.shutdown()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <device-ip>")
        sys.exit(1)
    asyncio.run(play(sys.argv[1]))
