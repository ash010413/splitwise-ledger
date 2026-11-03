# SideStore distribution assessment

Reviewed November 2, 2026. This is a limited review of official documentation,
release metadata and Minto's current credential boundaries, not an independent
security audit of SideStore, its installer, VPN implementation or dependencies.

## Recommendation

Consider a one-phone trial with a separate signing-only Apple Account after the
planned Minto security review. Do not treat SideStore as a guarantee against data
compromise or deploy it to every tester before verifying the complete workflow.
No SideStore software was installed during this assessment.

## Trust boundaries

- SideStore and its installer handle Apple signing authentication. Prefer a separate
  Apple Account with two-factor authentication, without personal iCloud data or
  payment details. Each user should control their own credentials.
- Device pairing records are sensitive trust credentials, not ordinary configuration
  files. Keep them private and out of Git, chat, shared drives and diagnostic uploads.
  A separate Apple Account does not remove the pairing risk to the physical phone.
- The official setup uses LocalDevVPN to communicate with local device services.
  Verify the exact App Store link from the official prerequisites page. Do not
  substitute an arbitrary VPN, installer, IPA source or signing service.
- SideStore says anisette-v3 servers do not receive account information. This is a
  project assertion, not an independently verified finding from this review. Its
  documentation describes account-lock risks with older shared anisette servers.
- Re-signing an IPA introduces trust in the signing tool and its update chain.
  Use Minto artifacts built from this repository, not third-party repackaged builds.

## Release selection

At review time the official GitHub `/releases/latest` endpoint returned
`0.7.0-alpha`, despite not marking it as a prerelease. The older `0.6.4` release
exists. Do not automate downloads from `latest` assuming that it means stable.
Verify the current official installation path and compatibility with each phone's
exact iOS version. An asset checksum verifies downloaded bytes against the
publisher's digest; it does not establish that the program is safe.

The repository security page had no SECURITY.md and no published advisories.
Neither observation establishes the absence of vulnerabilities.

## Minto data

The current app uses the hosted HTTPS endpoint and an account session in Keychain.
Splitwise credentials and the Gemini key remain server-side. SideStore setup does
not require either provider's credentials, financial exports or Minto backend
secrets. Existing security measures do not constitute a completed security audit.
Adding an app lock alone would not protect against a compromised signing tool or
stolen pairing record.

Changing the signing team or bundle identifier may prevent access to the previous
Keychain session and require Splitwise sign-in again. Hosted data remains associated
with the Splitwise account, but local migration and replacement behavior must be
tested. Do not delete the working app as a troubleshooting shortcut.

## Trial acceptance checks

Use one consenting user's phone first. Keep the current Xcode build available for
recovery. Verify the IPA source and exact tool versions; preserve the intended
bundle identity where supported; sign in through Splitwise; compare account data;
then verify that both SideStore and Minto refresh successfully on another Wi-Fi
network with the Mac offline. Check actual expiry dates. Refresh still requires
Wi-Fi and the documented VPN setup; cellular-only and unattended background refresh
must not be assumed. Pairing can break after OS updates or resets and require a
computer again. Stop if setup requires disabling device protections, installing
unknown trust roots, or using an unexplained certificate-revocation workaround.

## Primary references

- [Official prerequisites](https://docs.sidestore.io/docs/installation/prerequisites)
- [Official installation](https://docs.sidestore.io/docs/installation/install)
- [Anisette explanation](https://docs.sidestore.io/docs/advanced/anisette)
- [Pairing-file lifecycle](https://docs.sidestore.io/docs/advanced/pairing-file)
- [SideStore releases](https://github.com/SideStore/SideStore/releases)
- [Repository security page](https://github.com/SideStore/SideStore/security)
- [Apple pairing security](https://support.apple.com/guide/security/physical-pairing-model-security-secadb5b6434/web)
