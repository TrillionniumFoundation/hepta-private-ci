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

The browser E2E suite runs Chromium, Firefox, and WebKit. It covers keyboard/focus behavior, duplicate activation, stale revision typing, accepted-response-loss recovery, terminal backend observations, unavailable local recovery storage, and axe-core. Unit tests additionally qualify concurrent reservation, session identity and permission-revision fencing, fail-closed revoke/close, full-response-body timeout behavior, crash-consistent scope-directory transitions, and steady-state storage isolation from unrelated origin keys.

## Terminal maintenance ownership and lifecycle

`src/terminal-cleanup.js` is private browser maintenance, not another operation ledger. The browser passes only the client's observed terminal projection into this queue. `ScopedRecoveryStore.complete()` remains the owner of exact stored-identity comparison and removal under the existing cross-tab lock. A local cleanup memo is not admission, authorization, durable terminal evidence, or a reason to dispatch an operation again.

The queue uses the complete available operation/terminal binding, including method, intent digest, target, reason, session, generations, displayed revision, snapshot, protocol, terminal status, audit, and outcome. It coalesces concurrent attempts for an unchanged binding, retains failed work for later retry, and prunes successful memos when their records leave the displayed history. Failed or in-flight cleanup snapshots remain outstanding even after display-history eviction; only verified removal or verified absence retires them. A changed binding is not hidden behind an operation-ID-only cache. Pending and indeterminate records are never cleanup candidates.

Each scheduling pass admits at most 32 tasks, with one removal in flight and a 5,000 ms abort deadline shared across the batch. Rotation continues through the inventory so a slow record does not always precede every other record. The combined displayed/outstanding inventory bound is 4,096 entries; these are maintenance resource bounds, not new runtime authority. The next ordinary refresh advances any remaining backlog. Browser timer suspension or a blocked event loop can delay abort delivery; the deadline is not a hard real-time execution guarantee.

`browser-app.js` awaits maintenance results from refresh, submission settlement, and explicit recovery. An asynchronous lock or deletion failure becomes a sticky `UI_CONTROL_STORAGE` alert. An ordinary refresh does not silently clear it; successful cleanup of the displayed and retained outstanding terminal inventory does. A runtime terminal observation remains visible while its local record is retained. Cleanup failure never changes the terminal result and never triggers a new mutation. The existing store's global diagnostic reporting remains in place; the browser no longer relies on that diagnostic as its user-facing error path.

On disposal, the console aborts pending maintenance, drains the existing queue, and closes the client. Late error/live-region notifications are suppressed. Cancellation does not undo a removal already completed under the store's lock. A fresh console restores retained identities and queries the backend rather than replaying requests.

`TerminalCleanupQueue.diagnostics()` reports only bounded local maintenance counts: visible, pending, outstanding and retained-success entries plus configured limits. It exposes no operation identity and does not participate in cleanup or authority decisions.

## Incremental presentation without cached authority

`src/keyed-list.js` keeps module rows by module ID and pending/completed rows by exact operation ID. Full correlation identifiers remain in private JavaScript maps, never added to DOM attributes. Membership/order changes reuse surviving nodes; unchanged membership/order performs no list replacement. Text is written only when its displayed value changes. Removed rows and their retained presentation records are pruned.

The pending recovery button is reused while the operation remains indeterminate. Its in-flight state is tracked independently of rendering, preventing another activation during a lookup. When the focused recovery action disappears, focus returns to the existing live region. Target selection remains tab-private and is not changed silently when its module disappears.

Every render still reads the current view and evaluates permissions, connected/stale state, target availability, and lifecycle state. Confirmation is revalidated immediately before submission. Reusing a row never reuses an old authorization decision, and no session, permission, or runtime-generation proof is cached by these presentation helpers.

## Maintenance regression matrix

The focused Node tests use the production controller, queue, and scoped store with instrumented DOM/storage/lock adapters. They measure work counts, not production-machine latency. Run them directly with:

```bash
node --test \
  apps/hepta-control-ui/test/browser-maintenance.test.js \
  apps/hepta-control-ui/test/terminal-cleanup.test.js \
  apps/hepta-control-ui/test/recovery-directory.test.js
```

They also run in the default `npm test` command, in both exact-head and deterministic synthetic-merge qualification.

| Surface | Regression assertions |
|---|---|
| Async failure | Lock rejection and failed delete read-back reach the visible alert; the original record remains; successful refresh clears the alert without another mutation. |
| Identity and lifecycle | Concurrent cleanup is coalesced; changed binding is rechecked; unknown state is untouched; failed siblings retry independently; disposal and abort fence later removals. |
| History eviction | Failed cleanup remains retryable after the terminal disappears from presentation; an already in-flight cleanup is still joined rather than duplicated or forgotten. |
| Fairness and bounds | Over-capacity inventories schedule no deletion; a batch deadline aborts lock waiting; rotation reaches the next record. |
| Long-lived presentation | 2,048 modules plus 1,024 pending and 1,024 terminal records, followed by 100 unchanged renders, allocate no further list nodes or list replacements; a changed cell retains its row. |
| Scoped storage | One bounded legacy scan builds the scope directory; later load, prepare and cleanup do not enumerate unrelated origin keys, including with 20,000 unrelated keys present. |
| Interrupted transitions | Pre-ready records are repaired without becoming dispatch authority; post-ready uncertainty remains query-only; failed removal returns conservatively to a retryable ready record. |
| Authorization | Permission-revision changes disable controls and invalidate an existing confirmation even when the same module row is reused. |
| Corruption/capacity | Malformed records and directories remain intact; migration and per-scope capacity fail closed; an existing exact record remains ambiguous even if directory repair fails. |

`e2e/maintenance.spec.mjs` adds product-path checks in all three browser engines: 512 module rows with a real MutationObserver and axe, ordinary polling with reason-focus retention, and terminal cleanup under native Web Lock contention or failed storage deletion. The terminal fault tests retain the original recovery key, require a visible alert, release the fault, and verify the backend still contains only the original single mutation. The tests use the existing qualification server; they do not create a second application executor or supply production evidence.

## Scoped storage directory and incident handling

The store retains the existing exact per-operation record schema and adds one authenticated-scope directory with schema `hepta.ui-control.scoped-recovery-directory.v1`. The directory is local maintenance metadata only. It contains sorted operation IDs and `reserving`, `ready`, or `removing` states; it never contains credentials, permission decisions, runtime terminal facts, or authority.

For a new operation, the store writes and reads back `reserving`, the exact operation record, and then `ready` under the existing scope Web Lock. Only after `prepare()` returns may the client continue toward dispatch. An interrupted `reserving` transition is removed under the lock because the admission handoff did not complete. A `ready` record is always resolved by backend lookup, including when the final directory write succeeded but its caller did not observe success. Terminal cleanup uses `removing` so a failed deletion retains or restores an exact retryable record.

When no directory exists, initialization performs one origin-wide scan capped at 16,384 keys and validates only records from the exact scope. A verified all-ready directory then permits reopen, load, admission and cleanup without enumerating unrelated origin keys. The default scope capacity remains 1,024, the hard maximum remains 4,096, each record remains capped at 8,192 bytes, and the directory is capped at 1 MiB.

`ScopedRecoveryStore.diagnostics()` exposes only bounded counts and migration work, without operation IDs or secrets. Storage failures include a stable `details.storageReason` for redacted telemetry. Preserve the directory and all records on failure; never clear local storage and never submit a replacement for an unresolved operation identity.

Old pages do not maintain the new directory. Deployment must revoke or drain old mutation-capable sessions, invalidate cached HTML, and force every long-lived tab to load the exact qualified assets before mutation permission is restored. Mixed-version mutation is not an accepted rollout state.

The full state machine, migration rules, reason categories, and incident procedure are documented in [`RECOVERY_STORAGE.md`](../../docs/modules/ui.control/RECOVERY_STORAGE.md).

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
- [`RECOVERY_STORAGE.md`](../../docs/modules/ui.control/RECOVERY_STORAGE.md)

`projectRuntimeFromLocalCanonicalJson` and `buildLocalOperationProposalFromCanonicalJson` remain strict local qualification helpers. They are not production configuration loaders and accept only exact bounded canonical JSON.
