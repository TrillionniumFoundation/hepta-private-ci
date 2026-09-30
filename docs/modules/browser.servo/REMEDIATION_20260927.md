# browser.servo remediation ledger — 2026-09-27

## Exact integration line

The sole continuation is PR #1064 on
`codex/browser-servo-full-convergence-20260927`, based on
`main@a126987b84737dbc2ee2592442a314117bddb4a2`.

The exact runtime predecessor of this metadata and registry closure is
`75dacad78961b4a2278c4a9e7de69367c95f682e`, tree
`9c22fc0ec0e07d50a71f0c8325732f82e2fb9661`. This file is a source and
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

The generated registry inventories the complete tracked
`apps/hepta-browser` package plus the selected Agentd, workflow, documentation
and Servo-pin objects. Its import parser accepts only actual static import
statements; comments and string fixtures do not fabricate dependencies.
`journal-v2.js`, kernel journal ownership, evidence drivers, tests, the worker
loader and every bounded worker source part are in the exact source-object set.

The implementation map points to concrete worker source parts rather than the
`include!` loader facade. The registry verifier binds both the loader topology
and the implementation anchors in those parts.

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

This closes the former protocol failure in which a legitimate replay could be
misread as a missing authority challenge and reset the Browser child. It does
not convert replay into a fresh terminal observation.

### Durable worker-admission and network evidence

`DurableEvidenceBrowserDriver` reuses the same
`FileBrowserOperationJournal`; no second state owner is introduced. The Browser
owner records immutable dispatch intent first. The decorator then requires and
persists the worker-originated admission receipt before dispatch returns to the
final-use boundary. Missing admission fails closed.

Immediate, deferred-settlement and live-reconciliation egress receipts are
bound to the same profile/generation/operation/request/semantic identity and
written through the journal's monotonic `recordEgress` transition. These
receipts establish bounded operation-network observations only; they are not
remote business success.

### Kernel ownership, recovery and containment

The candidate retains:

- a permanent kernel `flock` owner protocol, without stale PID-directory
  rename/reclaim;
- validated incremental journal indexes with identity-change invalidation,
  compaction, torn-tail recovery and monotonic generation retirement;
- operation-scoped egress admission, frozen DNS/IP bindings, HTTP/CONNECT/SNI
  checks, request/response/deadline bounds and owned socket shutdown;
- `OwnedBrowserChild` process-lifetime tracking, observed exit before successful
  containment, retained ownership after failed cleanup and bounded descendant
  census;
- short random profile directories and explicit Unix-socket path bounds;
- deployment evidence parsing with bounded `lstat`/regular-file checks,
  duplicate-key rejection and exact run/source/lock binding.

These source controls still require exact native and target execution evidence.

### Worker-private target identity and atomic action

The Servo worker no longer treats a selector or observable control shape as the
final target identity.

At worker creation it installs one worker-owned `UserScript` bridge with a
random bridge name, random secret and random handle prefix. The bridge captures
native DOM primitives before the hostile page can replace them and retains
node-to-token identities in a private `WeakMap`. The bridge property is
non-writable, non-enumerable and non-configurable; calls without the secret are
rejected.

For an authoritative observation the worker:

1. takes a bounded preliminary semantic snapshot;
2. binds every observed actionable selector to a private node token;
3. takes the authoritative snapshot;
4. requires the same actionable-surface digest and the same selector-to-node
   token map across both snapshots;
5. stores those tokens beside the admitted document/navigation generation.

Immediately before dispatch, the worker recomputes the bounded action surface,
rebinds the selectors and requires exact equality with the authoritative token
map. For click/type/focus it reserves the selected token and emits the worker
`dispatch_boundary`. Execution then uses one bridge invocation that resolves
the selector, requires the same node token, rechecks visibility/disabled/type
constraints and performs the action with captured native primitives. There is
no second selector-only action evaluation.

`real-worker-smoke.js` exercises the real built worker through the production
sandbox against a hostile page. It requires:

- a page-realm `HTMLElement.prototype.click` replacement cannot intercept the
  worker action;
- an identical-shape node replacement after observation is rejected before the
  worker dispatch boundary;
- neither the replaced node nor the replacement node receives the stale action;
- the real worker still starts, speaks the private protocol and shuts down
  through the sandbox.

The emitted smoke receipt records
`privateAtomicActionBridge=true`,
`pageRealmMonkeypatchBypassed=true` and
`identicalShapeNodeReplacementRejected=true`. The source registry requires
these executable assertions to remain present. Source presence is not a claim
that the current exact build has passed them.

### Bounded owner measurement and qualification fanout

The existing journal owner now has an executable scale probe rather than a prose-only performance claim. `journal-scale-probe.js` drives 128 operations through dispatch, worker-admission, egress and terminal-observation transitions, records warm-path and restart statistics, compacts and reopens the same journal, and requires validated incremental-index reuse. It records hosted-runner latency but explicitly leaves performance qualification false.

Browser candidate branches are qualified by pull-request events. Browser-specific workflow push triggers are main-only, eliminating duplicate candidate builds that previously consumed two hosted runners for the same source SHA. Main pushes remain independently qualified and signed where applicable.

## Relevant commits in this continuation

| Commit | Published change |
| --- | --- |
| `d2daa5b06f4899aa8c1302fb303c592ca04f31ef` | Correct static-import parsing and restore exact Browser source-registry closure. |
| `e6eeec60958b6d11d089a03288dfd44eb7f55b11` | Bind the positive ownership fixture to the actual canonical identity without weakening the forged-digest regression. |
| `3f6709b44046ab0a598ee73fe41046732891ab62` / `d754ee59c04e8bdb4e1dbbdc4d4ad418ba4b080f` / `a0abe6da1c4a17dce6e234a09a52b98de3b842d2` | Add, compose and test durable admission/egress evidence on the existing journal owner. |
| `db937434ce04c66a1fb7c6a75722483963151a13` / `84d0d295b8b1e8d37fb06a8158d28a2576f459b1` / `772bbeb466eb940ece518d074699229ec063c1bb` / `7beeb32907ccd6bd4babff37592fe375480cb5c1` / `c9e997c63c8a65591ff5526fdcc88c7418b658d5` | Implement and test the reserved non-executing replay probe across Browser and Agentd. |
| `12762d626f53b64e81aa8b4cd70b10734699418e` | Refresh the exact generated source registry for the replay path. |
| `5ae44358f0b70c9539bec41dca6dc276014c72b2` | Add worker-private node handles, captured DOM primitives, one bridge action primitive and the hostile real-worker smoke. |
| `75dacad78961b4a2278c4a9e7de69367c95f682e` | Require target identity to remain stable across the authoritative observation itself. |

## Verification state

The exact-head Browser Agentd composition run for
`75dacad78961b4a2278c4a9e7de69367c95f682e` failed at the generated-source
registry step before Browser or Rust tests ran. The runtime commit split the
worker into bounded `include!` source parts and strengthened the smoke oracle,
but the prior registry generator still searched the loader facade for symbols
that had moved into those parts. The committed registry also retained the old
monolithic worker blob and omitted the six source parts.

This metadata closure corrects the generator anchors, implementation map and
source-object registry together. The earlier failure is retained as a failure;
it is not relabelled as a pass.

The final exact candidate still requires terminal-success evidence for:

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

It also requires the exact-lock Servo worker build, worker unit tests, the
hostile real-worker smoke, real Browser E2E, public HTTPS, storage isolation,
parent/descendant cleanup, recovery, soak, byte-identical independent rebuild,
SBOM and signed provenance gates on the same final source. Exact-head success
does not substitute for the deterministic merge candidate, and neither
substitutes for main-only target qualification.

## Remaining repository-controlled work

The four-stage source implementation must still be exercised on the final
exact head and deterministic merge candidate. In particular, an incomplete
sandbox observation is an unresolved qualification blocker, not independent
proof that the underlying process boundary is correct. Inspect and remediate
actual failures on this same candidate without weakening the invariants.

Queued, pending, skipped-applicable, cancelled, prior-head or donor-branch
results are not pass evidence.

## External and independently governed gates

Even after repository-controlled source and exact-head checks succeed, the
following remain separate:

- successful signed primary and independent artifacts from merged `main`;
- main-only trusted Linux target execution for namespace, launcher, listener,
  direct-egress, profile isolation, hostile-page atomic actions, process-tree
  cleanup and soak;
- independently operated signed remote-business terminal observations where
  business terminality is claimed;
- operator acceptance, production activation, promotion and release;
- macOS or Windows isolation only if those platforms enter scope.

Credential, upload and download remain fail-closed and disconnected.

## Completion boundary

The current booleans remain:

```text
source_root_present = true
repository_controlled_source_boundary_gaps_closed = false
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


## 2026-09-28 qualification continuation

This continuation starts from exact source
`9e9011fe06575e96265434c4de13e81d8f84ce86`, not from the older audit head.
The original complete Node suite was executed from the retained source archive:
245 passed, zero failed, cancelled or skipped. Those results are baseline
results, not acceptance of the subsequent changed source.

The Agentd revocation-feed conditional is aligned with the retained native
rustfmt diagnostic without changing its owner, inode or link-count checks.
Native formatting, compilation and strict lint must run again on the new head.

The Linux sandbox oracle now waits for acknowledged worker readiness before
releasing the launcher parent. Its C canary forks a live descendant before
publishing the readiness marker. The outer oracle captures bounded host PID
and start-time identities while the helper is still alive, sends an explicit
release, drains helper output through close, and observes disappearance of all
captured lifetimes. Empty/post-mortem censuses cannot pass. Where task/children
is absent, a bounded /proc parent-PID census is used for the stationary READY
canaries; missing observations are not silently interpreted as no descendants.
No arbitrary numeric PID is signalled by the observer.

Qualification processes now have monotonic deadlines and bounded diagnostics.
A signal request, SIGKILL, partial ready line, missing descendant, output flood
or timeout cannot become a successful probe receipt. Direct-network denial
must be a concrete routing/permission error, not an in-progress connection.
The resource limits and all filesystem/network/parent-death assertions remain
in force. The earlier sandbox SIGKILL is not assigned an unproved root cause;
a fresh successful real target execution is still required.

Eleven real-process observer regressions cover close/output ordering, explicit
release, early exit, SIGKILL, timeout, both output budgets, spawn failure,
partial readiness, invalid/empty census and live child/descendant retention.
They test the qualification observer, not Bubblewrap or Servo isolation.
The local environment has Node and a C compiler, but no Cargo/Rust/Bubblewrap;
local observer or JavaScript success must not be labelled native or target
qualification. All changed package files are included by the tracked-package
source inventory, including the new helper and tests. Production activation,
independent acceptance, promotion and release remain false.


## 2026-09-28 exact-head native follow-up

The exact candidate `d1a5c47965be4a1a01ef7753e346b99184d6982b`
produced two actionable native diagnostics. They are retained as failures and
are not relabelled as passes.

The Agentd Browser service tests showed that revocation updates could commit
before the worker emitted its dispatch or proven-rejection boundary. The
persistent port was still calling `FinalUseAuthority::with_verified_use`, whose
contract releases the owner mutex before executing the callback. The port now
uses `FinalUseAuthority::with_dispatch_boundary`, so the bounded callback that
sends `authority_enter` and waits for exactly one worker admission/rejection
receipt runs under the live revocation linearization fence. Remote execution
and terminal reconciliation remain outside that fence. The implementation map
and human technical documents bind the same API.

The standalone Linux sandbox diagnostic passed after explicitly enabling the
Ubuntu runner's unprivileged user namespace and disabling the AppArmor
restriction when that sysctl exists. The primary worker workflow previously
installed Bubblewrap without applying those host prerequisites. It now applies
the same fail-closed prerequisite ceremony and retains bounded sandbox-probe
stderr in the worker evidence directory on failure. No failed probe is inferred
to have passed.

The temporary branch-only diagnostic workflow used to isolate these failures
is removed from the candidate after transferring its proven prerequisites and
diagnostics into the canonical Agentd and worker workflows. It is not retained
as a parallel qualification or release path.

A fresh exact-head and deterministic-merge execution remains mandatory. The
repository-controlled source boundary, production implementation, product
execution, deployment qualification, operator acceptance, activation,
promotion and release booleans remain false until their designated terminal
evidence exists.
