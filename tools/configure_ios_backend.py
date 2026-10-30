"""Configure this Mac's non-secret backend address for a physical iPhone debug build."""

import re
import subprocess
from pathlib import Path

from splitwise_ledger.api import Settings


def main():
    host = subprocess.check_output(["scutil", "--get", "LocalHostName"], text=True).strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+", host):
        raise SystemExit("Unexpected local host name; configuration was not written.")
    root = Path(__file__).resolve().parents[1]
    # xcconfig treats // as a comment; $() safely separates the URL slashes.
    target = root / "ios" / "Development.local.xcconfig"
    settings = Settings()
    if settings.google_sheet_id or settings.google_summary_tab:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", settings.google_sheet_id):
            raise SystemExit("Set a valid GOOGLE_SHEET_ID or leave both sheet settings empty.")
        if not settings.google_summary_tab or any(
            c in settings.google_summary_tab for c in "\n\r/$"
        ):
            raise SystemExit("Set a valid GOOGLE_SUMMARY_TAB or leave both sheet settings empty.")
    target.write_text(
        f"MINTO_BACKEND_URL = http:/$()/{host}.local:8000\n"
        f"MINTO_SHEET_ID = {settings.google_sheet_id}\n"
        f"MINTO_SUMMARY_TAB = {settings.google_summary_tab}\n"
    )
    print("Configured the physical-device development endpoint. No credentials were written.")
    print(f"Splitwise callback for this Mac: http://{host}.local:8000/oauth/splitwise/callback")


if __name__ == "__main__":
    main()
