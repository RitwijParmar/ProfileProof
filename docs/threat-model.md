# Threat model

## Assets and trust boundaries

Assets include LinkedIn session secrets, licensed provider credits and API key,
professional-profile data, optional OIDC tokens, service availability, Cloud Run identity,
and the integrity of provenance. Trust boundaries are public internet to Cloud
Run, Cloud Run to the container, the container to fixed PDL/LinkedIn endpoints,
Secret Manager to the runtime identity, and CI to the container image.

## Principal threats and controls

| Threat | Control | Residual risk |
|---|---|---|
| SSRF through `profile_url` | Strict LinkedIn hostname/path parser; user URL is never fetched; provider endpoints are constants; redirects disabled | Parser or dependency defects; adversarial URL tests cover common variants |
| Provider-credit abuse | Request throttling, one-instance production cap, per-instance daily provider quota, TTL cache, identical-request single-flight | Distributed abuse still needs API Gateway/Cloud Armor and a shared quota store before scaling out |
| Incorrect identity match | PDL likelihood threshold defaults to 8/10; returned LinkedIn identifier must equal the requested identifier | Upstream source records can still be stale or wrong |
| Excessive personal-data collection | `data_include` requests named professional subfields only; API omits contact, email, phone, address, and unrelated social fields | Requested summaries may contain free-form personal information |
| Secret or token leakage | PDL key from Secret Manager; no key in capabilities/logs; OIDC token is neither logged nor cached; API keys stored as digests | Platform configuration and privileged operators remain trusted |
| Credential/session compromise | Session values live only in Secret Manager, are never logged/returned, and have a bounded call quota | The challenge path uses an undocumented authenticated endpoint; compromise or account restriction remains possible and requires immediate rotation |
| Resource exhaustion | Streaming 64 KiB request limit, bounded models/cache/rate-limit identities, provider timeout, Cloud Run concurrency and scale caps | Slow upstream responses consume slots until timeout |
| Cache privacy | Licensed records cached only in process memory for one hour; no database or disk persistence | Instance-memory inspection by a privileged operator is out of scope |
| Fabricated provenance | Provider, mode, license/consent flags, confidence, dataset version, limitations, and warnings are typed response fields | A future provider implementation must preserve the invariant |
| Supply-chain compromise | Locked dependencies, static analysis, strict typing, tests, dependency audit, minimal non-root image | Add signing, attestations, and continuous image scanning for regulated environments |
| XSS in demo UI | Static same-origin JS/CSS, JSON inserted with `textContent`, restrictive CSP and `nosniff` | Framework-hosted documentation pages have a separate asset surface |

## Non-goals

The service does not automate sign-in, solve challenges, crawl search results,
guarantee upstream correctness, or perform identity verification. It uses a
configured authenticated session only for profile URLs supplied by callers and
reports that acquisition mode explicitly.
