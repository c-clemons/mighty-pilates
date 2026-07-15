# Deploying the Mighty Pilates portal to Cloud Run

Target: a **private** Cloud Run service, SSO via **Cloudflare Access**, at
`https://mighty.empirica-analytics.com`. `empirica_core` is vendored, so builds
need no token.

> Entry point is `dashboard/app.py`. The Snowflake live-pull (`snowflake_actuals`)
> is optional and its import is guarded — the image ships **no** warehouse
> credentials, and `committed_actuals.json` is the source of truth. Add Snowflake
> secrets to the mounted `secrets.toml` only if you want the live actuals pull.

## Prerequisites (one-time per GCP project)

```bash
export PROJECT=<your-gcp-project>  REGION=us-central1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create portals \
  --repository-format=docker --location=$REGION --description="Empirica client portals"
```

## 1. Secrets

Create a local `.streamlit/secrets.toml` (gitignored):

```toml
github_token = "ghp_xxx"   # keeps committed_actuals.json durable across redeploys
app_password = "..."       # optional; ignored once Cloudflare Access is in front
# [snowflake]  # optional — only if you want the live actuals pull
# account = "..."; user = "..."; ...
```

```bash
gcloud secrets create mighty-secrets --data-file=.streamlit/secrets.toml
gcloud secrets versions add mighty-secrets --data-file=.streamlit/secrets.toml   # updates
PROJNUM=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding mighty-secrets \
  --member="serviceAccount:${PROJNUM}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## 2. Build + deploy

```bash
PROJECT=$PROJECT ./deploy.sh
```

Deploys **private**, mounting `mighty-secrets` at `~/.streamlit/secrets.toml`.

## 3. Test the private service

```bash
gcloud run services proxy mighty-portal --region $REGION   # http://localhost:8080
```

## 4. SSO front door — Cloudflare Access (email logins)

Same as the other portals: Cloudflare Tunnel to the private service, then a Zero
Trust → Access app on `mighty.empirica-analytics.com` allowing the client's
email(s). Access injects `Cf-Access-Authenticated-User-Email`, which
`auth.proxy_identity()` reads (skipping the password gate). Google IAP is the
alternative (its `X-Goog-Authenticated-User-Email` header is also handled).

## 5. Custom domain

Point `mighty.empirica-analytics.com` at the tunnel hostname / domain mapping.
Verify on the tunnel URL first, then attach DNS.

## 6. Retire the Streamlit Community Cloud app

Once `mighty.empirica-analytics.com` is verified live, delete the old SCC app.
