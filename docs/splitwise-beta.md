# Splitwise integration

Minto reads personal spending through an OAuth-authorized Splitwise application. OAuth is the authorization mechanism; it does not bypass Splitwise's API entitlement requirements. Keep the registered application's required subscription active and validate access for each beta tester.

## Connection and sync

Register the exact backend callback `<BACKEND_URL>/oauth/splitwise/callback` in the Splitwise application settings. Keep the client secret on the backend. The iOS URL scheme `minto` returns control to the app after authorization; it is not the provider's registered HTTPS callback.

The native flow uses `/mobile/auth/start`, browser `/mobile/auth/connect`, the provider callback, and `/mobile/auth/exchange`. Authenticated account and expense reads use `/mobile/account` and `/mobile/expenses`. `/mobile/sync` observes a daily guard; `?force=true` supports pull to refresh. `/internal/sync` accepts the configured scheduler identity, not an app session.

The service records only the authenticated user's owed share. Payments, settlements, debt consolidation, deleted records and zero-share records are excluded. Manual review updates Minto's category decision, never the source Splitwise record.

## Category definitions

| Category | Meaning |
| --- | --- |
| Home | Rent, utilities, renters insurance, electricity and home expenses |
| Car | Fuel, insurance, washes and other car expenses |
| Flights / Travel | Flights and travel expenses |
| Food / Dining | Meals, coffee and food eaten out |
| Groceries | Food and ingredients purchased for home |
| Misc | Necessary expenses outside other categories, or spending for others |
| Movie / Entertainment | Movies, event tickets, outside entertainment and Spotify subscriptions |
| Phone | Phone bills, iCloud and related subscriptions |
| AI | AI subscriptions and services |
| Badminton / Sports | Badminton and other sports spending |
| Gym | Gym membership and subscription |
| Lux | Extra discretionary purchases for yourself |
| Others | Historical purchases still unclear after classification |

Rules run first, Gemini handles unresolved descriptions using these same definitions, and human choices take precedence. Ordinary Costco shopping defaults to Groceries; an explicit fuel purchase stays Car, and other specific non-grocery purposes override that default. Elec/Elec bills map to Home. Unclear history can enter Others; unclear new expenses appear in the in-app review queue. AI errors remain queued rather than being treated as classification decisions. A new classification policy rechecks old automatic Others decisions once, preserving human choices and recording each retry in the audit trail. Remembered rules match a description within its group and currency scope.

The API uses bounded AI batches, source revisions and account leases to avoid overlapping work. Category matching and on-demand summaries are separate operations; summaries never mutate the ledger.

See [architecture](architecture.md) for security and persistence boundaries and [deployment](../deploy/gcp/README.md) for hosted configuration.


## Group context

The backend fetches Splitwise group IDs/titles with the account's authorization and caches
only the ID-to-title mapping. The full member list, debts and invite links are discarded.
Gemini receives a bounded title alongside the description and source category, not the
numeric group ID. Group titles are untrusted context rather than instructions. Generic
Friends/Housemates groups do not imply a category; explicit purchase descriptions take
priority over group themes. Month-only payments in a Spotify group map to Movie /
Entertainment. Manual choices still win.

Group metadata refreshes daily and on manual sync. A failed lookup preserves expenses and
cached context, shows a warning and backs off before retrying. A context fingerprint allows
previously uncertain automatic decisions to be reconsidered when titles change, without
changing financial source revisions or human reviews.
