#!/usr/bin/env python3
"""Build and/or flash the OpenTag nRF52811 firmware through an ST-Link."""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path


EPAPER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EPAPER_DIR / "tag_fw"
DEFAULT_OPENOCD_DIR = EPAPER_DIR / "openocd"
DEFAULT_ENV = "Newton_M3_Universal"


def find_platformio(explicit: str | None) -> list[str]:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return [str(candidate)]
        found = shutil.which(explicit)
        if found:
            return [found]
        raise FileNotFoundError(f"PlatformIO executable not found: {explicit}")

    for name in ("pio", "platformio"):
        found = shutil.which(name)
        if found:
            return [found]

    # PlatformIO IDE for VS Code commonly keeps its own Windows virtualenv.
    local_platformio = Path.home() / ".platformio" / "penv" / "Scripts"
    for name in ("platformio.exe", "pio.exe"):
        candidate = local_platformio / name
        if candidate.is_file():
            return [str(candidate)]

    if importlib.util.find_spec("platformio") is not None:
        return [sys.executable, "-m", "platformio"]

    raise FileNotFoundError(
        "PlatformIO CLI was not found. Install PlatformIO or pass --platformio PATH."
    )


def run(command: list[str], cwd: Path) -> None:
    print("\n> " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and/or flash the nRF52811 tag firmware via ST-Link/OpenOCD."
    )
    parser.add_argument("--project", type=Path, default=PROJECT_DIR,
                        help=f"tag firmware project directory (default: {PROJECT_DIR})")
    parser.add_argument(
        "--openocd-dir",
        type=Path,
        help=(
            "xPack OpenOCD directory; auto-detected in ./openocd or ../openocd "
            "when omitted"
        ),
    )
    parser.add_argument("--platformio", help="PlatformIO executable path, if it is not on PATH")
    parser.add_argument("--env", default=DEFAULT_ENV, help=f"PlatformIO environment (default: {DEFAULT_ENV})")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--flash", action="store_true",
                      help="flash the existing full-flash HEX without building")
    mode.add_argument("--build", action="store_true",
                      help="build the firmware only; do not flash")
    parser.add_argument("--yes", action="store_true",
                        help="build and flash without prompting (legacy)")
    parser.add_argument("--adapter-speed", type=int, default=100,
                        help="SWD clock in kHz (default: 100)")
    parser.add_argument(
        "--connect-under-reset",
        action="store_true",
        help="connect while holding reset; requires ST-Link NRST wired to the tag",
    )
    args = parser.parse_args()

    project_dir = args.project.expanduser().resolve()
    if args.adapter_speed < 100 or args.adapter_speed > 4000:
        parser.error("--adapter-speed must be from 100 to 4000 kHz")

    if not (project_dir / "platformio.ini").is_file():
        print(f"Tag firmware project not found: {project_dir}", file=sys.stderr)
        return 2

    image = project_dir / f"{args.env}-full-flash.hex"
    if not args.flash:
        try:
            platformio = find_platformio(args.platformio)
        except FileNotFoundError as error:
            print(error, file=sys.stderr)
            return 2

        try:
            run(platformio + ["run", "-e", args.env, "-t", "clean"], project_dir)
        except subprocess.CalledProcessError as error:
            print(f"Firmware clean failed with exit code {error.returncode}.", file=sys.stderr)
            return error.returncode or 1

        build_started = time.time()
        try:
            run(platformio + ["run", "-e", args.env], project_dir)
        except subprocess.CalledProcessError as error:
            print(f"Firmware build failed with exit code {error.returncode}.", file=sys.stderr)
            return error.returncode or 1
        if not image.is_file() or image.stat().st_mtime < build_started - 2:
            print(f"Build finished, but the expected image is missing or stale: {image}", file=sys.stderr)
            return 2
        print(f"\nBuilt firmware image: {image} ({image.stat().st_size:,} bytes)")

        if args.build:
            print("Build completed; flashing skipped.")
            return 0
    else:
        if not image.is_file():
            print(f"Firmware image not found: {image}", file=sys.stderr)
            return 2
        print(f"\nUsing existing firmware image: {image} ({image.stat().st_size:,} bytes)")

    if not args.flash and not args.yes:
        try:
            answer = input("Upload firmware now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nUpload skipped.")
            return 0
        while answer not in ("", "y", "yes", "n", "no"):
            print("Please answer yes or no.")
            try:
                answer = input("Upload firmware now? [Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nUpload skipped.")
                return 0
        if answer in ("n", "no"):
            print("Upload skipped; build completed.")
            return 0

    if args.openocd_dir:
        openocd_dir = args.openocd_dir.expanduser().resolve()
    else:
        candidates = (DEFAULT_OPENOCD_DIR, EPAPER_DIR.parent / "openocd")
        openocd_dir = next(
            (
                candidate
                for candidate in candidates
                if (candidate / "bin" / "openocd.exe").is_file()
                and (candidate / "openocd" / "scripts").is_dir()
            ),
            DEFAULT_OPENOCD_DIR,
        )

    executable = openocd_dir / "bin" / "openocd.exe"
    scripts_dir = openocd_dir / "openocd" / "scripts"
    interface_cfg = scripts_dir / "interface" / "stlink.cfg"
    target_cfg = scripts_dir / "target" / "nordic" / "nrf52.cfg"
    for required in (executable, interface_cfg, target_cfg):
        if not required.is_file():
            print(f"OpenOCD file not found: {required}", file=sys.stderr)
            return 2

    print("\nFlash target: Nordic nRF52811 tag firmware over ST-Link SWD")
    print(f"Image: {image}")
    print("Connect SWDIO, SWCLK, GND, and target voltage reference. Keep the tag powered.")
    print("The HEX includes the bootloader and application image and will replace those flash regions.")
    if args.connect_under_reset:
        print("Connect the ST-Link NRST pin to the tag reset pin for connect-under-reset mode.")
    image_for_tcl = image.as_posix()
    command = f"adapter speed {args.adapter_speed}; "
    if args.connect_under_reset:
        command += "reset_config srst_only srst_nogate connect_assert_srst; "
    command += (
        "init; reset halt; "
        f"program {{{image_for_tcl}}} verify; "
        "reset run; shutdown"
    )
    openocd_command = [
        str(executable),
        "-s", str(scripts_dir),
        "-f", str(interface_cfg),
        "-c", "set CHIPNAME nrf52811",
        "-c", "transport select swd",
        "-f", str(target_cfg),
        "-c", command,
    ]
    try:
        run(openocd_command, openocd_dir)
    except subprocess.CalledProcessError as error:
        print(f"OpenOCD flash failed with exit code {error.returncode}.", file=sys.stderr)
        print(
            "If the log says 'init mode failed', programming did not start: power-cycle the "
            "tag and check SWDIO, SWCLK, GND, and target power. A detected target voltage "
            "only confirms the reference voltage, not SWD communication. "
            "If the log failed after '** Programming Started **', the flash may be partial; "
            "stabilize the wiring and power before retrying.",
            file=sys.stderr,
        )
        return error.returncode or 1

    print("\nFirmware flash and verification completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
