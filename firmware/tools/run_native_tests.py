#!/usr/bin/env python3
"""Compile and run every native test with C++17, strict warnings and sanitizers.

Uses only the Python standard library. Run from any working directory:
    python3 firmware/tools/run_native_tests.py
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="clang++", help="C++ compiler (default: clang++)")
    parser.add_argument("--build-dir", type=Path, help="Keep test executables in this directory")
    args = parser.parse_args()

    compiler = shutil.which(args.compiler)
    if compiler is None:
        print(f"ERROR: compiler not found: {args.compiler}", file=sys.stderr)
        return 2
    firmware = Path(__file__).resolve().parents[1]
    tests = sorted((firmware / "tests").glob("test_*.cpp"))
    sources = sorted((firmware / "lib" / "sleep_core" / "src").glob("*.cpp"))
    if not tests or not sources:
        print("ERROR: expected tests/test_*.cpp and lib/sleep_core/src/*.cpp", file=sys.stderr)
        return 2

    flags = [
        "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-g", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-I", str(firmware / "lib" / "sleep_core" / "include"),
    ]
    environment = os.environ.copy()
    # Keep caller options, but sanitizer failures must fail the test run.
    for key, required in (
        ("ASAN_OPTIONS", "halt_on_error=1:abort_on_error=1"),
        ("UBSAN_OPTIONS", "print_stacktrace=1:halt_on_error=1"),
    ):
        previous = environment.get(key, "")
        environment[key] = f"{previous}:{required}" if previous else required

    if args.build_dir is not None:
        build_dir = args.build_dir.expanduser().resolve()
        build_dir.mkdir(parents=True, exist_ok=True)
        build_context = nullcontext(str(build_dir))
    else:
        build_context = tempfile.TemporaryDirectory(prefix="sleep-core-tests-")

    try:
        with build_context as directory:
            for test in tests:
                executable = Path(directory) / test.stem
                command = [compiler, *flags, str(test), *map(str, sources), "-o", str(executable)]
                print(f"BUILD {test.name}", flush=True)
                subprocess.run(command, check=True, cwd=firmware, env=environment, timeout=120)
                print(f"RUN   {test.name}", flush=True)
                subprocess.run([str(executable)], check=True, cwd=firmware,
                               env=environment, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1

    print(f"PASS: {len(tests)} native test executables (C++17, ASAN, UBSAN)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
