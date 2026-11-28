# Independent review of durable semantic-program integration

This is a source-level review of the existing native SmallHCSN owner, cohort
store, journal and inverse, followed by integration requirements. It is not a
claim that the new MCP route or crash tests have already passed.

Reviewed original modules in `hepta-runtime`:

- `src/mcp/rea_model_session_smallhcsn.rs`
- `src/mcp/weight_artifact_smallhcsn.rs`
- `src/mcp/weight_artifact_smallhcsn_journal.rs`
- `src/mcp/weight_artifact_smallhcsn_execution.rs`
- `src/mcp/weight_artifact_smallhcsn_inverse.rs`
- `src/mcp/weight_artifact_smallhcsn_evaluation.rs`
- `src/mcp/weight_artifact_cohort.rs`

## Existing properties to preserve

The session-derived authority is not deserializable as a permission token and
retains the original owner lease. Preflight is read-only. Mutation enters the
existing retained transaction and store lock. The cohort publishes a complete
model plus its immutable manifest. The manifest's `research_binding` participates
in the artifact identity. The fixed attempt charges each model phase durably
before starting it; a crash cannot refund that reservation or replay the phase.

The inverse reconstructs the exact original reverse from saved intent and the
retained candidate, without needing the original workspace source. Once a
publication can exist, normal failures flow through compensation. A previously
published inverse is reconciled by its original saved identity. Byte restoration
can proceed when the model-evaluation window has expired; a new forward still
requires the original same-boot and wall-clock window and valid authority.

These are useful existing primitives. A new late-information scope should reuse
them without changing the old sender40 schema, tensor admission, budget,
credentials, owner fencing, journal acceptance or inversion policy.

## Minimal semantic addition

Use a separately named closed profile and typed operations for the late-quote
task. Its prepared program must bind source parent, exact four mark coordinates,
task view, raw late and retention inputs, graph, request route, fixed initial
state, evaluator source/runtime identity and declared objective. Validate that
the operation/profile pair agrees; adding an enum variant must not make the old
sender authority accept a new profile by accident.

The existing `Saved::validate` is deliberately specialized to two sender tensors,
the sender40 research binding and its original budget. Generalizing it in place
would risk accepting the wrong scope or invalidating old inverse journals. A new
typed wrapper/schema should call the common cohort/owner primitives while
leaving historical inverse validation intact.

Put the complete parent, candidate and restored function descriptors in the
cohort's bound semantic manifest. Atomic model-plus-manifest publication then
publishes the parameter bytes and their graph meaning together. This avoids an
independent mutable graph registry that could drift from the weight artifact.
Never treat an unbound graph JSON file or a caller's label as an authority.

### Zero changed bytes is not zero semantic effect

Seed137 has identical candidate and parent weight SHA256, but bridge and original
graphs have different outputs. The fixed four-word cohort can contain
`expected == replacement` comparisons, which the generic cohort already permits.
No relaxation to permit empty cohorts is needed. The record must distinguish
`changed_weight_bytes = 0` from `function_changed = true`.

Because the semantic binding enters `manifest_id`, the graph-only candidate and
restored function must have distinct artifact/function identities even when all
model bytes are identical. Restoration must verify the original graph, route and
fixed reset/step0 contract, not stop when the model hash equals the parent.

### Goal-aware selection must not recur after a crash

If the runtime first measures bridge KEEP and then chooses whether to edit,
both possible function identities must be bound before evaluation. Persist the
selection exactly once before candidate publication. Recovery may reconcile that
choice; it may not remeasure KEEP, pick a different candidate or silently restart
the goal search. If a charged prepublication phase loses its result, report the
uncertainty and do not publish a newly chosen effect.

The old three 20-second phase reservations and 60-second total should remain
unchanged for the old profile. A new profile that evaluates both late and normal
tasks inside a phase must state the additional **forward count**, charge before
the grouped work and cap the entire phase. An interrupted grouped phase is not
permission to replay its missing sub-forwards. Forward counts and cost uncertainty
must remain visible rather than being hidden behind a phase count.

## Essential recovery regressions

| Boundary or mutation | Required observation |
| --- | --- |
| Graph-only same-SHA candidate published, process killed before outcome | Recover the original graph/route/initial-state descriptor and exact parent bytes; do not call it restored from SHA equality alone. |
| Inverse published, process killed before inverse receipt | Reconcile the one original inverse; no second candidate, compilation or model replay. |
| Model charge written but result missing | Mark the reserved cost uncertain/nonrefundable; never rerun that phase. |
| Expired wall window, changed kernel boot, backward clock or old evaluator | Permit only the exact admitted inverse/readback; no new model evaluation. |
| Original workspace parent removed after publication | Recover from the retained artifact and original intent without reopening the source. |
| Saved graph, route, initial-state, task/input digest or protected parameter modified | Reject the mismatched intent/candidate before any new effect; do not reconstruct trust by running the current compiler. |
| Caller cancellation or revocation after an admitted effect | The retained original owner continues the exact compensation path already permitted by the existing policy. |
| Wrong profile paired with a new operation, or a legacy generic restore used on a bound semantic artifact | Reject without widening existing authority. |
| Candidate or inverse request repeated after completion | Return the same durable result with zero new forwards or compilation; cannot obtain a fresh budget. |
| Failure or tampering during normal-task retention | Reject the unconditional semantic candidate and restore the complete original function before returning. |

At least one crash regression must use the actual zero-edit seed137 identity
shape or an equivalent fixture that has equal model hashes and unequal function
identities. A nonzero parameter edit alone does not test this failure mode.

## Review of the intermediate pure Rust program

The initial implementation correctly enforced four-word scope, all-zero signed
contrast abstention, label-free task checking, native endpoint verification and
graph-aware inversion. Independent review found three omissions: its evaluator
digest named only source, its phase named workflow stage rather than live state,
and its prepared program did not recheck the task binding on application.
The next version added source-specific naming, actual running executable and
lockfile hashes, explicit fixed reset/step0 state, and checked task equality.

A further review found that deriving `CheckedLateQuoteMinV1` solely from graph
mode mislabeled unconditional retention and wrong-graph rollback negative
controls. Those controls intentionally do not satisfy the late-task contract.
They need an explicit research-negative-control route in their receipts. This
changes the semantic witness, not the previously observed scientific numbers.

No persistent trader state, deployment or future utility is established by the
fixed reinitialized six-tick tests. A persistent live-state extension would need
its own state snapshot, phase and recovery contract.
