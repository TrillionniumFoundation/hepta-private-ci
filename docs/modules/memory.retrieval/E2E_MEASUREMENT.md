# End-to-end measurement and SLO receipt contract

Status: validator implemented; the complete native measurement producer, target-host execution and independently approved SLO are not established by this document. Unit fixtures are not Agentd measurements. Keep product/acceptance/activation/release claims false.

## Exact source and schema

`scripts/hepta_memory_retrieval_slo.py` accepts `hepta.memory-retrieval.e2e-samples.v2` and writes `hepta.memory-retrieval.slo-receipt.v2`. V2 requires both `source_head` and `source_tree`. The CLI observes the actual clean checkout's commit, tree and ordered parents before validation and observes them again before retaining the receipt. It rejects a wrong checkout, dirty tracked or untracked files, missing/mismatched tree, and changes during validation. A Git observation is not proof that an instrumented binary was built from it: retain the build receipt and executable digest separately for independent acceptance.

V1 sample files are not silently upgraded. Recover an old run's source identity from its original independently retained build/run records or rerun the real experiment. Never copy current Git labels onto an old measurement. The SLO policy remains `hepta.memory-retrieval.slo-policy.v1`; no acceptance threshold is created by this change.

Run on a checkout detached at the exact tested commit, keeping sample/policy/output files outside that checkout:

```sh
python3 scripts/hepta_memory_retrieval_slo.py \
  --root "$CHECKOUT" --head "$TESTED_SHA" \
  --samples "$RAW_SAMPLES" --policy "$APPROVED_SLO_POLICY" \
  --output-dir "$RECEIPT_DIRECTORY"
```

The command exits nonzero on an invalid contract or a measured SLO breach. A completed comparison is not an independent acceptance decision. The receipt content-addresses canonical sample/policy JSON; original raw files and build/profiler logs must also be retained.

## Required measurement envelope

In addition to source identity, the document must bind `producer=agentd-product`, `synthetic_fixture=false`, `host_profile`, `measurement_run_id`, `clock`, `allocator_instrumentation`, `sqlite_instrumentation`, `ranker_enabled=true` and `learning_sink_enabled=true`. These declarations are necessary but not sufficient: the independent owner must verify the real producer, calibrated clock/counters, binary identity and retained raw trace. A caller-written label alone is not authenticated evidence.

Each uniquely identified sample declares cold/warm cache, actual concurrency, owner-write contention, provider-rotation contention, positive end-to-end wall time, and all nine **exclusive**, nonoverlapping stage durations in microseconds:

1. `sqlite_observation`
2. `snapshot_binding`
3. `candidate_adaptation`
4. `hnmf_settling`
5. `downstream_ranker`
6. `final_revalidation`
7. `text_materialization`
8. `context_plan`
9. `learning_assignment_append`

The stage sum cannot exceed total wall time. Instrument actual boundaries; do not subtract an overlapping span and label the remainder as measured. A stage not executed or a missing profiler counter must remain explicitly unavailable in the raw trace, not be invented as zero to satisfy this full-chain schema. Keep partial/failure traces separately when they cannot meet this contract. A genuine measured sub-microsecond duration can round to zero; that is different from an unmeasured stage.

Every sample also reports measured `cpu_us`, `peak_rss_bytes`, `allocation_count`, `sqlite_read_count`, `candidate_count`, `node_count`, `synapse_count`, `traversed_synapses`, and Boolean `abstained`/`stale_rejected` outcomes. Request-scoped counters must not be process-wide deltas duplicated across overlapping requests. RSS is an observed process high-water mark and is aggregated by maximum, not summed. `sqlite_read_count` means actual instrumented read statements, not a guessed count of public store API calls. Allocation counts require allocator instrumentation, not a value derived from RSS.

The native source still needs a qualified producer for these fields. Standalone owner/HNMF probes cannot be added together and represented as an observed end-to-end request.

## Workload and arithmetic rules

The approved policy declares distinct required cases, at least 100 observations per case, and bounds for p95, p99, maximum latency, peak RSS, abstention ppm and stale-rejection ppm. Optional CPU/allocation/SQLite limits must also be bounded integers. Unknown limits, Boolean/negative/nonfinite numbers, rates above one million ppm, missing cases and duplicate sample identities are rejected.

Reports include p50/p95/p99/max for total latency and each stage; sums for request-scoped CPU/allocation/SQLite counters; maxima for resource ceilings; and observed outcome rates. Rate values use **ceiling ppm**, so one failure in 101 requests is reported as 9901 ppm rather than rounded down to 9900 and incorrectly accepted at that limit. For integer ppm limits this has the same pass/fail result as comparing the exact rational rate.

Run cold/warm and representative concurrency levels with and without actual owner writes/provider rotations. Preserve failure, timeout, stale-rejection and omitted samples; do not report only successful survivors. The experiment owner must choose and approve the workload matrix and thresholds before examining candidate results.
