# Architecture

Minto is a native iOS client backed by an account-scoped spending service. Splitwise supplies the source records. Firestore is the hosted system of record for normalized spending and category decisions. Google Sheets adapters remain in the codebase for legacy/local use and are outside the active hosted path.

## Boundaries

| Component | Responsibility |
| --- | --- |
| SwiftUI app | OAuth browser flow, Keychain session, charts, category drill-down, review, summaries |
| Mobile API | Authentication, account isolation, sync orchestration, review validation, AI requests |
| Splitwise adapter | Provider authorization and incremental expense retrieval |
| Domain layer | Personal share, exclusion rules, category precedence, source revisions |
| Firestore adapters | Durable account records, ledger pages, cursor, audit and operation leases |
| Gemini adapter | Structured category suggestions and aggregate-based conversational summaries |
| Cloud Scheduler | Authenticated wake-up; account timestamps determine whether a sync is due |

## Authentication

The app starts an OAuth attempt and retains a verifier. The browser completes Splitwise authorization through the backend callback. State, the browser cookie, and the native verifier bind the flow; a single-use exchange returns an opaque app session. Provider credentials never appear in the native callback URL. App sessions expire after 30 days and are stored in Keychain; the server stores session hashes and encrypted provider tokens.

Cloud mode exposes the mobile API, health check, OAuth callback, and authenticated scheduler route. Legacy static-token routes are not enabled there. Secret Manager injects provider and encryption credentials into the Cloud Run runtime.

## Spending correctness

- Use the authenticated user's `owed_share`, not the total bill, paid share, or net balance.
- Ignore settlements/payments, debt consolidation, deleted records, and purchases with no personal share.
- Upsert by expense ID and source revision. Edits and removals affect the normalized ledger on sync.
- Use decimal arithmetic on the backend and client; transfer amounts as decimal strings.
- Keep currencies separate; do not silently convert or combine them.
- Include pending classification amounts in totals, visibly separated from categorized spending.
- Reject stale review submissions rather than overwriting a newer source revision.

An incremental cursor and account operation lease coordinate manual and scheduled work. Firestore ledger updates atomically commit changed pages, cursor and audit state. Size guards fail before a partial oversized ledger commit. A version-checked cache reduces repeated reads without making container-local storage authoritative.

## Category decisions

Explicit human choices win. Remembered description/group/currency matches and clear deterministic rules precede Gemini. Conflicting or ambiguous evidence stays unresolved. Gemini receives bounded expense descriptions and source category labels with the category definitions; it does not receive friend identities, notes, amounts, or credentials for matching.

Classification uses bounded batches with validated structured output. Failures remain queued for retry. Historical expenses that remain unclear after a valid AI decision enter Others, avoiding a large onboarding review queue. New unclear records request in-app review, including newly discovered backdated purchases. Others remains editable. Misc and Lux require their actual meaning, rather than serving as generic fallbacks.

## Summaries

The app sends selected-period category totals, comparison totals when available, and the follow-up conversation to the authenticated analysis endpoint. The backend calls Gemini and briefly caches results per account and input fingerprint. The app renders lightweight Markdown as native text. Summaries are advisory and cannot update categories, expenses, or Splitwise.

## Hosting and operations

Cloud Run in `us-central1` uses request-based execution, zero minimum instances, and a maximum of one instance for the small beta. Firestore provides persistence across container restarts. An hourly OIDC-authenticated Cloud Scheduler request checks account timestamps; the Splitwise fetch interval is 24 hours unless the user forces a refresh. Bounded category work can continue on subsequent requests.

Dedicated runtime, scheduler, and build service accounts separate responsibilities. Runtime access is scoped to Firestore and the required secrets. Container builds use an allowlisted source context. No local account databases or `.env` files are included.

Current capacity is four accounts. This is not an invite allowlist. Before expanding distribution, implement the lifecycle/privacy work in the [TestFlight checklist](testflight.md), validate friend onboarding, and establish backup/restore and operational monitoring appropriate to the audience.

## Code map

- `src/splitwise_ledger/api.py`: application wiring and analysis API.
- `mobile.py`: native OAuth/session, spending, sync, review and scheduler routes.
- `domain.py`, `categorization.py`: financial normalization and category policy.
- `firestore_accounts.py`, `firestore_ledger.py`: hosted persistence and concurrency.
- `ios/LedgerApp`: native presentation, connection and review flows.
- `ios/LedgerCore`: parsing, aggregation and chart period logic.
- `tools/build_cloud_context.py`: deployment source allowlist.
