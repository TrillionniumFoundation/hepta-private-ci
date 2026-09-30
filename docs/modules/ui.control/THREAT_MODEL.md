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
- exact browser-build identity and the sole declared CSRF bootstrap substitution;
- browser recovery ledger containing non-secret operation metadata.

## Trust boundaries

1. **Untrusted browser environment.** Extensions, injected scripts, stale tabs, storage denial/corruption, and local state are not authority.
2. **Same-origin reverse proxy.** Terminates TLS, supplies security headers, injects only the declared CSRF bootstrap value, and routes only the versioned API.
3. **Authentication/session service.** Establishes identity, expiry, permission revision, connection generation, and protected CSRF rotation.
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
| Bootstrap or reverse-proxy rewriting | Build manifest v2 declares only the `index.html` CSRF meta-content slot. Qualification verifies the deployed token against the protected input, canonicalizes only that slot, and requires every remaining byte to match the exact candidate. |
| Cross-site scripting | No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, or inline executable script; use `textContent`; strict CSP. |
| Clickjacking | `frame-ancestors 'none'` and `X-Frame-Options: DENY`. |
| Identity substitution during refresh | Require the refreshed session ID and authenticated identity to match the active session; fail closed on identity drift. |
| Previous-identity recovery after login switch | Filter pending/completed projections, exports and lookup by the current authenticated identity; retain original records and apply one total pending-capacity bound. |
| Hidden permission change or revision rollback | Reject permission revision regression and reject permission-set drift at an unchanged permission revision. |
| Refresh/close/revoke race | Fence in-flight refresh against the active session object; clear local authority before transport cleanup so a failed close or revoke cannot preserve control access. |
| Snapshot equivocation | Same generation/revision with a different semantic digest is `UI_CONTROL_SNAPSHOT_DRIFT`. |
| Prototype pollution / hostile JSON | Plain objects only, forbidden prototype keys, bounded depth/entries/bytes, safe integers, NFC text, control/bidi-invisible rejection. |
| Request serialization side effects or amplification | Validate plain JSON without executing getters or `toJSON`, enforce a 64 KiB encoded request ceiling, and reject mutation-method substitution before dispatch. |
| Response amplification or slow body | One-megabyte response bound and timeout coverage across both response headers and body consumption; cancel unread or unfinished bodies when validation rejects them. |
| Credential or token persistence | Credentials stay in HttpOnly cookies; the CSRF token may exist only in the protected live bootstrap and in-memory transport provider, and is never exported to recovery or browser persistence. |
| DOM scraping or shoulder-surfing of correlation material | Render session, operation, audit-trace, snapshot, semantic, and outcome identifiers in a deterministic redacted form by default. Keep full values in authority-free client state and transport objects rather than DOM text, attributes, or live-region messages. The authenticated operator identity remains visible so the operator can detect account confusion. |
| Unexpected exception reflection | Render only known data-property error codes with fixed operator messages. Backend validation labels, typed messages, details and causes remain outside the DOM and live regions; unknown or accessor-shaped codes receive a generic failure. |
| Local storage denial or corruption | Recovery persistence is best-effort, typed, and visible; storage failure cannot wedge the UI, authorize a request, or manufacture terminal state. |
| Audit spoofing | Audit trace IDs are server-issued and validated; the client never synthesizes terminal success. |
| Open redirect / cross-origin exfiltration | Transport URL must remain beneath the configured same-origin API base; redirects are rejected; referrer policy is `no-referrer`. |
| Supply-chain drift in browser tests | CI uses the committed exact npm lock, records its SHA-256 digest and resolved graph, and runs installation with scripts disabled. |
| Receipt self-assertion | External bundle validation requires exact case sets, terminal observations, evidence digests, candidate/tree/deployment binding, accepted main ancestry, and all prerequisite stages before production or release claims can become true. |

## Required response headers

The deployed host must send at least:

```text
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
Strict-Transport-Security: max-age=<positive deployment policy value>
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Cache-Control: no-store
```

Production may strengthen CSP with nonces/hashes, Trusted Types, and COEP after validating downstream compatibility. HSTS, the listed CSP directives, browser-isolation headers, and no-store behavior are required by deployed qualification. A CSP meta element is defense-in-depth for the static repository fixture; it does not prove deployed headers.

## CSRF and cookie requirements

- session cookies: `Secure; HttpOnly; SameSite=Strict` unless a documented federated-login flow requires a narrower `Lax` exception;
- mutation requests: valid bounded CSRF token, expected `Origin`, and permitted Fetch Metadata headers;
- the live `index.html` token must equal the protected qualification/session token and be the only declared runtime browser-asset substitution;
- the token must rotate on authentication, privilege change, and connection-generation change;
- no mutation over `GET`;
- no wildcard CORS and no credentialed cross-origin CORS;
- no CSRF token in local storage, session storage, IndexedDB, recovery state, logs, receipts, or artifact names.

## Logging and privacy

Logs may include operation ID, semantic digest, action, target, generation, revision, permission revision, backend result code, and audit trace ID. Logs must not include session cookies, CSRF tokens, bearer tokens, full identity assertions, or unrestricted operator-entered text. Reasons should be length-bounded and handled under the deployment's retention policy.

The browser shell displays correlation identifiers only in redacted form. Full identifiers remain available to typed client-state and transport code for exact matching, recovery, and backend audit correlation; they are not copied into DOM text or attributes by the repository shell.

## Residual risks requiring external evidence

- production identity-provider correctness and emergency revocation latency;
- reverse-proxy/TLS/header correctness and correct bounded bootstrap substitution in the deployed route;
- backend ledger durability, uniqueness, outbox atomicity, and disaster recovery;
- runtime owner generation fencing and authorization;
- manual screen-reader and operator usability acceptance;
- browser-extension or endpoint-compromise risk outside the application trust model;
- authenticity and governance of independently produced security, operational, and approval evidence before those receipts are placed in protected workflow secrets.
