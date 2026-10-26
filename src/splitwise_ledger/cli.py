"""Local setup and scheduler entry point. Never print credentials or authorization URLs."""

import argparse
import secrets
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from .api import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init-local", "sync", "connect"])
    args = parser.parse_args()
    if args.command == "init-local":
        # Exclusive creation avoids accidentally replacing a working encryption key.
        with Path(".env").open("x", encoding="utf-8") as env:
            env.write(
                "SPLITWISE_CLIENT_ID=\nSPLITWISE_CLIENT_SECRET=\n"
                "SPLITWISE_REDIRECT_URI=http://127.0.0.1:8000/oauth/splitwise/callback\n"
                f"APP_API_TOKEN={secrets.token_urlsafe(32)}\n"
                f"TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n"
                "DATABASE_PATH=data/ledger.sqlite3\n"
            )
        Path(".env").chmod(0o600)
        print("Created ignored .env. Add your Splitwise client ID and secret locally.")
        return
    settings = Settings()
    path = "/sync" if args.command == "sync" else "/oauth/splitwise/start"
    try:
        response = httpx.post(
            "http://127.0.0.1:8000" + path,
            headers={"Authorization": "Bearer " + settings.app_api_token},
            timeout=300,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        raise SystemExit(
            "Request failed. Check the local server, configuration and connection."
        ) from None
    if args.command == "connect":
        import webbrowser

        webbrowser.open("http://127.0.0.1:8000" + response.json()["connection_url"])
        print("Opened the one-time Splitwise connection in your browser.")
    else:
        print("Sync completed successfully.")


if __name__ == "__main__":
    main()
