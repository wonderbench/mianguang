#!/usr/bin/env python3
"""Capture local USB CDC JSONL. No network, auto-port selection or flashing."""
import argparse
import gzip
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Explicit USB serial device")
    parser.add_argument("--output", type=Path, required=True, help="New .jsonl or .jsonl.gz file")
    parser.add_argument("--seconds", type=float, default=0, help="0: until Ctrl-C")
    parser.add_argument("--confirm-powered", action="store_true", help="Confirm real radar 5V, then enable UART")
    parser.add_argument("--confirm-installation", action="store_true", help="Confirm verified position/angle/range")
    parser.add_argument("--confirm-ambient", action="store_true", help="Confirm actual BH1750 and optical threshold check")
    args = parser.parse_args()
    if args.seconds < 0:
        parser.error("--seconds must be >= 0")
    if args.output.exists():
        parser.error("output exists; choose a new filename")
    try:
        import serial
    except ImportError:
        parser.error("pyserial is required; use the project .tooling/pio Python or install pyserial==3.5")
    commands = []
    if args.confirm_powered: commands.append("radar on")
    if args.confirm_installation: commands.append("install yes")
    if args.confirm_ambient: commands.append("ambient yes")
    started = time.monotonic()
    configured = False
    rows = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if args.output.suffix == ".gz" else open
    try:
        with serial.Serial(args.port, 115200, timeout=0.5, write_timeout=1) as stream:
            with opener(args.output, "xt", encoding="utf-8") as output:
                print("Recording locally. Ctrl-C stops. Confirmations are sent once after the first device sample.")
                while not args.seconds or time.monotonic() - started < args.seconds:
                    line = stream.readline(8192)
                    if not line:
                        if not configured and time.monotonic() - started > 15:
                            raise RuntimeError("No device sample after 15s; verify port/firmware. No commands sent.")
                        continue
                    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    output.write(text + "\n")
                    output.flush()
                    rows += 1
                    if not configured:
                        try:
                            value = json.loads(text)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(value, dict) or value.get("schema") != 1 or value.get("type") != "sample":
                            continue
                        for command in commands:
                            stream.write((command + "\n").encode("ascii"))
                        configured = True
                        print("Device ready; commands:", ", ".join(commands) or "none (observe only)")
    except KeyboardInterrupt:
        print("Stopped.")
    except (OSError, RuntimeError, serial.SerialException) as error:
        print(f"Capture error: {error}", file=sys.stderr)
        return 1
    print(f"Saved {rows} lines to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
