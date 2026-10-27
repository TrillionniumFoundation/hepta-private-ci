"""Cost-only aggregation of completed study and verification receipts.

Never reads primary deployment rows or efficacy/statistical fields. Only resource
aggregates are used from RESULT.summaries. Wall intervals can overlap; the ledger
does not estimate FLOPs or money.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEEDS = (17, 29, 43)
NONADDITIVE = {"fixed_refinements_per_forward_example"}


def counters(records):
    result = defaultdict(int)
    for record in records:
        for key, value in record.items():
            if type(value) is int and key not in NONADDITIVE:
                result[key] += value
    return dict(sorted(result.items()))


def build(workspace):
    sources = {}
    def identity(relative, fields):
        path = workspace/relative
        raw = path.read_bytes()
        sources[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "used_fields": fields}
        return raw
    def load(relative, fields):
        if "/eval/" in relative or relative.endswith((".jsonl", ".jsonl.gz")):
            raise ValueError("This ledger cannot read deployment rows")
        return json.loads(identity(relative, fields))
    def source(relative):
        identity(relative, "frozen implementation of recorded work counts; no execution")

    prefix = "bridge_repo/experiments/multimodal_output_portfolio/field_bridge_v2_20261027/"
    p = load(prefix+"PILOT_PROTOCOL.json", "candidate recipes, panel sizes, batch size, checkpoint frequency")
    source(prefix+"pilot.py")
    source(prefix+"learning.py")
    source(prefix+"field_bank.py")
    source(prefix+"directional_bank.py")
    source(prefix+"primary_training.py")
    source(prefix+"primary_runtime.py")
    primary = load(prefix+"PRIMARY_PROTOCOL.json", "runtime grid, data sizes and logical refinement charge")
    pilot = load("bridge_v2_pilot/PILOT_RESULT.json", "completed candidate recipe/history counts, gradient_examples, wall_ns; no outcome ranking used")
    panel = lambda name: (len(p[name]["conditions"]), p[name]["pairs"]*len(p[name]["conditions"]))
    response_calls, response_n = panel("response_panel")
    clean_calls, clean_n = panel("clean_probe")
    selection_calls, selection_n = panel("selection_panel")
    pilot_records = []
    for seed in SEEDS:
        row = pilot["results"][str(seed)]
        records = row["candidates"]
        assert len(records) == len(p["candidates"]) and not any(r.get("failed") for r in records)
        gradients = sum(r["recipe"]["steps"] for r in records)
        assert sum(r["gradient_examples"] for r in records) == gradients*p["batch_size"]
        for r in records:
            assert len(r["history"])-1 == (r["recipe"]["steps"]+p["checkpoint_frequency"]-1)//p["checkpoint_frequency"]
        hard_calls = 5*selection_calls+response_calls+clean_calls
        hard_examples = 5*selection_n+response_n+clean_n
        hard_calls += sum(len(r["history"])*response_calls+selection_calls+clean_calls for r in records)
        hard_examples += sum(len(r["history"])*response_n+selection_n+clean_n for r in records)
        pilot_records.append({"seed": seed, "completed_candidates": len(records), "fixed_action": row["action"],
            "gradient_forward_calls": gradients, "gradient_examples": gradients*p["batch_size"],
            "backward_calls": gradients, "optimizer_step_invocations": gradients,
            "frozen_teacher_forward_calls": gradients, "frozen_teacher_examples": gradients*p["batch_size"],
            "hard_value_forward_calls": hard_calls, "hard_value_examples": hard_examples,
            "reward_observer_digit_calls": 2*hard_calls, "reward_observer_digit_examples": 2*hard_examples})
    pilot_cost = {"classification": "shared actuator and fixed-action search; counted once", "per_seed": pilot_records,
        "totals": counters([{k:v for k,v in r.items() if k not in ("seed", "fixed_action")} for r in pilot_records]),
        "wall_ns": pilot["wall_ns"], "derivation": "Recorded gradients; hard-forward counts reconstructed from baseline five-action selection, initial/checkpoint response panels and final selection/clean panels in frozen pilot.py"}

    phase_costs, h7_resources = {}, {}
    for phase in ("fit", "audit"):
        rows = []
        for seed in SEEDS:
            relative = f"bridge_v2_bank/{phase}-{seed}/BANK.json"
            bank = load(relative, "resources, wall_ns, fixed_action, record count only")
            complete = load(f"bridge_v2_bank/{phase}-{seed}/COMPLETE.json", "bank_sha256, rows, wall_ns")
            assert complete["bank_sha256"] == sources[relative]["sha256"] and complete["rows"] == len(bank["records"]) == 288
            assert complete["wall_ns"] == bank["wall_ns"] and bank["phase"] == phase
            h7_resources[(phase, seed)] = bank["resources"]
            rows.append({"seed": seed, "snapshots": complete["rows"], "resources": bank["resources"], "wall_ns": bank["wall_ns"]})
        aggregate = counters([r["resources"] for r in rows])
        phase_costs[phase] = {"classification": "shared fitting search" if phase == "fit" else "frozen-predictor development qualification; separate from fitting",
            "per_seed": rows, "snapshots": sum(r["snapshots"] for r in rows), "complete_four_action_branch_sets": 864,
            "individual_branch_hard_values": 864*4*response_n, "resources": aggregate,
            "optimizer_step_invocations": 864*3*8, "gradient_calls_in_zero_update_branches": 864*8,
            "predictor_calls": 0 if phase == "fit" else 864*3,
            "sum_profile_wall_ns": sum(r["wall_ns"] for r in rows), "count_once_across_controller_modes": True}
    predictor = load("bridge_v2_bank/PREDICTOR_FREEZE.json", "fit_candidate_evaluations, wall_ns, controller file identities")
    assert predictor["fit_candidate_evaluations"] == 3*3*(20*8+1) == 1449
    predictor_cost = {"controllers": 9, "model_candidates_per_controller": 20, "whole_trajectory_folds": 8,
        "cross_validation_fits": 1440, "selected_final_fits": 9, "total_fits": 1449,
        "wall_ns": predictor["wall_ns"], "count_once": True,
        "interpretation": "One fit means one ridge/kernel estimator fit, not equal FLOPs or equal parameter count across model families"}

    directional_rows = []
    for seed in SEEDS:
        relative = f"bridge_v2_directional/fit-{seed}/BANK.json"
        bank = load(relative, "resources, wall_ns, measurement counts and inherited source/hash bindings; no outcomes used")
        complete = load(f"bridge_v2_directional/fit-{seed}/COMPLETE.json", "bank_sha256, rows, wall_ns")
        assert complete["bank_sha256"] == sources[relative]["sha256"] and complete["rows"] == 288
        resources = bank["resources"]
        assert resources["inherited_parent_fitting_resources"] == h7_resources[("fit", seed)]
        directional_rows.append({"seed": seed,
            "base_replay_and_H25_resources": {k:v for k,v in resources.items() if k not in
                ("inherited_parent_fitting_resources", "additional_directional_observation_work", "accounting")},
            "additional_directional_work": resources["additional_directional_observation_work"],
            "optimizer_step_invocations": 8*sum(row["trajectory_action"] != 0 for row in bank["records"]),
            "wall_ns": bank["wall_ns"]})
    inactive = load("bridge_v2_directional/NOT_ACTIVATED.json", "activation decision booleans; inherited metadata not counted again")
    integrity = load("bridge_v2_directional/FIT_INTEGRITY_AUDIT.json", "extra work totals, predictors_fitted, fresh audit count")
    assert not inactive["real_directional_predictor_fit_performed"] and not inactive["fresh_directional_audit_performed"]
    assert integrity["predictors_fitted"] == integrity["fresh_audit_trajectories"] == 0
    directional_base = counters([r["base_replay_and_H25_resources"] for r in directional_rows])
    directional_extra = counters([r["additional_directional_work"] for r in directional_rows])
    assert directional_extra == integrity["additional_directional_measurement_work"]
    directional = {"classification": "incurred conditional-development preparation; inactive in the primary treatment",
        "per_seed": directional_rows, "enriched_fit_snapshots": 864, "base_replay_and_H25_resources": directional_base,
        "additional_directional_work": directional_extra,
        "optimizer_step_invocations": sum(r["optimizer_step_invocations"] for r in directional_rows),
        "real_predictor_fits": 0, "fresh_audit_trajectories": 0, "new_branch_labels": 0,
        "primary_treatment": False, "sum_profile_wall_ns": sum(r["wall_ns"] for r in directional_rows),
        "deduplication": "Original H7 fit labels and inherited_parent_fitting_resources reference shared work above; not charged twice"}

    training = load("bridge_v2_primary/TRAINING_COMPLETE.json", "completed checkpoint/resources and source/hash bindings only")
    ordinary_rows, final_rows = [], []
    for seed in SEEDS:
        info = training["seeds"][str(seed)]
        complete = load(f"bridge_v2_primary/training/{seed}/COMPLETE.json", "resources, checkpoint and completion bindings")
        assert complete == info
        assert complete["shared_fit_resources_count_once"] == h7_resources[("fit", seed)]
        assert complete["qualification_audit_resources_count_once"] == h7_resources[("audit", seed)]
        ordinary = load(f"bridge_v2_primary/training/{seed}/ordinary.json", "reuse declarations and logical_path_resources_already_in_shared_bank")
        receipt = info["profiles"]["ordinary"]
        assert receipt["actual_new_gradient_calls"] == receipt["actual_new_boundary_probe_calls"] == 0
        ordinary_rows.append({"seed": seed, "actual_new_gradient_calls": 0, "actual_new_boundary_probe_calls": 0,
            "logical_reused_path_resources_not_added": ordinary["logical_path_resources_already_in_shared_bank"],
            "new_selection_resources": info["ordinary_selection_new_resources"]})
        for mode in ("field", "generic", "richer"):
            receipt = info["profiles"][mode]
            trace_path = "bridge_v2_primary/"+receipt["trace"]
            trace = load(trace_path, "resources and wall_ns only; no decision values")
            assert sources[trace_path]["sha256"] == receipt["trace_sha256"] and trace["resources"] == receipt["resources"]
            final_rows.append({"seed": seed, "mode": mode, "resources": receipt["resources"], "wall_ns": receipt["wall_ns"]})
    final_resources = counters([r["resources"] for r in final_rows])
    final_training = {"ordinary": {"per_seed": ordinary_rows, "actual_new_gradient_calls": 0,
        "actual_new_boundary_probe_calls": 0, "new_selection_resources": counters([r["new_selection_resources"] for r in ordinary_rows]),
        "logical_reused_path_resources_not_added": counters([r["logical_reused_path_resources_not_added"] for r in ordinary_rows]),
        "deduplication": "Three selected ordinary endpoints and their 864 logical gradient calls already exist in shared H7 fit; new selection rescoring is charged separately"},
        "new_field_generic_richer": {"per_seed_mode": final_rows, "resources": final_resources,
            "by_mode": {mode: counters([r["resources"] for r in final_rows if r["mode"] == mode]) for mode in ("field", "generic", "richer")},
            "sum_profile_wall_ns": sum(r["wall_ns"] for r in final_rows),
            "zero_update_calls": final_resources["gradient_forward_calls"]-final_resources["optimizer_steps"],
            "zero_update_cost": "All 288 calls per path compute model/teacher forwards and clipped gradients even when multiplier zero holds both weights and momentum"}}

    runtime_rows = []
    for seed in SEEDS:
        for profile in ("frozen", "ordinary", "field"):
            stem = f"bridge_v2_primary/runtime/{seed}-{profile}/"
            ids = load(stem+"BANK_IDENTITIES.json", "train_resources, development_resources and fixed data/count metadata")
            fit = load(stem+"READOUTS.json", "heads_fitted, native ticks, label counts, feature construction and wall/cpu times only")
            generation = counters(ids["train_resources"]+ids["development_resources"])
            runtime_rows.append({"seed": seed, "profile": profile, "generation_resources": generation,
                "heads_fitted": fit["heads_fitted"], "native_fitting_ticks": fit["original_sparse_tick_calls"],
                "hard_action_label_rows": fit["shared_train_development_label_rows"], "fit_wall_ns": fit["fit_wall_ns"],
                "fit_python_cpu_ns": fit["fit_python_cpu_ns"], "bank_and_fit_wall_ns": fit["total_bank_and_fit_wall_ns"]})
    runtime = {"classification": "nine shared checkpoint-specific runtime banks; same banks fit native and history",
        "per_seed_profile": runtime_rows, "generation_resources": counters([r["generation_resources"] for r in runtime_rows]),
        "heads_fitted": sum(r["heads_fitted"] for r in runtime_rows),
        "native_fitting_ticks": sum(r["native_fitting_ticks"] for r in runtime_rows),
        "hard_action_label_rows": sum(r["hard_action_label_rows"] for r in runtime_rows),
        "sum_bank_and_fit_wall_ns": sum(r["bank_and_fit_wall_ns"] for r in runtime_rows),
        "grid": "2 representations x2 families x4 transforms x3 ridges x3 seeds x3 checkpoints=432; no fixed fallback or refit",
        "deduplication": "Each public bank and native feature extraction is generated once per profile/transform and reused across fitted families/penalties"}
    assert runtime["heads_fitted"] == 432 and runtime["native_fitting_ticks"] == 221184

    replay_records = []
    for name, call_key, example_key in (
        ("bridge_v2_replay_fit/REPLAY_AUDIT.json", "actual_replay_gradient_calls", "gradient_examples"),
        ("bridge_v2_replay_audit/REPLAY_AUDIT.json", "actual_replay_gradient_calls", "gradient_examples"),
        ("bridge_v2_review/primary-training-audit/PRIMARY_TRAINING_REPLAY.json", "actual_gradient_calls", "actual_gradient_examples")):
        receipt = load(name, "actual replay gradient calls/examples and wall time")
        replay_records.append({"source": name, "actual_gradient_calls": receipt[call_key],
            "actual_gradient_examples": receipt[example_key], "wall_ns": receipt["wall_ns"],
            "other_network_work": "Not fully metered in this replay receipt; not assumed zero"})
    train_audit = load("bridge_v2_review/primary-training-audit/PRIMARY_TRAINING_AUDIT.json", "auditor model_inference_calls and reconstructed prediction rows; verified study counts not added again")
    runtime_audit = load("bridge_v2_review/PRIMARY_RUNTIME_AUDIT.json", "auditor-specific work fields and counts only")
    verification = {"classification": "additional verification work; not independent scientific replicates or treatment benefit",
        "gradient_replays": replay_records,
        "known_replay_gradient_calls": sum(r["actual_gradient_calls"] for r in replay_records),
        "known_replay_gradient_examples": sum(r["actual_gradient_examples"] for r in replay_records),
        "training_arithmetic_audit": {"model_inference_calls": train_audit["model_inference_calls"],
            "predictor_reconstruction_calls": train_audit["independently_reconstructed_prediction_rows"],
            "do_not_double_count": "new_final_gradient_calls and selection calls in this audit describe original treatment work already counted above"},
        "runtime_audit": {"reward_observer_digit_examples": sum(r["auditor_reward_observer_digit_examples"] for r in runtime_audit["profiles"]),
            "native_replay_ticks": sum(r["auditor_native_replay_ticks"] for r in runtime_audit["profiles"]),
            "independent_least_squares_solves": runtime_audit["total_heads_checked"],
            "sum_profile_wall_ns": sum(r["audit_wall_ns"] for r in runtime_audit["profiles"])},
        "unmetered_additional_verification": "Other synthetic contracts, derivative checks, arithmetic-only passes, native engineering benchmarks and development diagnoses are outside this receipt-level subtotal; they are not zero-cost"}

    interrupted = load("bridge_v2_primary/IO_RECOVERY_REGISTRATION.json", "partial_attempt_counts and recovery/deduplication declarations only")
    extra_rows = sum(r["complete_rows"] for r in interrupted["partial_attempt_counts"].values())
    assert extra_rows == 11808 and not interrupted["independent_replicate"]
    interruption = {"classification": "additional interrupted physical execution, outside final scientific sample count",
        "completed_extra_outcome_rows_lower_bound": extra_rows, "per_seed": interrupted["partial_attempt_counts"],
        "unflushed_or_incomplete_additional_work": None, "unknown_work_is_zero": False,
        "independent_replicate": False, "cost_bound": "At least 11,808 completed extra rows plus unknown unflushed/incomplete work",
        "models_predictors_thresholds_refitted": interrupted["predictors_models_or_thresholds_refit_or_changed"]}

    # Access only cost/provenance fields in completion and RESULT. Do not open any
    # outcome rows, media archives, observer scores, contrasts or efficacy gates.
    complete_path = "bridge_v2_primary/EVALUATION_COMPLETE.json"
    completion = load(complete_path, "rows, per-seed wall/media counts, frozen source identities and completion bindings")
    result_path = "bridge_v2_primary/RESULT.json"
    result = load(result_path, "summaries[*].rows and summaries[*].descriptive_resources only; no efficacy fields")
    freeze_path = "bridge_v2_primary/PRETEST_FREEZE.json"
    freeze = load(freeze_path, "source_files and source/protocol identities only")
    assert sources[result_path]["sha256"] == completion["result_sha256"]
    assert sources[freeze_path]["sha256"] == completion["pretest_freeze_sha256"]
    assert sources["bridge_v2_primary/IO_RECOVERY_REGISTRATION.json"]["sha256"] == completion["recovery_registration_sha256"]
    assert completion["original_attempt_counts"] == interrupted["partial_attempt_counts"]
    assert sum(row["rows"] for row in result["summaries"].values()) == completion["rows"] == 84480
    assert len(result["summaries"]) == 22
    reviewed_prefix = "bridge_repo/experiments/multimodal_output_portfolio/field_bridge_v2_20261027_review/"
    source(reviewed_prefix+"primary_io_recovery.py")
    assert sources[reviewed_prefix+"primary_io_recovery.py"]["sha256"] == completion["recovery_source_sha256"]
    seed_costs = []
    for seed in SEEDS:
        row = completion["seeds"][str(seed)]
        assert row["rows"] == 28160 and row["source_models_unchanged"]
        assert row["source_files"] == freeze["source_files"] and len(row["source_files"]) == 35
        for key in ("pretest_freeze_sha256", "recovery_source_sha256", "registered_recovery_commit"):
            assert row[key] == completion[key]
        assert row["media"]["logical_files"] == 6*row["rows"]
        seed_costs.append({"seed": seed, "rows": row["rows"], "wall_ns": row["wall_ns"],
            "media": row["media"], "registered_pretest_commit": row["registered_pretest_commit"],
            "registered_recovery_commit": row["registered_recovery_commit"],
            "reported_output_files_sha256": row["files_sha256"]})
    for relative, expected in freeze["source_files"].items():
        full = "bridge_repo/experiments/multimodal_output_portfolio/"+relative
        identity(full, "current byte identity checked against 35-file pretest and evaluation source freeze")
        assert sources[full]["sha256"] == expected
    source("bridge_repo/experiments/multimodal_output_portfolio/v6/observer.py")
    terms, measured = defaultdict(list), defaultdict(int)
    for summary in result["summaries"].values():
        for key, stats in summary["descriptive_resources"].items():
            assert stats["rows_with_measurement"] == summary["rows"]
            terms[key].append(stats["mean"]*stats["rows_with_measurement"])
            measured[key] += stats["rows_with_measurement"]
    recorded, timers = {}, {}
    for key, values in sorted(terms.items()):
        value = math.fsum(values)
        assert measured[key] == completion["rows"] and abs(value-round(value)) < 1e-3
        if key.endswith("_ns"):
            timers[key] = {"sum_of_recorded_intervals_ns": round(value),
                "weighted_mean_per_scientific_row_ns": value/measured[key],
                "rows_with_measurement": measured[key]}
        else:
            recorded[key] = round(value)
    assert recorded["native_tick_calls"] == 61440
    assert recorded["prepare_encoder_examples"] == recorded["finish_decoder_examples"] == completion["rows"]
    assert recorded["prepare_decoder_examples"] == 2*completion["rows"]
    assert recorded["finish_unchosen_continuations_executed"] == 0
    logical_files = sum(row["media"]["logical_files"] for row in seed_costs)
    unique_files = sum(row["media"]["unique_files"] for row in seed_costs)
    unique_bytes = sum(row["media"]["unique_payload_bytes"] for row in seed_costs)
    assert (logical_files, unique_files, unique_bytes) == (506880, 108793, 91662356)
    phase_totals = {key: recorded["prepare_"+key]+recorded["finish_"+key] for key in (
        "encoder_examples", "encoder_batches", "transition_examples", "transition_batches",
        "decoder_examples", "decoder_batches", "observer_digit_examples", "observer_batches",
        "png_reads", "png_writes", "utf8_reads", "utf8_writes", "target_accesses")}
    deployment = {"status": "completed and independently verified", "scientific_rows": completion["rows"],
        "disjoint_resource_summary_groups": len(result["summaries"]), "per_seed": seed_costs,
        "logical_media_references": logical_files, "unique_media_members": unique_files,
        "unique_media_payload_bytes": unique_bytes,
        "storage_deduplication": "Physical ZIP members only; all six logical file references per row still require actual output generation and readback",
        "recorded_resource_totals": recorded, "prepare_plus_finish_event_totals": phase_totals,
        "additional_postdecision_observer_work": {"digit_examples": 4*completion["rows"],
            "digit_batches": 4*recorded["finish_decoder_batches"], "separate_timing_available": False,
            "derivation": "Frozen deploy_batch calls observe_tensors for reward and audit after finish; each observer classifies left/right digits. This work is outside prepare/finish counters."},
        "observer_digit_examples_including_postdecision_scoring": phase_totals["observer_digit_examples"]+4*completion["rows"],
        "recorded_interval_aggregates": timers,
        "aggregation_rule": "For each resource sum group mean times rows_with_measurement over 22 disjoint split/arm groups; integer recovery tolerance 0.001. No global median or p95 inferred from group quantiles.",
        "timing_scope": "Per-phase timers overlap/nest and can run concurrently across seeds. Their totals are interval sums, not additive end-to-end elapsed time. Postdecision scoring and other bookkeeping may be outside phase timers.",
        "concurrent_seed_wall_ns_range": [min(row["wall_ns"] for row in seed_costs), max(row["wall_ns"] for row in seed_costs)],
        "global_elapsed_ns": None,
        "global_elapsed_interpretation": "The three seed jobs ran concurrently; duration-only metadata does not identify shared start/end elapsed time. Do not sum their approximately 313-second durations.",
        "source_files_verified_unchanged": 35,
        "primary_rows_or_media_opened_by_ledger": False}

    media_path = "bridge_v2_primary/INDEPENDENT_MEDIA_AUDIT.json"
    media = load(media_path, "passed, row/batch/media counts, actual auditor observer/native work, wall_ns, source/hash bindings only")
    assert media["passed"] and media["pretest_freeze_sha256"] == completion["pretest_freeze_sha256"]
    assert media["source_files"] == freeze["source_files"]
    assert media["rows"] == deployment["scientific_rows"] and media["native_replayed_ticks"] == 61440
    assert media["logical_media_files"] == logical_files and media["unique_media_entries"] == unique_files
    assert media["unique_payload_bytes"] == unique_bytes
    for seed in SEEDS:
        row = completion["seeds"][str(seed)]
        assert media["archive_sha256"][str(seed)] == row["files_sha256"]["media.zip"]
        path = f"bridge_v2_primary/{completion['evaluation_subdirectory']}/{seed}/COMPLETE.json"
        seed_done = load(path, "completion identity only; no deployment rows")
        assert seed_done == row and sources[path]["sha256"] == media["seed_completions_sha256"][str(seed)]
    for name, key in (("primary_media_audit.py", "audit_source_sha256"), ("primary_audit_support.py", "audit_support_sha256")):
        source(reviewed_prefix+name)
        assert sources[reviewed_prefix+name]["sha256"] == media[key]
    verification["deployment_media_audit"] = {key: media[key] for key in (
        "rows", "batches", "independently_rescored_rows", "observer_digit_examples", "native_replayed_ticks",
        "generator_forward_calls", "audit_wall_ns", "logical_media_files", "unique_media_entries", "unique_payload_bytes")}
    verification["deployment_media_audit"]["counting"] = "Extra observer/native execution; media entries/rows describe verified study coverage, not new generated samples or media"
    parity_path = "bridge_v2_primary/RECOVERY_PARITY_AUDIT.json"
    parity = load(parity_path, "passed, original complete row/native receipt counts and source bindings only; no raw records")
    source(reviewed_prefix+"primary_recovery_parity.py")
    assert sources[reviewed_prefix+"primary_recovery_parity.py"]["sha256"] == parity["script_sha256"]
    assert parity["passed"] and parity["evaluation_completion_sha256"] == sources[complete_path]["sha256"]
    assert parity["recovery_registration_sha256"] == completion["recovery_registration_sha256"]
    assert parity["original_complete_rows_reproduced"] == extra_rows and not parity["scientific_choices_changed"]
    partial_native = parity["original_complete_native_receipts_reproduced"]
    assert partial_native == 6560
    interruption.update({"preserved_complete_native_receipts": partial_native,
        "recorded_extra_native_ticks_lower_bound": 2*partial_native,
        "native_count_derivation": "Each preserved original native receipt contains the same two-tick episode path verified against recovered records; unflushed work remains unknown"})
    verification["recovery_parity"] = {"complete_partial_rows_compared": extra_rows,
        "native_receipts_compared": partial_native, "additional_model_forward_calls": 0,
        "additional_native_replay_ticks": 0,
        "scope": "Hash/JSON comparison of preserved repeated execution only; no model/native reexecution. Comparator work was not separately timed in its receipt."}

    gradient_total = pilot_cost["totals"]["gradient_forward_calls"]+sum(v["resources"]["candidate_gradient_forward_calls"] for v in phase_costs.values())
    gradient_total += directional_base["candidate_gradient_forward_calls"]+directional_extra["next_gradient_forward_calls"]+final_resources["gradient_forward_calls"]
    optimizer_total = pilot_cost["totals"]["optimizer_step_invocations"]+sum(v["optimizer_step_invocations"] for v in phase_costs.values())
    optimizer_total += directional["optimizer_step_invocations"]+final_resources["optimizer_steps"]
    ledger = {"schema": "hepta.field-bridge-v2.study-cost-ledger.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Completed V2 pilot, H7 fit/audit, predictor search, inactive D1 enrichment, final training, runtime fitting and recovered primary deployment; selected verification and interrupted-attempt lower bound",
        "primary_deployment_rows_read": False, "outcome_statistics_used": False,
        "pilot": pilot_cost, "H7_banks": phase_costs, "H7_predictor_fitting": predictor_cost,
        "inactive_D1": directional, "final_training": final_training, "runtime_fitting": runtime,
        "verification": verification, "interrupted_primary_attempt": interruption,
        "nonduplicated_predeployment_work": {"gradient_forward_backward_calls": gradient_total,
            "gradient_examples": gradient_total*p["batch_size"], "frozen_teacher_forward_calls": gradient_total,
            "frozen_teacher_examples": gradient_total*p["batch_size"], "optimizer_step_invocations": optimizer_total,
            "directional_probe_reverse_calls_additional_to_training_gradients": directional_extra["response_probe_reverse_calls"]+directional_extra["clean_probe_reverse_calls"],
            "predictor_model_fits": 1449, "runtime_ridge_head_fits": 432,
            "excludes": "verification, original V1/pretraining, unmetered development, interrupted and recovered primary deployment; these are separate, not zero"},
        "logical_tariff": {"utility_charge_per_refinement": primary["refinement_charge"],
            "stop_charge": .002, "nonstop_charge": .004,
            "definition": "Common first couple is charged once; a non-stop final continuation adds one charge. Final decoding still runs for stop.",
            "not_a_measure_of": ["latency", "FLOPs", "energy", "money"],
            "do_not_sum_as_financial_bill": True},
        "timing_interpretation": "Receipt wall intervals include host contention and may overlap across seeds or stages; their sums are not end-to-end elapsed time or latency advantages. Counts are calls/examples, not FLOPs.",
        "recovered_primary_deployment": deployment,
        "known_native_work": {"runtime_fitting_ticks": runtime["native_fitting_ticks"],
            "scientific_deployment_ticks": recorded["native_tick_calls"],
            "interrupted_extra_ticks_lower_bound": 2*partial_native,
            "study_ticks_lower_bound": runtime["native_fitting_ticks"]+recorded["native_tick_calls"]+2*partial_native,
            "additional_verification_ticks": verification["runtime_audit"]["native_replay_ticks"]+media["native_replayed_ticks"],
            "excludes": "Unflushed interrupted work, earlier V1/development/normalization and native engineering benchmarks; excluded work is not zero"},
        "sources": sources}
    identity(str(Path(__file__).resolve().relative_to(workspace)), "cost aggregation implementation")
    return ledger


def markdown(d):
    c = lambda x: f"{x:,}"
    p, h, q, z, t, r, v = d["pilot"], d["H7_banks"], d["H7_predictor_fitting"], d["inactive_D1"], d["final_training"], d["runtime_fitting"], d["verification"]
    deployment = d["recovered_primary_deployment"]
    events = deployment["prepare_plus_finish_event_totals"]
    native = d["known_native_work"]
    walls = deployment["concurrent_seed_wall_ns_range"]
    table = ["| Stage | Gradient forward/backward calls | Gradient examples | Other declared work |", "|---|---:|---:|---|"]
    table.append(f"| Shared pilot: 18 completed candidates | {c(p['totals']['gradient_forward_calls'])} | {c(p['totals']['gradient_examples'])} | {c(p['totals']['hard_value_examples'])} hard-value forward examples |")
    for phase in ("fit", "audit"):
        a = h[phase]
        table.append(f"| H7 {phase}: 864 complete branch sets | {c(a['resources']['candidate_gradient_forward_calls'])} | {c(a['resources']['candidate_gradient_examples'])} | {c(a['individual_branch_hard_values'])} individual branch labels |")
    table.append("| H7 predictor search | 0 | 0 | 1,440 CV fits +9 final fits =1,449 |");
    table.append(f"| Inactive D1 replay | {c(z['base_replay_and_H25_resources']['candidate_gradient_forward_calls'])} | {c(z['base_replay_and_H25_resources']['candidate_gradient_examples'])} | 864 inherited fitting states; no new branch labels |")
    table.append(f"| D1 extra next-gradient measurement | {c(z['additional_directional_work']['next_gradient_forward_calls'])} | {c(z['additional_directional_work']['next_gradient_forward_examples'])} | 2,592 additional probe reverse calls; no optimizer update from measurement |")
    table.append("| Ordinary final path reuse | 0 new | 0 new | 864 logical gradient calls already in H7 fit; 15,360 new selection-scoring examples |")
    a = t["new_field_generic_richer"]["resources"]
    table.append(f"| New field/generic/richer final training | {c(a['gradient_forward_calls'])} | {c(a['gradient_examples'])} | 9 paths; 324 predictor decisions |")
    table.append("| Runtime banks and readouts | 0 | 0 | 138,240 scored actions; 432 heads; 221,184 native ticks |")
    n = d["nonduplicated_predeployment_work"]
    lines = ["# V2 study cost ledger", "", "This ledger counts shared work once and retains the cost of inactive preparation and the interrupted primary attempt. It uses completed receipts only; it does not read primary deployment rows or use outcome statistics. The full machine-readable ledger includes every source path and SHA-256.", "", *table, "",
        f"The listed preparation and final-training stages execute **{c(n['gradient_forward_backward_calls'])} gradient computations on {c(n['gradient_examples'])} examples**, plus the same number of frozen-teacher calls/examples. D1 adds 2,592 probe reverse calls beyond these training-gradient computations. Actual optimizer-step invocations are recorded separately: {c(n['optimizer_step_invocations'])}. These totals exclude verification and deployment; they are not a claim about the entire session's compute.", "",
        "## Shared search and inactive preparation", "", "Pilot search is six recipes on each of three seeds. Its hard-forward count includes the five-action fixed-policy search, original response/clean panels, each candidate's initial and periodic response panels, and final selection/clean panels. The 18 candidate runs all completed. Hard-forward counts are derived from the frozen loop and completed history lengths; gradient examples are also recorded directly.", "",
        "H7 fitting and development qualification each execute 864 snapshots with four actual eight-step branches. Both phases are charged separately. The nine field/generic/richer predictors share fitting banks; the search is exactly 9×(20×8+1)=1,449 fits. It is not charged once per eventual experimental arm. A fit count does not imply equal arithmetic cost between a ridge and a kernel model.", "",
        "D1 was not activated: zero real directional predictor fits, zero fresh audit trajectories and zero primary D1 treatments. Its 6,912 chosen-path gradient calls, 864 additional next-gradient measurements, H25 probes and directional forward/reverse work nevertheless occurred and remain charged. Its inherited H7 labels and inherited-parent resource block are references, not a second H7 search.", "",
        "## Reused ordinary training versus newly executed paths", "", "The ordinary checkpoint is selected from four already completed constant-action H7 fitting trajectories and copied with its complete optimizer state. Its 864 logical gradient calls across three seeds are already included in H7 fitting. Newly executed ordinary selection scoring is 60 hard-forward calls /15,360 examples, with 30,720 reward-observer digit examples.", "",
        "Each field/generic/richer path still performs 288 gradient and teacher computations. A zero multiplier preserves weights and momentum but does not skip their forward/backward work. Across the nine final paths there are 2,592 gradient calls, while only 840 optimizer-step invocations occur. Their feature/probe and margin work is retained in the JSON; it is not hidden inside the gradient count.", "",
        "## Runtime fitting", "", "The nine checkpoint-specific banks are generated once and shared by native/history fitting. They execute 27,648 encoder examples, 138,240 transition examples, 193,536 decoder examples and 387,072 reward-observer digit examples. The 432 heads comprise two representations, two families, four transforms, three penalties, three seeds and three checkpoints. Native extraction executes 221,184 ticks and is reused across families/penalties. These counters describe offline train/development search, not selected deployment work.", "",
        "## Completed scientific deployment", "", f"The recovered, frozen evaluation contains **{c(deployment['scientific_rows'])} scientific rows** across eleven arms, three seeds, four test conditions and the declared retention condition. It generated and read back {c(deployment['logical_media_references'])} logical PNG/UTF-8 media references. Exact-byte deduplication retains {c(deployment['unique_media_members'])} physical ZIP members containing {c(deployment['unique_media_payload_bytes'])} payload bytes; it does not reduce logical generation work. Each seed contributes 28,160 rows.", "",
        "| Deployment event | Count |", "|---|---:|",
        f"| Encoder examples / batches | {c(events['encoder_examples'])} / {c(events['encoder_batches'])} |",
        f"| Transition examples / batches | {c(events['transition_examples'])} / {c(events['transition_batches'])} |",
        f"| Decoder examples / batches | {c(events['decoder_examples'])} / {c(events['decoder_batches'])} |",
        f"| Public preview observer digit examples | {c(events['observer_digit_examples'])} |",
        f"| Additional postdecision reward/audit digit examples | {c(deployment['additional_postdecision_observer_work']['digit_examples'])} |",
        f"| Total observer digit examples including final scoring | {c(deployment['observer_digit_examples_including_postdecision_scoring'])} |",
        f"| Actual native ticks | {c(deployment['recorded_resource_totals']['native_tick_calls'])} |",
        f"| PNG writes / reads | {c(events['png_writes'])} / {c(events['png_reads'])} |",
        f"| UTF-8 writes / reads | {c(events['utf8_writes'])} / {c(events['utf8_reads'])} |",
        "| Executed unchosen final continuations | 0 |", "",
        "Deployment event totals are recovered from resource means multiplied by the measured row count in each of 22 disjoint split/arm summaries. All integer sums reconcile within 0.001. Final observer scoring is outside the prepare/finish resource dictionaries: its additional count follows directly from two declared observers, each classifying the two delivered digits. It is explicitly separated from the recorded phase counts. No observer scores, efficacy statistics, primary outcome rows or media contents were read for this ledger.", "",
        f"The three seed jobs ran concurrently, with individual wall intervals from **{walls[0]/1e9:.3f} to {walls[1]/1e9:.3f} seconds**. Duration-only receipts do not identify a common start/end elapsed time. Their durations are not summed as elapsed. The JSON retains weighted resource intervals separately: prepare/finish, neural work, media I/O, decision work, native kernel and evidence storage. Nested or concurrent timers cannot be added as a single end-to-end latency, and no global median or p95 is inferred from group quantiles.", "",
        "## Verification and recovery overhead", "", f"Recorded H7 and final-training replays add {c(v['known_replay_gradient_calls'])} gradient calls /{c(v['known_replay_gradient_examples'])} examples. Runtime verification adds 276,480 reward-observer digit examples, 221,184 native replay ticks and 432 independent least-squares solves. The arithmetic training audit performs no model forward call; its reported 2,592 new gradient calls describe the already counted treatment, not extra auditing work.", "",
        "The independent deployment media audit adds **61,440 native replay ticks and 675,840 observer digit examples**, covering all 84,480 original scientific rows and all logical media references. Its 191.321-second wall interval is verification overhead. It performs zero generator forward calls, and its coverage does not create additional generated samples or unique media. Recovery parity additionally compares 11,808 repeated records and 6,560 native receipts without reexecuting the model or native kernel.", "",
        "The interrupted primary attempt produced **at least 11,808 complete extra outcome rows**: 5,824 for seed17, 3,296 for seed29 and 2,688 for seed43. Its 6,560 preserved native receipts establish **at least 13,120 additional native ticks**. Unflushed or incomplete work is unknown and is not set to zero. Recovered runs are the same registered execution, not a new independent replicate; partial outputs are excluded from the final scientific sample count but remain execution overhead.", "",
        f"Known native study work is therefore at least {c(native['study_ticks_lower_bound'])} ticks: 221,184 for runtime fitting, 61,440 for scientific deployment and 13,120 from the interrupted attempt. Independent runtime/deployment verification adds {c(native['additional_verification_ticks'])} ticks. Earlier development or engineering benchmarks are outside this subtotal.", "",
        "Other synthetic contracts, derivative checks, native engineering benchmarks, earlier development diagnoses and original V1/pretraining are not fully metered by this receipt set. The verification subtotal is therefore a documented lower bound, not a zero-cost declaration for omitted work.", "",
        "## Logical tariff and elapsed time", "", "The objective subtracts 0.002 for the common first refinement and another 0.002 for a non-stop final continuation. Thus stop carries a 0.002 logical charge and non-stop carries 0.004; final decoding still occurs for stop. This tariff is not measured latency, FLOPs, energy or money, and repeated scores must not be summed as a financial bill.", "",
        "Per-receipt wall and CPU times are preserved. Seeds and stages can overlap on the shared host, so sums of wall intervals are not end-to-end duration or evidence that one treatment is faster. No FLOPs or financial estimates are supplied.", "",
        "## Evidence", "", "[STUDY_COST_LEDGER.json](STUDY_COST_LEDGER.json) contains per-seed counters, deduplication rules and all input hashes. Principal inputs are the pilot result/protocol; six H7 BANK/COMPLETE pairs; PREDICTOR_FREEZE; three D1 BANK/COMPLETE pairs and NOT_ACTIVATED; final TRAINING_COMPLETE and path resources; nine runtime BANK_IDENTITIES/READOUTS pairs; verification receipts; and IO_RECOVERY_REGISTRATION. The completed append also binds EVALUATION_COMPLETE, RESULT resource fields, all three seed completion receipts, PRETEST_FREEZE, INDEPENDENT_MEDIA_AUDIT and RECOVERY_PARITY_AUDIT. The 35 frozen scientific source files match their pretest and completion identities. No frozen scientific file or archive was modified.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=HERE)
    parser.add_argument("--replace", action="store_true", help="Replace existing review ledger outputs after completed metadata reconciliation")
    args = parser.parse_args()
    ledger = build(args.workspace.resolve())
    mode = "w" if args.replace else "x"
    with (args.out/"STUDY_COST_LEDGER.json").open(mode) as stream:
        json.dump(ledger, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    with (args.out/"STUDY_COST_LEDGER.md").open(mode) as stream:
        stream.write(markdown(ledger))
    print(json.dumps({"nonduplicated_predeployment_work": ledger["nonduplicated_predeployment_work"],
                      "source_count": len(ledger["sources"]), "interrupted_rows_lower_bound": ledger["interrupted_primary_attempt"]["completed_extra_outcome_rows_lower_bound"],
                      "scientific_rows": ledger["recovered_primary_deployment"]["scientific_rows"],
                      "known_native_work": ledger["known_native_work"]}, indent=2))


if __name__ == "__main__":
    main()
