"""Launch a simulator debug build with developer-owned auth; never print credentials.

Run after installing the app: .venv/bin/python tools/run_ios_development.py
The Gemini key stays in .env on the backend. Only the application session token is
provisioned to this local debug app, where it is saved in device-only Keychain.
"""

import argparse
import os
import subprocess

from splitwise_ledger.api import Settings


def main():
    parser = argparse.ArgumentParser(description="Launch Minto on a booted iOS simulator")
    parser.add_argument("--device", default="booted")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    settings = Settings()
    child_env = os.environ.copy()
    child_env["DEVELOPER_DIR"] = "/Applications/Xcode.app/Contents/Developer"
    child_env["SIMCTL_CHILD_MINTO_APP_TOKEN"] = settings.app_api_token
    child_env["SIMCTL_CHILD_MINTO_BACKEND_URL"] = args.backend_url
    subprocess.run(
        [
            "xcrun",
            "simctl",
            "launch",
            "--terminate-running-process",
            args.device,
            "com.ashwin.splitwiseledger",
        ],
        env=child_env,
        check=True,
    )
    print("Minto launched with its local development session. No Gemini key was sent to the app.")


if __name__ == "__main__":
    main()
