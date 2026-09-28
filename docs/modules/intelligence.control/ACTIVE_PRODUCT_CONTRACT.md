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

## 2. Stage dataflow

A receipt predecessor is not sufficient by itself. The actual owner output must
bind the successor owner request:

- the admitted NDU output binds the Neuron tick;
- the actual Neural output and canonical candidate-set digest derive the Prompt
  request identity;
- the actual Prompt output and candidate-set digest derive the Intuition request
  identity and state binding;
- the actual Prompt and Intuition outputs are inserted as typed untrusted
  evidence in the Context request;
- the selected candidate is rechecked against the canonical candidate set before
  Context, evaluation, Agentd admission or physical dispatch.

A caller-supplied request whose retained stage binding conflicts with these
values is rejected. Raw candidate order cannot change candidate-set identity.

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

The canonical profile uses a supervised host invocation provider. A physical
worker reservation is acquired before the seven-owner factory runs. Timeout,
request cancellation, result-channel loss or panic cannot release that
reservation before the synchronous worker really exits. Factory panic is
converted to a typed protocol failure and cannot poison the worker count.

The product continuation uses a separately supervised owner wrapper for signed
Decision/Outcome inputs and physical prompt/context construction. The same
reservation rule applies: dropping the waiting future cannot make abandoned
owner work invisible or increase effective concurrency.

The complete profile advertises canonical capability only after runner,
supervised provider and product continuation installation have all succeeded.
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

## 6. Recovery scheduling and currentness files

Each learning-runtime cycle reserves bounded work for both unsettled recovery
and newly prepared operations. A batch of one alternates classes. Larger batches
reserve at least one dispatch slot. Temporary capacity, lease, I/O and final-use
availability failures remain retryable without fabricating a terminal state or
terminating the required service.

The signed seven-owner currentness manifest is read through one bounded opened
handle, checked against the path identity and private parent, and verified under
the externally configured signer. An owner-local anti-rollback anchor rejects an
older authority epoch and same-epoch content substitution. The anchor is a floor
for already accepted signed facts, not a replacement authority source.

## 7. Acceptance boundary

`REQUIREMENT_TEST_MAP.json` is the human-reviewed mapping from each Phase A-D
requirement to exact source symbols and non-ignored tests. The broad generated
`TEST_TRACEABILITY.json` remains a source/test inventory and does not infer new
closure semantics from function-name similarity.

The closure workflow executes both `source-head` and deterministic `base-merge`
lanes for pull requests. Each lane verifies formatting, the explicit mapping,
Agentd and inference-worker native tests, all-target compilation, strict Clippy,
selected process-loss/no-redispatch cuts and resource measurements. Artifacts
bind the executed checkout SHA and lane.

Until those exact jobs pass, tracked source keeps current-candidate execution,
real-process provider E2E, target-host qualification, independent acceptance,
activation, promotion and release false.
