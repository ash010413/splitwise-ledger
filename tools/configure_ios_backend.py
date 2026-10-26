"""Configure this Mac's non-secret backend address for a physical iPhone debug build."""

import re
import subprocess
from pathlib import Path


def main():
    host = subprocess.check_output(["scutil", "--get", "LocalHostName"], text=True).strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+", host):
        raise SystemExit("Unexpected local host name; configuration was not written.")
    root = Path(__file__).resolve().parents[1]
    # xcconfig treats // as a comment; $() safely separates the URL slashes.
    target = root / "ios" / "Development.local.xcconfig"
    target.write_text(f"MINTO_BACKEND_URL = http:/$()/{host}.local:8000\n")
    print("Configured the physical-device development endpoint. No credentials were written.")


if __name__ == "__main__":
    main()
