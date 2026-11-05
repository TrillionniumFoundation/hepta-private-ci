# Agentd fallible-transition review

Base: `4e31abc907f09740d402d1ddef7a1d2fe0a366a6`.
Updated patch SHA-256: `2b2bbe9b6987fc1c12d080d6b90f08fb4c6e441c9faa25d6f5b4bf92a39b234e`.

## Scope and semantics

Arithmetic rejection is now atomic for the affected run record. Every ACK deadline and revision increment is checked before publishing that record's phase, context, reason, or ACK deadline. Batch methods retain previously completed records; they are deliberately not whole-batch transactions. `begin_drain` closes admissions before work and keeps them closed when a later record fails. No unknown observation becomes terminal and no redispatch path is introduced.

| Method | Changed behavior | Public reachability and coverage |
| --- | --- | --- |
| `attach_context` | Revision overflow cannot install context or advance phase. | Exhaustion in the short pre-dispatch chain is not reachable through the ordinary public sequence. Internal exhaustion fixture exercises the checked boundary. |
| `mark_dispatched` | Revision overflow cannot mark dispatched. | Same pre-dispatch reachability limit; internal exhaustion fixture. |
| `cancel_run` | ACK deadline is computed before revision; both precede cancellation state publication. | Deadline overflow is reachable through public `u64` clock/deadline inputs; explicit public failure and exact-upper-bound success cases. Exhausted revisions in transient phases use internal fixtures. |
| `observe_terminal` | Revision overflow preserves unknown phase, capacity, and complete receipt. | Public `recover_indeterminate` accepts a nonzero `u64::MAX` revision. Public negative replay and last-available-revision positive cases cover all three terminal phases. |
| `expire_record` | ACK timeout and request timeout check revision/ACK deadline before state mutation. | Request clock/deadline upper bound is publicly reachable. Revision-boundary transient phases are internal fixtures. |
| `expire_deadlines` | Count preflight precedes the current record transition. Failed record is unchanged; completed prefix remains. | Public two-run deadline-overflow case checks prefix receipt and retained dispatched record. The count cannot reach `usize::MAX` under the existing 1024-record bound. |
| `begin_drain` | Same record preflights; admissions remain closed on failure. | Public deadline-overflow path and internal revision fixture; batch prefix semantics verified. |
| `mark_unresolved_indeterminate` | Count/revision preflight precedes changing phase/reason or clearing ACK deadline. | Internal exhaustion fixture verifies unchanged failed record and valid completed prefix. |
| `start_run`, `start_revalidated_run_start`, `recover_indeterminate`, `remove_closed_run` | Unchanged. | All returned validation/arithmetic errors already occur before insert/remove. |

The existing `cancel_run` autonomous-expiry behavior is unchanged: a due cancellation-ACK timeout can commit a complete transition to `Indeterminate` and then return the existing `InvalidTransition` classification. It retains capacity and cannot redispatch. This patch does not claim that every `Err` from a compound operation leaves the entire coordinator unchanged.

## Validation

- Corresponding source obtained at the exact base commit.
- `git apply --check` against the retained original files: exit 0.
- Both `git diff --no-index --check` invocations emitted no whitespace errors (the expected no-index difference exit is 1).
- Added eight behavioral tests, including public API refusal, exact arithmetic-boundary success, retained capacity, repeated observations, and batch-prefix behavior.
- No local Rust toolchain. Original `just fmt` and `just test --locked -p codex-hepta-agentd --lib` remain required on the combined candidate. No native pass is claimed.

## Independent B test review

Reviewed `adaptive/holdout-plan-integrity.patch` with production blob `fcd7d3cf378f63482077b1cb6f6fdf4513faa173` and tests blob `ea87b0cd88679eaf6810e14973f4f3b8435f293d`.

No static compilation obstacle found: the tested fields are public mutable numeric fields, capture-free closures coerce to the annotated function-pointer array, `TemporalEvaluationError` already converts to `ProductEvaluationError`, the anchor supports Copy/Debug/Eq/PartialEq, returned receipt/error types support Debug, `pretty_assertions` is an existing dev dependency, and the existing test module path includes the changed file. The fixture borrows disjoint plan/provider fields without retaining borrowed inputs in its returned receipt.

The regression distinguishes old from corrected behavior: the original runner consumes the holdout and releases provider data before the lower evaluator detects the altered canonical digest; the changed runner rejects before either action. The test checks unchanged owner anchor and zero release, then successfully consumes the unchanged frozen plan once. This is a static source review, not a substitute for native compilation or tests.
