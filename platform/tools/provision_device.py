#!/usr/bin/env python3
"""Configure one device over explicit USB; never print or read back secrets."""
import argparse
import getpass
import json
from pathlib import Path
import re
import stat
import sys
import time
from urllib.parse import urlsplit
from uuid import UUID


FIELDS = {"device_id", "binding_id", "endpoint", "token", "wifi_ssid",
          "wifi_password", "ntp_server", "ca_pem"}


def load_config(args):
    if args.config:
        if stat.S_IMODE(args.config.stat().st_mode) != 0o600:
            raise ValueError("Configuration file must have mode 0600 (chmod 600).")
        try:
            config = json.loads(args.config.read_text(encoding="utf-8"))
        except (UnicodeError, ValueError):
            raise ValueError("Configuration file must contain a UTF-8 JSON object.") from None
        if not isinstance(config, dict):
            raise ValueError("Configuration must be an object.")
    else:
        if not sys.stdin.isatty():
            raise ValueError("Interactive secrets require a terminal; use a mode-0600 file otherwise.")
        config = {
            "device_id": input("Platform device_id UUID: ").strip(),
            "binding_id": input("Platform binding_id UUID (blank: unbound): ").strip() or None,
            "endpoint": input("Full HTTPS telemetry endpoint: ").strip(),
            "token": getpass.getpass("Device token (hidden): "),
            "wifi_ssid": input("Wi-Fi SSID: "),
            "wifi_password": getpass.getpass("Wi-Fi password (hidden; blank for open network): "),
            "ntp_server": input("NTP host [pool.ntp.org]: ").strip() or "pool.ntp.org",
        }
        if not args.ca:
            args.ca = Path(input("Server CA PEM file: ").strip())
    if args.ca:
        config["ca_pem"] = args.ca.read_text(encoding="ascii")
    validate_config(config)
    config["new_identity"] = args.new_identity
    wire = ("net configure " + json.dumps(config, ensure_ascii=True, separators=(",", ":"))).encode("ascii")
    if len(wire) > 8191:
        raise ValueError("Encoded configuration exceeds the firmware's 8191-byte command limit.")
    return wire + b"\n"


def validate_config(config):
    if set(config) != FIELDS:
        raise ValueError("Configuration needs exactly: " + ", ".join(sorted(FIELDS)) + ".")
    for name in ("device_id", "binding_id"):
        value = config[name]
        if name == "binding_id" and value is None:
            continue
        try:
            if not isinstance(value, str) or str(UUID(value)) != value.lower():
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError(name + " must be a hyphenated UUID.") from None
        config[name] = value.lower()
    if not isinstance(config["token"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", config["token"]):
        raise ValueError("token must be the platform's 43-character base64url credential.")
    for name, maximum in (("wifi_ssid", 32), ("wifi_password", 64), ("endpoint", 192),
                          ("ntp_server", 128), ("ca_pem", 4096)):
        value = config[name]
        if not isinstance(value, str) or "\0" in value or len(value.encode("utf-8")) > maximum:
            raise ValueError(name + " must be a string within the firmware byte limit.")
        if not value and name != "wifi_password":
            raise ValueError(name + " must not be empty.")
    endpoint = urlsplit(config["endpoint"])
    if (endpoint.scheme != "https" or endpoint.geturl() != config["endpoint"]
            or not endpoint.hostname or endpoint.hostname[0] in ".-" or endpoint.hostname[-1] in ".-"
            or endpoint.username is not None
            or endpoint.password is not None or endpoint.query or endpoint.fragment
            or endpoint.path != "/api/device/v1/telemetry"
            or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", endpoint.netloc)):
        raise ValueError("endpoint must be an HTTPS DNS/IPv4 URL ending in /api/device/v1/telemetry.")
    if endpoint.port is not None and not 1 <= endpoint.port <= 65535:
        raise ValueError("endpoint port must be 1..65535.")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", config["ntp_server"]):
        raise ValueError("ntp_server must be a DNS/IPv4 host, without scheme or path.")
    if ("-----BEGIN CERTIFICATE-----" not in config["ca_pem"]
            or "-----END CERTIFICATE-----" not in config["ca_pem"]):
        raise ValueError("ca_pem must contain the HTTPS server's trusted PEM CA certificate.")


def wait_for(stream, predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            record = json.loads(stream.readline(8192))
        except (ValueError, UnicodeError):
            continue
        if isinstance(record, dict) and predicate(record):
            return record
    raise RuntimeError(message)


def provision(stream, wire):
    stream.write(b"net status\n")
    wait_for(stream, lambda row: row.get("type") == "network" and row.get("status") == "status",
             15, "No network firmware status received; configuration was not sent.")
    stream.write(b"radar off\n")
    wait_for(stream, lambda row: row.get("schema") == 1 and row.get("type") == "sample"
             and row.get("client_state") == 0 and row.get("last_command") == "radar_disabled_high_z",
             10, "Radar-off acknowledgement not received; configuration was not sent.")
    stream.write(wire)
    reply = wait_for(stream, lambda row: row.get("type") == "network"
                     and row.get("status") in ("configured", "config_error"),
                     30, "No final configuration acknowledgement. Check device status before retrying.")
    if reply["status"] != "configured" or reply.get("restarting") is not True:
        raise RuntimeError("Firmware rejected configuration or did not acknowledge its restart.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Explicit USB serial port; required unless --check")
    parser.add_argument("--config", type=Path, help="Mode-0600 JSON file; otherwise prompt interactively")
    parser.add_argument("--ca", type=Path, help="CA PEM file, replaces ca_pem in the private config")
    parser.add_argument("--new-identity", action="store_true", help="A newly registered, different device UUID")
    parser.add_argument("--check", action="store_true", help="Validate locally without opening USB")
    args = parser.parse_args(argv)
    if not args.check and not args.port:
        parser.error("--port is required unless --check")
    try:
        wire = load_config(args)
    except (OSError, UnicodeError):
        parser.error("Could not read the configuration or CA file.")
    except ValueError as error:
        parser.error(str(error))
    if args.check:
        print("Configuration valid; USB was not opened. Secrets are hidden.")
        return 0
    try:
        import serial
    except ImportError:
        parser.error("pyserial is required; install pyserial==3.5 in your tooling environment.")
    try:
        with serial.Serial(args.port, 115200, timeout=0.5, write_timeout=5) as stream:
            provision(stream, wire)
    except (OSError, serial.SerialException):
        print("USB I/O failed. Configuration may have been saved; inspect device status before retrying.", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Inspect device status before retrying.", file=sys.stderr)
        return 1
    print("Firmware confirmed that configuration was saved and restart is pending. Secrets were not read back.")
    print("After restart, verify net status and platform receipt; perform the existing on-site confirmations separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
