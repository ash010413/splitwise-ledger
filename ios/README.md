# Ledger for iOS

Native SwiftUI app, iOS 17+ and Xcode 16+. Open `LedgerApp.xcodeproj`, choose the
`Ledger` scheme and an iPhone simulator, then Run. Existing signing settings are
preserved. On a physical device select your own signing team.

## Live Google Sheets

The app reads the existing shared spreadsheet directly over HTTPS, using its current
Anyone-with-the-link viewing access. No Google credentials, backend, AI key or sheet
edits are required for the dashboard. Sharing permissions are not changed by the app.
If access is restricted later, add a Google authorization adapter; do not silently
fall back to preview numbers. `SheetsLedgerRepository.sheetID` identifies the sheet.

- Summary tab: `2026`. Category rows must match the twelve configured category names.
- Month headers: `Jul 2026` format; Average and YTD columns are not imported as months.
- Monthly category sums must exactly match `Total Monthly Expenses`. Invalid data
  leaves the previous successful snapshot intact and displays an error.
- Activity tab: `Transactions`, with Date, Description, Category, My Share and Expense ID.
- Summary totals remain authoritative; activity is not added to them. Signed share
  values are displayed as recorded with a warning for negative values. `Dining out`
  is an explicit alias for `Food / Dining`; unknown categories appear as Needs review.
- Currency is USD. Invalid currency formats, blank amounts, duplicate IDs, malformed
  CSV, invalid dates and incomplete category rows fail validation rather than becoming zero.
- Refresh on launch, foreground entry, every 60 seconds while foreground, and pull-to-refresh.
- Last successful snapshot is cached locally. The UI displays fetch time, errors and
  partial transaction refresh warnings. There is no claim of real-time or background push.

Tap a monthly chart bar to select its month and see the amount. Category charts
also select months. Explicit month buttons provide an accessible alternative to
chart gestures. Category rows open definitions and their spending history.

## Ask Ledger (Gemini)

The floating Ask Ledger button opens an on-demand summary sheet. Press Summarize
this month to send only selected-month and optional comparison-month category totals
through the authenticated Python backend to Gemini. No transaction descriptions,
friends, IDs or sheet URL enter the model payload. Summaries never alter categories,
totals or the sheet. A summary remains labeled with the snapshot and month it analyzed.

1. Add `GEMINI_API_KEY` to the repository's ignored `.env`. Optional `GEMINI_MODEL`
   defaults to `gemini-3.8-flash`; choose another supported model if your project requires it.
2. Start or restart the backend from the repository root:

   ```sh
   .venv/bin/uvicorn splitwise_ledger.api:create_app --factory --host 127.0.0.1 --no-access-log
   ```

3. In app Settings, keep Backend URL as `http://127.0.0.1:8000` for the simulator.
   Copy the backend `APP_API_TOKEN` from your local `.env` into the secure token field
   and Save. This is the application token, **not** the Gemini key. It is stored in
   device-only Keychain storage, never UserDefaults or source code.
4. Tap Ask Ledger, then Summarize this month.

For a real iPhone, localhost refers to the phone. Use an HTTPS-hosted backend, or for
local development run Uvicorn on `0.0.0.0` and enter your Mac's reachable `.local`
hostname. Both devices must be on the same trusted network. The app includes a local
network purpose string and allows local networking without disabling HTTPS checks
for public hosts. An iOS local-network prompt may appear. Never expose the development
server to the public Internet. A hosted, multi-user release needs real per-user login.

The backend serializes model requests and caches the latest identical aggregate
request for five minutes. It returns actionable missing-key, auth and provider errors
without logging secret-bearing provider bodies. Gemini outputs are advisory; months
may be incomplete. The monthly figures remain the deterministic source of truth.

## Architecture and checks

Foundation-only domain, CSV parser and Sheets repository live in
`LedgerCore/Sources/LedgerCore/Ledger.swift`. That source is compiled by the Xcode target
and by the standalone test package. `LedgerApp.swift` contains the main-actor model,
views, Keychain boundary and analysis HTTP client. Sheets traffic is independent of
AI availability. The Python `analysis.py` adapter is independent of Splitwise OAuth.

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path ios/LedgerCore
# Explicit network integration test against the configured shared sheet:
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer LEDGER_LIVE_SHEETS=1 swift test --package-path ios/LedgerCore
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -project ios/LedgerApp.xcodeproj -scheme Ledger -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/ledger-ios-build CODE_SIGNING_ALLOWED=NO build
```

App Store icons, Google authorization for private sheets, multi-year tab selection,
background push and production deployment are not included. The project generator is
optional; do not regenerate over personal signing/scheme changes in Xcode.
