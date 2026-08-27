# Cloud Run deployment

## Preconditions

- GCP project with billing, Cloud Run, Cloud Build, Artifact Registry, and Secret
  Manager enabled;
- `gcloud` authenticated as a deployer;
- dedicated runtime service account;
- LinkedIn `li_at` and `JSESSIONID` session values stored as separate secrets,
  never in source or command history.

## Configure authenticated LinkedIn secrets

```bash
PROJECT_ID="your-project-id"
REGION="us-east1"
SERVICE="profileproof-api"
RUNTIME_SA="profileproof-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
for SECRET in profileproof-linkedin-li-at profileproof-linkedin-jsessionid; do
  gcloud secrets create "$SECRET" --replication-policy=automatic
  gcloud secrets versions add "$SECRET" --data-file=-
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

The `versions add` command reads the key from standard input. Do not put the key
directly in the command or an environment file.

## Deploy from source

```bash
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account="$RUNTIME_SA" \
  --allow-unauthenticated \
  --port=8080 \
  --cpu=1 \
  --memory=512Mi \
  --min-instances=0 \
  --max-instances=1 \
  --concurrency=20 \
  --timeout=20s \
  --set-env-vars="PROFILEPROOF_ENVIRONMENT=production,PROFILEPROOF_CACHE_TTL_SECONDS=3600,PROFILEPROOF_LINKEDIN_CALLS_PER_INSTANCE_PER_DAY=100,PROFILEPROOF_LINKEDIN_MIN_INTERVAL_SECONDS=5" \
  --set-secrets="PROFILEPROOF_LINKEDIN_LI_AT=profileproof-linkedin-li-at:latest,PROFILEPROOF_LINKEDIN_JSESSIONID=profileproof-linkedin-jsessionid:latest" \
  --quiet
```

One maximum instance makes the in-memory daily provider quota and serialized
upstream pacing meaningful. Increase it only after moving coordination to a
shared store or fronting the service with authenticated, centrally enforced quota.

## Residential relay for blocked data-center egress

LinkedIn can reject data-center addresses even when the direct HTTP implementation
is correct. ProfileProof can keep Cloud Run as its stable public boundary while a
residential worker performs the same browserless LinkedIn request:

1. The worker opens a reverse HTTPS tunnel and writes its current origin to a
   public Cloud Storage text object. The object contains no credentials or profile data.
2. Cloud Run reads that pointer and accepts only `storage.googleapis.com`.
3. It accepts only HTTPS Serveo origins, forwards the canonical LinkedIn URL, validates
   the typed response, and verifies the returned public identifier.
4. `scripts/serveo_tunnel.py` republishes the origin after every reconnect, so the
   Cloud Run URL does not change.

Set the pointer on a zero-traffic candidate first:

```bash
gcloud run deploy "$SERVICE" --source . --region "$REGION" --no-traffic \
  --tag=relay-candidate \
  --update-env-vars="PROFILEPROOF_RELAY_POINTER_URL=https://storage.googleapis.com/BUCKET/current-origin.txt"
```

The worker must run the same application without `PROFILEPROOF_RELAY_POINTER_URL`;
otherwise it would relay back to itself. Keep its local API and tunnel supervisor
under the operating system's service manager so both restart automatically.

## Verify

```bash
SERVICE_URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --format='value(status.url)')"

curl -fsS "$SERVICE_URL/health"
curl -fsS "$SERVICE_URL/v1/capabilities"
curl -fsS "$SERVICE_URL/v1/profiles/resolve" \
  -H 'Content-Type: application/json' \
  -d '{"profile_url":"https://www.linkedin.com/in/seanthorne"}'
```

Verify that capabilities reports `linkedin_direct` as configured and that the
returned public identifier matches the request. With valid session secrets, require
`source.mode: authenticated_linkedin_voyager` and multiple populated professional
field groups. Without them, the service uses `source.mode: public_linkedin_jsonld`
and reports LinkedIn's omissions explicitly. A repeated lookup must report
`meta.cached: true`.

Promote only after the tagged candidate returns a real profile and a repeat call
reports `meta.cached: true`. If the relay is unavailable, the API fails explicitly
with problem details instead of returning sample data as if it were real.

## Rotate and roll back

Add a new secret version, deploy or restart the revision, verify, then disable the
old version. For application rollback:

```bash
gcloud run revisions list --service "$SERVICE" --region "$REGION"
gcloud run services update-traffic "$SERVICE" \
  --region "$REGION" --to-revisions="KNOWN_GOOD_REVISION=100"
```
