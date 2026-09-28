# kernel.authority remediation — 2026-09-28

This is a source-delivery note, not a release or independent-acceptance receipt.
The authoritative current state remains `qualification/kernel-authority/status_manifest.json`.
Its generated projections must all match the same non-self-referential source anchor.
No qualification workflow may repair, push, reset or self-approve the source it tests.

## Preserved invariants

The existing authority owner and TaskFlow durable owner remain the only owners of
their facts. Fleet still derives the exact allocation binding and consumes a
one-shot dispatch capability at its actual ledger boundary. FinalUse still burns
nonces durably, uses frontier-first ordering and retains V4 pending revocations.
Recovery cannot reset history or invent an external frontier. The Agentd provider
path retains the original external idempotency-key profile and persists attempt
and non-authorizing witness before provider contact. Unknown outcomes require
owner evidence, not blind redispatch.

## Source changes

`pilot_execution.py` and `runtime_qualification.py` require actual expected libtest
identities and matching result totals, not just a successful exit code. Zero tests,
ignored cases, renamed cases, duplicates, contradictions and stale raw benchmark
outputs fail closed. The enrolled pending-recovery suite requires its exact two
cases. The parser tests are Python unit tests and are not native pilot evidence.

`AuthorityClock::now_with_uncertainty` preserves compatibility defaults while
production constructors retain their qualified time/custody adapter. FinalUse
checks both endpoints of one coherent possible-time interval at claim, after
nonce persistence, and at final entry. Observed custody identity or generation
drift remains fenced even if the provider later reports an older state. The new
native regression files must still be compiled and run on the exact candidate.

The registered Agentd host binds a verified signed-feed interval into the owner
clock and rechecks it after durable witness persistence. Feed replacement is
invalidated before authority mutation and published after successful apply. The
provider driver uses the existing runtime via the existing async TaskFlow API,
not one OS thread and runtime per effect. A bounded host-owned task set retains
in-flight work when a response receiver is dropped. It joins completed/panicked
handles before task-table capacity reuse. A new-dispatch reserve gate preserves
nonce headroom and does not issue epoch-rollover authority. Terminal reads and
reconciliation retain their independent progress paths.

`run_native_checks.py` executes and retains an explicit plan: toolchain identity,
formatting, all-target compilation, full affected package tests with no retries
and zero-test failure, strict Clippy, Python regressions, B4, full caller closure,
state projections and clean-source identity. Missing tools, timeouts, source drift,
failed commands and a partially executed plan remain failures. Receipts bind commands,
exit codes, log digests, source/merge subject and available workflow/runner identity.
The production-closure workflow now includes core authority and affected consumer
paths, and has a distinct exact-main observation for applicable post-merge pushes.
This does not assert that branch-protection rules are configured or that main was merged.

The canonical manifest now enumerates every target ModulePort declared by the
technical guide. It separately records contract definition, named source composition,
normal product invocation proof, exact execution, target-host qualification and
independent acceptance. Existing independent owner protocols are not relabelled as
generic-authority consumers. Same-process owner reopen, two normal product processes
and target-host crash drills are distinct evidence scopes.

## Validation boundary

Native source changes in this revision have not been locally compiled or formatted:
the editing environment has no Rust toolchain. Exact-head and fixed-merge native
checks are required and may reveal formatting, compiler, lint or runtime issues.
Do not merge or promote this candidate based on the existence of these files.
Local Python regression observations concern the materialized qualification files
only; they are not a full-checkout, native-package or target-deployment receipt.

## Remaining repository-controlled work

- Resolve all exact-candidate native formatting, compilation, lint and execution
  results, including cross-crate API and normal host behavior, before accepting source closure.
- Apply possible-time interval semantics to ordinary lease validity. The new
  production custody wrapper is retained, but the ordinary lease path still uses point time.
- Attach selected real production time, independent frontier and custody providers
  to normal Agentd/Fleet bootstrap; reject production configuration without them.
- Complete explicit normal Agentd shutdown/drain integration and fault-qualified
  cancellation/reconciliation. A task table is not a graceful-shutdown acceptance test.
- Establish two normal product-process cold-start recovery using the actual provider
  and independent frontier, not only unit-test owner drop/reopen.
- Implement/execute the full five-state-point by eleven-operation measurement matrix,
  at least 100 samples per row, and all eight fault cuts on the selected production
  profile. The existing four-operation benchmark is not that matrix.
- Measure full nonce-set frontier hashing, complete lease-image replacement, time-floor
  persistence and restart costs before changing authenticated storage representation.
  The WAL/checkpoint/sharding reference model remains a qualification model only.
- Complete target-only generic-authority ports without creating a second authority or
  treating another module's separate verifier protocol as this port's implementation.

## External evidence not manufactured

No attested clock, independent production frontier, KMS/HSM deployment, real key
rotation/compromise ceremony, revocation transport fanout, target-host latency result,
operator/independent acceptance, canary, promotion or release is created by this change.
All corresponding authority and acceptance flags remain false.
