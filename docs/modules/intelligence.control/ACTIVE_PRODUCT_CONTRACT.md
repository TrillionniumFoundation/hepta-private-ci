# intelligence.control active product contract

This document is the effective implementation contract for the canonical
`intelligence.control` product path. It consolidates the product-closure
amendments to `TECHNICAL.md`, `PRODUCT_CLOSURE.md` and
`RESTART_RECONCILIATION.md`. Historical read-only, shadow, qualification-only
learning and in-process pending-replay descriptions remain compatibility
references; they are not the product route defined here.

Documentation does not establish execution, activation, promotion or release.
The exact source-head and deterministic merge candidate must execute the native
closure workflow, and real-process/target-host claims require their own retained
evidence.

## 1. Authority and ownership

`intelligence.control` remains an authority-free composition facade. Objective,
utility, neuron, prompt, intuition, context, evaluation, physical execution and
learning facts remain with their registered owners. The facade may bind and
sequence owner outputs but may not mint model, tool, filesystem, network,
learning-writer or deployment authority.

The only product topology is:

```text
authenticated ObjectiveStart
-> durable RunStart
-> supervised host-owned seven-owner invocation
-> canonical seven-stage composition
-> Agentd ContextAttached run
-> durable authenticated Decision
-> existing runtime.codex/App Server turn
-> exact Agentd/provider terminal observation
-> durable authenticated Outcome
```

No stage may introduce a second control plane, executor, durable fact store or
learning writer.

## 2. Stage dataflow and final context identity

A receipt predecessor is not sufficient by itself. The actual owner output must
bind the successor owner input or the successor product identity:

- the admitted NDU output is inserted into the Neuron tick and conflicting
  caller input is rejected;
- the actual Neural output is retained as the Prompt predecessor;
- owner-backed Prompt delivery freezes the exercised portfolio, serialized
  payload, context attachment and materialization proof;
- the actual Neural and Prompt outputs derive the Intuition state binding;
- NDU feasibility constrains which Intuition candidates may remain selectable;
- the native Context owner output is wrapped in one final context-stage digest
  that also binds the actual Intuition receipt, canonical candidate-set digest
  and selected candidate;
- the selected candidate is rechecked before Context, evaluation, Agentd
  admission, physical dispatch and learning publication.

The physical App Server payload remains exactly the owner-backed serialized
Prompt delivery. The derived context-stage digest does not rewrite those bytes;
it proves that the frozen payload/context attachment is being used for this
specific Intuition decision and candidate universe. A caller-supplied binding
that conflicts with any actual stage result is rejected. Raw candidate order
cannot change candidate-set identity.

`intelligence_product_runner.rs` activates
`StageBoundAgentdOwnerPortsV1` as the runner's owner-port type. The unwrapped
native adapters remain implementation details and are not a second product
route.

## 3. Historical event time and current validation time

The `now` retained in an immutable Decision or Outcome payload is historical
admission metadata. It is never reused as proof that evidence remains valid at
a delayed first application or after restart.

For a not-yet-applied event, the learning host obtains current wall-clock time,
current final-use authority and current learning evidence immediately before the
sole `LedgerWriter` mutation. Clock rollback relative to the historical
admission time is `Indeterminate`, not success.

Destination-first recovery is deliberately different. If the exact complete V2
ledger event is already present, recovery acknowledges that historical fact
without requesting new authority. If it is absent, replay uses the immutable
payload and original predecessor but must pass current validation time and fresh
final-use authority.

## 4. Bounded host and owner execution

There is one supervised host invocation provider. The historical exported
provider name is a source-compatible alias to the same implementation, not a
second worker implementation.

A physical worker reservation is acquired before the seven-owner factory runs.
Timeout, request cancellation, result-channel loss, thread-spawn failure or panic
cannot release that reservation before the synchronous worker really exits.
Factory panic is converted to a typed protocol failure and cannot poison the
worker count. Caller-owned immutable RunStart copies remain available after the
worker exits and are used for the final durable-identity overwrite and
validation.

The canonical cognition worker and the product continuation use separately
bounded supervision. Dropping a waiting future cannot make abandoned owner work
invisible or increase effective concurrency. The complete profile advertises
canonical capability only after runner, supervised provider, independent
anti-rollback witness and product continuation installation have all succeeded.
Telemetry is not marked configured during a failed partial composition.

## 5. Physical identity and no redispatch

Before runtime.codex admission, the owner-supplied physical request identity is
overwritten with a deterministic identity bound to:

- durable run identity;
- canonical run-snapshot digest;
- advisory Decision digest;
- learning episode identity.

A retry of the same logical run therefore reaches the same durable native
reservation. Changed prompt/context/model payload under that identity conflicts;
it cannot create a fresh physical request. Once dispatch may have crossed the
App Server boundary, absence of an exact terminal observation remains
`Indeterminate` and never authorizes automatic redispatch.

A terminal Outcome requires agreement between the provider terminal correlation
digest and the same Agentd run's terminal phase. Provider completion alone,
Agentd state alone, queue acknowledgement or transport acknowledgement is not a
terminal product result.

The product loop exposes three distinct terminal postures:

- `Completed`: the exact Decision, physical terminal and authenticated Outcome
  are durably acknowledged;
- `Indeterminate`: physical dispatch may have happened, but no exact provider
  terminal digest is available; only physical reconciliation may close it;
- `ReconciliationRequired`: an exact provider terminal digest exists, but the
  same-run Agentd terminal witness or authenticated Outcome closure is not yet
  complete.

`ReconciliationRequired` retains the physical terminal digest and, once known,
the exact Outcome operation identity. Agentd terminal RPC loss, Outcome-owner
timeout, Outcome enqueue failure, current-authority unavailability or terminal
learning rejection after a physical result therefore cannot erase the physical
observation or turn the logical operation into a fresh request. ObjectiveStart
surfaces this state as `canonical_reconciliation_required`.

A profile without a product continuation falls back before canonical
preparation/admission. It cannot leave a `ContextAttached` run that no physical
owner can finish.

## 6. Exact learning settlement and fair recovery

Interactive Decision and Outcome settlement stays bound to the exact
`scope_id/operation_id`. It uses `kernel.operations::claim_operation`; it never
spends authority or work on whichever queued operation happens to sort first.

Each background learning-runtime cycle reserves bounded work for both unsettled
recovery and newly prepared operations. A batch of one alternates classes.
Larger batches reserve at least one dispatch slot. Temporary capacity, lease,
I/O and final-use availability failures remain retryable without fabricating a
terminal state or terminating the required service. Deterministic malformed,
conflicting or revoked operations retain their distinct terminal
classification.

## 7. Currentness files and anti-rollback

The active currentness path is:

```text
intelligence_files::read_bounded
-> signed manifest verification in intelligence_product_base
-> IntelligenceAuthorityRollbackGuardV1
```

The manifest is opened through a bounded no-follow descriptor walk. The opened
regular file, size, permissions and single-link property are checked on the same
handle used for the bounded read. Non-Unix platforms fail closed until an
equivalent reparse-point-safe implementation is qualified.

The signed seven-owner manifest is then checked under the externally configured
signer. Only after the full owner universe is structurally valid may the
independently retained monotonic witness advance. The witness rejects an older
authority epoch and same-epoch content substitution. It is a floor for already
accepted signed facts, not a replacement authority source, and must be retained
outside the Agent-home rollback domain.

## 8. Traceability and acceptance boundary

`REQUIREMENT_TEST_MAP.json` is the human-reviewed mapping from each Phase A-D
requirement to exact active source symbols and non-ignored tests. Dead or
uncompiled alternative files are not valid evidence.

The broad generated `IMPLEMENTATION_MAP.json` and `TEST_TRACEABILITY.json`
remain inventory projections. Their stable entrypoint explicitly points source
assertions at the active split implementation files rather than accepting
`include!` wrappers or stale alternatives.

The closure workflow executes both `source-head` and deterministic `base-merge`
lanes for pull requests. Each lane verifies formatting, the explicit mapping,
Agentd and inference-worker native tests, NDU tests, all-target compilation,
strict Clippy, selected process-loss/no-redispatch cuts and resource
measurements. Artifacts bind the executed checkout SHA and lane.

A separate macOS portability workflow executes the signed-authority product
fixtures, anti-rollback persistence, bounded no-follow file tests and strict NDU
lint. Unix temporary fixtures explicitly set owner-only directory permissions;
a permissive test-runner umask may not weaken the production file contract or
turn a platform-specific fixture failure into a skipped check.

Until those exact jobs pass, tracked source keeps current-candidate execution,
real-process provider E2E, target-host qualification, independent acceptance,
activation, promotion and release false.
