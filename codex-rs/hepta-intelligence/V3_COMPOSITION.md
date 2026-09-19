# Intelligence V3 composition

run_composition_v3 is the canonical composition graph for intelligence.control.
The older read-only vertical, V1 shadow pipeline, V2 capability router and evaluated
shadow wrapper remain compatibility/qualification surfaces. New product composition
must not build another parallel facade around them.

## Graph

The V3 predecessor chain is:

1. objective.compiler — objective validation.
2. intelligence.control — native LegalActionCandidateSetV1 construction.
3. utility.ndu — utility/NDU evaluation.
4. learning.eval — independent evaluation admission.
5. neuron.runtime — optional neural signal; absence or bounded failure is explicit fallback.
6. prompt.optimizer — optional prompt portfolio; absence or bounded failure is explicit fallback.
7. intuition.policy — continue, abstain or slow-path decision.
8. context.compiler — required only for continue.
9. intelligence.control — native IntelligenceHostEnvelopeV1 construction.
10. runtime.agentd — typed host-envelope acceptance.
11. learning.ledger — durable decision/exposure owner boundary.

Every external stage consumes one PortInputV3 containing the exact run,
capability-snapshot digest, predecessor digest and stage budget. Every successful
receipt must echo the stage, snapshot and predecessor, identify the registered
producer, return a non-zero output digest and retain AuthorityPosture::DENY_ALL.
Required-stage failure is terminal. Only neuron and prompt may use
FallbackUsed. Intuition alone may return abstain or slow path.

## Capability snapshot

V3 consumes one admitted CapabilitySnapshotV2. The following capabilities are
required and owner-checked before any owner callback:

- objective.validation -> objective.compiler
- legal.actions -> intelligence.control
- utility.evaluation -> utility.ndu
- learning.evaluation -> learning.eval
- intuition.decision -> intuition.policy
- context.compilation -> context.compiler
- host.handoff -> runtime.agentd
- learning.record -> learning.ledger

neural.signal and prompt.portfolio are optional. If absent, the graph records a
deterministic unavailable fallback without calling a fabricated adapter.

## Native contracts

build_legal_candidates_v1 produces the registered LegalActionCandidateSetV1. It
canonicalizes candidate ordering, rejects duplicates, caps the set at 128, binds
state/grammar/support and never grants authority.

IntelligenceHostEnvelopeV1 binds the admitted snapshot, objective, legal candidate
set, utility, evaluation, optional neural/prompt signals, intuition, compiled
context, pre-handoff trace and total budget. The consumer identity is fixed to
runtime.agentd. The envelope is a proposal/context handoff only; it is not
model/tool/effect authority.

codex-hepta-agentd::AgentdIntelligenceHostV1 is the product-side typed consumer.
It validates the exact envelope and returns an authority-free acceptance digest
that can be used as the HostHandoffAccepted stage output. Existing Codex/App
Server code remains the sole model/tool execution spine.

## Deadline and cancellation semantics

run_composition_v3_with_control checks cooperative cancellation and real Instant
elapsed time before and after each owner port. A cancelled or over-budget owner
call becomes a typed Cancelled or TimedOut failure/fallback according to the stage
policy.

The V3 coordinator is synchronous. It cannot safely preempt a port while that port
is blocked. Ports therefore remain proposal-only and must enforce their supplied
deadline at their own I/O boundary. A host that requires hard interruption must
adapt the owner call to its existing async cancellation/timeout primitive before
implementing the V3 port.

## Post-execution Outcome/Credit closure

`append_outcome_credit_v1` closes the learning side after execution without
making `intelligence.control` the learning fact owner. The caller supplies the
exact Decision ledger predecessor, a terminal independent `OutcomeObservation`
and its `CreditAssignment`. The adapter checks episode/outcome/support bindings
before writing, appends Outcome first, then Credit through the sealed
`DurableLearningJournal`, and returns both durable receipts.

Outcome and Credit are intentionally separate commits. If Outcome is durable but
Credit fails, the returned error retains the Outcome receipt and the caller must
reconcile/retry the exact Credit; it must not roll back or fabricate an atomic
success. Exact replay after anchored reopen is idempotent.

## Compatibility and remaining gates

V1/V2 receipt meanings are unchanged. run_read_only_vertical remains the concrete
objective/cognitive/context/NDU read-only slice. run_evaluated_shadow_v1 remains
the signed evaluation + durable Decision qualification path. They must not be
reported as product execution merely because V3 exists.

Source completion for V3 requires package/workspace tests, strict lint and
synthetic-merge qualification on the exact candidate. Product execution additionally
requires a named runtime callsite that supplies authenticated current owner facts,
real calibration/evaluation observations, Codex delivery evidence and durable
outcome/credit handling. Independent acceptance, canary, promotion and release
remain external gates.
