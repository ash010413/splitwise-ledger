# Cloud deployment runbook

Project: `minto-513300` · Region: `us-central1`

Backend: https://minto-997824541815.us-central1.run.app

Health: https://minto-997824541815.us-central1.run.app/health

Splitwise registered callback:
`https://minto-997824541815.us-central1.run.app/oauth/splitwise/callback`

## Runtime and costs

Cloud Run uses request-based billing, zero minimum instances, a maximum of one
instance, 1 CPU, 512 MiB, concurrency 8 and a 900-second timeout. The service can
sleep between requests. SDK-managed identity accesses Firestore and three pinned
Secret Manager versions; no service-account key files are generated.

The default Firestore database is Standard/Native mode in `us-central1`, eligible
for the database free allowance. No paid PITR, TTL deletion or scheduled database
backup feature is enabled. Establish and test a restore procedure before expanding the beta.

One Cloud Scheduler job, `minto-daily-sync`, runs hourly and checks persisted daily
sync timestamps. It does not fetch Splitwise hourly: each account is imported at
most once per 24 hours unless the user explicitly refreshes. Each job checks a
bounded number of AI batches and can resume on a subsequent invocation. Native
foreground matching continues the remaining batches too.

These settings target the published free allowances for a handful of users. They
are not a hard dollar cap. Free allowances can be shared with other projects on
the billing account. Container builds, registry storage, logs and network usage
also have limits. The image repository keeps its two latest backend versions and
cleans up older versions after a day. OAuth callback request URLs are excluded
from the default log sink to avoid retaining authorization-code query strings.
Review Cloud Billing after deployment and after adding users.
Do not raise minimum instances or add a load balancer/NAT for this beta.

## Durable storage and correctness

The local SQLite adapter remains available for development. Hosted routes use
Firestore repositories; no authoritative state lives in the container filesystem.
The service refuses to start on Cloud Run with SQLite or its local background loop.
Legacy static-token endpoints are not registered in hosted mode.

Each account's ledger is partitioned into 64 documents, with an atomic versioned
metadata document. A bounded cache is validated against that version on every
transaction. This keeps normal refreshes from reading one document per expense.
Changed pages, cursor and audit batches commit together. Page and request size
checks fail before committing, preserving existing data. This layout is intended
for a small beta; capacity errors require repartitioning rather than dropping data.

OAuth attempts and native session hashes are separate documents with server-side
expiry validation. Provider tokens remain encrypted. Native sessions are bound to
the backend URL on the device and are not copied during migration. The initial beta
allows four connected accounts (up to four users; capacity is not an invitation allowlist).

Firestore transactions protect one-use OAuth exchanges and category edits. Per-user
leases coordinate sync and matching across overlapping Cloud Run revisions. Writes
from expired workers are fenced. AI decisions still check source revisions and
human choices before application. The scheduler endpoint checks Google's signed
OIDC token, audience, verified email and the dedicated scheduler identity.

## Redeploy

Authenticate with `gcloud auth login` using an authorized deployment account. Install
backend tools with `pip install -e '.[dev,cloud]'`. No password or key belongs in Git.

Create an empty, allowlisted context (choose a new temporary directory each time):

```sh
.venv/bin/python tools/build_cloud_context.py /tmp/minto-cloud-build-next
```

This copies only the Dockerfile, package metadata, locked runtime dependencies,
backend source and Cloud Build recipe. It excludes local databases, `.env`, iOS
configuration, Git history and tests.

Build with a new image tag:

```sh
gcloud builds submit /tmp/minto-cloud-build-next \
  --config=deploy/gcp/cloudbuild.yaml \
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/minto-513300/minto/backend:NEW_TAG \
  --service-account=projects/minto-513300/serviceAccounts/minto-build@minto-513300.iam.gserviceaccount.com \
  --default-buckets-behavior=regional-user-owned-bucket \
  --region=us-central1 --project=minto-513300

gcloud run services update minto \
  --image=us-central1-docker.pkg.dev/minto-513300/minto/backend:NEW_TAG \
  --region=us-central1 --project=minto-513300
```

Updating the image retains the existing runtime configuration and secret bindings.
Keep both Cloud Run and Firestore in the same region. Keep a single Uvicorn worker;
leases provide cross-revision coordination, not a reason to increase scale.

Required runtime settings are `STORAGE_BACKEND=firestore`,
`FIRESTORE_PROJECT=minto-513300`, `DAILY_SYNC_ENABLED=false`, the HTTPS Splitwise
callback, scheduler audience equal to the backend URL, and scheduler identity
`minto-scheduler@minto-513300.iam.gserviceaccount.com`. Gemini matching remains enabled.

Secrets are `minto-splitwise-secret`, `minto-encryption-key`, `minto-gemini-key`.
The runtime has access to these secrets only. Do not rotate the encryption key
without migrating encrypted provider tokens. Bind explicit secret versions when
rotating a key; older disabled versions and stale images should not accumulate.

The scheduler uses POST `/internal/sync` with its Google-signed OIDC identity.
Do not put the app bearer token or a static key in the scheduler URL or headers.

## Migration and verification

`tools/migrate_to_firestore.py` transfers local settings, rules, expenses, current
AI decisions, historical markers and audit records. It verifies the hosted
category/share data against the source, checks the hosted encryption key, and
refuses to overwrite an existing hosted ledger. Re-running an identical migration
preserves subsequent cloud edits. Run it only after taking a SQLite backup:

```sh
.venv/bin/python tools/migrate_to_firestore.py --project=minto-513300
```

Verify `/health`, unauthorized expense/scheduler rejection, signed-in expenses,
profile, manual sync followed by automatic skip, Gemini summaries, and a genuine
Scheduler invocation. Synthetic live Firestore tests must use an isolated negative
account ID and clean up only their own pages/audit documents afterward.

## iPhone builds

`ios/Production.xcconfig` contains the public HTTPS endpoint. Release builds use it
directly. Debug builds inherit it, with optional overrides from ignored
`ios/Development.local.xcconfig`. Credentials remain exclusively on the backend.

After changing from the Mac endpoint, rebuild and sign in once on the iPhone.
No Mac server or shared Wi-Fi is needed. TestFlight upload and Apple's beta review
are a separate distribution step; an unsigned Release verification build is not
an uploaded or distributable TestFlight build.
