# Threat model

## Assets

- caller-supplied professional data;
- optional LinkedIn OIDC bearer tokens;
- API availability and quota;
- Cloud Run service identity and metadata endpoint;
- integrity of provenance and synthetic-data labels.

## Trust boundaries

1. Public internet to Cloud Run HTTPS frontend.
2. Cloud Run frontend to the application container.
3. Application to the fixed LinkedIn OIDC `userinfo` endpoint.
4. CI build to the produced container image.

## Principal threats and controls

| Threat | Control | Residual risk |
|---|---|---|
| SSRF through `profile_url` | Strict LinkedIn hostname/path parsing; the URL is never fetched | Parser bugs; tests cover encoded and alternate-host cases |
| Cloud metadata theft | No arbitrary outbound URL; fixed OIDC endpoint; no runtime IAM roles | A dependency compromise could still issue network calls |
| Credential leakage | No passwords/cookies; bearer token used for one request and never logged or cached | Infrastructure access logs must also avoid authorization headers |
| Fabricated provenance | Provider/mode/consent and warnings are mandatory response fields | A future provider must preserve these invariants |
| Resource exhaustion | 64 KiB body limit, model collection limits, per-instance rate limit, bounded cache | Distributed clients require Cloud Armor or API Gateway |
| PII retention | No database; consented and OIDC responses are not cached | Platform request tracing should remain body-free |
| Supply-chain compromise | Locked dependencies, CI lint/type/test/container build, minimal runtime image | Add image signing and vulnerability scanning for regulated use |
| XSS in demo UI | JSON rendered with `textContent`; CSP and `nosniff` headers | Swagger UI assets are framework-managed |

## Non-goals

The service does not evade access controls, automate login, solve challenges,
reuse browser sessions, crawl search results, or provide identity verification.
