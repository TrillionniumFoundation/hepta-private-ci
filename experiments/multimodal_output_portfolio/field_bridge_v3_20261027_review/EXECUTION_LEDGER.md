# V3 execution ledger

`execution_ledger.py` aggregates already-recorded work. It never loads a source corpus, invokes a generator or observer, fits a controller, executes a native tick, changes a gate, or authorizes a retry. The output makes no scientific efficacy claim. Native authority remains `DENY_ALL`, with no owner integration.

## Accounting boundary

Every registered job has one explicit disposition. The current protocol produces 63 jobs: 18 training jobs over six phases and three seeds, plus 45 runtime jobs over three profiles, three seeds, bank/fit/audit and separate primary/retention confirmation. The supplied index is a template, not a statement that already-running jobs have not started. Fill it from immutable completed metadata and qualification decisions before aggregation. Do not inspect partial outcomes merely to populate an index.

| Evidence scope | Source of counted work | Nested records not counted again |
|---|---|---|
| Training reference, bank, fit, development, audit, final | Top-level phase `COMPLETE.resources` | Per-candidate, branch, block and closed-loop-path resources |
| Runtime counterfactual bank | Exactly `runtime_fit/COMPLETE.resources` and `runtime_select/COMPLETE.resources` | Parent inventory and repeated tree/node evidence |
| Runtime fitting | Retained candidate-policy count, 144 stage-head fits, actual native ticks and native duration | Per-candidate and feature-matrix sub-timers |
| Runtime audit/confirmation | Parent `COMPLETE.resources`, checked against `selected/COMPLETE` | The identical selected-path child copy |
| Independent verification | Each bound verification receipt once | Report copies, original study counters repeated inside audit narratives |

Counters retain their original units. They are not FLOPs, energy, money or a single interchangeable compute measure. Scientific and verification totals remain separate. Logical observer work and cache hits remain separate from actual observer batch calls and digit examples. Verification input/output copies cannot be charged twice under different receipt IDs if their receipt SHA is identical.

Recorded component wall durations are summed as cumulative worker durations. They can overlap across parallel processes and exclude setup outside the frozen timers. Nested native/select timers overlap parent durations and are separately labelled. Training-fit completion does not record a phase wall timer; the ledger reports that timer as missing. Exact elapsed span is reported only when a separately bound operational receipt provides start and finish on a specified common monotonic clock. No end time is invented from a phase START plus an inner timer.

## Index bindings and dispositions

Every file binding has exactly `{"path": "...", "sha256": "..."}`. Relative paths resolve against the index file's directory. `source_root` is the portfolio parent containing `field_bridge_v3_20261027`, `field_bridge_20261027` and `v6`; `run_root` is the original execution root. The ledger hashes all bound sources and all completed evidence members.

For a completed stage, preserve its template `id`, set `status` to `complete`, and add bindings named `start`, `complete` and `freeze`. Runtime jobs additionally require `native`, binding the actual compiled library. The freeze must match the original START exactly, including protocol, registered commit, source files, prior artifacts and native identity. Do not substitute a later freeze for the one used to execute that phase.

For `failed`, bind `start`, `freeze`, `failure`, and runtime `native`; bind `complete` too if one was written before the final failure. A failure with no complete counters is `unknown_failed_work`, never a zero-cost successful stage. An optional `failure_cost` receipt can add an observed lower bound; it must contain the exact `failure_sha256`, `accounting_scope: "observed_lower_bound"` and an integer-valued `resources` map. Missing work remains explicitly unknown.

For `not_started`, supply a reason and leave the execution directory absent. For `in_progress`, bind only immutable START/freeze/native metadata; costs remain unknown and the ledger is not terminal. These states remain unresolved work.

For `skipped_unqualified`, supply a reason, a `decision` binding, a `decision_field` list such as `["passed"]`, and `decision_value: false`. The indexed field must actually be boolean false. For `skipped_protocol`, bind the exact decision field/value and explain the registered rule. Skipped jobs must have no execution directory. A failed qualification is a terminal study disposition; it is not converted into an execution failure or a positive result.

Each canonical job may occur exactly once. Extra START receipts anywhere in the run root are rejected, exposing undeclared attempts. A non-study START may be listed under `nonstudy_start_files` only when its own receipt explicitly states `verification_only: true`. This helper provides no retry mechanism. A real recovery would require a separately reviewed ledger/index extension, with the failed attempt retained and counted.

## Independent verification entries

Each `verification` entry has `id`, `kind`, `status` (`complete` or `failed`), a `receipt` binding, a nonempty `sources` list, and a nonempty `artifacts` list. Source bindings must include the producer and all helper hashes embedded in the receipt. Each supplied artifact hash must also occur in that receipt; an unrelated file cannot stand in for verified input. Use the exact original audit receipt, not a rewritten summary.

Supported actual-cost fields include replay `verification_resources`; training-fit `verification_least_squares_solves`; runtime-fit `ridge_heads_rebuilt`; native `verification_native_ticks`; runtime-media `verification_observer_digit_forwards`; and hard-score `actual_observer_batch_calls` / `actual_observer_digit_examples`. Native, wall and CPU times are recorded separately. Existing metadata-only reports can retain their zero gradient count and measured duration. `logical_observer_*` and `observer_batch_cache_hits` are diagnostic work descriptors, never added to actual neural calls.

Compatibility fields `generator_forwards`, `observer_forwards`, `native_tick_calls` and the join's `additional_generator_or_observer_calls` are retained as explicit actual counters. If native kernel or bridge roundtrip durations occur only in every per-seed record, those measured durations are summed once. An untimed metadata join retains null wall/CPU times. Its source bindings name the bound input auditors; they do not claim a standalone join producer existed.

Include at least the executed bank replay, all three independent training-fit audits, every executed runtime-fit/native-session audit, and every executed hard-score/runtime-media audit. Include completed metadata/statistics audits as separate entries where their measured duration is available. A synthetic contract or environment/build operation is outside the default ledger scope unless explicitly added; state any broader scope in `accounting_scope`, and preserve unknown counters rather than estimating them.

The known bank replay adds 1,200 gradient microsteps and one directional measurement. The three training-fit audits add 180 independent least-squares solves. These quantities are verification overhead, never new independent observations or additional trained candidates. Later native/observer verification costs must come from their actual receipts rather than predetermined expected counts.

## Commands

Generate a template without reading run outcomes:

```bash
PYTHONPATH=/workspace/scratch/9b2cd2b58376/bridge_repo python -m experiments.multimodal_output_portfolio.field_bridge_v3_20261027_review.execution_ledger --template --run /tmp/hepta-field-v3-run --source /workspace/scratch/9b2cd2b58376/bridge_repo/experiments/multimodal_output_portfolio --protocol /workspace/scratch/9b2cd2b58376/bridge_repo/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/PROTOCOL.json --out /tmp/V3_EXECUTION_INDEX.json
```

After the parent authorizes terminal evidence aggregation and fills the index:

```bash
PYTHONPATH=/workspace/scratch/9b2cd2b58376/bridge_repo python -m experiments.multimodal_output_portfolio.field_bridge_v3_20261027_review.execution_ledger --index /tmp/V3_EXECUTION_INDEX.json --out /tmp/V3_EXECUTION_LEDGER.json
```

An optional operational timing receipt uses schema `hepta.field-bridge.v3.operational-span.1` and fields `run_root`, `clock_domain`, `scope`, `started_monotonic_ns`, `finished_monotonic_ns`. Bind it under `operational_timing`. Without it, elapsed is null. The output's `accounting_validation_passed` says that the declared evidence binds and aggregates correctly; `all_stage_dispositions_terminal` and `unknown_or_lower_bound_cost_attempts` separately identify unfinished work and accounting limits.
