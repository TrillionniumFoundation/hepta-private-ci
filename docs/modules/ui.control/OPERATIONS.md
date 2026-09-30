# ui.control deployment, monitoring, and rollback runbook

## Deployment topology

Recommended production path:

```text
operator browser
  -> TLS reverse proxy / static asset host
     -> /api/ui-control/v1/session/*  identity/session service
     -> /api/ui-control/v1/view       coherent runtime projection service
     -> /api/ui-control/v1/operations durable operation ledger / runtime dispatcher
```

The static shell and API must share an origin. Cross-origin credentialed deployment is not supported by the repository transport.

## Build and promotion

```bash
npm ci --prefix apps/hepta-control-ui --ignore-scripts --no-audit --no-fund
npm run check --prefix apps/hepta-control-ui
npm run test:e2e --prefix apps/hepta-control-ui
```

The committed `apps/hepta-control-ui/package-lock.json` is part of the source identity. Qualification records its SHA-256 digest and resolved dependency graph; do not replace `npm ci` with an unlocked install. Promote only generated `dist/` contents whose `build-manifest.json` digest and dependency-lock digest are present in the exact-head qualification receipt. Do not promote a working-tree artifact or a build from another SHA.

`hepta.ui-control.browser-build.v2` declares one and only one runtime substitution: the empty `index.html` CSRF meta slot may be replaced with the bounded, attribute-safe token selected for the authenticated deployment session. External qualification reads the exact candidate `index.html`, verifies its manifest digest, verifies the deployed token equals the selected protected token, restores the canonical empty slot in memory, and then requires byte identity with the candidate. Every other browser asset remains byte-for-byte exact. Template engines, proxies, or identity products must not rewrite any other HTML, script, style, or module byte.

Each deployed release must have an immutable deployment ID. The external qualification tools derive a backend deployment digest from the HTTPS origin, normalized base path, and that deployment ID. Reusing a mutable name such as `current`, `latest`, or an environment name across releases defeats exact evidence binding and is prohibited.

## Required backend capabilities

- exact protocol `hepta.ui-control.v1`;
- authenticated session connect, refresh, revoke, and close;
- permission revision and connection generation;
- stable authenticated identity across refresh;
- coherent snapshot endpoint;
- durable operation admission with unique ID/digest semantics;
- authenticated operation lookup; `found: false` reports current absence and cannot finalize non-admission;
- terminal observation;
- server-issued audit trace;
- generation fencing at execution;
- durable ledger and reconciliation state across Agentd restart;
- same-principal lookup continuity across session rotation;
- revocation fencing before mutation admission.

## Configuration

The repository shell uses `/api/ui-control/v1/` by default. Deployment configuration may change the same-origin base before constructing `SameOriginHttpTransport`; it must still end with `/` and remain under the page origin. The repository browser build consumes the declared `index.html` CSRF bootstrap slot. The serving tier must substitute exactly that slot from a protected same-origin/session mechanism, rotate the token with the session, and leave every other candidate byte unchanged. A different bootstrap mechanism requires a new reviewed browser-build schema and matching qualification logic; it must not be smuggled in as an untracked deployment rewrite.

Credentials, cookies, CSRF tokens, raw evidence, and approval signatures belong in protected environment secrets or a dedicated evidence store. They must never be placed in tracked source, workflow summaries, browser storage, or uploaded unrestricted logs. The CSRF token may exist in the live page bootstrap and in-memory transport provider; it must not be copied into recovery state, local/session storage, IndexedDB, logs, receipts, or artifact names.

Production approval accepts only retained `sigstore-bundle` metadata, three distinct authority identities, an approval lifetime of at most 90 days, and the exact prerequisite digest set. The independent release process must cryptographically verify the Sigstore bundle and signer identities before placing the approval receipt in the protected environment secret; the repository validator deliberately does not treat a self-supplied public key or unsigned JSON assertion as authority.

## Health and readiness

Static readiness requires:

- `index.html`, JS modules, CSS, and `build-manifest.json` available;
- candidate byte identity for every static asset, with only the declared CSRF meta-content substitution canonicalized for `index.html`;
- the deployed CSRF bootstrap value matches the protected token selected for the qualification session;
- CSP and other security headers present on HTML and modules;
- no mixed content or cross-origin module fetches;
- TLS 1.2 or newer with an authorized, unexpired certificate and retained SHA-256 certificate fingerprint.

API readiness requires:

- session connect/refresh operational;
- coherent view available;
- ledger insert and lookup healthy;
- runtime dispatcher able to consume fenced work;
- audit trace backend available or safely buffered;
- revocation and permission-revision propagation healthy;
- restart reconciliation able to recover admitted operations without duplicate effects.

## Metrics

At minimum collect:

- connect, refresh, revoke, and permission-denied counts;
- session identity-drift and permission-revision-regression rejection counts;
- snapshot latency, stale-view duration, drift rejection count;
- operation admission latency and result code;
- unique conflict count and identical replay count;
- accepted-to-terminal latency by action and target;
- indeterminate submission count and lookup recovery outcome;
- absent-but-indeterminate lookup count and accepted-acknowledgement/`found:false` contradiction count;
- pending ledger age, maximum lookup wait, lookup latency, recovery-backoff deferrals, active backoff entries, and next eligible lookup time;
- outbox backlog and generation-fence rejection count;
- frontend error code count, including local recovery-storage degradation, without tokens or unrestricted reason text;
- CSP violation reports and failed integrity/build-manifest checks;
- crash/restart reconciliation duration and duplicate-side-effect count;
- credential/session rotation success and stale-session rejection counts.

Suggested alerts should be calibrated from observed traffic rather than copied as unverified constants. Always alert on sustained ledger write failure, lookup failure, accepted-acknowledgement/lookup contradiction, recovery starvation, outbox growth, snapshot drift, authorization anomalies, inability to revoke sessions, asset digest drift, undeclared bootstrap rewriting, CSRF bootstrap mismatch, or inability to reconcile after restart.

## External qualification sequence

1. Freeze an exact candidate SHA and Git tree.
2. Run the repository exact-head and deterministic synthetic-merge qualification and retain both `hepta.ui-control.qualification-receipt.v2` artifacts.
3. Merge or otherwise make that exact candidate reachable from `main`; production release authorization is impossible while the candidate remains off-main.
4. Deploy that exact browser build and backend release under an immutable deployment ID. Substitute only the declared `index.html` CSRF bootstrap slot.
5. Run deployment-security qualification. This checks TLS and certificate identity, candidate asset bytes plus the one bounded CSRF substitution, CSP, HSTS, CORS, CSRF, cookie policy, authenticated read, and close.
6. On disposable identities and target, run real Agentd/backend qualification with independently retained chaos and authority evidence.
7. Obtain independent Chrome, Firefox, Safari, keyboard-only, and screen-reader/operator acceptance against the same deployment.
8. Obtain independent security/penetration review with no open critical or high finding.
9. Exercise rollback, disaster recovery, alert routing, log redaction, and credential rotation.
10. Have deployment, release, and security authorities sign a non-expired approval binding the SHA-256 digest of every prerequisite receipt.
11. Run `validate-external-evidence.mjs` or the production-evidence workflow job and retain the accepted bundle. The validator independently checks main ancestry and cannot project `productionDeploymentApproved` or `releaseAuthorized` from a production-approval receipt alone.

A missing or failed item must produce a failed/absent stage. It must never be replaced with a hand-edited status boolean.

## Incident handling

1. Disable mutation routes or revoke the affected permission while keeping read-only diagnostics available where safe.
2. Preserve operation ledger, scoped browser recovery records, audit traces, reverse-proxy logs, build receipt, exact dependency-lock digest, exact deployed asset digest, deployment ID, declared bootstrap-substitution mode, and external evidence bundle.
3. Identify all indeterminate operations by operation ID; resolve through the ledger before any replay.
4. Treat `found: false` after an accepted acknowledgement as a backend durability incident, not safe non-admission.
5. Fence affected runtime generations if stale work may remain queued.
6. Rotate sessions/CSRF material after identity or origin compromise.
7. Invalidate any approval or evidence bundle whose candidate, deployment identity, credentials, findings, operational facts, bootstrap substitution, or certificate identity changed.
8. Restore mutation capability only after ledger, dispatcher, authorization, asset, header, bootstrap, and restart-reconciliation checks pass.

## Rollback

1. Select a previously qualified browser build, dependency lock, and receipt.
2. Confirm protocol compatibility with the currently deployed API.
3. Atomically switch static assets; do not roll back the durable operation ledger.
4. Keep operation ID namespace and terminal records intact across rollback.
5. Invalidate cached HTML and service-worker state; this repository does not install a service worker.
6. Refresh/revoke sessions and rotate the CSRF bootstrap material if permission, protocol, or deployment identity changed.
7. Run read-only smoke, one fenced non-destructive qualification operation, lookup, and terminal observation.
8. Record the deployed build-manifest digest, dependency-lock digest, immutable rollback deployment ID, and rollback reason.
9. Re-run deployment-security and applicable real-backend qualification; the previous production approval does not automatically authorize the rollback deployment.

## Disaster recovery exercise

The retained exercise must demonstrate, rather than merely describe:

- restoration of the durable operation ledger and audit linkage;
- exactly-once-or-at-most-once behavior for admitted operations after restart;
- reconciliation of pending work to an authoritative terminal or retained pending state;
- absence of duplicate side effects in the tested crash windows;
- restored revocation and permission-revision enforcement;
- measured recovery time and operator-visible status;
- alert delivery and evidence preservation throughout the exercise.

## Release checklist

- authoritative source is reachable from `main`, and the exact SHA/tree is identified;
- exact package lock is present and its digest is bound into the source receipt;
- generated docs are current;
- exact-head and deterministic synthetic-merge receipts are both accepted;
- unit, contract, build, three-browser E2E, axe, Lane B, and external-evidence validator tests are green;
- deployed browser assets match the exact candidate build manifest, with only the declared and token-bound `index.html` CSRF slot canonicalized;
- TLS, certificate fingerprint, CSP, CSRF, CORS, cookie, identity, and session observations are accepted for the selected deployment digest;
- real Agentd receipt contains the complete required case set, terminal observations, distinct identities, runtime generation/revision, and retained chaos/authority evidence digests;
- real Agentd idempotency, response-loss recovery, crash/restart, revocation, permission revision, and session-switch evidence is accepted;
- monitoring and alert routes are verified;
- rollback, disaster recovery, log redaction, and credential rotation are exercised;
- independent accessibility/operator acceptance is signed;
- independent security review has no open critical or high finding;
- deployment, security, and release authorities are three distinct identities, cryptographically verify the retained Sigstore bundle outside the candidate, and explicitly approve the exact evidence-digest set for no more than 90 days;
- the final `hepta.ui-control.external-evidence-bundle.v1` status is `accepted`, main ancestry is accepted, and `releaseAuthorized` is true.

## Client recovery and freshness contract

A failed runtime-view refresh clears that view for mutation; a later valid snapshot restores it. The last coherent snapshot retains its generation/revision fence until session invalidation, so clearing freshness cannot admit a regressed replacement. Read-only view inspection also removes expired session metadata and permissions, without discarding pending operations. Session refresh retries transient failures at 1, 2, 4, 8, 16, 32 and at most 60 seconds, bounded by expiry and the current provider lifecycle. Successful refresh resets backoff; unchanged near-expiry responses have a minimum one-second refresh interval. Stop and revocation fence future retries.

Recovery import joins compatible identities rather than replacing the live ledger. It preserves in-flight promises and completed observations, rejects semantic conflicts atomically, and enforces capacity on the union. Never use an empty import as a reset or use an old image to reopen terminal history. Authenticated lookup must retain the exact audit trace established by admission; a missing or changed trace leaves work unresolved.

The runtime projection and snapshot use a structural budget that admits all 1,000 documented module rows while retaining the 1 MiB byte ceiling. Accessors, sparse arrays and malformed canonical data are rejected before projection; optional backend fields are captured before asynchronous hashing.

V1 absent lookup does not prove final non-admission. Retain local records and investigate backend admission/outbox progress; do not clear storage, generate replacement requests or declare failure from absence. A future final-non-admission contract must include a durable fence against delayed admission and independent backend evidence.
