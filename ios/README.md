# Minto for iPhone

Native SwiftUI and Swift Charts client, targeting iOS 17+. Open `LedgerApp.xcodeproj` in Xcode and select the **Ledger** scheme. Choose your development team before building on a device. Preserve your local signing settings.

## Configuration

`Configuration.xcconfig` includes the public `Production.xcconfig` and an optional ignored `Development.local.xcconfig`. Release uses the production configuration. The backend address is public configuration; Splitwise and Gemini secrets belong only on the backend.

Debug simulator builds default to localhost unless `MINTO_BACKEND_URL` is supplied in the scheme environment. For a physical device, use the hosted HTTPS endpoint or a reachable development hostname with a matching OAuth callback. Do not distribute a build pointing to a developer's Mac.

## Offline simulator demo

Build **Debug** for an iPhone simulator and launch with `--demo`:

```sh
xcrun simctl launch booted com.ashwin.splitwiseledger --demo
```

Add `--demo-tour` alongside `--demo` to advance automatically through the recorded screens.

This capture harness uses a fictional profile and 12 months of synthetic transactions. Totals and drill-down lists come from the same records. It bypasses login, Keychain provisioning and persisted account caches; mobile network requests are blocked. Explore demo opens the regular spending UI. AI responses are illustrative and labeled. Category edits are disabled in this presentation mode. This mode cannot activate in a Release build or on a physical iPhone. It does not demonstrate real OAuth or Gemini connectivity.

Record with `xcrun simctl io <SIMULATOR_ID> recordVideo --codec=h264 <OUTPUT.mov>` and stop with SIGINT. Encode the result as H.264 MP4 for browser compatibility. Keep the visible synthetic-data label in exported media. The published walkthrough is in `docs/media`.

## Structure and validation

`LedgerApp` contains the app shell, dashboard, expense lists, category review, account settings and interactive summary view. `LedgerCore` owns financial parsing, aggregation and chart calculations. Backend sessions are stored in Keychain; cached spending is scoped to account and currency. Sign-out clears the local session and spending cache.

```sh
cd LedgerCore
swift test
```

Also build both Debug simulator and Release device configurations after changing app wiring. An unsigned device build verifies compilation; it does not verify distribution signing or constitute a TestFlight upload.

See the [TestFlight checklist](../docs/testflight.md) before distributing.

## Reinstall on paired development iPhones

`tools/reinstall_ios.py` builds a signed Release app using the existing Xcode account
and signing configuration, checks the embedded provisioning profile and signature,
and optionally installs over Minto on explicitly selected physical phones. It does
not delete or launch the app. Device identifiers, signing records and logs stay in
the ignored `data/ios-reinstall/` directory with private permissions.

Run from the repository root:

```sh
python3 tools/reinstall_ios.py --list-devices
# Exact device name or CoreDevice ID; without a mode this is a dry run.
python3 tools/reinstall_ios.py --device 'Your iPhone name'
python3 tools/reinstall_ios.py --device 'Your iPhone name' --build-only
python3 tools/reinstall_ios.py --device 'Your iPhone name' --install
# Select both explicitly when their devices are covered by the signing profile.
python3 tools/reinstall_ios.py --device 'First iPhone' --device 'Second iPhone' --install
```

Keep the Mac awake and selected phones unlocked and reachable via USB or the paired
home network. Devices must have Developer Mode enabled. Sign into the intended
Apple account in Xcode first; register each phone by running the app from Xcode
once if it is not covered by the existing profile. Use `--developer-dir` to select
a different Xcode installation. Newer iOS versions can prevent device operations
with older Xcode; successful pairing alone is not proof of install compatibility.

**Reinstalling is not necessarily renewal.** Xcode may reuse a profile with its
original expiry. The script reports the actual expiry, refuses profiles with less
than 48 hours remaining by default, and only records successful installations.
`--require-renewal` additionally refuses installation unless the profile expiry
advanced beyond the last installation recorded by this script. A first run cannot
prove renewal, because there is no prior recorded expiry. Missing device coverage,
changed signing team, invalid signature and insufficient validity stop installation.
Failures are reported with a nonzero exit status; offline phones can be retried by
running the command again. The process lock prevents overlapping script runs.

No recurring task is installed by this script. Before scheduling it, demonstrate
that Xcode actually renews the profile near expiry. If it does not, resolve signing
in Xcode manually; do not delete shared profiles or revoke certificates to force it.
The script cannot guarantee unattended weekly renewal with free signing.
