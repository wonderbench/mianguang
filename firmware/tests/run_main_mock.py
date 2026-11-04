#!/usr/bin/env python3
"""Test actual main.cpp with Arduino/Wire mocks, then parse emitted JSON logs.

Only Python's standard library and clang++ are required. This separate runner
keeps Arduino adapter mocks outside the native test_*.cpp discovery directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def validate_logs(output: str) -> None:
    records = {}
    for line in output.splitlines():
        if not line.startswith("LOG "):
            continue
        _, fixture, payload = line.split(" ", 2)
        if fixture in records:
            raise ValueError(f"duplicate fixture: {fixture}")
        record = json.loads(payload, parse_constant=reject_nonfinite)
        assert record["schema"] == 1 and record["type"] == "sample"
        assert isinstance(record["installation_confirmed"], bool)
        assert isinstance(record["presence"]["valid"], bool)
        records[fixture] = record

    assert set(records) == {"i2c_expiry", "manual_priority", "max_values"}
    expired = records["i2c_expiry"]
    assert expired["t_ms"] == expired["clock_ms"] == 10025
    assert expired["presence"]["age_ms"] == 5025
    assert expired["presence"]["valid"] is False
    assert expired["presence"]["reason"] == "stale"
    assert expired["lamp"]["target"] == expired["lamp"]["pwm"] == 0
    assert expired["ambient"]["known"] is True
    assert expired["ambient"]["estimated_lux"] == 0.0

    manual = records["manual_priority"]
    assert manual["lamp"] == {"mode": "manual", "pwm": 96, "target": 96}
    assert manual["transport_ok"] is False
    assert manual["last_command"] == "radar_disabled_high_z"

    maximum = records["max_values"]
    assert maximum["t_ms"] == 2**64 - 1
    assert maximum["hr"]["raw"] == maximum["rr"]["raw"] == 65535
    assert maximum["hr"]["reason"] == "out_of_range"
    assert maximum["vendor_stage"]["raw"] == 254
    assert maximum["vendor_stage"]["valid"] is False
    assert all(value == 2**32 - 1 for value in maximum["parser"].values())


def main() -> int:
    firmware = Path(__file__).resolve().parents[1]
    compiler = shutil.which("clang++")
    if compiler is None:
        print("ERROR: clang++ is required", file=sys.stderr)
        return 2
    integration = firmware / "tests" / "integration"
    sources = sorted((firmware / "lib" / "sleep_core" / "src").glob("*.cpp"))
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "halt_on_error=1:abort_on_error=1"
    environment["UBSAN_OPTIONS"] = "print_stacktrace=1:halt_on_error=1"
    try:
        with tempfile.TemporaryDirectory(prefix="sleep-main-mock-") as directory:
            executable = Path(directory) / "test_main"
            command = [
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", '-DMIANGUANG_VERSION="mock-test"',
                "-I", str(integration / "mocks"), "-I", str(firmware / "include"),
                "-I", str(firmware / "lib" / "sleep_core" / "include"),
                str(integration / "test_main.cpp"), *map(str, sources), "-o", str(executable),
            ]
            subprocess.run(command, check=True, env=environment, timeout=120)
            completed = subprocess.run([str(executable)], check=True, env=environment,
                                       text=True, capture_output=True, timeout=60)
            validate_logs(completed.stdout)
            for line in completed.stdout.splitlines():
                if not line.startswith("LOG "):
                    print(line)
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.TimeoutExpired, ValueError, AssertionError, KeyError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print("PASS: actual main.cpp mock assertions and 3 parsed JSON log fixtures (ASAN, UBSAN)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
