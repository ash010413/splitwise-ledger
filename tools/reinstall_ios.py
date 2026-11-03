"""Build and reinstall Minto on explicitly selected paired iPhones; never delete app data.

Uses Xcode's existing account/signing settings. Does not store Apple credentials,
remove provisioning profiles, revoke certificates, launch the app or create a schedule.
"""

import argparse
import fcntl
import json
import os
import plistlib
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ID = "com.ashwin.splitwiseledger"


class ReinstallError(Exception):
    pass


def read_profile(app, run=subprocess.run):
    decoded = run(
        ["security", "cms", "-D", "-i", str(app / "embedded.mobileprovision")],
        capture_output=True,
        check=True,
    )
    return plistlib.loads(decoded.stdout)


def expiry(profile):
    value = profile["ExpirationDate"]
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def validate_profile(profile, bundle_id, devices, min_hours, now=None):
    now = now or datetime.now(UTC)
    if bundle_id != BUNDLE_ID:
        raise ReinstallError("Unexpected app bundle ID; refusing to install.")
    entitlements = profile.get("Entitlements", {})
    if not entitlements.get("application-identifier", "").endswith("." + bundle_id):
        raise ReinstallError("Provisioning profile does not match Minto.")
    if not entitlements.get("get-task-allow") or not profile.get("TeamIdentifier"):
        raise ReinstallError("Expected a development profile with a signing team.")
    if expiry(profile) < now + timedelta(hours=min_hours):
        raise ReinstallError(
            "Signing did not provide enough remaining validity. Open Signing & Capabilities "
            "in Xcode and resolve/renew the profile, then retry. No app was installed."
        )
    covered = set(profile.get("ProvisionedDevices", []))
    if any(d.get("hardwareProperties", {}).get("udid") not in covered for d in devices):
        raise ReinstallError(
            "The profile does not cover every selected iPhone. Run Minto from Xcode on "
            "each phone once with the intended signing team, then retry."
        )


def select_devices(devices, selectors):
    selected = []
    for selector in selectors:
        matches = [
            d
            for d in devices
            if selector
            in (
                d.get("identifier"),
                d.get("hardwareProperties", {}).get("udid"),
                d.get("deviceProperties", {}).get("name"),
            )
        ]
        if len(matches) != 1:
            raise ReinstallError("Each --device must match exactly one paired device.")
        device = matches[0]
        if device.get("hardwareProperties", {}).get("platform") != "iOS":
            raise ReinstallError("Only physical iOS devices are supported.")
        if device.get("connectionProperties", {}).get("pairingState") != "paired":
            raise ReinstallError("Pair the selected iPhone with Xcode first.")
        if device not in selected:
            selected.append(device)
    return selected


def renewal_status(previous, current):
    if not previous:
        return "unknown (first recorded install; renewal not proven)"
    old = datetime.fromisoformat(previous["expires_at"])
    return "advanced" if current > old else "unchanged (reinstallation is not signing renewal)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument(
        "--device", action="append", default=[], help="Exact name or ID; repeatable"
    )
    parser.add_argument(
        "--install", action="store_true", help="Install after a successful signed build"
    )
    parser.add_argument("--build-only", action="store_true", help="Build/verify without installing")
    parser.add_argument("--min-valid-hours", type=int, default=48)
    parser.add_argument(
        "--require-renewal",
        action="store_true",
        help="Refuse installation unless expiry advanced since last recorded install",
    )
    parser.add_argument("--developer-dir", default="/Applications/Xcode.app/Contents/Developer")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "data/ios-reinstall")
    args = parser.parse_args()
    if args.min_valid_hours < 1:
        parser.error("--min-valid-hours must be positive")
    if args.install and args.build_only:
        parser.error("Choose --install or --build-only")
    if not args.list_devices and not args.device:
        parser.error("Select --device explicitly, or use --list-devices")
    os.umask(0o077)
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DEVELOPER_DIR"] = args.developer_dir

    def command(argv, *, output=None, timeout=90):
        if output:
            with output.open("w") as log:
                subprocess.run(
                    argv, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=timeout
                )
        else:
            subprocess.run(argv, env=env, capture_output=True, check=True, timeout=timeout)

    with (state / "run.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ReinstallError("Another reinstall run is already active.") from error
        device_json = state / "devices.json"
        command(
            [
                "xcrun",
                "devicectl",
                "list",
                "devices",
                "--timeout",
                "30",
                "--json-output",
                str(device_json),
                "--quiet",
            ]
        )
        devices = json.loads(device_json.read_text())["result"]["devices"]
        if args.list_devices:
            for d in devices:
                print(
                    d["deviceProperties"]["name"],
                    "|",
                    d["identifier"],
                    "|",
                    d["connectionProperties"].get("tunnelState", "unknown"),
                )
            return
        selected = select_devices(devices, args.device)
        for d in selected:
            print("Selected:", d["deviceProperties"]["name"], flush=True)
        if not args.install and not args.build_only:
            print("Dry run: no build or installation. Add --build-only or --install.")
            return
        print("Building signed Release app with existing Xcode signing settings…", flush=True)
        command(
            [
                "xcodebuild",
                "-project",
                str(ROOT / "ios/LedgerApp.xcodeproj"),
                "-scheme",
                "Ledger",
                "-configuration",
                "Release",
                "-sdk",
                "iphoneos",
                "-destination",
                "generic/platform=iOS",
                "-derivedDataPath",
                str(state / "DerivedData"),
                "-allowProvisioningUpdates",
                "build",
            ],
            output=state / "build.log",
            timeout=900,
        )
        app = state / "DerivedData/Build/Products/Release-iphoneos/Ledger.app"
        with (app / "Info.plist").open("rb") as file:
            bundle = plistlib.load(file)["CFBundleIdentifier"]
        profile = read_profile(app)
        validate_profile(profile, bundle, selected, args.min_valid_hours)
        command(["codesign", "--verify", "--deep", "--strict", str(app)])
        current = expiry(profile)
        print("Verified signature. Profile expires:", current.isoformat(), flush=True)
        record_file = state / "installed.json"
        records = json.loads(record_file.read_text()) if record_file.exists() else {}
        team = profile["TeamIdentifier"][0]
        for d in selected:
            prior = records.get(d["identifier"])
            if prior and prior["team"] != team:
                raise ReinstallError(
                    "Signing team changed; refusing to replace an existing install."
                )
            status = renewal_status(prior, current)
            print(d["deviceProperties"]["name"], "— profile expiry:", status, flush=True)
            if args.require_renewal and status != "advanced":
                raise ReinstallError("A later signing expiry was not proven. Nothing installed.")
        if not args.install:
            print("Build-only verification passed. No device installation attempted.")
            return
        failed = []
        for d in selected:
            result_file = state / (d["identifier"] + "-install.json")
            try:
                print("Installing on", d["deviceProperties"]["name"], flush=True)
                command(
                    [
                        "xcrun",
                        "devicectl",
                        "device",
                        "install",
                        "app",
                        "--device",
                        d["identifier"],
                        str(app),
                        "--timeout",
                        "90",
                        "--json-output",
                        str(result_file),
                        "--quiet",
                    ],
                    output=state / "install.log",
                    timeout=120,
                )
                result = json.loads(result_file.read_text())
                if result.get("info", {}).get("outcome") != "success":
                    raise ReinstallError("Device installation did not report success.")
                records[d["identifier"]] = {
                    "expires_at": current.isoformat(),
                    "team": team,
                    "bundle_id": bundle,
                    "installed_at": datetime.now(UTC).isoformat(),
                }
                temporary = record_file.with_suffix(".tmp")
                temporary.write_text(json.dumps(records, indent=2))
                temporary.replace(record_file)
                print("Installed successfully; app was not deleted or launched.", flush=True)
            except (subprocess.SubprocessError, ReinstallError):
                failed.append(d["deviceProperties"]["name"])
                print(
                    "Install failed; check pairing, unlock the phone, and verify Xcode supports "
                    "its iOS version. Details are in the private install log.",
                    flush=True,
                )
        if failed:
            raise ReinstallError("Could not install on: " + ", ".join(failed))


if __name__ == "__main__":
    try:
        main()
    except (ReinstallError, subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
        print(
            "Reinstall failed:",
            str(error)
            if isinstance(error, ReinstallError)
            else "Build/tooling failed. Check data/ios-reinstall/build.log, Xcode account sign-in, "
            "network access, and device compatibility.",
            file=sys.stderr,
        )
        sys.exit(1)
