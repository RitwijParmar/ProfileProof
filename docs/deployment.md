# Cloud Run deployment

## Preconditions

- an active GCP project with billing, Cloud Run, Cloud Build, and Artifact
  Registry enabled;
- `gcloud` authenticated as a deployer;
- a dedicated service account with no project roles for this application.

## Deploy from source

```bash
PROJECT_ID="your-project-id"
REGION="us-east1"
SERVICE="profileproof-api"

gcloud config set project "$PROJECT_ID"
gcloud iam service-accounts create profileproof-runtime \
  --display-name="ProfileProof Cloud Run runtime"

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account="profileproof-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
  --allow-unauthenticated \
  --port=8080 \
  --cpu=1 \
  --memory=512Mi \
  --min-instances=0 \
  --max-instances=3 \
  --concurrency=40 \
  --set-env-vars="PROFILEPROOF_ENVIRONMENT=production" \
  --quiet
```

No LinkedIn secret is needed for the demo or consented providers. If optional
API-key protection is enabled, store its digest in Secret Manager and mount a
pinned secret version as `PROFILEPROOF_API_KEY_SHA256`.

## Verify

```bash
SERVICE_URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --format='value(status.url)')"

curl -fsS "$SERVICE_URL/healthz"
curl -fsS "$SERVICE_URL/v1/profiles/resolve" \
  -H 'Content-Type: application/json' \
  -d '{"profile_url":"https://www.linkedin.com/in/profileproof-demo","provider":"demo"}'
```

Confirm the deployed revision, service identity, traffic allocation, ingress,
and environment configuration with `gcloud run services describe`.

## Rollback

List revisions, then direct all traffic to the last known-good revision:

```bash
gcloud run revisions list --service "$SERVICE" --region "$REGION"
gcloud run services update-traffic "$SERVICE" \
  --region "$REGION" --to-revisions="KNOWN_GOOD_REVISION=100"
```
