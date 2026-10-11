"""Read-only measurement inventory: no unmeasured cache, serving or energy claims.

Observed seconds from one CPU execution are not per-arm latency or hardware TCO.
Existing experiment emissions remain unchanged and source pinned.
"""

from collections import defaultdict
import math

from stem_audit_archive import require


def finite_nonnegative(value, what):
    require(
        type(value) in (int, float) and math.isfinite(value) and value >= 0,
        "invalid or missing resource measure: " + what,
    )
    return value


def audit_resources(report, encoding):
    """Reconcile logged successful encoder calls and preserve unknown work."""
    caches = report["caches"]
    weights = report["backend_resident_weight_bytes"]
    require(
        isinstance(caches, dict) and caches and set(caches) == set(weights),
        "cache/backend inventory drift",
    )
    grouped = defaultdict(list)
    for row in encoding:
        backend = row["backend"]
        require(backend in caches, "unknown logged encoder backend")
        cost = row["cost"]
        require(type(cost["cache_hit"]) is bool, "cache hit flag is not Boolean")
        seconds = finite_nonnegative(cost["incremental_encoder_seconds"], "encoder")
        if cost["cache_hit"]:
            require(seconds == 0.0, "cached feature incorrectly billed as new encoding")
        else:
            require("extraction" in cost, "missing real encoding receipt")
            ext = cost["extraction"]
            finite_nonnegative(ext["seconds"], "encoder receipt")
            require(
                math.isclose(seconds, ext["seconds"], rel_tol=0, abs_tol=1e-9),
                "encoder receipt time detached from cache bill",
            )
            require(
                type(ext["pairs"]) is int and ext["pairs"] >= 0,
                "invalid executed pair count",
            )
            require(
                type(ext["pair_tokens"]) is int and ext["pair_tokens"] >= 0,
                "invalid executed token count",
            )
        grouped[backend].append(cost)
    encoders = {}
    for backend in sorted(caches):
        log = grouped[backend]
        hit = sum(x["cache_hit"] for x in log)
        misses = len(log) - hit
        recorded = caches[backend]
        require(
            recorded["hits"] == hit, "cache hits differ from immutable encoding records"
        )
        require(
            type(recorded["misses"]) is int and recorded["misses"] >= misses,
            "cache misses less than successful encoded requests",
        )
        require(
            type(recorded["evictions"]) is int and recorded["evictions"] >= 0,
            "invalid cache eviction count",
        )
        require(
            recorded["retained_estimated_bytes"] <= recorded["maximum_bytes"]
            and recorded["retained_estimated_bytes"] >= 0,
            "cache budget exceeded",
        )
        require(
            type(weights[backend]) is int and weights[backend] > 0,
            "unknown or invalid backend memory",
        )
        extracts = [x["extraction"] for x in log if not x["cache_hit"]]
        encoders[backend] = dict(
            resident_model_weight_bytes=weights[backend],
            successful_encoder_misses=misses,
            successful_cache_hits=hit,
            total_reported_misses=recorded["misses"],
            unmatched_or_failed_encoder_misses=recorded["misses"] - misses,
            executed_query_candidate_pairs=sum(e["pairs"] for e in extracts),
            executed_pair_tokens=sum(e["pair_tokens"] for e in extracts),
            measured_successful_encoding_seconds=math.fsum(
                e["seconds"] for e in extracts
            ),
            retained_cache_estimated_bytes=recorded["retained_estimated_bytes"],
            cache_allocator_overhead_unmeasured=True,
            cold_start_included_in_encoding_seconds=False,
        )

    heads = defaultdict(
        lambda: dict(
            successful_sessions=0,
            failed_sessions=0,
            attempted_training_seconds=0.0,
            sgd_optimizer_steps=0,
            prototype_examples_consolidated=0,
            consumed_training_iterations=0,
            persisted_head_artifact_bytes=0,
            maximum_reported_gradient_bytes=0,
            maximum_reported_parameter_bytes=0,
            maximum_reported_optimizer_bytes=0,
        )
    )
    for row in report["learning"]:
        arm = row["arm"]
        require(isinstance(arm, str) and arm, "invalid Head arm")
        ledger = heads[arm]
        ledger["attempted_training_seconds"] += finite_nonnegative(
            row["inclusive_attempt_seconds"], "Head fitting wall time"
        )
        if row["status"] == "succeeded":
            ledger["successful_sessions"] += 1
            receipt = row["receipt"]
            require(
                type(receipt["consumed_steps"]) is int
                and receipt["consumed_steps"] >= 0,
                "invalid Head optimizer steps",
            )
            ledger["consumed_training_iterations"] += receipt["consumed_steps"]
            if arm == "prototype":
                ledger["prototype_examples_consolidated"] += receipt["consumed_steps"]
            elif arm != "frozen_rerank":
                ledger["sgd_optimizer_steps"] += receipt["consumed_steps"]
            else:
                require(
                    receipt["consumed_steps"] == 0,
                    "frozen baseline has nonzero training iterations",
                )
            ledger["persisted_head_artifact_bytes"] += row["artifact_bytes"]
            for dest, name in (
                ("maximum_reported_gradient_bytes", "gradient_bytes"),
                ("maximum_reported_parameter_bytes", "parameter_bytes"),
                ("maximum_reported_optimizer_bytes", "persistent_optimizer_bytes"),
            ):
                if name in receipt:
                    measured = finite_nonnegative(receipt[name], name)
                    ledger[dest] = max(ledger[dest], measured)
        else:
            require(row["status"] == "failed", "invalid Head fit status")
            ledger["failed_sessions"] += 1

    reader = report["reader"]
    duration = finite_nonnegative(reader["measured_call_seconds"], "Reader calls")
    require(
        type(reader["actual_attempts"]) is int
        and type(reader["cache_hits"]) is int
        and reader["actual_attempts"] >= reader["actual_successes"] >= 0,
        "Reader counter inventory missing or invalid",
    )
    index = report["index_costs"]
    require(isinstance(index, list), "index cost inventory absent")
    index_seconds, index_bytes = 0.0, 0
    for i, entry in enumerate(index):
        index_seconds += finite_nonnegative(entry["seconds"], f"index {i}")
        index_bytes += finite_nonnegative(entry["file_bytes"], f"index bytes {i}")
    cold_seconds = {}
    for key, value in report["cold_load"].items():
        cold_seconds[key] = finite_nonnegative(value, "cold load " + key)
    peak_rss_kib = finite_nonnegative(report["process_peak_rss_kib"], "peak RSS")
    output_bytes = finite_nonnegative(
        report["retained_output_bytes_before_report"], "artifact bytes"
    )
    return dict(
        schema="hepta.stem-resource-accounting.v1",
        encoders=encoders,
        head_training=dict(heads),
        reader_actual_calls=reader["actual_attempts"],
        reader_cache_hits=reader["cache_hits"],
        measured_reader_execution_wall_seconds=duration,
        index_creation_measured_seconds=index_seconds,
        index_files_reported_bytes=index_bytes,
        cold_load_measured_seconds=cold_seconds,
        entire_experiment_peak_rss_kib=peak_rss_kib,
        output_files_reported_bytes_before_summary=output_bytes,
        backend_shared_reader_cannot_be_naively_assigned_to_single_arm=True,
        absent_cache_events_do_not_count_as_zero_compute=True,
        per_arm_serving_latency_unknown=True,
        per_arm_energy_and_dollar_tco_unknown=True,
        hardware_benefit_over_421m_replicas_proven=False,
        energy_savings_proven=False,
        production_accepted=False,
    )
