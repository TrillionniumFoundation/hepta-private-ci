#!/usr/bin/env python3
"""Publish a strict aggregate projection of a private, frozen audit stdout.

The executed audit source captured per-step training IDs. Its full stdout is
private. This derivative never exports those steps, IDs, parameter values,
ledger data, paths, or unrecognized nested fields. It does not rerun the audit.
"""
import argparse
import hashlib
import json
from pathlib import Path


def pick(obj, keys):
    return {key: obj[key] for key in keys if key in obj}


def scalar_pick(obj, keys):
    result = pick(obj, keys)
    assert all(value is None or type(value) in (str, bool, int, float)
               for value in result.values())
    return result


def strings(value):
    assert isinstance(value, list) and all(isinstance(x, str) for x in value)
    return value


def project(raw):
    a = json.loads(raw)
    assert a["status"] == "PASS_BOUND_CURRENT_SMALL_ADAPTER_STATIC_AUDIT"
    out = scalar_pick(a, [
        "schema", "status", "started_utc", "finished_utc", "finished_america_new_york",
        "read_only", "training_started", "model_forward_executed", "broker_queries_sent",
        "orders_sent", "services_changed", "base_weight_content_refreshed",
        "performance_qualified", "full_trader_to_hepta_neuron_semantic_mapping_verified",
        "atomic_cross_file_snapshot", "effective_service_config_match",
        "live_process_identity_stable", "source_sha256",
    ])
    out["public_projection"] = {
        "schema": "hepta.wsp.readonly_audit_public_projection.v1",
        "original_private_stdout_sha256": hashlib.sha256(raw).hexdigest(),
        "original_private_stdout_bytes": len(raw),
        "raw_stdout_published": False,
        "derivation": "Explicit field whitelist; per-step records and private row IDs omitted",
        "sanitizer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "new_remote_reads_or_model_calls": 0,
    }
    out["sources"] = {
        key: scalar_pick(a["sources"][key], ["bytes", "sha256", "observed_start_utc",
             "observed_end_utc", "same_descriptor_and_path_metadata_during_read"])
        for key in ["guardian_config", "original_config", "trainer_status_before",
                    "bound_job_configuration", "candidate_manifest", "adapter",
                    "trainer_status_after"]
    }
    out["adapter"] = scalar_pick(a["adapter"], ["all_finite",
        "data_layout_nonoverlapping_and_complete", "parameter_count", "tensor_count"])
    out["adapter"]["tensors"] = []
    allowed_names = {"model.act_head.2.A", "model.act_head.2.B", "model.scorer.1.A",
                     "model.scorer.1.B", "model.scorer.3.A", "model.scorer.3.B"}
    for tensor in a["adapter"]["tensors"]:
        assert tensor["name"] in allowed_names
        value = scalar_pick(tensor, ["name", "dtype", "parameters", "finite_parameters"])
        assert all(type(n) is int for n in tensor["shape"])
        value["shape"] = tensor["shape"]
        out["adapter"]["tensors"].append(value)
    out["candidate_binding"] = scalar_pick(a["candidate_binding"], ["candidate_id",
        "job_id", "manifest_adapter_hash_matches", "plan_file_exists",
        "registration_is_performance_result", "registration_state",
        "same_candidate_and_job_at_end", "training_state"])
    out["candidate_binding"]["created"] = scalar_pick(a["candidate_binding"]["created"],
        ["utc", "america_new_york"])
    t = a["trainer"]
    out["trainer"] = scalar_pick(t, ["at_ms", "blocking_deferred_training_candidates",
        "completed_candidates_without_forward_trial", "current_blockers_checked_at_ms",
        "deferred_training_candidates", "no_forward_trial_is_not_performance_rejection",
        "pending_evaluations", "schema", "state", "viable_pending_evaluations"])
    out["trainer"]["job_counts"] = scalar_pick(t["job_counts"], ["ADMITTED", "COMPLETED", "FAILED", "RUNNING"])
    out["trainer"]["source_time"] = scalar_pick(t["source_time"], ["utc", "america_new_york"])
    for key in ["current_blockers", "forward_registration_wait_reasons"]:
        out["trainer"][key] = strings(t[key])
    lineage = a["training_lineage"]
    out["training_lineage"] = scalar_pick(lineage, ["mode", "completed_jobs_are_cumulative_updates",
        "optimizer_reset_each_job", "optimizer_reset_between_epochs", "price_steps_exclude_auxiliary_action_steps"])
    out["training_lineage"]["episode_profile"] = scalar_pick(lineage["episode_profile"], [
        "batch_order", "batch_rows", "checkpoint_selection", "epochs", "max_optimizer_steps",
        "max_unique_rows", "measurement_scope", "optimizer_state", "schema"])
    out["training_lineage"]["auxiliary_action_phase"] = scalar_pick(lineage["auxiliary_action_phase"], [
        "encoder_parameters_updated", "epochs", "gradient_norm_cap", "loss_weight",
        "max_optimizer_steps", "max_pairs", "max_unique_rows", "optimizer",
        "price_parameters_updated", "repeated_presentations_are_new_independent_rows"])
    f = a["forward_preflight"]
    out["forward_preflight"] = scalar_pick(f, ["at_ms", "admit_new_worker", "minimum_available_bytes",
        "worker_launched", "worker_launch_authority", "trial_allocated"])
    out["forward_preflight"]["reasons"] = strings(f["reasons"])
    nested = {
        "full_memory_psi": ["avg10", "avg60"],
        "memory_bytes": ["MemAvailable", "MemTotal", "SwapFree", "SwapTotal"],
        "registration_stability": ["future_resource_capacity_reserved", "healthy_samples",
            "maximum_observation_gap_ms", "minimum_sample_interval_ms", "minimum_span_ms",
            "observed_span_ms", "profile", "ready", "required_samples", "reset_reason",
            "scope", "state_survives_restart"],
        "original_live_source_evidence": ["broker_queries_sent", "fresh_original_live_source_proven",
            "source_ttl_ms", "status"],
        "cached_probe_diagnostic": ["broker_queries_sent", "cached_probe_status_at_ms",
            "cached_probe_unusable", "cached_probe_usable", "fresh_original_live_source_proven",
            "live_quote_relabelled", "observed_source_state", "orders_sent", "schema"],
    }
    for key, fields in nested.items():
        out["forward_preflight"][key] = scalar_pick(f[key], fields)
    report = a["candidate_reported_training"]
    out["candidate_reported_training"] = {"scope": report["scope"]}
    nested = {
        "selected": ["status", "trainable_parameters", "changed_parameters", "effective_changed_coordinates",
            "wall_seconds", "max_gpu_allocated_bytes", "action_update_steps", "pretrained_base_unchanged",
            "pnl_reward_used", "automatic_cutover", "canonical_owner_activation_claimed", "broker_orders_sent"],
        "measurement": ["candidate_brier", "candidate_ce", "parent_brier", "parent_ce", "rows",
            "training_only", "unique_action_labels"],
        "resource_usage": ["gpu_peak_scope", "max_gpu_allocated_bytes", "max_gpu_reserved_bytes",
            "max_process_rss_bytes", "rss_and_gpu_bytes_are_not_additive", "scope"],
        "calibration": ["model_weight", "model_weight_max", "calibration_is_train_only",
            "future_value_proven", "additional_independent_training_rows"],
        "calibration_measurement": ["exact_prior_fallback", "held_out", "training_only", "future_value_proven"],
    }
    for key, fields in nested.items():
        out["candidate_reported_training"][key] = scalar_pick(report[key], fields)
    resources = a["resources"]
    out["resources"] = scalar_pick(resources, ["observed_utc", "logical_cpu_count"])
    assert len(resources["loadavg"]) == 3 and all(type(x) is float for x in resources["loadavg"])
    out["resources"]["loadavg"] = resources["loadavg"]
    out["resources"]["memory_kib"] = scalar_pick(resources["memory_kib"], ["MemAvailable", "MemTotal", "SwapFree", "SwapTotal"])
    out["resources"]["pressure"] = scalar_pick(resources["pressure"], ["memory", "cpu", "io"])
    out["services"] = {}
    for unit in ["heptatrader-laya-trainer.service", "heptatrader-laya-evaluator.service", "heptatrader-execution.service"]:
        service = a["services"][unit]
        out["services"][unit] = {
            "observed_utc": service["observed_utc"],
            "properties": scalar_pick(service["properties"], ["ActiveState", "SubState", "MemoryCurrent",
                "MemoryPeak", "MemoryHigh", "MemoryMax", "CPUQuotaPerSecUSec", "TasksCurrent", "NRestarts"]),
        }
    for key in ["live_trainer_binding_before", "live_trainer_binding_after"]:
        out[key] = scalar_pick(a[key], ["observed_utc", "config_argument_matches", "process_start_and_argument_commitment_sha256"])
    out["cost"] = scalar_pick(a["cost"], ["cpu_seconds", "max_rss_kib_linux", "wall_seconds"])
    encoded = json.dumps(out, indent=2, sort_keys=True, allow_nan=False) + "\n"
    for forbidden in ["training_row_ids", "gradient_digest", '"steps"', "/home/", "/Users/", "account_id", "order_id"]:
        assert forbidden not in encoded, forbidden
    return encoded


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-stdout", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.private_stdout.read_bytes()
    assert len(raw) <= 262144
    result = project(raw)
    with args.public_output.open("x") as stream:
        stream.write(result)
    print(json.dumps({"status": "PUBLIC_PROJECTION_WRITTEN", "bytes": len(result.encode()),
        "sha256": hashlib.sha256(result.encode()).hexdigest(), "private_stdout_sha256": hashlib.sha256(raw).hexdigest()}))
