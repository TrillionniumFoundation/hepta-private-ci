# control.engineering adversarial review, 2026-10-02

## Scope and documentation

Baseline: PR #1175, `d0cf7acf35e8054cab8b3f5c1b7ec6a05e9cf8b4`.
This follow-up reviews the existing Python engineering-coordination owner,
recovery, signed worker ingress and local command boundary. It does not create a
parallel owner, native runtime adapter, deployment controller or authority grant.

Detailed technical development documentation exists: `TECHNICAL.md` covers module
placement, contracts, dependencies, ownership and lifecycle; `IMPLEMENTATION.md`
explains the executable SQLite v10 owner and CLI; `BOUNDED_OWNER_CONTRACT.md`
describes paging/capacity/renewal semantics; `OPERATIONS.md`, `SANDBOX_SECURITY.md`
and `EXTERNAL_ACCEPTANCE.md` cover operational, isolation and acceptance limits.
The documents distinguish registered target contracts from implemented Python
operations. Existing `STATUS.json` false production/acceptance/activation claims
remain unchanged.

## Reproduced findings and repairs

1. **Recovery integrity inconsistency.** Full startup audit verification accepted
   an altered final sequence and semantically equal noncanonical/duplicate-key
   stored JSON, although bounded suffix validation rejected those representations.
   New real SQLite reopen regressions failed before repair. A common event
   validator now enforces the same sequence, byte, metadata, digest and event-ID
   invariants in both readers. Valid bytes remain unchanged; rejection does not
   repair or rewrite history. Full verification streams its one snapshot cursor,
   removing whole-history payload retention without pretending the cold scan is
   constant-time or fully allocator-bounded.
2. **Worker scalar admission.** A boolean revision could revoke a revision-1
   registration. Authenticated heartbeat/result receipts accepted boolean fence
   aliases, and oversized signed expiries reached SQLite as raw overflow errors.
   Real owner/signature regressions failed before repair. The existing worker
   ingress now validates exact integer identities and representable times before
   comparing/persisting them. Time is sampled after revocation lock acquisition;
   revision exhaustion rejects atomically. Existing result acknowledgement replay
   and signature/revocation behavior are retained.
3. **CLI blocking special-file input.** A FIFO without a writer blocked the normal
   CLI before the 2 MiB/depth limits could apply. A subprocess regression timed out
   before repair. The CLI now opens nonblocking where supported, checks the actual
   descriptor is a regular file, checks its size and retains the bounded read.
   Regular-file symlink inputs keep their existing behavior; no path is reopened
   between inspection and read.

## Executed local verification

- Original supported baseline: 480 tests, 478 passed, 2 strong-host skips; its
  historical harness explicitly excludes 31 unprivileged-profile tests.
- Modified full ordinary discovery: **518 tests, 516 passed, 2 strong-host skips**.
  The current unprivileged environment ran those additional 31 tests successfully.
- Modified supported coverage run: 487 tests, 485 passed, 2 strong-host skips;
  branch-inclusive coverage **81.41611965995911%**, above the unchanged 80% gate.
- Focused audit recovery/paging, worker lifecycle/renewal and public CLI regressions
  passed, including the previously failing scenarios.
- Pinned Ruff 0.13.2 passed the package, tests and existing status/API script scope.
- Pinned mypy 1.18.2 passed the existing aligned 14 owner/product/evidence files.
- Generated status and public API checks passed. No public export or persistent
  schema changed.
- `just fmt` completed with Rust 1.95.0 after installing the repository-documented
  DotSlash 0.5.8 and using writable formatter caches. Unrelated pre-existing Python
  script formatting churn was discarded to preserve this module's review scope.
  No Rust or shared script source was changed.

These are local source observations. The two strong-sandbox skips are not passing
qualification. Final source-map verification and exact-head hosted CI are separate
requirements, never inferred from focused tests or old candidate evidence.

## Current upstream observation

At the unchanged baseline, the formerly queued Python quality run
`36796992824` and development-document run `36796992775` have since succeeded.
Consolidated qualification `36796992703` and architecture `36796992743` concluded
cancelled. Other blocking workflows failed. These are baseline results and do not
qualify this follow-up source.

## Completion and further optimization

The bounded Python coordination owner, durable work/lease/claim/integration state,
repository product caller and detailed development guides exist and are exercised.
Its architectural role remains engineering orchestration, consuming external
kernel.evidence facts; it cannot self-merge or issue runtime capabilities.

A single common audit validator is preferable to diverging cold/hot-path rules.
Streaming recovery removes avoidable retained-history memory. Typed ingress and
nonblocking descriptor checks close reproducible failures without broad redesign,
new caches, a second execution plane or weakened evidence thresholds.

Registered iteration/golden-fixture/adaptive-proposal native composition, actual
strong source/merge qualification, governed clock/fence/audit/key-custody providers,
independent semantic review and target deployment/recovery/rollback/operator
acceptance remain substantive gaps. They require their real owners and evidence;
repository fixture signatures or local passing tests cannot complete them.

Repeated review stops when no additional reproducible defect remains in the
inspected changes and their owner callers after regression and independent review.
This is not a proof that every possible optimization is exhausted or that the
whole module is production complete.
