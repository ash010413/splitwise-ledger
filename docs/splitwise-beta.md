# Minto: small-group Splitwise beta

The hosted Cloud Run/Firestore beta is now configured. See the
[GCP deployment guide](../deploy/gcp/README.md) for the current endpoint and release
configuration. The local Mac setup below remains available for development.

Keep the existing app and repository. The chart, category-history and AI views are
shared; the authenticated Splitwise adapter replaces Sheets for connected users.
Sheets code remains available for the older prototype, and no Sheets data is copied
into a Splitwise account. New installations start on the Splitwise sign-in screen.

## Authentication

1. The native app starts a ten-minute login at `POST /mobile/auth/start`.
2. It opens `/mobile/auth/connect` in `ASWebAuthenticationSession`. The server binds
   the attempt to a browser cookie and redirects to Splitwise's OAuth consent page.
3. Splitwise returns to the **registered server callback** at
   `/oauth/splitwise/callback`. The server checks and consumes the state before
   exchanging the code, then looks up the authenticated Splitwise user ID.
4. The browser returns to `minto://oauth/complete`. No provider or app token is put
   into the callback URL. The native app exchanges the attempt with its separate
   random verifier at `POST /mobile/auth/exchange`; this exchange is one-use.
5. A random Minto session is stored in device-only Keychain, scoped to the server
   endpoint. Only a hash is stored on the server. Sessions expire after 30 days;
   logout revokes the current session. Reconnect when Splitwise authorization expires.

Provider tokens are encrypted with `TOKEN_ENCRYPTION_KEY`. Each Splitwise account
has a separate ledger database, review rules, audit history and sync cursor, keyed
by the server-verified user ID. Routes never accept a client-supplied account ID.
AI cache entries are also scoped to the authenticated account.

## Local iPhone setup

- Keep the existing Splitwise consumer key/secret in the ignored `.env`. Pro needs
  to be active on the account owning that registered application.
- Set `SPLITWISE_REDIRECT_URI` to `http://<MacLocalHostName>.local:8000/oauth/splitwise/callback`
  and set **the identical callback URL** in the Splitwise developer app's Edit form.
  `127.0.0.1` resolves to the iPhone itself when signing in on the phone.
- Run `.venv/bin/python tools/configure_ios_backend.py`, then start the backend:
  `.venv/bin/uvicorn splitwise_ledger.api:create_app --factory --host 0.0.0.0 --no-access-log`.
- Rebuild the `Ledger` scheme on the iPhone. Keep Mac and phone on the same network.
  Tap **Continue with Splitwise**; authorize the app, then return to Minto.
- The app session is provisioned by OAuth. No Xcode token environment variable or
  Gemini key is needed on the phone for the Splitwise mode.

The `.local` HTTP endpoint is for trusted local development only. Friends outside
that network need a stable hosted HTTPS backend and registered HTTPS callback.
Do not expose the local debug server directly to the internet. Before that rollout,
add invite-based access/admission limits, account deletion and a privacy notice.
One backend worker is required for this SQLite beta's in-process sync/AI locks.
Do not treat this as a production deployment template.

## Spending and category correctness

- Import the signed-in user's `owed_share`, whoever added or paid for the expense.
  Never use the total bill, `paid_share`, or net balance as personal spending.
- Exclude payment/settlement entries, `debt_consolidation` balance transfers (even
  when Splitwise marks `payment=false`), deleted expenses and zero shares. Settlement
  status of an ordinary expense does not remove historical spending.
- First sync backfills history; later syncs paginate by update time with an overlap.
  Records are upserted by source ID and revision. Cursor and batch commit together.
  Failed syncs keep the previous records; retrying does not add duplicates.
- Clear Splitwise categories and specific description phrases are matched automatically.
  Conflicting signals, broad categories (Insurance, Electronics, General) and ambiguous
  merchants stay in **Needs review**. Personal saved rules take precedence, and human
  choices survive matcher upgrades. All unclear expenses start in **Needs review**. Their shares remain in the overall
  total and in a separate unreviewed amount. They are not silently filed as Misc.
- The Expenses tab supports manual categories and optional remembered exact-description
  rules, constrained by group and currency. Remembered choices also match existing
  unreviewed imports; each sync reapplies matcher upgrades to eligible old records. Material source edits invalidate a human
  approval and stale review submissions return a conflict.
- Currencies are selectable in Settings and never summed together. This version
  does not perform exchange-rate conversion or split one expense across categories.
- The backend checks due accounts every 15 minutes and fetches each account at most
  once per 24 hours after its last successful sync. The timestamp is persisted across
  restarts. Foreground entry checks whether a sync is due; it does not poll every minute.
  Pull-to-refresh and Sync now explicitly force a fresh import. Splitwise read permission
  and deletion/update behavior must still be checked on each real account during the trial.
- AI uses selected aggregates, currency, the Needs review amount and follow-up text.
  It cannot mutate imported expenses, confirmed categories, or Splitwise.

## Validation and remaining live test

Automated tests cover browser cookie/state binding, one-use native handoff,
wrong/expired verifiers, account isolation even for the same shared expense ID,
revoked sessions, individual shares, stale reviews, edits/deletions, provider failures,
currency separation, pending totals and per-account AI caching. A signed iOS build
checks the native OAuth integration compiles.

The owner’s OAuth connection and full expense import have been verified against
the live API. Connect one non-Pro friend using the same registered OAuth app and
verify their expense fetch succeeds. Do not infer free-user eligibility just from
your own Pro account succeeding.

## Gemini category matching

With `GEMINI_AUTO_CATEGORIZE=true` (default) and the server Gemini key configured,
sync first uses explicit personal rules and deterministic source/description matches,
then checks a bounded Gemini batch. The foreground iPhone app continues the remaining
backlog through `/mobile/categories/auto`, updating totals after each batch. The daily backend worker also completes remaining batches when the app is closed. Provider failures never prevent
sync; failures back off for five minutes. Set the environment flag to false to disable
Gemini classification without disabling Ask Minto.

Gemini receives only expense descriptions (capped at 240 characters), existing source
category labels and the twelve-category definitions from `categorization.py`. No
amounts, notes, group names, source IDs, credentials or separate friend fields are
included. Descriptions can contain personal text entered by users. Uncertain or mixed
purchases from the initial import go into Others only after an actual uncertain Gemini decision.
New uncertain purchases prompt for review. Initial history is frozen by source ID so a newly
added backdated purchase still counts as new. Failed model requests remain queued for retry;
they are never treated as uncertain decisions. Misc and Lux are not unknown-category fallbacks.

Results are schema-validated, required to cover each batch exactly once, and applied
only if the source revision is unchanged and no human/rule decision has intervened.
Model and policy version are audited. Duplicate descriptions in the same group/currency
are classified together. Every checked revision, including uncertain outcomes, is
cached in that account's ledger to prevent repeated calls for unchanged expenses.
Manual overrides and remembered personal rules win over Gemini. No model is perfectly
accurate; automatically matched entries are labeled and remain editable in Expenses.

## Chart periods

Both overview and category charts default to six calendar months. The 3M/6M/12M
selector changes only the visible chart window. Previous/next controls navigate older
periods; selecting an older month repositions the window when needed. Month and year
labels use separate lines, with at most six x-axis labels even in the 12-month view.
Missing months are not fabricated as zero spending. All months totals still cover
all loaded data, independently of the chart window.

## Launch, daily sync and category review UX

Signed-out installations show a dedicated OAuth welcome screen, without dashboard
tabs. Saved sessions go straight to the dashboard; a server 401 returns to sign-in.

The backend daily worker runs for all connected accounts while the service is up,
including when phones are closed. It uses the same per-account lock as manual sync.
Failed scheduled requests retain data and back off for an hour. Explicit manual sync
bypasses freshness checks. No native every-minute timer remains. A sleeping/offline
Mac cannot run the worker; accounts catch up when the backend returns. A continuously
hosted backend is required for reliable daily service for friends outside the LAN.
Set `DAILY_SYNC_ENABLED=false` to disable the worker for tests or another scheduler.

The app opens a dismissible category-review sheet for newly encountered pending
revisions after matching finishes. Users choose a category one expense at a time,
optionally remember the choice, or skip/return later. The Overview review card stays
visible until all expenses are categorized. The same pending revision is not repeatedly
auto-presented during a session. Gemini and manual decisions never change personal
shares. Saving a category refreshes backend data without fetching Splitwise again.

Category detail shows expenses for the selected month or All months. Category history
month rows open that month's expense list. These lists use the same currency-filtered
personal-share dataset as the category totals, include offline cached rows, and exclude
settlements and pending expenses that have not yet been assigned to that category.
