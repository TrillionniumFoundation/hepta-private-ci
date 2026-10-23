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

## Repository-controlled closure now in source

`pilot_execution.py` and `runtime_qualification.py` require actual expected libtest
identities and matching result totals, not just a successful exit code. Zero tests,
ignored cases, renamed cases, duplicates, contradictions and stale raw benchmark
outputs fail closed. The enrolled pending-recovery suite requires its exact two
cases. The parser tests are Python unit tests and are not native pilot evidence.

`AuthorityClock::now_with_uncertainty` preserves compatibility defaults while
production constructors retain their qualified time/custody adapter. FinalUse and
ordinary leases evaluate the complete possible-time interval at their owner-lock
checks. FinalUse resamples after nonce persistence. Observed custody identity or
generation drift remains fenced even if the provider later reports an older state.
These source changes still require exact-candidate native execution.

The registered Agentd host binds a verified signed-feed interval into the owner
clock and rechecks it after durable witness persistence. Feed replacement is
invalidated before authority mutation and published after successful apply. The
provider driver uses the existing Tokio runtime via the existing async TaskFlow
API, not one OS thread and runtime per effect. A bounded host-owned task set
retains in-flight work when a response receiver is dropped, joins completed or
panicked handles before capacity reuse, closes admission at shutdown and keeps
unjoined work owned after drain timeout or cancellation.

`owner_runtime_qualification.py` makes those task-owner guarantees exact pilot
requirements. It selects and parses seven named native tests for bounded
admission, client cancellation, unrelated runtime progress, panic joining,
shutdown admission fencing, timeout retention and submit/close races. A zero-test
exit, renamed case, ignored test, missing case or projected success without the
captured identity is a failure. These are repository-process guarantees, not
provider terminality or target-host acceptance.

`authority_effect_process_restart.rs` now exercises two fresh normal
`codex-hepta-agentd` processes through the ordinary Fleet lifecycle and public
Agentd control socket. The first process crosses the real configured provider
adapter, durably records the attempt and authority witness, persists an exact
pending revocation while the effect is active, and is terminated before a remote
response can be consumed. The second Fleet generation reopens the same owners,
commits the pending head, reconciles the original provider occurrence by status
lookup, reuses the terminal receipt and proves that no second provider POST or
second nonce frame was created. It checks the V4 pending/committed snapshot,
40-byte claim frame, attempt, witness and terminal receipt identities. The
provider and trust services are controlled process fixtures, so this is normal
product-process recovery evidence, not selected production-provider or
rollback-independent target-host evidence.

`product_process_recovery.py` requires the exact single integration-test identity
and a coherent one-test libtest summary. The dedicated read-only workflow runs
parser regressions, formatting, strict Clippy and the product-process test on both
exact-head and deterministic synthetic-merge candidates. Missing, ignored,
renamed, duplicate or zero-test execution cannot project the process guarantees.
Until those exact runs complete successfully, the source test is execution
pending rather than a pass receipt.

`capacity_matrix.py` implements a strict target-host collector for the full
five-state-point by eleven-operation matrix, all eight fault cuts, reserve alert
and 25 history-sensitive diagnostics. It binds every driver response to one
candidate, profile and host; retains request/response/log hashes; and rejects
synthetic, incomplete, mixed-host, contradictory or authority-claiming output.
Its CI self-test is explicitly synthetic and cannot count as a target row or a
production-evidence pass.

The manual target-capacity workflow is read-only, main-dispatched, protected by
the `kernel-authority-target` environment and restricted to the matching
self-hosted runner label. It executes only the exact main-branch collector and
hot-path evaluator; the selected candidate checkout supplies commit/tree identity
but no candidate script is executed on the privileged runner. The host driver and
site policy use fixed paths and independently supplied SHA-256 identities. Control,
candidate, collector, evaluator, driver and policy identities are retained with
the 55 measurement rows, eight fault cuts, 25 diagnostics and reserve observation.
The workflow cannot run from this branch and has not produced a target receipt.

`hot_path_gate.py` reopens a validated real collection against a separately owned,
candidate/profile-bound policy. It checks absolute p99 and touched-byte limits at
all five history points plus bounded work-per-history growth for frontier hashing,
lease cloning, lease serialization, clock-floor persistence and restart rebuild.
A pass still sets `runtimeOptimizationAuthorized=false`; it is evidence for a
later reviewed design decision, not authority to replace the current owner,
frontier ordering or runtime store.

`run_native_checks.py` executes and retains an explicit plan: toolchain identity,
formatting, all-target compilation, full affected package tests with no retries
and zero-test failure, strict Clippy, Python regressions, B4, full caller closure,
state projections and clean-source identity. Missing tools, timeouts, source drift,
failed commands and a partially executed plan remain failures. Receipts bind
commands, exit codes, log digests, source/merge subject and available
workflow/runner identity.

The production-closure workflow runs the ordinary product pilots and the exact
Agentd owner-task pilot in both source-head and deterministic-merge subjects. Its
performance lane runs the limited source benchmark plus only the synthetic
collector self-test. It does not execute or claim the target-host capacity matrix.
The workflow remains read-only and has a distinct exact-main observation for
applicable post-merge pushes.

The canonical manifest enumerates every target ModulePort declared by the
technical guide. It separately records contract definition, named source
composition, normal product invocation proof, exact execution, target-host
qualification and independent acceptance. Existing independent owner protocols
are not relabelled as generic-authority consumers. Same-process owner reopen, two
normal product processes and target-host crash drills remain distinct evidence
scopes.

## Validation boundary

This editing environment does not provide the repository Rust toolchain, so the
new native selections have not been compiled or executed here. Exact-head and
fixed-merge native checks are required and may reveal formatting, compiler, lint
or runtime issues. Do not merge or promote this candidate based on the existence
of these files. Local Python observations cover the materialized qualification
scripts only; they are not a full-checkout, native-package or target-deployment
receipt.

The current product-process and production-closure workflow runs are pending in
the hosted queue. Pending, queued, missing-job, cancelled, skipped, stale or
historical runs are not pass receipts.

## Remaining repository-controlled work

- Obtain successful formatting, all-target compilation, package tests, strict
  lint, closed-caller proof and generated-state checks for the same exact source
  and deterministic merge candidate.
- Obtain successful exact-head and deterministic-merge receipts for the new two-
  normal-Agentd-process recovery test. Keep its fixture scope separate from
  selected production-provider and target-host claims.
- Attach selected real production time, independent frontier and custody
  providers to normal Agentd/Fleet bootstrap; reject production configuration
  without them rather than falling back to compatibility trust.
- Repeat cold-start recovery on the selected target with the actual provider and
  independently protected frontier, preserving nonce history, pending revocation,
  attempt identity, exact provider occurrence and provider-owned terminal or
  indeterminate evidence.
- Provision the protected target environment, runner, candidate runtime, reviewed
  fixed-path driver and independent site policy. Execute and independently reopen
  the complete real 55/8/25 collection. A collector, workflow, policy or synthetic
  self-test is not a measurement, SLO approval or external fault receipt.
- Use the retained hot-path decision to determine whether frontier hashing,
  lease-image persistence, clock-floor commits or restart reconstruction justify
  an incremental digest/checkpoint migration. The WAL/checkpoint/sharding model
  remains qualification-only until a runtime design preserves existing
  linearization and anti-rollback proofs.
- Complete target-only generic-authority ports without creating a second
  authority or treating another module's separate verifier protocol as this
  port's implementation.

## External evidence not manufactured

No attested clock, independent production frontier, KMS/HSM deployment, real key
rotation/compromise ceremony, revocation transport fanout, selected target-host
latency result, operator/independent acceptance, canary, promotion or release is
created by this change. All corresponding authority and acceptance flags remain
false.
