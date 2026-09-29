# `@hepta/control-ui`

Authority-free runtime-control client core and framework-free browser console shell.

The package may project coherent runtime state and submit authenticated requests. It does not own runtime state, grant authority, or infer terminal success from a local acknowledgement. The durable server operation ledger and runtime owner remain authoritative.

## Stable imports

```js
import {
  RuntimeClient,
  SameOriginHttpTransport,
  SessionProvider,
  createControlConsole,
} from "@hepta/control-ui";
```

Supported subpaths are `@hepta/control-ui/core`, `@hepta/control-ui/browser`, and `@hepta/control-ui/transport/http`. Imports from `src/*` are intentionally blocked.

## Repository checks

```bash
npm ci --prefix apps/hepta-control-ui --ignore-scripts --no-audit --no-fund
npm run lint --prefix apps/hepta-control-ui
npm test --prefix apps/hepta-control-ui
npm run test:contract --prefix apps/hepta-control-ui
npm run build --prefix apps/hepta-control-ui
npm run test:e2e --prefix apps/hepta-control-ui
```

The browser E2E suite runs Chromium, Firefox, and WebKit. It covers keyboard/focus behavior, duplicate activation, stale revision typing, accepted-response-loss recovery, terminal backend observations, unavailable local recovery storage, and axe-core. Unit tests additionally qualify concurrent reservation, session identity and permission-revision fencing, fail-closed revoke/close, and full-response-body timeout behavior.

## Terminal maintenance ownership and lifecycle

`src/terminal-cleanup.js` is private browser maintenance, not another operation ledger. The browser passes only the client's observed terminal projection into this queue. `ScopedRecoveryStore.complete()` remains the owner of exact stored-identity comparison and removal under the existing cross-tab lock. A local cleanup memo is not admission, authorization, durable terminal evidence, or a reason to dispatch an operation again.

The queue uses the complete available operation/terminal binding, including method, intent digest, target, reason, session, generations, displayed revision, snapshot, protocol, terminal status, audit, and outcome. It coalesces concurrent attempts for an unchanged binding, retains failed work for later retry, and prunes successful memos when their records leave the displayed history. A changed binding is not hidden behind an operation-ID-only cache. Pending and indeterminate records are never cleanup candidates.

Each scheduling pass admits at most 32 tasks, with one removal in flight and a 5,000 ms abort deadline shared across the batch. Rotation continues through the inventory so a slow record does not always precede every other record. The inventory bound is 4,096 entries; these are maintenance resource bounds, not new runtime authority. The next ordinary refresh advances any remaining backlog. Browser timer suspension or a blocked event loop can delay abort delivery; the deadline is not a hard real-time execution guarantee.

`browser-app.js` awaits maintenance results from refresh, submission settlement, and explicit recovery. An asynchronous lock or deletion failure becomes a sticky `UI_CONTROL_STORAGE` alert. An ordinary refresh does not silently clear it; successful cleanup of the currently displayed terminal inventory does. A runtime terminal observation remains visible while its local record is retained. Cleanup failure never changes the terminal result and never triggers a new mutation. The existing store's global diagnostic reporting remains in place; the browser no longer relies on that diagnostic as its user-facing error path.

On disposal, the console aborts pending maintenance, drains the existing queue, and closes the client. Late error/live-region notifications are suppressed. Cancellation does not undo a removal already completed under the store's lock. A fresh console restores retained identities and queries the backend rather than replaying requests.

## Incremental presentation without cached authority

`src/keyed-list.js` keeps module rows by module ID and pending/completed rows by exact operation ID. Full correlation identifiers remain in private JavaScript maps, never added to DOM attributes. Membership/order changes reuse surviving nodes; unchanged membership/order performs no list replacement. Text is written only when its displayed value changes. Removed rows and their retained presentation records are pruned.

The pending recovery button is reused while the operation remains indeterminate. Its in-flight state is tracked independently of rendering, preventing another activation during a lookup. When the focused recovery action disappears, focus returns to the existing live region. Target selection remains tab-private and is not changed silently when its module disappears.

Every render still reads the current view and evaluates permissions, connected/stale state, target availability, and lifecycle state. Confirmation is revalidated immediately before submission. Reusing a row never reuses an old authorization decision, and no tokenizer, session, permission, or runtime-generation proof is cached by these presentation helpers.

## Maintenance regression matrix

The focused Node tests use the production controller, queue, and unchanged scoped store with instrumented DOM/storage/lock adapters. They measure work counts, not production-machine latency. Run them directly with:

```bash
node --test apps/hepta-control-ui/test/browser-maintenance.test.js apps/hepta-control-ui/test/terminal-cleanup.test.js
```

They also run in the default `npm test` command, in both exact-head and deterministic synthetic-merge qualification.

| Surface | Regression assertions |
|---|---|
| Async failure | Lock rejection and failed delete read-back reach the visible alert; the original record remains; successful refresh clears the alert without another mutation. |
| Identity and lifecycle | Concurrent cleanup is coalesced; changed binding is rechecked; unknown state is untouched; failed siblings retry independently; disposal and abort fence later removals. |
| Fairness and bounds | Over-capacity inventories schedule no deletion; a batch deadline aborts lock waiting; rotation reaches the next record. |
| Long-lived presentation | 2,048 modules plus 1,024 pending and 1,024 terminal records, followed by 100 unchanged renders, allocate no further list nodes or list replacements; a changed cell retains its row. |
| Shared storage | Two store instances clean 1,024 terminal records in bounded passes while preserving 1,000 unrelated origin keys; repeated unchanged passes acquire no further cleanup locks or inventory enumerations. |
| Authorization | Permission-revision changes disable controls and invalidate an existing confirmation even when the same module row is reused. |
| Corruption/capacity | Malformed records remain intact; oversized origin inventory fails closed before unbounded enumeration or a new admission. |

`e2e/maintenance.spec.mjs` adds product-path checks in all three browser engines: 512 module rows with a real MutationObserver and axe, ordinary polling with reason-focus retention, and terminal cleanup under native Web Lock contention or failed storage deletion. The terminal fault tests retain the original recovery key, require a visible alert, release the fault, and verify the backend still contains only the original single mutation. The tests use the existing qualification server; they do not create a second application executor or supply production evidence.

## Storage capacity and incident handling

This revision does not replace or relax the scoped recovery store. Its 16,384-key origin-wide enumeration budget, 1,024 default per-scope capacity, 8,192-byte record bound, read-back verification, and corruption retention still apply. Admission continues to check current capacity under the shared lock; no cached inventory authorizes a write. Origin-wide storage contention remains a deployment capacity concern. Unchanged completed-history refreshes now avoid repeat cleanup calls; this is not a claim that all storage enumeration has been eliminated.

When recovery storage fails, preserve the original scope and operation identities. Do not clear local storage and re-submit an uncertain action. Diagnose lock availability, origin quota, corrupt records, and scope binding separately, then reconcile through the authoritative backend. A future transactional/indexed storage migration must account for legacy records, interruption, mixed-version tabs, and exact scope before changing the store schema.

## External execution readiness

The canonical seven-stage state remains `qualification/ui-control/UI_CONTROL_MANIFEST.json`; the generated technical/status projections are not hand-edited by this maintenance change. Passing a local test, observing a CI success, accepting an exact-tree receipt, and authorizing production are separate events. Every new head requires its own exact-head and synthetic-merge receipts; receipts for an earlier head are not copied forward.

The existing `ui-control-external-qualification.yml` workflow must be dispatched from `main`. It requires `candidate_sha` already reachable from `main` and `repository_qualification_run_id` identifying a successful official pull-request run containing both repository receipts. `run_production_evidence=true` requires `run_real_backend=true`. Secretless preflight and exact-build relay precede the protected `ui-control-production-qualification` environment. Off-main candidates cannot use this path to acquire production authority.

The protected deployment inputs include `HEPTA_UI_CONTROL_BASE_URL`, immutable `HEPTA_UI_CONTROL_DEPLOYMENT_ID`, cookie, CSRF token, and cookie path. Independently retained backend chaos/authority evidence, distinct disposable identities and target, accessibility/operator review, security review, operational exercises, and production approval must describe that same deployment and candidate. Values belong in the protected environment/evidence store, never this README or tracked fixtures.

Follow the existing operations runbook for real-backend uniqueness, cross-principal rejection, response-loss lookup, session rotation, restart continuity, deployment asset/TLS/CSP/CSRF/cookie checks, screen-reader acceptance, rollback, disaster recovery, monitoring, redaction, and credential rotation. The deployment, release, and security signers remain three distinct authorities. Repository write permission is not a substitute for their evidence or signatures. Missing prerequisites remain missing; this change creates no external acceptance or release credential.

## Security and operations

- [`TECHNICAL.md`](../../docs/modules/ui.control/TECHNICAL.md)
- [`THREAT_MODEL.md`](../../docs/modules/ui.control/THREAT_MODEL.md)
- [`SERVER_IDEMPOTENCY.md`](../../docs/modules/ui.control/SERVER_IDEMPOTENCY.md)
- [`OPERATIONS.md`](../../docs/modules/ui.control/OPERATIONS.md)

`projectRuntimeFromLocalCanonicalJson` and `buildLocalOperationProposalFromCanonicalJson` remain strict local qualification helpers. They are not production configuration loaders and accept only exact bounded canonical JSON.
