# TestFlight readiness

The backend is deployed and the app can read live Splitwise expenses. A local device build is not a TestFlight release. No signed archive has been uploaded as part of the documentation/demo update.

## Distribution steps

1. Upgrade the upload toolchain to **Xcode 26 or later with the iOS 26 SDK**. Apple has required this for App Store Connect uploads since April 28, 2026. This checkout was verified locally with Xcode 16.4, which is insufficient for a new upload. See [Apple's SDK requirements](https://developer.apple.com/news/upcoming-requirements/).
2. Use an active Apple Developer Program membership and the correct team in Xcode. Create an App Store Connect app record matching the bundle identifier. Confirm ownership and signing before changing identifiers.
3. Choose a version/build number and archive the **Release** configuration for a generic iOS device. Confirm it points to the hosted HTTPS backend and contains no developer tokens or local configuration.
4. Validate and upload the signed archive using Xcode Organizer. Resolve processing and export-compliance questions based on the actual shipped encryption usage.
5. Complete TestFlight beta description, feedback email, what-to-test notes and review contact/access instructions. Provide a working, permitted review account or another review-access arrangement; the Debug-only simulator demo is not present in Release builds.
6. Create an external tester group and submit the first build for TestFlight App Review. After approval, invite the intended testers by email. They install through the TestFlight app; a public App Store listing is not required.

Apple requires first-build approval for external testing. Builds are available for testing for up to 90 days. See [TestFlight overview](https://developer.apple.com/testflight/) and [App Store Connect testing guide](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview).

## Product and operational work before inviting friends

- **Privacy and account lifecycle:** publish an accurate privacy policy and support contact, link them in the app, and implement account/data deletion with provider disconnection. Current sign-out removes a session; it does not delete the hosted account or its financial history. Review [Apple's account deletion guidance](https://developer.apple.com/support/offering-account-deletion-in-your-app/) for this OAuth-backed account model.
- **Privacy manifest:** add and validate required-reason API declarations (including UserDefaults usage) and audit third-party SDK privacy requirements before upload.
- **AI disclosure:** document description-based automatic matching and totals/conversation-based summaries, including the Gemini transfer. Check consent and privacy behavior against [App Review privacy requirements](https://developer.apple.com/app-store/review/guidelines/#privacy). Classification is fallible and remains editable.
- **Independent onboarding:** test a fresh friend's account end to end, verify provider entitlement, account separation, daily/manual sync, category correction, session expiry and sign-out. Do not assume an existing successful owner connection proves every tester's access.
- **Review access and capacity:** four account slots are configured, not an invitation allowlist. Plan reviewer access without consuming the intended tester capacity unexpectedly. Confirm how expired trials/subscriptions affect service continuity.
- **Operations:** verify billing alerts, sanitized error monitoring, recovery/backup procedures and secret rotation ownership. Scale-to-zero and instance caps reduce usage but do not impose a hard zero-dollar budget.

The exact submission requirements depend on App Store Connect's current checks and Apple's review. Inspect current upload SDK/Xcode requirements before archiving. The repository's minimum supported iOS version does not establish upload eligibility.

## Suggested beta test

Connect a fresh account, compare a personal purchase and shared purchase against Splitwise owed shares, confirm a settlement is absent, correct a category, inspect a monthly drill-down, request and follow up on a summary, force refresh, then sign out and sign back in. Repeat on a second account to verify isolation. Use fictional test transactions where possible.
