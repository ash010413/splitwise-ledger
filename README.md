> **Current integration:** Minto now includes a per-user Splitwise OAuth beta,
> personal-share syncing, category review and separate currency views. See
> [Splitwise beta setup and architecture](docs/splitwise-beta.md). The older
> single-account CLI and Google Sheets prototype are retained below for reference.

# Minto

Make room for clarity. A personal spending app with live Google Sheets totals and
on-demand Gemini summaries. The repository and internal module names retain their
original identifiers so existing clones, signing settings and credentials keep working.

**Current focus: native iOS viewer for your manually maintained sheet.**
The [iOS app setup and architecture](ios/README.md) describe the SwiftUI viewer,
live read-only Sheets connection, interactive charts and on-demand Gemini summaries.
Sheets refresh works without the backend. Gemini requires a backend key in `.env`
and the app's Settings connection; Splitwise OAuth is independent and optional.

The original Splitwise ingestion scaffold below tracks **your share**, approved
category rules and explicit review. Splitwise access remains unverified. The app
currently uses the manually maintained sheet rather than that ingestion path.

Read [the architecture and flow map](docs/architecture.md) first.

## Run locally

Python 3.11 or newer:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m splitwise_ledger.cli init-local
```

Register an OAuth application in the [Splitwise developer portal](https://secure.splitwise.com/apps).
Use `http://127.0.0.1:8000/oauth/splitwise/callback` as the redirect URI if accepted.
Edit the generated `.env` locally to set `SPLITWISE_CLIENT_ID` and
`SPLITWISE_CLIENT_SECRET`. Do not paste secrets into chat or commit them.

```sh
.venv/bin/uvicorn splitwise_ledger.api:create_app --factory --host 127.0.0.1 --no-access-log
```

In a second terminal in this repository:

```sh
.venv/bin/python -m splitwise_ledger.cli connect
# After authorizing in your browser:
.venv/bin/python -m splitwise_ledger.cli sync
```

App endpoints require `Authorization: Bearer <APP_API_TOKEN>`. Local interactive API
documentation is available at http://127.0.0.1:8000/docs; use its Authorize button.

| Endpoint | Purpose |
| --- | --- |
| `POST /oauth/splitwise/start` | Create one-time browser connection URL |
| `GET /oauth/splitwise/connect` | Bind browser state and redirect to Splitwise |
| `GET /oauth/splitwise/callback` | Validate state and exchange authorization code |
| `POST /sync` | Hook for Sync now or an external daily scheduler |
| `GET /expenses?pending_only=true` | Review inbox |
| `POST /expenses/{id}/review` | Choose category using current revision |
| `GET /categories` | Allowed category values |
| `GET /summary` | Monthly totals, separated by currency and category |

Review example (body only):

```json
{
  "revision": "revision-returned-by-expenses-endpoint",
  "category": "Food / Dining",
  "remember_rule": false
}
```

Remembering a rule is optional and scoped to exact normalized description, group
and currency. Review mixed purchases manually once allocations are implemented;
do not force an ambiguous purchase into one category.

## Verify

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

Tests use a fake provider or mock HTTP transport and never contact real accounts.
`requirements.lock` records the tested development environment. Install it for an
exact environment, then install this package with `pip install -e . --no-deps`.

## Current limits

Single account and one backend worker only. Local bearer-token authentication is
for development, not an App Store release. No Google Sheets authorization or writes,
deployed scheduler, iOS app, push notifications, token auto-refresh, mixed-category
allocations or production deletion reconciliation yet. The architecture document
defines these next steps and the financial invariants they must preserve.

## Public source, private data

The repository includes only synthetic sample expenses. Keep your personal Sheet ID,
summary-tab name, Gemini key, application token and OAuth secrets in the ignored
`.env`, using `.env.example` as the template. Run:

```sh
.venv/bin/python tools/configure_ios_backend.py
```

This generates ignored, machine-specific Xcode configuration. The dashboard uses
real sheet rows only; examples are never substituted when a refresh fails. Currency
is intentionally USD and the twelve categories follow the documented personal
schema. Months, totals, labels, category counts, chart hit targets and summary scope
are data-driven. Configure the summary tab rather than editing a hardcoded year.

Before publishing changes, audit reachable history without displaying secrets:

```sh
.venv/bin/python tools/check_public_history.py --env .env
```
