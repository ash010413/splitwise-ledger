"""Device-selection and signing gates for a script that installs on real phones."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "reinstall_ios", Path(__file__).parents[1] / "tools/reinstall_ios.py"
)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
NOW = datetime(2026, 11, 2, tzinfo=UTC)


def phone(name="Test iPhone", identifier="core-1", udid="phone-1"):
    return {
        "identifier": identifier,
        "deviceProperties": {"name": name},
        "hardwareProperties": {"platform": "iOS", "udid": udid},
        "connectionProperties": {"pairingState": "paired"},
    }


def profile():
    return {
        "ExpirationDate": NOW + timedelta(days=6),
        "TeamIdentifier": ["TESTTEAM"],
        "Entitlements": {
            "application-identifier": "TESTTEAM." + script.BUNDLE_ID,
            "get-task-allow": True,
        },
        "ProvisionedDevices": ["phone-1"],
    }


def test_selection_is_explicit_unique_and_cannot_pick_another_phone():
    first, second = phone(), phone("Other iPhone", "core-2", "phone-2")
    assert script.select_devices([first, second], ["Test iPhone"]) == [first]
    assert script.select_devices([first, second], ["core-1", "phone-1"]) == [first]
    with pytest.raises(script.ReinstallError):
        script.select_devices([first, second], ["iPhone"])
    with pytest.raises(script.ReinstallError):
        script.select_devices([first, phone()], ["Test iPhone"])
    first["connectionProperties"]["pairingState"] = "unpaired"
    with pytest.raises(script.ReinstallError):
        script.select_devices([first], ["core-1"])


@pytest.mark.parametrize(
    "failure", ["expired", "too_short", "wrong_app", "uncovered", "distribution"]
)
def test_installation_is_blocked_for_invalid_or_insufficient_signing(failure):
    value = profile()
    if failure == "expired":
        value["ExpirationDate"] = NOW - timedelta(hours=1)
    elif failure == "too_short":
        value["ExpirationDate"] = NOW + timedelta(hours=47)
    elif failure == "wrong_app":
        value["Entitlements"]["application-identifier"] = "TESTTEAM.another.app"
    elif failure == "uncovered":
        value["ProvisionedDevices"] = ["someone-else"]
    else:
        value["Entitlements"]["get-task-allow"] = False
    with pytest.raises(script.ReinstallError):
        script.validate_profile(value, script.BUNDLE_ID, [phone()], 48, NOW)


def test_valid_profile_and_naive_apple_plist_expiry():
    value = profile()
    value["ExpirationDate"] = value["ExpirationDate"].replace(tzinfo=None)
    script.validate_profile(value, script.BUNDLE_ID, [phone()], 48, NOW)
    assert script.expiry(value).tzinfo == UTC


def test_reinstalling_the_same_profile_is_not_reported_as_renewal():
    expires = NOW + timedelta(days=6)
    previous = {"expires_at": expires.isoformat()}
    assert script.renewal_status(previous, expires).startswith("unchanged")
    assert script.renewal_status(previous, expires + timedelta(days=1)) == "advanced"
    assert script.renewal_status(None, expires).startswith("unknown")
