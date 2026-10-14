#!/usr/bin/env python3
"""Read-only, fail-closed A-F evidence conformance. Never issues authority."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "hepta.cell-meta-execution.af.v1"
ARMS = {
    "A": ("no_change", "frozen_head", "learning_head"),
    "B": ("unsplit", "shared_head", "child_heads"),
    "C": ("fixed_graph", "learned_router", "adaptive_depth"),
    "D": ("no_adaptation", "fixed_rule", "learned_rule"),
}
CONTRASTS = {
    "A": {"learning_head": ("no_change", "frozen_head")},
    "B": {"child_heads": ("unsplit", "shared_head")},
    "C": {"learned_router": ("fixed_graph",), "adaptive_depth": ("fixed_graph",)},
    "D": {"learned_rule": ("no_adaptation", "fixed_rule")},
}
SCALES = (64, 256, 1024, 4096)
DEPLOYMENTS = ("in_process", "shared_worker", "per_cell_process")
LOADS = ("fixed_active", "vary_active")
ROUTES = ("full_codex_agent", "app_server_provider", "direct_effect")
CASES = ("allowed", "denied")
PHASES = ("artifact_cas", "state_migration", "child_bootstrap", "cns_cutover", "supervisor_fence")
CRASH_CASES = ("before_effect", "during_cutover", "after_cutover")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class InvalidEvidence(ValueError):
    """The supplied data is incomplete or internally inconsistent."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise InvalidEvidence(reason)


def record(obj: Any, name: str) -> dict[str, Any]:
    require(type(obj) is dict, f"{name}: object required")
    return obj


def sequence(obj: Any, name: str) -> list[Any]:
    require(type(obj) is list, f"{name}: array required")
    return obj


def field(obj: dict[str, Any], key: str, name: str) -> Any:
    require(key in obj, f"{name}: missing {key}")
    return obj[key]


def digest(value: Any, name: str, *, git: bool = False) -> str:
    require(type(value) is str and (HEX40 if git else HEX64).fullmatch(value) is not None,
            f"{name}: exact lowercase {'Git SHA' if git else 'SHA256'} required")
    require(set(value) != {"0"}, f"{name}: empty digest sentinel")
    return value


def identity(value: Any, name: str) -> str:
    require(type(value) is str and 2 <= len(value) <= 128 and value.strip() == value,
            f"{name}: bounded nonblank identity required")
    return value


def number(value: Any, name: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        finite = type(value) in (float, int) and math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite, f"{name}: finite number required")
    require(value >= minimum and (maximum is None or value <= maximum), f"{name}: out of bounds")
    return float(value)


def count(value: Any, name: str, *, positive: bool = False) -> int:
    require(type(value) is int and (0 < value if positive else 0 <= value) and value <= (1 << 64) - 1,
            f"{name}: exact nonnegative u64 required")
    return value


def timestamp(value: Any, name: str) -> datetime:
    require(type(value) is str and value.endswith("Z"), f"{name}: UTC timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidEvidence(f"{name}: malformed timestamp") from exc
    require(result.utcoffset().total_seconds() == 0, f"{name}: UTC offset required")
    return result


def exact_membership(items: list[Any], expected: set[Any], name: str) -> dict[Any, Any]:
    """Accept no missing, duplicate, or unregistered arms (not even extra successes)."""
    found: dict[Any, Any] = {}
    for key, entry in items:
        require(key in expected, f"{name}: unregistered {key}")
        require(key not in found, f"{name}: duplicate {key}")
        found[key] = entry
    require(set(found) == expected, f"{name}: missing {sorted(expected - set(found))}")
    return found


def common(input_data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, tuple[datetime, datetime]]]:
    require(input_data.get("schema") == SCHEMA, "unrecognized evidence schema")
    meta = record(field(input_data, "candidate", "root"), "candidate")
    digest(field(meta, "source_sha", "candidate"), "source_sha", git=True)
    digest(field(meta, "source_tree", "candidate"), "source_tree", git=True)
    for name in ("objective_sha256", "no_change_sha256", "budget_sha256", "source_dataset_sha256"):
        digest(field(meta, name, "candidate"), name)
    ids = [identity(field(meta, name, "candidate"), name) for name in
           ("generator_id", "outcome_observer_id", "evaluator_id", "selector_id", "executor_id")]
    require(len(set(ids)) == len(ids), "generator / observer / evaluator / selector / executor must differ")
    slices = sequence(field(meta, "protected_slices", "candidate"), "protected_slices")
    require(len(slices) >= 1 and len(slices) == len(set(slices)),
            "protected_slices: nonempty unique protected slices required")
    for label in slices:
        identity(label, "protected slice")
    snapshots = sequence(field(meta, "independent_snapshots", "candidate"), "independent_snapshots")
    require(len(snapshots) >= 3 and len(set(snapshots)) == len(snapshots),
            "independent snapshots: at least three distinct evidence snapshots required")
    for snapshot in snapshots:
        digest(snapshot, "independent snapshot")
    families = sequence(field(meta, "train_task_families", "candidate"), "train_task_families")
    require(len(families) >= 1 and len(families) == len(set(families)),
            "train task families must be a frozen unique inventory")
    for family in families:
        identity(family, "train task family")
    cutoff = timestamp(field(meta, "train_cutoff", "candidate"), "train_cutoff")
    frozen = timestamp(field(meta, "frozen_at", "candidate"), "frozen_at")
    require(cutoff <= frozen, "baseline must be frozen after train cutoff")
    raw = record(field(meta, "future_windows", "candidate"), "future_windows")
    require(set(raw) == {"future_1", "future_2"}, "exactly two named future windows required")
    windows: dict[str, tuple[datetime, datetime]] = {}
    for name in ("future_1", "future_2"):
        w = record(raw[name], name)
        start = timestamp(field(w, "start", name), name + ".start")
        end = timestamp(field(w, "end", name), name + ".end")
        require(start < end, f"{name}: invalid window")
        windows[name] = (start, end)
    require(frozen < windows["future_1"][0] and windows["future_1"][1] <= windows["future_2"][0],
            "future-window chronology/independence violated")
    return meta, windows


def validate_study(letter: str, study: Any, meta: dict[str, Any],
                   windows: dict[str, tuple[datetime, datetime]]) -> dict[str, Any]:
    obj = record(study, letter)
    digest(field(obj, "budget_sha256", letter), letter + ".budget_sha256")
    require(obj["budget_sha256"] == meta["budget_sha256"], f"{letter}: unfair budget profile")
    digest(field(obj, "objective_sha256", letter), letter + ".objective_sha256")
    require(obj["objective_sha256"] == meta["objective_sha256"], f"{letter}: objective mismatch")
    alpha = number(field(obj, "interval_alpha", letter), letter + ".interval_alpha")
    contrasts = sum(len(controls) for controls in CONTRASTS[letter].values())
    require(0 < alpha <= 0.05 / (2 * contrasts),
            f"{letter}: missing conservative two-window multiple-testing allocation")
    records = sequence(field(obj, "records", letter), f"{letter}.records")
    parsed = exact_membership(
        [((record(r, letter + ".row").get("arm"), r.get("window")), r) for r in records],
        {(arm, window) for arm in ARMS[letter] for window in windows}, letter)
    task_sets: dict[str, set[str]] = {k: set() for k in windows}
    frozen_bundles: dict[str, set[str]] = {arm: set() for arm in ARMS[letter]}
    d_families: dict[str, set[tuple[str, ...]]] = {k: set() for k in windows}
    c_graphs: set[str] = set()
    c_policies: dict[str, set[str]] = {arm: set() for arm in ARMS["C"]}
    result: dict[tuple[str, str], dict[str, float]] = {}
    for (arm, window), r in parsed.items():
        name = f"{letter}/{arm}/{window}"
        input_sha = digest(field(r, "task_set_sha256", name), name + ".task_set_sha256")
        task_sets[window].add(input_sha)
        if letter == "D":
            heldout = sequence(field(r, "heldout_task_families", name), name + ".heldout_task_families")
            require(heldout and len(set(heldout)) == len(heldout), f"{name}: missing unique heldout families")
            for family in heldout:
                identity(family, name + ".heldout_family")
            require(not set(heldout).intersection(meta["train_task_families"]),
                    f"{name}: unseen-task-family train/test overlap")
            d_families[window].add(tuple(sorted(heldout)))
        if letter == "C":
            c_graphs.add(digest(field(r, "fixed_circuit_graph_sha256", name),
                                name + ".fixed_circuit_graph_sha256"))
            c_policies[arm].add(digest(field(r, "routing_policy_sha256", name),
                                       name + ".routing_policy_sha256"))
            digest(field(r, "actual_route_trace_sha256", name), name + ".actual_route_trace_sha256")
            count(field(r, "sequential_cell_depth", name), name + ".sequential_cell_depth", positive=True)
        digest(field(r, "prediction_sha256", name), name + ".prediction_sha256")
        digest(field(r, "outcome_receipt_sha256", name), name + ".outcome_receipt_sha256")
        digest(field(r, "evaluation_receipt_sha256", name), name + ".evaluation_receipt_sha256")
        bundle = digest(field(r, "model_bundle_sha256", name), name + ".model_bundle_sha256")
        frozen_bundles[arm].add(bundle)
        bundle_frozen_at = timestamp(field(r, "model_bundle_frozen_at", name),
                                     name + ".model_bundle_frozen_at")
        require(bundle_frozen_at <= timestamp(meta["frozen_at"], "candidate.frozen_at"),
                f"{name}: candidate model was not frozen before future evaluation")
        count(field(r, "independent_episodes", name), name + ".independent_episodes", positive=True)
        ess = number(field(r, "effective_sample_size", name), name + ".effective_sample_size", minimum=1)
        require(ess <= r["independent_episodes"] and ess >= 400
                and ess >= 0.1 * r["independent_episodes"],
                f"{name}: independent ESS/support gate not met")
        pred = timestamp(field(r, "predictions_committed_at", name), name + ".predictions_committed_at")
        observed = timestamp(field(r, "outcomes_finalized_at", name), name + ".outcomes_finalized_at")
        require(windows[window][0] <= pred <= windows[window][1] and pred < observed,
                f"{name}: post-label or out-of-window prediction")
        v = record(field(r, "metrics", name), name + ".metrics")
        slices = record(field(v, "protected_slice_degradation", name), name + ".protected_slice_degradation")
        require(set(slices) == set(meta["protected_slices"]),
                f"{name}: missing or unregistered protected slices")
        per_slice_max = max(number(value, name + "/slice/" + key, maximum=1)
                            for key, value in slices.items())
        result[(arm, window)] = {
            "utility_lcb": number(field(v, "net_utility_lcb", name), name + ".net_utility_lcb", minimum=-1e12),
            "utility_ucb": number(field(v, "net_utility_ucb", name), name + ".net_utility_ucb", minimum=-1e12),
            "brier": number(field(v, "brier", name), name + ".brier", maximum=1),
            "ece": number(field(v, "ece", name), name + ".ece", maximum=1),
            "ood": number(field(v, "ood_false_accept", name), name + ".ood_false_accept", maximum=1),
            "negative_transfer": number(field(v, "negative_transfer_rate", name), name + ".negative_transfer_rate", maximum=1),
            "old_drop": number(field(v, "old_task_degradation", name), name + ".old_task_degradation", maximum=1),
            "worst_slice_drop": per_slice_max,
        }
        require(result[(arm, window)]["utility_lcb"] <= result[(arm, window)]["utility_ucb"],
                f"{name}: inverted utility interval")
        count(field(v, "real_model_invocations", name), name + ".real_model_invocations", positive=True)
        count(field(v, "training_bytes", name), name + ".training_bytes")
        count(field(v, "inference_bytes", name), name + ".inference_bytes")
    require(all(len(s) == 1 for s in task_sets.values()), f"{letter}: unpaired future task set")
    require(task_sets["future_1"] != task_sets["future_2"], f"{letter}: reused future task set")
    require(all(len(bundles) == 1 for bundles in frozen_bundles.values()),
            f"{letter}: candidate model bundle changed across future windows")
    if letter == "D":
        require(all(len(families) == 1 for families in d_families.values()),
                "D: heldout task-family distribution drift between paired arms")
        require(set(next(iter(d_families["future_1"]))).isdisjoint(
                next(iter(d_families["future_2"]))),
                "D: future task families reused between independent test windows")
    if letter == "C":
        require(len(c_graphs) == 1, "C: changed graph confounds routing/depth learning")
        require(all(len(policies) == 1 for policies in c_policies.values()),
                "C: routing policy changed between future windows")
        require(len({next(iter(policies)) for policies in c_policies.values()}) == 3,
                "C: fixed and learned routing/depth policies indistinguishable")
    passing: list[str] = []
    for proposed, comparators in CONTRASTS[letter].items():
        if all(
            result[(proposed, window)]["utility_lcb"] > result[(control, window)]["utility_ucb"]
            and result[(proposed, window)]["old_drop"] <= 0.02
            and result[(proposed, window)]["worst_slice_drop"] <= 0.02
            and all(result[(proposed, window)][metric] <= result[(control, window)][metric]
                    for metric in ("brier", "ece", "ood", "negative_transfer"))
            for window in windows for control in comparators
        ):
            passing.append(proposed)
    return {"status": "shadow_structurally_complete", "provisional_gain_arms": passing,
            "not_independent_qualification": True}


def validate_resources(value: Any, meta: dict[str, Any]) -> dict[str, Any]:
    obj = record(value, "E")
    host = identity(field(obj, "host_id", "E"), "E.host_id")
    device_profile = digest(field(obj, "device_profile_sha256", "E"), "E.device_profile_sha256")
    digest(field(obj, "runtime_profile_sha256", "E"), "E.runtime_profile_sha256")
    entries = sequence(field(obj, "runs", "E"), "E.runs")
    expected = {(mode, scale, profile) for mode in DEPLOYMENTS for scale in SCALES for profile in LOADS}
    runs = exact_membership(
        [((record(r, "E.row").get("mode"), r.get("logical_cells"), r.get("load_profile")), r)
         for r in entries], expected, "E")
    shared: dict[tuple[int, str], set[tuple[str, int, int]]] = {}
    variable_by_scale: dict[int, set[int]] = {s: set() for s in SCALES}
    active: dict[str, set[int]] = {p: set() for p in LOADS}
    varied: set[int] = set()
    summary: dict[str, dict[str, float]] = {}
    for (mode, scale, profile), r in runs.items():
        name = f"E/{mode}/{scale}/{profile}"
        require(identity(field(r, "host_id", name), name + ".host_id") == host, f"{name}: host drift")
        require(r.get("runtime_profile_sha256") == obj["runtime_profile_sha256"], f"{name}: runtime drift")
        require(digest(field(r, "device_profile_sha256", name),
                       name + ".device_profile_sha256") == device_profile,
                f"{name}: device profile drift")
        trace = digest(field(r, "attempt_trace_sha256", name), name + ".attempt_trace_sha256")
        digest(field(r, "terminal_receipt_sha256", name), name + ".terminal_receipt_sha256")
        concurrency = count(field(r, "active_concurrency", name), name + ".active_concurrency", positive=True)
        require(concurrency <= scale, f"{name}: concurrency exceeds cell count")
        attempts = count(field(r, "attempted", name), name + ".attempted", positive=True)
        completed = count(field(r, "completed", name), name + ".completed")
        failed = count(field(r, "failed", name), name + ".failed")
        rejected = count(field(r, "rejected", name), name + ".rejected")
        require(attempts == completed + failed + rejected, f"{name}: terminal accounting mismatch")
        calls = count(field(r, "backend_calls", name), name + ".backend_calls")
        batch = count(field(r, "native_batch_requests", name), name + ".native_batch_requests")
        require(batch <= completed and batch <= calls * 256, f"{name}: impossible batch accounting")
        if completed:
            require(calls > 0, f"{name}: completed execution without backend call")
        for key in ("rss_peak_bytes", "gpu_peak_bytes", "network_bytes", "fsync_count", "replayed_effects"):
            count(field(r, key, name), name + "." + key)
        require(r["rss_peak_bytes"] > 0 and r["replayed_effects"] == 0, f"{name}: invalid RSS or duplicate effect")
        for key in ("p50_ms", "p95_ms", "p99_ms", "cpu_seconds", "elapsed_seconds",
                    "queue_p99_ms", "lock_wait_ms", "cas_p99_ms", "signature_p99_ms",
                    "cns_p99_ms", "recovery_ms"):
            number(field(r, key, name), name + "." + key)
        require(r["elapsed_seconds"] > 0 and r["p50_ms"] <= r["p95_ms"] <= r["p99_ms"],
                f"{name}: invalid elapsed time or percentiles")
        require(r.get("real_worker_executed") is True and r.get("crash_recovery_tested") is True,
                f"{name}: source-only fixture is not a host measurement")
        shared.setdefault((scale, profile), set()).add((trace, concurrency, attempts))
        active[profile].add(concurrency)
        if profile == "vary_active":
            varied.add(concurrency)
            variable_by_scale[scale].add(concurrency)
        summary[name] = {"rps": completed / r["elapsed_seconds"], "p99_ms": r["p99_ms"],
                         "rss_bytes": r["rss_peak_bytes"], "network_bytes": r["network_bytes"]}
    require(all(len(rows) == 1 for rows in shared.values()), "E: unmatched source trace, requests, or concurrency")
    require(len(active["fixed_active"]) == 1, "E: fixed-active load varies with Cell scale")
    require(len(varied) > 1 and min(varied) >= next(iter(active["fixed_active"])),
            "E: varying-concurrency experiment is not independently varied")
    require(all(len(variable_by_scale[scale]) == 1 for scale in SCALES),
            "E: same Cell scale measured at different concurrency")
    sequence_values = [next(iter(variable_by_scale[scale])) for scale in SCALES]
    require(all(x < y for x, y in zip(sequence_values, sequence_values[1:])),
            "E: variable active concurrency must increase independently with scale")
    return {"status": "host_measurements_structurally_complete", "run_count": len(runs),
            "observed_summary": summary, "host_authenticity_unverified": True}


def validate_codex(value: Any, resource_value: Any) -> dict[str, Any]:
    obj = record(value, "F")
    resource_value = record(resource_value, "F.shared_E_resources")
    digest(field(obj, "task_suite_sha256", "F"), "F.task_suite_sha256")
    same_device = digest(field(obj, "device_profile_sha256", "F"), "F.device_profile_sha256")
    require(same_device == resource_value.get("device_profile_sha256"),
            "F: device profile does not match E")
    tasks = sequence(field(obj, "task_ids", "F"), "F.task_ids")
    require(len(tasks) >= 2 and len(set(tasks)) == len(tasks), "F: need two distinct registered task classes")
    for task in tasks:
        identity(task, "F.task_id")
    require("host_id" in resource_value and obj.get("host_id") == resource_value["host_id"],
            "F: different host from E")
    runs = sequence(field(obj, "runs", "F"), "F.runs")
    expected = {(route, task, case) for route in ROUTES for task in tasks for case in CASES}
    parsed = exact_membership(
        [((record(r, "F.row").get("route"), r.get("task_id"), r.get("case")), r)
         for r in runs], expected, "F")
    peers: dict[tuple[str, str], set[tuple[str, str]]] = {}
    successful: dict[str, int] = {route: 0 for route in ROUTES}
    for (route, task, case), r in parsed.items():
        name = f"F/{route}/{task}/{case}"
        trace = digest(field(r, "task_input_sha256", name), name + ".task_input_sha256")
        policy = digest(field(r, "policy_sha256", name), name + ".policy_sha256")
        digest(field(r, "terminal_observation_sha256", name), name + ".terminal_observation_sha256")
        digest(field(r, "sandbox_sha256", name), name + ".sandbox_sha256")
        peers.setdefault((task, case), set()).add((trace, policy))
        require(r.get("host_id") == obj["host_id"], f"{name}: host drift")
        require(digest(field(r, "device_profile_sha256", name),
                       name + ".device_profile_sha256") == same_device,
                f"{name}: device profile drift")
        require(type(r.get("authorized")) is bool and
                type(r.get("external_effect_observed")) is bool,
                f"{name}: malformed authorization/effect flags")
        for key in ("tool_attempts", "model_calls", "token_count", "rss_peak_bytes"):
            count(field(r, key, name), name + "." + key)
        for key in ("cpu_seconds", "elapsed_seconds", "task_quality", "total_cost"):
            number(field(r, key, name), name + "." + key,
                   maximum=1 if key == "task_quality" else None)
        require(r["elapsed_seconds"] > 0 and r["rss_peak_bytes"] > 0,
                f"{name}: missing real resource measurements")
        require(r.get("real_invocation_observed") is True, f"{name}: synthetic tool call")
        if route == "direct_effect":
            require(r["model_calls"] == 0 and r["token_count"] == 0,
                    f"{name}: direct execution must not conceal an Agent/model call")
        if case == "denied":
            require(r.get("status") == "rejected" and r.get("authorized") is False
                    and r.get("external_effect_observed") is False
                    and r.get("effect_owner_receipt_sha256") is None,
                    f"{name}: denied action leaked an effect")
        else:
            require(r.get("status") in ("succeeded", "failed", "indeterminate"),
                    f"{name}: unrecognized allowed-case terminality")
            if r["status"] == "succeeded":
                require(r.get("authorized") is True and r.get("external_effect_observed") is True,
                        f"{name}: unobserved effect presented as success")
                digest(field(r, "effect_owner_receipt_sha256", name), name + ".effect_owner_receipt_sha256")
                successful[route] += 1
            if r["external_effect_observed"]:
                require(r["authorized"] is True,
                        f"{name}: unauthorized external effect observed")
                digest(field(r, "effect_owner_receipt_sha256", name), name + ".effect_owner_receipt_sha256")
            else:
                require(r.get("effect_owner_receipt_sha256") is None,
                        f"{name}: owner receipt without observed effect")
    require(all(len(x) == 1 for x in peers.values()), "F: unmatched task input or policy among routes")
    return {"status": "codex_path_comparison_structurally_complete", "run_count": len(parsed),
            "observed_successes": successful, "effect_authority_unverified": True}


def validate_split(value: Any, meta: dict[str, Any]) -> dict[str, Any]:
    obj = record(value, "split_safety")
    require(obj.get("no_change_sha256") == meta["no_change_sha256"],
            "split: original frozen no-change baseline mismatch")
    digest(field(obj, "split_plan_sha256", "split"), "split_plan_sha256")
    effects = exact_membership(
        [(record(v, "split.phase").get("phase"), v) for v in
         sequence(field(obj, "effects", "split"), "split.effects")], set(PHASES), "split.effects")
    signers: set[str] = set()
    for phase, entry in effects.items():
        signer = identity(field(entry, "original_owner_id", phase), phase + ".original_owner_id")
        require(signer not in (meta["generator_id"], meta["selector_id"]), f"{phase}: not independent owner")
        signers.add(signer)
        require(entry.get("terminal") == "committed" and entry.get("generation_fenced") is True,
                f"{phase}: no committed fenced original-owner effect")
        for name in ("signed_receipt_sha256", "signed_readback_sha256", "independent_witness_sha256"):
            digest(field(entry, name, phase), phase + "." + name)
    require(len(signers) >= 4, "split: insufficient distinct original effect owners")
    restart = exact_membership(
        [(record(v, "split.crash").get("case"), v) for v in
         sequence(field(obj, "restarts", "split"), "split.restarts")], set(CRASH_CASES), "split.restarts")
    ledger = record(field(obj, "coordinator_ledger", "split"), "split.coordinator_ledger")
    require(identity(field(ledger, "coordinator_id", "split.ledger"), "split.ledger.coordinator_id")
            != meta["generator_id"], "split: generator cannot own commit ledger")
    for label in ("prepared_intent_sha256", "committed_receipt_sha256",
                  "synced_prefix_sha256", "recovered_frontier_sha256"):
        digest(field(ledger, label, "split.ledger"), "split.ledger." + label)
    require(ledger.get("single_writer_fenced") is True, "split: durable ledger owner fence missing")
    for name, r in restart.items():
        require(r.get("no_duplicate_effect") is True and r.get("readback_reconciled") is True,
                f"split/{name}: incomplete crash recovery")
        digest(field(r, "observer_receipt_sha256", name), name + ".observer_receipt_sha256")
    require(obj.get("independent_final_use") is True and obj.get("selector_current_after_last_readback") is True,
            "split: missing independently checked final-use/selector")
    return {"status": "split_recovery_structurally_complete", "original_effect_owners": len(signers),
            "signatures_and_remote_custody_unverified": True}


def verify(input_data: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema": SCHEMA + ".report", "status": "blocked", "authority_posture": "DENY_ALL",
        "physical_split_permitted": False, "production_selection_permitted": False,
        "model_promotion_permitted": False, "merge_or_release_permitted": False,
        "gates": {}, "limitations": [
            "JSON digest fields are declarations, not cryptographic signature verification",
            "No target-host or actual model is run by this tool",
            "Any provisional gain requires independent outcome, NDU and Selector acceptance",
            "Source/test success and reference host measurements never mint Final-use authority",
        ],
    }
    try:
        root = record(input_data, "root")
        meta, windows = common(root)
    except (InvalidEvidence, KeyError, TypeError, OverflowError) as exc:
        out["gates"]["identity"] = {"status": "blocked", "reason": str(exc)}
        return out
    out["gates"]["identity"] = {"status": "structurally_complete", "signature_verified": False}
    for key in ARMS:
        try:
            studies = record(root.get("studies"), "studies")
            result = validate_study(key, field(studies, key, "studies"), meta, windows)
        except (InvalidEvidence, KeyError, TypeError) as exc:
            result = {"status": "blocked", "reason": str(exc)}
        out["gates"][key] = result
    for key, fn in (
        ("E", lambda: validate_resources(root.get("resources"), meta)),
        ("F", lambda: validate_codex(root.get("codex"), root.get("resources"))),
        ("split_safety", lambda: validate_split(root.get("split_safety"), meta)),
    ):
        try:
            result = fn()
        except (InvalidEvidence, KeyError, TypeError, ValueError) as exc:
            result = {"status": "blocked", "reason": str(exc)}
        out["gates"][key] = result
    if all(item.get("status") != "blocked" for item in out["gates"].values()):
        out["status"] = "shadow_structural_review_only"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="external observation bundle JSON (never a fixture receipt)")
    parser.add_argument("--out", type=Path, help="write a read-only audit report")
    args = parser.parse_args(argv)
    try:
        report = verify(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        report = {"schema": SCHEMA + ".report", "status": "blocked",
                  "authority_posture": "DENY_ALL", "error": str(exc),
                  "physical_split_permitted": False, "production_selection_permitted": False,
                  "model_promotion_permitted": False, "merge_or_release_permitted": False}
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["status"] == "shadow_structural_review_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
