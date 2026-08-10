"""List the microphone/input devices visible to the live voice pipeline."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

import live_audio_io as audio


def main():
    devices = audio.list_input_devices()

    if not devices:
        print("No PortAudio input devices were found.")
        raise SystemExit(1)

    print("\nAvailable microphone/input devices:\n")

    for item in devices:
        print(
            f"[{item['index']}] {item['name']} "
            f"(inputs={item['max_input_channels']}, "
            f"default_rate={item['default_sample_rate']})"
        )

    print("\nCurrent selection:")
    try:
        info = audio.selected_input_device_info()
        print(f"  [{int(info['index'])}] {info.get('name')}")
    except Exception as exc:
        print(f"  Could not determine it: {exc}")

    print(
        "\nSet the physical microphone you want in .env, for example:\n"
        "LIVE_INPUT_DEVICE_INDEX=3\n"
    )
    print(
        "Avoid devices named Stereo Mix, Loopback, Monitor, "
        "CABLE Output, or other virtual/system-audio capture devices."
    )


if __name__ == "__main__":
    main()
