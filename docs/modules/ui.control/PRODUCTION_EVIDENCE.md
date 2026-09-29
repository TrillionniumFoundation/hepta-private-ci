# ui.control production-evidence contract

This document describes the evidence accepted by the repository validator. It does not declare that a deployment has passed. Production status remains external, exact-subject evidence and must never be inferred from a source-tree boolean.

## Authority boundary

The browser remains a projection and intent-capture surface. A local snapshot, confirmation, operation digest, recovery record, test result, or evidence receipt does not grant runtime authority. The preserved mutation path is:

```text
confirmed current view and intent
  -> exact operation identity reserved
  -> scoped recovery record durably prepared
  -> authenticated backend admission and unique ledger constraint
  -> runtime owner executes under generation and permission fences
  -> authoritative operation lookup supplies terminal observation
```

Timeout or acknowledgement loss is `indeterminate`; it is resolved by lookup of the exact operation identity and is never replayed as a fresh mutation.

## Five production gates

The external bundle accepts only one mutually bound set for the exact candidate commit, Git tree, immutable HTTPS deployment subject, backend deployment digest, and prerequisite receipt digests.

1. **Real backend and durable ledger.** The receipt covers duplicate concurrent admission, changed-payload conflict, cross-identity lookup and rebind denial, authoritative non-admission, response-loss lookup, terminal continuity, crash/restart reconciliation, and distinct operation/audit bindings.
2. **Production identity and permissions.** Retained authority evidence must show a permission-revision advance, revocation fencing before operation creation, and a session switch that changes the session identity or advances the connection generation.
3. **Deployment security.** The deployed asset set must match the exact qualified build except for the one declared CSRF bootstrap substitution. TLS, certificate identity, CSP, HSTS, isolation, CORS, CSRF, cookie, authenticated view/mutation/close, and reverse-proxy behavior are observed against the same deployment digest.
4. **Independent accessibility and operator acceptance.** Three-browser browser-operator and keyboard-only observations are required. Screen-reader observations must include Safari and a non-Safari browser, at least two distinct assistive technologies, and actual runtime reading, lookup recovery, and visible storage-failure flows.
5. **Operations and release.** Rollback, disaster recovery, alert routing, log redaction, credential rotation, and mixed-version mutation fencing require typed semantic outcomes, not a `passed` label. Three distinct authorities then approve the exact evidence-digest set after all prerequisite evidence exists.

## Independent-acceptance matrix

Every observation is bound to a browser version, operating system, modality, raw-evidence digest, and one or more exact flows. The aggregate must cover:

- reading the runtime view;
- start, reconcile, and stop confirmation;
- stale-confirmation rejection;
- indeterminate recovery by exact operation lookup;
- visible terminal-cleanup/storage failure without mutation replay;
- keyboard focus restoration.

Browser-operator and keyboard-only observations each cover Chrome, Firefox, and Safari. Screen-reader evidence covers Safari plus Chrome or Firefox and names at least two distinct assistive-technology/version pairs. Non-screen-reader observations cannot claim an assistive-technology identity.

## Operational semantic evidence

### Rollback

The receipt identifies both the distinct rollback build and the exact qualified build restored afterward. It proves that a mutation fence was active, durable ledger continuity was preserved, no qualification operation remained unresolved, and no duplicate side effect was observed.

### Disaster recovery

The receipt records objective and observed RPO/RTO values, each within a bounded one-day window, and requires the observation to meet its own retained objectives. Ledger restoration, audit linkage, terminal lookup continuity, zero unresolved qualification operations, and zero duplicate effects are mandatory.

### Alert routing

The alert rule and route configuration are digest-bound. The exercise records its acknowledgement objective and observed acknowledgement time and proves trigger, route match, acknowledgement, and escalation-policy verification.

### Log redaction

The retained corpus is digest-bound and contains positive secret and correlation canary populations. It must contain zero secret canaries, zero full correlation identifiers, and zero credential matches, while preserving the expected redacted correlation form for every correlation canary.

### Credential rotation

Old and new credential fingerprints are distinct digests. No old credential remains active; the old credential receives 401 or 403 and creates no operation. The new credential authenticates, the permission revision advances, and authoritative post-rotation operation lookup succeeds.

### Mixed-version mutation fence

Old mutation-capable sessions are revoked or drained, cached HTML is invalidated, no legacy mutation session remains, a stale client receives 401 or 403 without creating a durable operation, and the fresh client is bound to the exact qualified build manifest.

## Evidence handling

Raw logs, screenshots, recordings, traces, credentials, tokens, and signatures stay in the protected evidence store. Tracked receipts contain only bounded metadata and SHA-256 digests. A repository validator verifies structure, exact subject binding, chronology, principal separation, and digest relationships; it does not manufacture external observations or cryptographically bless a self-supplied signer.

Receipt status is schema-exact rather than interchangeable: real-backend support evidence, independent acceptance, independent security, and operational evidence must carry `passed`; only the production approval receipt may carry `approved`. The runtime validator rejects status substitution even when every other common field is well formed.

Every evidence-bearing stage must attach the exact SHA-256 digest of its receipt before that stage can be accepted. Deployment identity and main ancestry are the only non-receipt stages. A failed bundle always projects `productionDeploymentApproved=false` and `releaseAuthorized=false`, including a failure after every evidence stage was individually accepted. Earlier accepted stages remain visible for diagnosis, but a failed final bundle is never release authority.

A missing field, failed observation, stale candidate, mismatched deployment, reused authority, premature approval, or absent prerequisite leaves the bundle failed. No workflow or maintainer should edit `productionDeploymentApproved` or `releaseAuthorized` directly.
