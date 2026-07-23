#!/usr/bin/env bash
# Publish Mighty's committed actuals to the LIVE store + restart the app.
#
# WHY: on Cloud Run the app reads its committed state (which includes the
# accountant actuals: pl/bs/scf/studios) from GCS —
#   gs://empirica-portals-state/state/mighty/committed_actuals.json
# — NOT from the repo file. GCS wins; the committed file in the image is only a
# seed used when GCS is empty. So updating the file + redeploying is NOT enough;
# the new month must be pushed to GCS and the running instance restarted.
#
# Run this AFTER Stage 2 of the monthly actuals pipeline:
#   1. python run.py import-financials "<accountant .xlsx>"
#   2. python run.py update-dashboard --month YYYY-MM --source-label "<file>"
#   3. git commit dashboard/data/committed_actuals.json (+ deploy, for durability/seed)
#   4. ./scripts/publish_actuals.sh          <-- THIS: makes it live
#
# Requires: gcloud active account = chandler@empirica-analytics.com
set -euo pipefail

PROJECT="${PROJECT:-empirica-portals}"
REGION="${REGION:-us-central1}"
SRC="dashboard/data/committed_actuals.json"
DST="gs://empirica-portals-state/state/mighty/committed_actuals.json"

acct=$(gcloud config get-value account 2>/dev/null || true)
if [ "$acct" != "chandler@empirica-analytics.com" ]; then
  echo "!! gcloud account is '$acct' — must be chandler@empirica-analytics.com" >&2
  echo "   run: gcloud config set account chandler@empirica-analytics.com" >&2
  exit 1
fi

month=$(python3 -c "import json;print(json.load(open('$SRC'))['metadata']['last_actuals_month'])")
echo ">> Publishing committed actuals (through $month) to GCS"
gcloud storage cp "$SRC" "$DST"

echo ">> Restarting mighty-portal so it reloads committed state from GCS"
gcloud run services update mighty-portal --project "$PROJECT" --region "$REGION" \
  --update-env-vars "STATE_REFRESH=$(date +%Y%m%d%H%M%S)" --quiet >/dev/null

echo ">> Done. Verify: mighty.empirica-analytics.com shows 'Actuals through: $month'."
