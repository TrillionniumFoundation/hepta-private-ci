# TaskFlow review remediation — 2026-09-27

This is an implementation progress record, not an acceptance or release receipt.
The canonical continuation is PR #1063 on
`work/automation-taskflow-full-closure-2026-09-27`. PR #1056 is superseded: its
head `9b5ea887fa5d7f2c25e614d3e5324802643a0348` is an ancestor of the continuation.
No branch history is deleted and no merge or activation is performed.

## Exact observation and completion boundary

Source observation: `162baefae1b985b9235cb8abce56704fc2153b88`, tree
`1b2f4d9bec23e0e57efd6f59ccbbe44a06ba2bbd`.

This delivery is **partial implementation of the requested three stages**.
It must not inherit the earlier schema-v19 documents' whole-source-closure
claims. The implementation map now records schema **21**, actual observed
source objects and explicit remaining gaps. Its source-base ancestor remains
provenance, not evidence that the present native candidate passed.

The older `TECHNICAL.md`, `SCHEMA_CONTRACT.json`, SLO, migration and Lane B
projections have not yet been fully converged to this revision. Their old
schema-19 and fairness/closure statements are not acceptance evidence. The
existing contract gate remains blocking; its failures are not waived, and the
new command driver does not hide them by short-circuiting all native diagnostics.

## Implemented source

### Admission and errors

`AutomationScheduler::tick_batch_cancellable` samples cancellation before every
new claim. A tick that already started is allowed to preserve/complete its
acknowledgement; cancellation does not erase possible provider contact.
The compatibility batch delegates to the same implementation. The first proven
pre-admission failure returns `RetryDeferred` to the actual Agentd loop for
cross-cycle exponential backoff. Fatal, fenced and conflicting failures retain
their error class; they no longer silently become generic retry results.

The Agentd constructor uses the policy's lease and dispatch timeout. Its product
loop calls the new cancellation-aware entrypoint. The existing in-flight
acknowledgement service test now supplies the required runtime-policy argument.

### Durable recovery scheduling

Migration 20 adds two permanent sweep records inside the existing AutomationStore,
not a new scheduler, service or database. Each lane stores an independent keyset
cursor and upper key. Cursor movement is fenced by the existing timer writer,
uses exact prior-state CAS and cannot modify occurrence business timestamps.
Missing cursor state rejects rather than bootstrapping fresh polling history.

Migration 21 retains migration 20's published checksum and adds a sparse-unknown
identity index. Its view selects the indexed dispatch key rather than an equivalent
joined key that caused SQLite to sort retained history. No existing V1 identity,
provider attempt, terminal receipt or historical migration is rewritten.

For a finite current frontier, persistent keyset rotation fixes the counterexample
where the oldest eight nonterminal records hide the ninth forever. The tests also
cover new task IDs above the frozen cut. This is not a proof of bounded latency
under arbitrary overload, backdated IDs or unlimited new occurrences inside an
already-frozen key range; target admission/fairness qualification remains required.

The actual Agentd recovery path consumes the persistent selection and exact owner
reads. A transient unknown-query error is retained while the reserved terminal
lane is attempted; the batch returns the error and therefore permits no new
admission that cycle. Fence/corruption/identity errors stop immediately.
Read-only queue reconciliation and each turn-history page have a five-second
request timeout. Timeout never becomes provider absence. Selected exact keys no
longer depend on finding the record in an unrelated global 1024-row prefix.

### Qualification evidence

The two source-writing repair/fact-sync workflows were removed. Existing historical
one-shot scripts are not qualification entrypoints and have not been used to issue
completion claims.

The focused workflow now invokes `automation_taskflow_commands.py`, which reuses
`hepta_ci_exec.py`. Each actually dispatched command records exact source identity,
arguments, working directory, exit status, timing, retained log digest and observed
test counts. A missing compile receipt leaves dependent tests `not_run`, never
`passed`. A filtered zero-test invocation cannot satisfy the native review-test
minimum. Changed source/log bytes, timeout and nonzero status reject.
The wrapper makes no independent acceptance, promotion or release decision.
Source-head evidence still does not replace the existing deterministic-merge gates.

## Validation actually executed

Local command, using the exact new SQL strings and protocol implementation:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest -v \
  scripts.test_automation_recovery_sweeps \
  scripts.test_automation_taskflow_commands
```

Result: **23 passed** — 14 Python SQLite migration/query/protocol regressions and
9 command-receipt validation tests. The SQL fixture uses a minimal predecessor
shape, not the full historical SQLx migration chain. The 5000-pending-row and
10000-retained-dispatch/3-unknown cases check bounded pages, polling-state size,
query plan and SQLite instruction work; they are not selected-host SLO results.

Added native source tests: four scheduler/error/cancellation regressions, three
real-owner recovery/reopen/fencing regressions and three product error-accumulator
regressions. **Their native execution is not reported as passed.** No local
Cargo/rustc/rustfmt toolchain or complete native workspace was available for this
execution. Current-head CI, formatting, Clippy, SQLx migration, actual product
recovery and synthetic-merge qualification remain required.

## Remaining requested work

The full original scope remains in force:

- converge the technical/schema/SLO/Lane B documents and executable contract checks;
  run the strict source-map and generated-projection verifiers on one final commit;
- execute and repair native/format/Clippy/product and deterministic-merge failures;
- persist Neural Circuit ingress/activation, choices, reservations and Wait/Effect
  continuation through the existing TaskFlow owner, with real product ports and
  crash tests that do not rerun historical choices;
- connect the cross-host manifest to a verified external fence controller, actual
  checkpoint transport and a two-host failover/recovery exercise;
- bind selected-host receipts to the runtime's actually consumed timezone profile,
  provider, authority/revocation configuration and native SQLite build;
- stream occurrence and TaskFlow startup integrity verification instead of loading
  complete histories, then run long-retention capacity and operational restore tests;
- complete executable migration/recovery tooling and independently provisioned
  deployment/acceptance evidence.

`productionImplementation`, product execution proof, independent acceptance,
activation, promotion and release remain false. Missing repository source work is
not relabeled as merely an external deployment gate.
