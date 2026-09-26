# Complete-pipeline SLO measurement contract

Status: required instrumentation and acceptance contract. No numerical values in this document are measured product results. The validator is implemented; a complete production harness and accepted named-host results remain open.

## Measurement boundary

Time one request from SQLite observation through exact snapshot binding, candidate adaptation, HNMF settling, optional downstream ranker, final source revalidation, text materialization, context planning and durable learning-assignment append. Do not sum phase p95s to manufacture an E2E p95. Record failures and abstentions in the same offered workload instead of timing only successful requests.

Prebuild the binary and fixtures before the timed region. Request CPU/RSS/allocation and SQLite-read counters must come from actual instrumentation, not constants or the number of Rust wrapper method calls. Cargo/GNU-time RSS is a whole-command metric and can include compilation. Record unsupported metrics as unavailable and fail the relevant qualification; never fill zero.

## Input schema

`hepta.memory-retrieval.agentd-e2e.v1` requires phase `agentd-e2e`, `resource_scope=request_pipeline`, an explicit `cache_state` of `cold` or `warm`, positive attempts and concurrency, and the following non-negative integer measurements:

`p50_us`, `p95_us`, `p99_us`, `max_us`, `cpu_time_us`, `peak_rss_bytes`, `allocation_count`, `sqlite_read_count`, `candidate_count`, `node_count`, `synapse_count`, `owner_write_contention_count`, `provider_rotation_count`, `abstention_count`, `stale_rejection_count`, `failure_count`, `delivered_count`.

The four outcome counters are mutually exclusive and sum to attempts. Abstention and stale-rejection rates use those explicit denominators and integer parts-per-million arithmetic. Percentiles are nondecreasing. Preserve raw per-request samples separately to permit independent recomputation; a structurally valid aggregate is not proof of measurement provenance.

`stage_observations` and `stage_executions` have exactly these keys:

```
owner_observation
snapshot_binding
candidate_adaptation
hnmf_settling
downstream_ranker
final_revalidation
text_materialization
context_plan
learning_assignment_append
```

Every request must have a stage disposition, even if a prior failure causes a stage not to execute. Each required stage must actually execute in the qualifying scenario; a permanently disabled ranker or ledger is not full-pipeline evidence. `pending_learning_assignments` must be zero at collection completion. Prepared/published context still does not prove downstream model consumption.

## Scenario matrix and acceptance

Run independent cold/warm scenarios at predeclared concurrency levels, small/large owner stores, normal/ceiling graph sizes, owner-write contention and provider renewal/rotation contention. Retain scenario seeds, workload identity, all artifact/policy digests, host architecture, OS/kernel, toolchain and exact source identity. Use separate profiles for ARM and x86 or for different deployment hardware.

Predeclare latency, CPU and RSS thresholds in a versioned profile before collecting the acceptance sample. Run the strict validator with `--require-e2e`. Never alter thresholds in response to the same sample and then call it an independent pass. Regression comparison must reference an accepted matching-host baseline; an old microbenchmark is not the E2E baseline.

Store raw logs, per-request samples, exact threshold bytes, provenance and the generated qualification receipt in content-addressed long-term storage. An independent reviewer must verify provenance, scope, privacy filtering and all required checks before any production flag changes.
