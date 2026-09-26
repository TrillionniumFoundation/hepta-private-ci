# ui.control threat model

## Security objective

`ui.control` is an authority-free request surface. A compromised or stale browser must not be able to manufacture runtime facts, bypass server authorization, replay a request under different semantics, or turn an uncertain network result into a second side effect.

## Assets

- authenticated operator identity and permission revision;
- session ID and connection generation;
- runtime generation, revision, module status, and semantic digests;
- operation ID, semantic digest, action, target, reason, and displayed revision;
- server audit trace and durable terminal observation;
- CSRF token and same-origin session cookie;
- browser recovery ledger containing non-secret operation metadata.

## Trust boundaries

1. **Untrusted browser environment.** Extensions, injected scripts, stale tabs, and local storage are not authority.
2. **Same-origin reverse proxy.** Terminates TLS and must supply security headers and route only the versioned API.
3. **Authentication/session service.** Establishes identity, expiry, permission revision, and connection generation.
4. **Operation ledger.** Owns the unique operation ID constraint and durable lookup.
5. **Runtime authority.** Decides whether and how a request mutates runtime state and emits terminal facts.
6. **Audit/monitoring systems.** Correlate operation and trace identities but do not substitute for runtime truth.

## Threats and mitigations

| Threat | Required mitigation |
|---|---|
| Stale-view control | Bind every mutation to session, connection generation, runtime generation, displayed revision, and snapshot digest; reject 409/412 server-side. |
| Double click or concurrent duplicate | Reserve operation ID before dispatch, share one in-flight promise, and enforce a server unique constraint. |
| Same ID with different intent | Compare semantic digest under the unique operation ID and reject conflict without side effect. |
| Accepted request with lost response | Mark indeterminate; perform durable lookup; never automatically resend a mutation. |
| Cross-site request forgery | SameSite/HttpOnly/Secure session cookie, same-origin API, per-session CSRF token, Origin/Fetch-Metadata checks, no permissive CORS. |
| Cross-site scripting | No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, or inline executable script; use `textContent`; strict CSP. |
| Clickjacking | `frame-ancestors 'none'` and `X-Frame-Options: DENY`. |
| Permission change or revocation | Session refresh carries permission revision and expiry; revoked/expired sessions disable all actions; changed connection generation invalidates the snapshot. |
| Snapshot equivocation | Same generation/revision with a different semantic digest is `UI_CONTROL_SNAPSHOT_DRIFT`. |
| Prototype pollution / hostile JSON | Plain objects only, forbidden prototype keys, bounded depth/entries/bytes, safe integers, NFC text, control/bidi-invisible rejection. |
| Response amplification | One-megabyte response bound and bounded module/pending counts. |
| Credential or token persistence | Credentials stay in HttpOnly cookies; CSRF token is not exported in recovery state; recovery state contains operation metadata only. |
| Audit spoofing | Audit trace IDs are server-issued and validated; the client never synthesizes terminal success. |
| Open redirect / cross-origin exfiltration | Transport URL must remain beneath the configured same-origin API base; redirects are rejected; referrer policy is `no-referrer`. |
| Supply-chain drift in browser tests | CI pins direct Playwright and axe package versions and records resolved package identity in logs/receipt inputs. |

## Required response headers

The deployed host must send at least:

```text
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

Production may add nonce/hash-based script policy, Trusted Types, HSTS, and COEP after validating downstream compatibility. A CSP meta element is defense-in-depth for the static repository fixture; it does not prove deployed headers.

## CSRF and cookie requirements

- session cookies: `Secure; HttpOnly; SameSite=Strict` unless a documented federated-login flow requires a narrower exception;
- mutation requests: valid CSRF token, expected `Origin`, and permitted Fetch Metadata headers;
- no mutation over `GET`;
- no wildcard CORS and no credentialed cross-origin CORS;
- CSRF token rotation on authentication, privilege change, and connection-generation change.

## Logging and privacy

Logs may include operation ID, semantic digest, action, target, generation, revision, permission revision, backend result code, and audit trace ID. Logs must not include session cookies, CSRF tokens, bearer tokens, full identity assertions, or unrestricted operator-entered text. Reasons should be length-bounded and handled under the deployment's retention policy.

## Residual risks requiring external evidence

- production identity-provider correctness and emergency revocation latency;
- reverse-proxy/TLS/header correctness in the deployed route;
- backend ledger durability, uniqueness, outbox atomicity, and disaster recovery;
- runtime owner generation fencing and authorization;
- manual screen-reader and operator usability acceptance;
- browser-extension or endpoint-compromise risk outside the application trust model.
