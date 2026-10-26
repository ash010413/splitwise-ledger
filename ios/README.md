# Ledger for iOS

Native SwiftUI app for manually maintained expense summaries. Requires iOS 17+
and Xcode 16+. Open `LedgerApp.xcodeproj`, choose the `Ledger` scheme and an iPhone
simulator, and Run. No Python backend, OAuth credentials or AI key is needed.
For a physical device, select your own signing team in Signing & Capabilities.

## Current features

- Overview with July–October selection, category totals and a monthly spending chart.
- Transparent comparisons with the prior calendar month (periods may be incomplete).
- Calculated insight showing the largest category's share; no AI-generated claims.
- All twelve categories with definitions and individual monthly charts.
- Searchable illustrative activity, category filtering and read-only transaction details.
- Settings with connection status and data provenance.
- Loading, error and empty-search states; VoiceOver labels on charts and standard controls.

Summary figures are a static snapshot of the table supplied in the chat. Example
transactions are fictional and explicitly labeled; they do not reconcile to those
totals. Everything remains in memory. There are no network calls or writes.

## Architecture

`LedgerCore/Sources/LedgerCore/Ledger.swift` contains Foundation-only categories,
Decimal amounts, monthly snapshots, transaction models and the repository protocol.
The Xcode target compiles that same domain source directly. `LedgerCore` is also a
standalone Swift package, allowing its invariants to be tested without running iOS.

`LedgerApp/LedgerApp.swift` contains the main-actor observable model and SwiftUI
screens. Screens depend on `LedgerRepository` via the model, never spreadsheet cell
addresses. Monthly summaries and transaction records remain separate domain types.

Later, add a Sheets-backed repository with explicit schema validation, currency and
date parsing, source freshness, authentication and last-successful-load caching.
Because the sheet will be maintained manually, the app should initially remain
read-only. Decide whether monthly summary cells or transaction rows are authoritative
before deriving totals; never silently combine both.

Gemini analysis is deferred. If added, it needs server-side credentials and explicit
data sharing choices. It must not change figures or categories in a read-only viewer.

## Verification commands

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path ios/LedgerCore
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -project ios/LedgerApp.xcodeproj -scheme Ledger -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/ledger-ios-build CODE_SIGNING_ALLOWED=NO build
```

The checked-in Xcode project and shared scheme require no generator or third-party
packages. `tools/generate_project.py` reproduces the small project deterministically.
The preview uses a deliberate light cream/green theme. App Store icons, release
signing, live data, persisted preferences and automated UI tests are future work.
