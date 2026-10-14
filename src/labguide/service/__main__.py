"""Frozen entry point for the LabGuide sidecar and its probe children.

PyInstaller bundles ignore `-m` and re-run this entry with any arguments,
so a probe child spawned from the packaged sidecar is re-dispatched here to
the probe CLI. Everything else starts the JSON-RPC stdio service.
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--ui-probe":
        from labguide.ui_probe import main as probe_main

        return probe_main(sys.argv[2:])
    from labguide.service.server import main as service_main

    return service_main()


if __name__ == "__main__":
    raise SystemExit(main())