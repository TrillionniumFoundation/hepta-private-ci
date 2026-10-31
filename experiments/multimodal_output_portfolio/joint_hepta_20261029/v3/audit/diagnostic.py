"""Independently bind paired diagnostic files and critic-only checkpoints."""

from collections import defaultdict
import math

import numpy as np
import torch

from .core import ce, decode, groups, read, sha, source, tensor_digest, trajectory


def restore_npz(path):
    """Recover the declared state tree from flat, non-pickle numeric NPZ data."""
    flat = np.load(path, allow_pickle=False)
    state = {}
    core = {}
    for key in flat.files:
        parts = key.split("/")[1:]
        array = flat[key]
        value = array.item() if array.ndim == 0 else torch.from_numpy(array.copy())
        if parts[0] == "core":
            core.setdefault(int(parts[1]), {})[parts[2]] = value
        elif len(parts) == 1:
            state[parts[0]] = value
        else:
            raise ValueError("Unknown retained state-tree path")
    if core:
        state["core"] = [core[index] for index in range(len(core))]
    return state


def run(audit, v3, selected):
    root = v3 / "evidence/diagnostics_frozen_20261030"
    protocol, summary = read(root/"STUDY_PROTOCOL.json"), read(root/"STUDY_SUMMARY.json")
    payload = torch.load(selected, map_location="cpu", weights_only=True)
    model_hash = tensor_digest(payload["state_dict"])
    audit.check(protocol["checkpoint_sha256"] == sha(selected) and protocol["model_sha256"] == model_hash,
                "diagnostic_final_checkpoint_binding", root)
    audit.sources(protocol["source_sha256"], v3)
    files = sorted(root.glob("*/source-*/prefix-*/*/DIAGNOSTICS.json"))
    expected_groups = len(protocol["namespaces"]) * protocol["sources_per_role"] * len(protocol["prefixes"]) * len(protocol["continuations"])
    audit.check(len(files) == expected_groups == summary["completed_groups"], "diagnostic_group_completeness", root)
    all_rows, failures = [], 0
    for path in files:
        result, prefix = read(path), read(path.with_name("PREFIX.json"))
        role = path.relative_to(root).parts[0]
        namespace, identity, input_hash, _ = source(result["source_id"])
        audit.check(namespace == protocol["namespaces"][role] and 0 <= identity < protocol["sources_per_role"],
                    "diagnostic_source_role", path)
        audit.check(result["model_sha256"] == model_hash and result["input_sha256"] == input_hash,
                    "diagnostic_model_input_binding", path)
        audit.check(sha(path.with_name("PREFIX_STATE.npz")) == prefix["state_payload_sha256"] and
                    sha(path.with_name("PUBLIC_INPUT.npz")) == prefix["public_payload_sha256"], "diagnostic_prefix_payload_sha", path)
        state = restore_npz(path.with_name("PREFIX_STATE.npz"))
        frozen = tensor_digest({"state": state, "budget": prefix["budget"], "prefix_cost": prefix["prefix_cost"]})
        audit.check(frozen == prefix["frozen_prefix_sha256"], "independent_prefix_state_identity", path)
        audit.check(tensor_digest(restore_npz(path.with_name("PUBLIC_INPUT.npz"))) == input_hash,
                    "independent_prefix_input_identity", path)
        seen, arms, randomness = set(), defaultdict(list), defaultdict(set)
        for row in result["rows"]:
            key = (row["draw"], row["arm"])
            audit.check(key not in seen, "unique_diagnostic_arm_draw", path); seen.add(key)
            branch = path.parent / f"draw-{row['draw']:04d}" / row["arm"]
            item = trajectory(audit, branch/"TRAJECTORY.json", "diagnostic."+role, model_hash)
            audit.check(read(branch/"PAIRED_OUTCOME.json") == row, "paired_outcome_record_identity", branch)
            audit.check(row["frozen_prefix_sha256"] == frozen, "same_conditioning_prefix", branch)
            expected_seed = result["seed"] + 7919 * row["draw"]
            tape = {"actor_rng": torch.Generator().manual_seed(expected_seed).get_state(),
                    "emission_rng": torch.Generator().manual_seed(expected_seed ^ 0x5EED1234).get_state()}
            audit.check(row["future_randomness_sha256"] == tensor_digest(tape), "independent_named_future_rng", branch)
            randomness[row["draw"]].add(row["future_randomness_sha256"])
            audit.near(row["complete_cost"], item["sealed_cost"], "diagnostic_sealed_cost", branch)
            audit.near(row["complete_return"], item["sealed_return"], "diagnostic_sealed_return", branch)
            audit.near(row["utility"], item["utility"], "diagnostic_delivered_utility", branch)
            audit.near(row["prefix_cost"], prefix["prefix_cost"], "diagnostic_same_sunk_cost", branch)
            audit.near(row["suffix_cost"], item["sealed_cost"]-prefix["prefix_cost"], "diagnostic_suffix_cost", branch)
            audit.near(row["suffix_return"], row["utility"]-row["suffix_cost"], "diagnostic_suffix_return", branch)
            audit.check(row["failure"] == item["failure"], "diagnostic_failure_retained", branch)
            failures += int(item["failure"] is not None)
            if item["failure"] is None:
                receipt = read(branch/"READBACK_SCORE.json")
                audit.check(receipt == row["readback"] and sha(branch/"READBACK.npz") == receipt["payload_sha256"],
                            "diagnostic_readback_receipt_payload", branch)
                actual = {k: torch.from_numpy(v) for k, v in decode(branch/"outputs").items()}
                retained = restore_npz(branch/"READBACK.npz")
                audit.check(all(torch.equal(actual[k], retained[k]) for k in actual), "diagnostic_readback_actual_bytes", branch)
                audit.check(tensor_digest(actual) == receipt["readback_sha256"], "diagnostic_readback_tensor_identity", branch)
            if row["critic_fit_available"]:
                audit.near(row["critic_fit_suffix_return"], item["utility"]-(item["sealed_cost"]-row["critic_fit_origin_cost"]),
                           "critic_target_actual_suffix", branch)
            arms[row["arm"]].append(row); all_rows.append(row)
        for draw, hashes in randomness.items():
            audit.check(len(hashes) == 1, "paired_future_randomness", path)
        required = {"shared", "image", "audio", "video", "text", "verify", "stop", "verify_twice"} - set(result["skipped"])
        audit.check(set(seen) == {(draw, arm) for draw in range(protocol["draws"]) for arm in required},
                    "diagnostic_all_legal_interventions_retained", path)
        for arm, rows in arms.items():
            report = result["summary"]["arms"][arm]
            observed = ce([r["suffix_return"] for r in rows])
            predicted = ce([-r["predicted_suffix_log_moment"]/2 for r in rows])
            audit.near(report["critic"]["observed_conditional_ce_plugin"], observed, "diagnostic_conditional_ce", path)
            audit.near(report["critic"]["predicted_ce_from_mean_moment"], predicted, "diagnostic_prediction_moment_ce", path)
            audit.near(report["paired_vs_stop"]["ce_delta"], ce([r["complete_return"] for r in rows])-
                       ce([r["complete_return"] for r in arms["stop"]]), "diagnostic_difference_of_population_ce", path)
    audit.check(len(all_rows) == summary["actual_continuations"], "diagnostic_continuation_count", root)
    calibrated = torch.load(root/"MODEL_CALIBRATED.pt", map_location="cpu", weights_only=True)
    audit.check(sha(root/"MODEL_CALIBRATED.pt") == summary["calibrated_checkpoint_sha256"], "calibrated_checkpoint_identity", root)
    original_groups, calibrated_groups = groups(payload["state_dict"]), groups(calibrated["state_dict"])
    for group in ("generator", "actor"):
        audit.check(original_groups[group] == calibrated_groups[group], "critic_fit_preserved_"+group, root)
    fit = read(root/"critic_fit/FIT_VALIDATION.json")
    audit.check(fit["model_after_sha256"] == tensor_digest(calibrated["state_dict"]), "critic_fitted_state_identity", root)
    audit.check(sha(root/"critic_fit/CRITIC_STATE.pt") == fit["critic_checkpoint_sha256"], "critic_only_file_identity", root)
    fit_state = torch.load(root/"critic_fit/CRITIC_STATE.pt", map_location="cpu", weights_only=True)
    audit.check(all(torch.equal(value, calibrated["state_dict"][name]) for name, value in fit_state.items()),
                "critic_only_weights_match_full_checkpoint", root)
    fit_protocol = fit["protocol"]
    audit.check(not set(fit_protocol["training_sources"]) & set(fit_protocol["validation_sources"]), "critic_fit_original_source_disjoint", root)
    audit.check(not fit["validation_used_for_selection"] and not fit["policy_improvement_established"], "critic_fit_claim_boundary", root)
    return {"groups": len(files), "actual_trajectories": len(all_rows), "failures_retained": failures,
            "checkpoint_sha256": sha(selected), "critic_only_changes_verified": True,
            "raw_summary_sha256": sha(root/"STUDY_SUMMARY.json")}
