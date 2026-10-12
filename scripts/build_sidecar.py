"""Build the LabGuide sidecar executable for the Tauri shell.

Produces sidecar-dist/labguide-sidecar-<target-triple>.exe — the name and
location Tauri's externalBin convention expects. Run from the repo root:

    python scripts/build_sidecar.py

The output directory is a build artifact and is not committed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Tauri resolves externalBin relative to src-tauri/, so the sidecar lives
# under desktop/. This keeps the shell and its binary in one place.
OUTPUT_DIR = REPO_ROOT / "desktop" / "sidecar-dist"
BINARY_BASENAME = "labguide-sidecar"

# Keep in sync with migration plan phase 1: the service entry point is the
# only thing the sidecar should expose.
ENTRY_POINT = REPO_ROOT / "src" / "labguide" / "service" / "__main__.py"


def _rustc() -> str:
    """Locate rustc: PATH first, then the default rustup install location."""
    candidate = Path.home() / ".cargo" / "bin" / ("rustc.exe" if sys.platform == "win32" else "rustc")
    if candidate.exists():
        return str(candidate)
    return "rustc"


def target_triple() -> str:
    """Host target triple, e.g. x86_64-pc-windows-msvc (matches tauri's naming)."""
    output = subprocess.run(
        [_rustc(), "-Vv"], capture_output=True, text=True, check=True
    ).stdout
    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split()[-1]
    raise RuntimeError("could not determine rustc host triple")


def build(backend: str = "onefile") -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    workpath = OUTPUT_DIR / "_build"
    spec_name = f"{BINARY_BASENAME}_{backend}"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--{backend}",
        "--name",
        spec_name,
        "--distpath",
        str(OUTPUT_DIR),
        "--workpath",
        str(workpath),
        "--specpath",
        str(workpath),
        # stdout is the JSON-RPC channel; keep the console subsystem so
        # stdio pipes work. Tauri spawns sidecars with CREATE_NO_WINDOW on
        # Windows, so no console window flashes for the end user.
        str(ENTRY_POINT),
    ]
    subprocess.run(command, check=True)

    suffix = ".exe" if sys.platform == "win32" else ""
    if backend == "onefile":
        built = OUTPUT_DIR / f"{spec_name}{suffix}"
    else:
        built = OUTPUT_DIR / spec_name / f"{spec_name}{suffix}"
    if not built.exists():
        raise RuntimeError(f"PyInstaller did not produce {built}")

    final = OUTPUT_DIR / f"{BINARY_BASENAME}-{target_triple()}{suffix}"
    final.write_bytes(built.read_bytes())
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=["onefile", "onedir"],
        default="onefile",
        help="PyInstaller backend (onefile is the default; onedir starts faster)",
    )
    args = parser.parse_args()
    output = build(args.backend)
    print(f"sidecar built: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
