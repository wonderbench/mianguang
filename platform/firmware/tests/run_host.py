#!/usr/bin/env python3
"""Check actual firmware serialization against the existing ingestion contract."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="clang++")
    parser.add_argument("--sanitizers", action="store_true")
    args = parser.parse_args()
    compiler = shutil.which(args.compiler)
    if not compiler:
        parser.error(f"compiler not found: {args.compiler}")
    root = Path(__file__).resolve().parents[3]
    network = root / "platform/firmware"
    core = root / "firmware/lib/sleep_core"
    flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1",
             '-DMIANGUANG_VERSION="0.3.0-dev"', "-I", str(network / "include"),
             "-I", str(core / "include")]
    if args.sanitizers:
        flags += ["-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                  "-fno-omit-frame-pointer"]
    try:
        with tempfile.TemporaryDirectory(prefix="mianguang-network-") as directory:
            executable = Path(directory) / "test_network"
            subprocess.run([compiler, *flags, str(network / "tests/test_network.cpp"),
                            str(network / "src/network_core.cpp"),
                            str(core / "src/monitor_logic.cpp"), "-o", str(executable)],
                           check=True, timeout=120)
            output = subprocess.run([str(executable)], check=True, capture_output=True,
                                    text=True, timeout=15).stdout
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1

    sys.path.insert(0, str(root / "platform/app"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
    import django
    django.setup()
    from monitoring.services.ingestion import parse_payload, validate_quality

    packets = []
    for line in output.splitlines():
        payload, _, _ = parse_payload(line.encode())
        validate_quality(payload)
        packets.append(payload)
    assert len(packets) == 3
    normal, disabled, limits = packets
    assert normal["captured_at"] == "2024-01-01T00:00:00.123Z"
    for field, raw, age in (("presence", 1, 100), ("bed", 1, 200), ("rr", 16, 80), ("hr", 70, 20)):
        assert normal["sample"][field] == {"raw": raw, "available": True,
            "valid": True, "reason": "ok", "age_ms": age}
    assert disabled["binding_id"] is None and not disabled["sample"]["radar_enabled"]
    assert not disabled["sample"]["ready"]
    for field in ("presence", "bed", "rr", "hr", "low_motion"):
        assert not disabled["sample"][field]["available"]
        assert not disabled["sample"][field]["valid"]
    assert limits["boot_id"] == limits["seq"] == 2**32 - 1
    assert limits["uptime_ms"] == 2**53 - 1
    assert limits["sample"]["lamp"] == {"mode": "manual", "pwm": 255, "target": 255}
    print("PASS: 3 actual evaluate→Snapshot→JSON ingestion checks; stable retry bytes, sequence exhaustion and bounded backoff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
