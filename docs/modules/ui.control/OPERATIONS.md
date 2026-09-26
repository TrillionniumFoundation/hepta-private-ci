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
npm install --no-package-lock --ignore-scripts --prefix apps/hepta-control-ui
npm run check --prefix apps/hepta-control-ui
npm run test:e2e --prefix apps/hepta-control-ui
```

Promote only the generated `dist/` contents whose `build-manifest.json` digest is present in the exact-head qualification receipt. Do not promote a working tree artifact or a build from a different SHA.

## Required backend capabilities

- exact protocol `hepta.ui-control.v1`;
- authenticated session connect, refresh, revoke, and close;
- permission revision and connection generation;
- coherent snapshot endpoint;
- durable operation admission with unique ID/digest semantics;
- operation lookup and terminal observation;
- server-issued audit trace;
- generation fencing at execution.

## Configuration

The repository shell uses `/api/ui-control/v1/` by default. Deployment configuration may change the same-origin base before constructing `SameOriginHttpTransport`; it must still end with `/` and remain under the page origin. CSRF token injection must occur through a protected bootstrap response or equivalent same-origin mechanism and must rotate with the session.

## Health and readiness

Static readiness requires:

- `index.html`, JS modules, CSS, and `build-manifest.json` available;
- CSP and other security headers present on HTML and modules;
- no mixed content or cross-origin module fetches.

API readiness requires:

- session connect/refresh operational;
- coherent view available;
- ledger insert and lookup healthy;
- runtime dispatcher able to consume fenced work;
- audit trace backend available or safely buffered.

## Metrics

At minimum collect:

- connect, refresh, revoke, and permission-denied counts;
- snapshot latency, stale-view duration, drift rejection count;
- operation admission latency and result code;
- unique conflict count and identical replay count;
- accepted-to-terminal latency by action and target;
- indeterminate submission count and lookup recovery outcome;
- pending ledger age and outbox backlog;
- generation-fence rejection count;
- frontend error code count, without tokens or unrestricted reason text;
- CSP violation reports and failed integrity/build-manifest checks.

Suggested alerts should be calibrated from observed traffic rather than copied as unverified constants. Always alert on sustained ledger write failure, lookup failure, outbox growth, snapshot drift, authorization anomalies, or inability to revoke sessions.

## Incident handling

1. Disable mutation routes or revoke the affected permission while keeping read-only diagnostics available where safe.
2. Preserve operation ledger, audit traces, reverse-proxy logs, build receipt, and exact deployed asset digest.
3. Identify all indeterminate operations by operation ID; resolve through the ledger before any replay.
4. Fence affected runtime generations if stale work may remain queued.
5. Rotate sessions/CSRF material after identity or origin compromise.
6. Restore mutation capability only after ledger, dispatcher, authorization, and header checks pass.

## Rollback

1. Select a previously qualified browser build and its receipt.
2. Confirm protocol compatibility with the currently deployed API.
3. Atomically switch static assets; do not roll back the durable operation ledger.
4. Keep operation ID namespace and terminal records intact across rollback.
5. Invalidate cached HTML and service-worker state; this repository does not install a service worker.
6. Refresh/revoke sessions if permission or protocol semantics changed.
7. Run read-only smoke, one fenced non-destructive qualification operation, lookup, and terminal observation.
8. Record deployed build-manifest digest and rollback reason.

## Release checklist

- authoritative source merged and exact SHA identified;
- generated docs current;
- unit, contract, build, three-browser E2E, axe, and Lane B checks green;
- receipt artifact stored;
- backend idempotency/generation-fence evidence attached;
- deployed security headers observed;
- monitoring and alert routes verified;
- rollback build and procedure exercised;
- independent accessibility/operator acceptance signed;
- release authority explicitly approves activation.
