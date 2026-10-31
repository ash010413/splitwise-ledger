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
