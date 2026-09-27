# browser.servo remediation ledger — 2026-09-27

## Exact integration line

The sole continuation is PR #1064 on
`codex/browser-servo-full-convergence-20260927`, based on
`main@a126987b84737dbc2ee2592442a314117bddb4a2`.

The exact implementation predecessor of this ledger is
`12762d626f53b64e81aa8b4cd70b10734699418e`, tree
`bc8dcaca21d71bf5dfa9e6abb2b55740f8c58fc9`. This file is a source and
qualification ledger, not an activation or release receipt. Later metadata-only
successors do not widen runtime claims.

No parallel Browser candidate is used as evidence. Donor branches were read
only to identify reviewed fixes; every accepted change is represented by bytes
and tests on this branch.

## Repository-controlled convergence now published

### One bootable source line

The Browser parent accepts class-based host capabilities and the production
entrypoint composes the real `BrowserProfileHost`, persistent file journal,
profile-affine subprocess pool, operation-scoped network owner, observation
redactor, worker-admission boundary, durable-evidence decorator and private
Agentd service.

The generated registry now inventories the complete tracked
`apps/hepta-browser` package plus the selected Agentd, workflow, documentation
and Servo-pin objects. Its import parser accepts only actual static import
statements; comments and string fixtures no longer fabricate dependencies.
`journal-v2.js`, journal ownership, evidence drivers, tests and service
composition are all in the exact source-object set.

The stale runtime ownership fixture now expects the canonical digest of the
actual profile/principal/generation/manifest/grant tuple. The negative forged
ownership test remains intact.

### Authority-free exact replay

The long-lived Agentd service performs a reserved read-only replay probe before
new `navigate_or_act` authorization:

1. Agentd adds internal `replayOnly=true` to a `reconcile_operation` probe;
2. `ReplayProbeBrowserHost` routes that probe through
   `BrowserProfileHost.navigateOrAct`;
3. an existing immutable operation returns its stored receipt before final-use
   authority and without calling the driver;
4. a missing operation reaches `admitNewOperation`, which returns the single
   typed absence error and cannot authorize or dispatch;
5. only that exact absence permits the ordinary signed final-use path.

Caller-supplied `replayOnly` is rejected by the named Agentd service. Semantic
substitution remains an error, not proof of absence. Ordinary
`reconcile_operation` retains its live observer semantics.

This closes the previous protocol failure in which a legitimate replay could be
misread as a missing authority challenge and reset the Browser child. It does
not convert replay into a fresh terminal observation.

### Durable worker-admission and network evidence

`DurableEvidenceBrowserDriver` reuses the same
`FileBrowserOperationJournal`; no second state owner was added. The Browser
owner records immutable dispatch intent first. The decorator then requires and
persists the worker-originated admission receipt before dispatch returns to the
final-use boundary. Missing admission fails closed.

Immediate, deferred-settlement and live-reconciliation egress receipts are
bound to the same profile/generation/operation/request/semantic identity and
written through the journal's monotonic `recordEgress` transition. These
receipts establish bounded operation-network observations only; they are not
remote business success.

### Existing safety and owner semantics retained

The candidate retains:

- the permanent kernel `flock` owner protocol, without stale PID-directory
  rename/reclaim;
- validated incremental journal indexes with identity-change invalidation,
  compaction, torn-tail recovery and monotonic generation retirement;
- operation-scoped egress admission, frozen DNS/IP bindings, HTTP/CONNECT/SNI
  checks, request/response/deadline bounds and owned socket shutdown;
- `OwnedBrowserChild` process-lifetime tracking, observed exit before successful
  containment, retained ownership after failed cleanup and bounded descendant
  census;
- short random profile directories and explicit Unix-socket path bounds;
- `lstat`/`stat.S_ISREG` deployment evidence validation with bounded reads,
  duplicate-key rejection and exact run/source/lock checks.

These source controls still require exact native and target execution evidence.

## Commits in this continuation

| Commit | Published change |
| --- | --- |
| `d2daa5b06f4899aa8c1302fb303c592ca04f31ef` | Correct static-import parsing and restore exact Browser source-registry closure. |
| `e6eeec60958b6d11d089a03288dfd44eb7f55b11` | Bind the positive ownership fixture to the actual canonical identity without weakening the forged-digest regression. |
| `3f6709b44046ab0a598ee73fe41046732891ab62` / `d754ee59c04e8bdb4e1dbbdc4d4ad418ba4b080f` / `a0abe6da1c4a17dce6e234a09a52b98de3b842d2` | Add, compose and test durable admission/egress evidence on the existing journal owner. |
| `db937434ce04c66a1fb7c6a75722483963151a13` / `84d0d295b8b1e8d37fb06a8158d28a2576f459b1` / `772bbeb466eb940ece518d074699229ec063c1bb` / `7beeb32907ccd6bd4babff37592fe375480cb5c1` / `c9e997c63c8a65591ff5526fdcc88c7418b658d5` | Implement and test the reserved non-executing replay probe across Browser and Agentd. |
| `12762d626f53b64e81aa8b4cd70b10734699418e` | Refresh the exact generated source registry for the replay path. |

## Verification state

At this ledger's implementation predecessor, exact-source workflows were
created for Browser Node/source checks, Agentd composition, Lane B, blocking CI,
Servo worker build and independent rebuild. They were queued or pending when
this ledger was written. Queued, pending, skipped-applicable, cancelled,
prior-head or donor-branch results are not pass evidence.

Earlier runs on `fb0395fd1cf9a20c4049614b5d9f75b07eacf928`
failed before Browser tests because the former registry parser interpreted a
string fixture as an import. That defect is fixed in the current source, but the
old failures are not relabelled as passes.

The current exact candidate still requires terminal-success evidence for:

```sh
npm --prefix apps/hepta-browser run verify:registry
node --test apps/hepta-browser/test/*.test.js
node --check apps/hepta-browser/src/*.js

cd codex-rs
cargo fmt --package codex-hepta-agentd -- --check
cargo test --locked -p codex-hepta-agentd browser_servo --lib
cargo test --locked -p codex-hepta-agentd --bin hepta-agentd-browser-service
cargo check --locked -p codex-hepta-agentd \
  --bin hepta-agentd-browser \
  --bin hepta-agentd-browser-service
cargo clippy --locked -p codex-hepta-agentd \
  --lib \
  --bin hepta-agentd-browser \
  --bin hepta-agentd-browser-service \
  --no-deps -- -D warnings
```

It also requires the exact-lock Servo worker build, real Browser E2E, public
HTTPS, storage isolation, parent/descendant cleanup, recovery, soak,
byte-identical independent rebuild, SBOM and signed provenance gates on the same
final source.

## Remaining repository-controlled blocker

The native worker still performs action-surface revalidation and
click/type/focus execution in separate JavaScript evaluations. The exact Servo
worker has not yet established an engine-private DOM node handle or a single
atomic final validation-and-action primitive. A hostile page-realm API
monkeypatch or identical-shape node replacement therefore remains outside the
proved invariant.

This must be closed in the real worker and exercised by a real-page regression;
a fixture flag, another digest comparison, or a document statement is not
sufficient. Until then, repository-controlled source-boundary closure remains
false.

## External and independently governed gates

Even after repository-controlled source and exact-head checks succeed, the
following remain separate:

- successful signed primary and independent artifacts from merged `main`;
- main-only trusted Linux target execution for namespace, launcher, listener,
  direct-egress, profile isolation, process-tree cleanup and soak;
- independently operated signed remote-business terminal observations where
  business terminality is claimed;
- operator acceptance, production activation, promotion and release;
- macOS or Windows isolation only if those platforms enter scope.

Credential, upload and download remain fail-closed and disconnected.

## Completion boundary

The current booleans remain:

```text
source_root_present = true
production_implementation = false
product_execution_proved = false
deployment_qualification = false
operator_acceptance = false
activation = false
promotion = false
release = false
```

No main update, protected-branch bypass, deployment, activation, independent
acceptance, promotion or release is performed by this continuation.
