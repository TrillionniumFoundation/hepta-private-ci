# ui.control external qualification

Repository qualification proves the client, browser shell, protocol fixture, exact source head, and deterministic synthetic merge. It does **not** prove a selected real Agentd deployment, independent accessibility or security acceptance, or authorize production. External observations remain separate, exact-subject receipts and are never copied into tracked source as mutable truth.

## Stage and evidence model

`UI_CONTROL_MANIFEST.json` owns the seven stage definitions. `scripts/ui-control-status.mjs` projects those definitions into `STATUS.md` and `GATE_MAP.json`. The source-head and synthetic-merge jobs emit `hepta.ui-control.qualification-receipt.v2` receipts from that same manifest.

The stages remain deliberately separate:

1. design defined;
2. code present;
3. source tests passed;
4. browser tests passed;
5. merge tree passed;
6. real backend passed;
7. production deployment approved.

No later stage is inferred from an earlier stage. An observation and an accepted receipt are also different facts: every external probe writes a structured pass or failure receipt, while production approval requires an independently signed bundle of all prerequisite receipts.

## Exact deployment identity

Every external receipt binds all three values below:

```text
candidate commit
candidate Git tree
backend deployment digest
```

The backend deployment digest is SHA-256 over the normalized tuple:

```text
[HTTPS origin, normalized base path, operator-supplied immutable deployment ID]
```

The immutable deployment ID must identify the deployed backend and reverse-proxy release, not a mutable label such as `latest`. Receipts from another commit, tree, path, origin, or deployment ID are rejected.

## Deployment-security probe

`deployment-security.mjs` emits `hepta.ui-control.deployment-security-receipt.v2`. It runs only against an externally authenticated HTTPS deployment and verifies:

- a valid TLS 1.2 or TLS 1.3 handshake and unexpired authorized certificate;
- required CSP, HSTS, cache, framing, MIME, referrer, COOP, and CORP policy;
- attacker-origin preflight and credentialed request rejection;
- CSRF enforcement before session establishment and before mutation admission;
- authenticated connect, coherent view, and close;
- Secure, HttpOnly, SameSite, host-only cookie policy with the selected path;
- byte-for-byte SHA-256 identity for every deployed browser asset against the exact candidate build manifest.

Required environment:

```text
HEPTA_UI_CONTROL_BASE_URL
HEPTA_UI_CONTROL_DEPLOYMENT_ID
HEPTA_UI_CONTROL_COOKIE
HEPTA_UI_CONTROL_CSRF_TOKEN
```

Optional:

```text
HEPTA_UI_CONTROL_COOKIE_PATH
HEPTA_UI_CONTROL_BUILD_MANIFEST
```

A passing receipt proves only the observed endpoint, deployment identity, and exact candidate assets. It does not prove durable runtime semantics, independent acceptance, or release authority.

## Real Agentd/backend probe

`real-backend-contract.mjs` emits `hepta.ui-control.real-backend-receipt.v2`. It performs mutations and therefore requires disposable qualification identities and a disposable target. It verifies:

- concurrent identical operation identity resolves to one durable record;
- reuse of an operation identity with changed semantics returns conflict;
- a request rejected before admission creates no durable record;
- a deliberately discarded accepted acknowledgement is recovered by immutable operation ID;
- a second authenticated identity cannot observe the first identity's operation;
- terminal facts remain discoverable through lookup;
- revocation immediately removes session authority;
- reconnect after revocation receives a new session identity or connection generation;
- durable same-principal operation lookup survives that session switch.

The probe also validates two independently retained evidence documents before sending traffic:

- `AGENTD_CHAOS_EVIDENCE_SCHEMA.json` / `hepta.ui-control.agentd-chaos-evidence.v2`;
- `AUTHORITY_EVIDENCE_SCHEMA.json` / `hepta.ui-control.authority-evidence-receipt.v1`.

The chaos evidence contains four ordered case observations but only three independent operation identities. The post-dispatch crash and restart-reconciliation observations must bind the same operation ID, semantic digest, and durable-record digest; they must identify different Agentd instances, and the restart observation may not regress or duplicate the side-effect count:

- crash before admission commit: zero records, zero side effects, and no durable-record identity;
- crash after admission but before dispatch: one bound durable record and zero side effects;
- crash after dispatch but before terminal observation: one bound durable record, at most one side effect, and no premature terminal observation;
- restart reconciliation of that exact same operation and durable record: a different Agentd instance, at most one cumulative side effect, and a retained terminal observation.

The authority evidence must prove an advancing permission revision, a revoked mutation rejected without creating an operation, and a session switch that changes the session identity or advances its connection generation.

Required environment:

```text
HEPTA_UI_CONTROL_BASE_URL
HEPTA_UI_CONTROL_DEPLOYMENT_ID
HEPTA_UI_CONTROL_COOKIE
HEPTA_UI_CONTROL_CSRF_TOKEN
HEPTA_UI_CONTROL_SECONDARY_COOKIE
HEPTA_UI_CONTROL_SECONDARY_CSRF_TOKEN
HEPTA_UI_CONTROL_TARGET_ID
HEPTA_UI_CONTROL_CHAOS_EVIDENCE
HEPTA_UI_CONTROL_AUTHORITY_EVIDENCE
HEPTA_UI_CONTROL_ALLOW_MUTATION=I_UNDERSTAND_THIS_USES_A_DISPOSABLE_QUALIFICATION_TARGET
```

Optional settings are `HEPTA_UI_CONTROL_ACTION` (`request_reconcile`, `request_start`, or `request_stop`) and `HEPTA_UI_CONTROL_TERMINAL_TIMEOUT_MS`.

## Independent acceptance, security, and operations

The remaining external schemas are intentionally separate:

| Schema | Required evidence |
|---|---|
| `INDEPENDENT_ACCEPTANCE_SCHEMA.json` | Independent Chrome, Firefox, and Safari observations; keyboard-only coverage; at least two distinct screen-reader/assistive-technology observations |
| `INDEPENDENT_SECURITY_REVIEW_SCHEMA.json` | Eleven explicit passing control observations, each with its own raw-evidence digest: TLS, CSP, CSRF, CORS, cookie policy, production identity provider, session handling, operation ledger, browser token non-persistence, logging redaction, and penetration testing; no open critical or high finding |
| `OPERATIONAL_EXERCISE_SCHEMA.json` | Passed rollback, disaster-recovery, alert-routing, log-redaction, and credential-rotation exercises |
| `PRODUCTION_APPROVAL_SCHEMA.json` | Deployment, release, and security authorities; retained signature metadata; expiry; exact digests of all prerequisite evidence |

A scope declaration alone is not an accepted security review. Every required control needs an explicit `passed` observation and a bound raw-evidence digest. In particular, production IdP integration, browser token non-persistence, and logging redaction cannot be inferred from adjacent controls.

These receipts must bind the same candidate commit, candidate tree, and backend deployment digest. Evidence has bounded freshness windows, and duplicate or incomplete cases fail closed.

## Production evidence bundle

`validate-external-evidence.mjs` emits `hepta.ui-control.external-evidence-bundle.v1`. It accepts a production claim only when all of the following are present and mutually consistent:

1. exact-head `hepta.ui-control.qualification-receipt.v2`;
2. deterministic synthetic-merge `hepta.ui-control.qualification-receipt.v2`;
3. deployment-security v2 receipt whose deployed build-manifest digest matches the exact-head receipt;
4. real-backend v2 receipt;
5. independent acceptance v2 receipt;
6. independent security-review v1 receipt;
7. operational-exercise v1 receipt;
8. non-expired production-approval v1 receipt whose signed evidence-digest map covers items 1–7.

The production workflow additionally requires the candidate commit to be reachable from `main`. Missing, duplicate, malformed, stale, cross-candidate, cross-deployment, or failed evidence produces a structured failure bundle with every production and release claim set to false.

## Workflow dispatch

`.github/workflows/ui-control-external-qualification.yml` supports three progressively stronger modes:

1. deployment-security observation only;
2. deployment-security plus real Agentd/backend qualification;
3. the complete production-evidence bundle.

For mode 3, pass the workflow run ID that contains the exact-head and synthetic-merge artifacts for the same `candidate_sha`. The workflow downloads those immutable receipts rather than trusting hand-copied status text.

Repository or environment secrets used by the workflow are:

```text
HEPTA_UI_CONTROL_BASE_URL
HEPTA_UI_CONTROL_DEPLOYMENT_ID
HEPTA_UI_CONTROL_COOKIE
HEPTA_UI_CONTROL_CSRF_TOKEN
HEPTA_UI_CONTROL_COOKIE_PATH                       # optional
HEPTA_UI_CONTROL_SECONDARY_COOKIE
HEPTA_UI_CONTROL_SECONDARY_CSRF_TOKEN
HEPTA_UI_CONTROL_TARGET_ID
HEPTA_UI_CONTROL_CHAOS_EVIDENCE_JSON
HEPTA_UI_CONTROL_AUTHORITY_EVIDENCE_JSON
HEPTA_UI_CONTROL_INDEPENDENT_ACCEPTANCE_JSON
HEPTA_UI_CONTROL_INDEPENDENT_SECURITY_REVIEW_JSON
HEPTA_UI_CONTROL_OPERATIONAL_EXERCISE_JSON
HEPTA_UI_CONTROL_PRODUCTION_APPROVAL_JSON
```

Use a protected GitHub environment for credentials and authority receipts. The workflow has read-only repository and Actions permissions, never writes source, and uploads pass or failure evidence with bounded retention.

## Failure receipts

The deployment, real-backend, and bundle validators all fail closed. Once the exact candidate has been checked out, validation failures are written as structured JSON before the command exits nonzero. Failure receipts contain a bounded error code and sanitized message, never credentials, tokens, cookies, unrestricted reason text, or full backend responses.

Infrastructure failure before checkout or before the validator starts remains `infrastructure-invalid`; it must not be translated into a semantic pass.

## Non-claims

Schema presence, repository tests, a mock server, a configured secret, or an uploaded JSON document is not evidence that an external stage passed. Production completion exists only in an accepted external bundle for one exact candidate and deployment, together with the retained independent raw evidence and explicit release authority.
