"""Posthoc V4 mechanism report; no new gate, fitting, policy selection, or endpoint inference.

Run only after the supervising task authorizes a completed run. The script
refuses incomplete endpoint inventories before opening training traces. It
never loads ENDPOINTS.npz or independent endpoint utility/media arrays.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

SEEDS = (17, 29, 43)
METHODS = ("ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", "raw_field",
           "origin_field", "origin_generic", "origin_richer", "origin_h7")
SCHEDULES = (14000, 14001, 14002, 14003)
INDICES = (0, 1, 2, 3, 12, 13, 14, 15, 24, 25, 26, 27, 28, 29)
PREFIX = "hepta.field-bridge.v4"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Inputs:
    def __init__(self):
        self.files = {}

    def bind(self, path, expected=None):
        path = Path(path).resolve()
        identity = digest(path)
        require(expected is None or identity == expected, "Changed input: " + str(path))
        self.files[str(path)] = {"sha256": identity, "bytes": path.stat().st_size}
        return path

    def json(self, path, expected=None):
        return json.loads(self.bind(path, expected).read_text())

    def trace(self, path, expected):
        with gzip.open(self.bind(path, expected), "rt") as stream:
            return [json.loads(line) for line in stream]

    def unchanged(self):
        return all(digest(path) == value["sha256"] for path, value in self.files.items())


def completed_run_headers(inputs, root, protocol, protocol_sha):
    """Completeness/access checks only; never require a successful scientific result."""
    require((root / "QUALIFICATION.json").is_file(), "A completed one-shot qualification is required")
    require(not (root / "QUALIFICATION_FAILED.json").exists(), "Qualification execution did not complete")
    for seed in SEEDS:
        directory = root / "evaluate" / str(seed)
        require((directory / "COMPLETE.json").is_file() and not (directory / "FAILED.json").exists(),
                "All endpoint outputs must complete before posthoc trace access")
    seal = inputs.json(root / "TRAINING_SEAL.json")
    require(seal["schema"] == PREFIX + ".training-seal.1" and seal["study_id"] == protocol["study_id"]
            and seal["paths"] == 108 and seal["scope"]["protocol_sha256"] == protocol_sha, "Incomplete training seal")
    for seed in SEEDS:
        record = inputs.json(root / "evaluate" / str(seed) / "COMPLETE.json")
        require(record["schema"] == PREFIX + ".evaluated-seed.1" and record["study_id"] == protocol["study_id"]
                and record["seed"] == seed and record["scope"]["protocol_sha256"] == protocol_sha
                and record["training_seal_sha256"] == digest(root / "TRAINING_SEAL.json"),
                "Endpoint header identity differs")
        expected = {f"{method}/schedule-{sid}" for method in METHODS for sid in SCHEDULES}
        require(set(record["paths"]) == expected, "Endpoint path inventory is incomplete")
        require(all((root / "evaluate" / str(seed) / name).is_file() for name in record["files"]),
                "An endpoint artifact is missing")
    # Hash the completed formal result without parsing its numeric results.
    inputs.bind(root / "QUALIFICATION.json")
    return seal


def number_summary(values):
    x = np.asarray(values, dtype=np.float64)
    require(x.size > 0 and np.isfinite(x).all(), "Nonfinite or empty mechanism observations")
    return {"count": int(x.size), "mean": float(x.mean()), "min": float(x.min()), "max": float(x.max()),
            "q10": float(np.quantile(x, .1)), "median": float(np.median(x)), "q90": float(np.quantile(x, .9))}


def normalized(values, head):
    z = (values - np.asarray(head["raw_mean"])) / np.asarray(head["raw_scale"])
    projected = z @ np.asarray(head["projection"])
    readout = (projected - np.asarray(head["projected_mean"])) / np.asarray(head["projected_scale"])
    require(np.isfinite(z).all() and np.isfinite(readout).all(), "Invalid frozen normalization")
    return z, readout


def coordinate_summary(raw, mapped, head, names):
    raw_z, raw_readout = normalized(raw, head)
    mapped_z, mapped_readout = normalized(mapped, head)
    coordinates = []
    for index, name in enumerate(names):
        coordinates.append({"index": index, "name": name, "translated": index in INDICES,
            "raw_mean_fit_scaled": float(raw_z[:, index].mean()),
            "mapped_mean_fit_scaled": float(mapped_z[:, index].mean()),
            "raw_max_abs_fit_scaled": float(np.abs(raw_z[:, index]).max()),
            "mapped_max_abs_fit_scaled": float(np.abs(mapped_z[:, index]).max()),
            "raw_count_abs_gt3": int((np.abs(raw_z[:, index]) > 3).sum()),
            "mapped_count_abs_gt3": int((np.abs(mapped_z[:, index]) > 3).sum())})
    return {"interpretation": "Descriptive fit-scale distances; neither normality tests nor new acceptance cutoffs",
        "coordinates": coordinates, "raw_h12_max_abs": float(np.abs(raw_z[:, :12]).max()),
        "mapped_h12_max_abs": float(np.abs(mapped_z[:, :12]).max()),
        "raw_calibrated_max_abs": float(np.abs(raw_z[:, INDICES]).max()),
        "mapped_calibrated_max_abs": float(np.abs(mapped_z[:, INDICES]).max()),
        "raw_direction_max_abs": float(np.abs(raw_z[:, 7:12]).max()),
        "mapped_direction_max_abs": float(np.abs(mapped_z[:, 7:12]).max()),
        "readout_dimension": head["dimension"], "raw_readout_max_abs": float(np.abs(raw_readout).max()),
        "mapped_readout_max_abs": float(np.abs(mapped_readout).max())}


def path_summary(done, rows, baseline):
    decisions, outcomes = rows[::2], rows[1::2]
    require(len(rows) == 12 and [row["step"] for row in decisions] == list(range(0, 288, 48))
            and all(row["kind"] == "decision_before_update" for row in decisions)
            and all(row["kind"] == "block_outcome" for row in outcomes), "Incomplete full-path trace")
    receipts = [row["receipt"] for row in outcomes]
    deltas = [row["guard_delta"] for row in receipts]
    recomputed = [float((np.asarray(row["guard_values"]) - baseline).mean()) for row in receipts]
    actions, accepted = [row["action_index"] for row in decisions], [row["accepted"] for row in receipts]
    require(done["final_step"] == 288 and len(actions) == 6, "Wrong complete-path budget")
    summary = {"schedule_id": done["schedule_id"], "policy_sha256": done["policy_sha256"],
        "actions": actions, "accepted": accepted, "guard_deltas": deltas,
        "guard_delta_reconstruction_max_abs_error": max(abs(a - b) for a, b in zip(deltas, recomputed, strict=True)),
        "guard_threshold_decision_disagreements": sum(bool(a) != (d >= 0.) for a, d in zip(accepted, deltas, strict=True)),
        "final_identity": done["final_identity"], "resources": done["resources"], "wall_ns": done["wall_ns"],
        "cpu_ns": done["cpu_ns"]}
    return summary, decisions, np.asarray([row["raw_state"] for row in decisions]), np.asarray([row["mapped_state"] for row in decisions])


def first_step(mask):
    return next((48 * index for index, value in enumerate(mask) if value), None)


def paired_mechanism(raw_path, origin_path, raw_rows, origin_rows, scale):
    actions_differ = [a != b for a, b in zip(raw_path["actions"], origin_path["actions"], strict=True)]
    same_state = [a["before"] == b["before"] for a, b in zip(raw_rows, origin_rows, strict=True)]
    guard_differ = [a != b for a, b in zip(raw_path["accepted"], origin_path["accepted"], strict=True)]
    distances = [float(np.linalg.norm((np.asarray(a["raw_state"]) - b["raw_state"]) / scale))
                 for a, b in zip(raw_rows, origin_rows, strict=True)]
    return {"schedule_id": raw_path["schedule_id"], "diagnostic_only": True,
        "raw_actions": raw_path["actions"], "origin_actions": origin_path["actions"],
        "action_disagreements": int(sum(actions_differ)), "first_action_disagreement_step": first_step(actions_differ),
        "same_model_optimizer_before_block": same_state,
        "same_state_action_disagreements": sum(a and s for a, s in zip(actions_differ, same_state, strict=True)),
        "first_before_state_divergence_step": first_step([not s for s in same_state]),
        "first_guard_outcome_difference_step": first_step(guard_differ),
        "raw_state_distance_in_common_fit_scale": distances,
        "final_parameters_equal": raw_path["final_identity"]["parameters"] == origin_path["final_identity"]["parameters"],
        "final_optimizer_equal": raw_path["final_identity"]["optimizer"] == origin_path["final_identity"]["optimizer"],
        "same_actions_but_different_final_identity": not any(actions_differ) and raw_path["final_identity"] != origin_path["final_identity"],
        "control_cpu_ns_origin_minus_raw": origin_path["resources"]["policy_control_cpu_ns"] - raw_path["resources"]["policy_control_cpu_ns"],
        "control_wall_ns_origin_minus_raw": origin_path["resources"]["policy_control_wall_ns"] - raw_path["resources"]["policy_control_wall_ns"],
        "interpretation": "After the first action/state divergence these are comparisons of different visited trajectories, not logged-state counterfactual values"}


def execute(root, old_root, protocol_path):
    started, inputs = time.perf_counter_ns(), Inputs()
    protocol = inputs.json(protocol_path)
    require(protocol["qualification"]["methods"] == list(METHODS) and protocol["qualification"]["schedule_ids"] == list(SCHEDULES),
            "Not the fixed V4 method/schedule scope")
    seal = completed_run_headers(inputs, root, protocol, digest(protocol_path))
    methods, paired, phase_costs = {}, {}, {}
    for seed in SEEDS:
        pinned = protocol["frozen_v3_learning_artifacts"][str(seed)][f"fit/{seed}/CONTROLLERS.json"]
        fitted = inputs.json(old_root / "fit" / str(seed) / "CONTROLLERS.json", pinned["sha256"])
        require(fitted["seed"] == seed, "Historical head seed mismatch")
        names = fitted["controllers"]["field"]["feature_names"]
        directory = root / "train" / str(seed)
        completed = inputs.json(directory / "COMPLETE.json", seal["files"][f"train/{seed}/COMPLETE.json"])
        baseline = np.asarray(completed["baseline_guard"]["values"], dtype=np.float64)
        phase = f"PHASE_RECEIPTS/train-{seed}.json"
        phase_costs[str(seed)] = inputs.json(root / phase, seal["files"][phase])
        seed_methods, decision_cache = {}, {}
        for method in METHODS:
            paths, raw_states, mapped_states, decision_cache[method] = [], [], [], []
            for sid in SCHEDULES:
                relative = f"train/{seed}/{method}/schedule-{sid}"
                folder = root / relative
                done = inputs.json(folder / "COMPLETE.json", seal["files"][relative + "/COMPLETE.json"])
                rows = inputs.trace(folder / "decisions-and-outcomes.jsonl.gz", seal["files"][relative + "/decisions-and-outcomes.jsonl.gz"])
                summary, decisions, raw, mapped = path_summary(done, rows, baseline)
                paths.append(summary); raw_states.extend(raw); mapped_states.extend(mapped); decision_cache[method].append(decisions)
            actions = [a for path in paths for a in path["actions"]]
            accepted = [a for path in paths for a in path["accepted"]]
            costs = {key: sum(path["resources"].get(key, 0) for path in paths) for key in set().union(*(p["resources"] for p in paths))}
            mode = "field" if method.startswith("ordinary_") or method == "raw_field" else method.removeprefix("origin_")
            head = fitted["controllers"][mode]
            seed_methods[method] = {"diagnostic_only": True, "paths": paths, "action_counts": np.bincount(actions, minlength=4).tolist(),
                "zero_action_fraction": actions.count(0) / len(actions), "accepted_blocks": sum(accepted),
                "rejected_blocks": len(accepted) - sum(accepted),
                "accepted_nonzero_microsteps": 48 * sum(a != 0 and ok for a, ok in zip(actions, accepted, strict=True)),
                "guard_delta": number_summary([d for path in paths for d in path["guard_deltas"]]),
                "coordinate_shift": coordinate_summary(np.asarray(raw_states), np.asarray(mapped_states), head, names),
                "normalizer_mode": mode, "field_normalizer_for_ordinary_is_descriptive_only": method.startswith("ordinary_"),
                "resources_sum": costs,
                "calibration": {"active_float64_values_per_path": 14, "active_payload_bytes_per_path": 112,
                    "captures": costs.get("panel_origin_captures", 0), "translation_calls": costs.get("panel_origin_translation_calls", 0),
                    "new_baseline_model_calls": 0,
                    "all_methods_also_compute_mapped_state_for_common_instrumentation": True,
                    "time_scope": "policy_control CPU/wall combines origin mapping, prediction, and first policy hashing; calibration alone is not separately identified",
                    "memory_scope": "112 bytes is the active 14-value payload, not total memory; full30/raw/mapped/policy metadata and arrays are additional"}}
        methods[str(seed)] = seed_methods
        scale = np.asarray(fitted["controllers"]["field"]["raw_scale"])
        paired[str(seed)] = [paired_mechanism(seed_methods["raw_field"]["paths"][i], seed_methods["origin_field"]["paths"][i],
            decision_cache["raw_field"][i], decision_cache["origin_field"][i], scale) for i in range(4)]
    require(inputs.unchanged(), "An input changed during posthoc analysis")
    return {"schema": PREFIX + ".posthoc-mechanism.1", "study_id": protocol["study_id"],
        "diagnostic_only": True, "new_scientific_gate": False, "new_policy_selection": False, "hypothesis_tests": [],
        "formal_comparison_family_unchanged": 6, "all_complete_paths": 108,
        "endpoint_numeric_arrays_or_media_read": False, "formal_numeric_fields_parsed": False, "formal_result_file_hash_only": True,
        "training_control_probe_guard_values_read": True, "new_model_calls": 0,
        "methods_by_seed": methods, "origin_field_vs_raw_field_paired_paths": paired,
        "complete_training_phase_costs": phase_costs,
        "phase_timing_scope_clarification": "Measured after argument parsing through postflight verification; interpreter startup, argument parsing and final cost-receipt write are excluded",
        "inputs_unchanged": True, "input_identities": inputs.files, "script_sha256": digest(__file__),
        "analysis_wall_ns": time.perf_counter_ns() - started}


def markdown(result):
    lines = ["# V4 训练机制诊断", "", "**Diagnostic only：不增加比较族、门槛、策略选择或新假设检验。**",
        "", "本报告使用已完成的 108 条训练轨迹。正式增益与 clean NI 由独立的六比较资格结果决定；这里没有读取独立 endpoint 数值或媒体。", "",
        "| seed | 方法 | 动作次数 [0,1,2,3] | 接受/拒绝块 | guard Δ均值 | raw→mapped 最大 H12 fit-scale |",
        "|---|---|---|---|---:|---:|"]
    for seed, methods in result["methods_by_seed"].items():
        for method, item in methods.items():
            c = item["coordinate_shift"]
            lines.append(f"| {seed} | {method} | {item['action_counts']} | {item['accepted_blocks']}/{item['rejected_blocks']} | "
                         f"{item['guard_delta']['mean']:.6f} | {c['raw_h12_max_abs']:.3f}→{c['mapped_h12_max_abs']:.3f} |")
    lines += ["", "fit-scale 是沿旧冻结归一化器的描述性距离，不是正态显著性或新的合格阈值。", "",
        "## 原点 H12 与原始 H12 的配对轨迹", "",
        "| seed | schedule | 动作分歧数 | 首次动作分歧步 | 首次模型/SGD状态分歧步 | 最终参数相同 |",
        "|---|---:|---:|---:|---:|---|"]
    for seed, paths in result["origin_field_vs_raw_field_paired_paths"].items():
        for p in paths:
            lines.append(f"| {seed} | {p['schedule_id']} | {p['action_disagreements']} | {p['first_action_disagreement_step']} | "
                         f"{p['first_before_state_divergence_step']} | {p['final_parameters_equal']} |")
    lines += ["", "动作分歧后的状态属于不同访问轨迹。动作改善、坐标回到 fit 原点或 guard 接受增加，均不能替代独立终点效应。",
        "", "## 费用口径", "", "每路径的活跃校准载荷为 14 个 float64（112 字节）。完整原始状态、mapped 状态和 policy 审计元数据另计；112 字节不表示总内存。",
        "所有方法都为共同仪器计算 mapped 状态。policy_control 时间包含平移、预测及首次 policy 哈希，不能将整段时间归因于校准。",
        "phase 时间实际从参数解析之后开始，直到 postflight 验证结束；解释器启动、参数解析和最终费用回执写入不在此范围。",
        "", "完整逐路径动作、guard、30 坐标偏移、实际成本和输入身份见同目录 MECHANISM.json。", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--v3-run-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, old_root, out = args.run.resolve(), args.v3_run_root.resolve(), args.out.resolve()
    require(root != old_root and not out.exists(), "Separate completed run and new output directory required")
    require(not out.is_relative_to(old_root) and not out.is_relative_to(root / "train")
            and not out.is_relative_to(root / "evaluate"), "Output cannot modify frozen evidence directories")
    result = execute(root, old_root, args.protocol.resolve())
    out.mkdir(parents=True, exist_ok=False)
    with (out / "MECHANISM.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    (out / "MECHANISM.md").write_text(markdown(result))
    print(json.dumps({"diagnostic_only": True, "paths": result["all_complete_paths"],
                      "new_model_calls": 0, "endpoint_numeric_arrays_read": False, "output": str(out)}))
