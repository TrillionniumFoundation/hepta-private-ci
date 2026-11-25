"""Stdlib-only, read-only analysis of sealed experiment receipts.

This module is never imported by training. It does not construct data, load
Torch/checkpoints, choose models, change thresholds, or rerun an attempt.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys


METRICS = ("accuracy", "brier", "pre_late_accuracy", "final_over_pre_late",
           "initial_accuracy", "learned_over_initial", "cross_entropy", "stopping_utility")
SUM_COSTS = ("training_cpu_seconds", "fit_body_cpu_seconds", "fit_body_wall_seconds",
             "worker_cpu_seconds", "worker_wall_seconds", "parent_launch_exit_wall_seconds",
             "training_cpu_overrun_seconds", "test_pair_cpu_seconds", "test_pair_wall_seconds")
MAX_COSTS = ("worker_peak_rss_bytes", "fit_process_peak_rss_bytes", "maximum_chunk_state_tensor_bytes",
             "max_probability_balance_error")


def canonical_digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("expected a finite real number, got " + repr(value))
    return value


def stats(values):
    values = [numeric(v) for v in values if v is not None]
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "sample_std": statistics.stdev(values) if len(values) > 1 else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


class Receipts:
    def __init__(self):
        self.files, self.warnings = {}, []

    def read(self, path, required=True):
        path = Path(path)
        if not path.exists() and not required:
            self.warnings.append("Missing optional receipt: " + str(path))
            return None
        data = path.read_bytes()
        self.files[str(path.resolve())] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        def invalid_constant(value):
            raise ValueError("nonfinite JSON constant: " + value)
        return json.loads(data, object_pairs_hook=reject_duplicates, parse_constant=invalid_constant)

    def checksum(self, path):
        path = Path(path)
        if not path.exists():
            self.warnings.append("Missing prediction artifact: " + str(path))
            return None
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024*1024), b""):
                digest.update(chunk)
                size += len(chunk)
        self.files[str(path.resolve())] = {"sha256": digest.hexdigest(), "bytes": size, "parsed": False}
        return digest.hexdigest()


def cost_totals(rows):
    result = {}
    for key in SUM_COSTS + MAX_COSTS:
        values = [numeric(row["costs"][key]) for row in rows if row["costs"].get(key) is not None]
        aggregate = "sum" if key in SUM_COSTS else "max"
        result[key] = {aggregate: (sum(values) if aggregate == "sum" else max(values)) if values else None,
                       "available_attempts": len(values), "expected_attempts": len(rows)}
    result["process_energy_joules"] = None
    result["energy_status"] = "unknown; no process-attributable measurement; CPU time is not converted to Joules"
    return result


def attempt_costs(record, worker, parent, test):
    body, test_body = record.get("cost", {}), test.get("cost", {})
    metric_sets = (record.get("initial_development") or {}, record.get("selected_development") or {},
                   test.get("metrics") or {}, test.get("initial_metrics") or {})
    states = [m["maximum_chunk_state_tensor_bytes"] for m in metric_sets if m.get("maximum_chunk_state_tensor_bytes") is not None]
    balances = [numeric(m["max_probability_balance_error"]) for m in metric_sets if m.get("max_probability_balance_error") is not None]
    rss = body.get("process_max_rss_kib")
    return {"training_cpu_seconds": record.get("training_cpu_seconds"),
            "training_cpu_overrun_seconds": record.get("training_cpu_overrun"),
            "fit_body_cpu_seconds": body.get("cpu_seconds"), "fit_body_wall_seconds": body.get("wall_seconds"),
            "worker_cpu_seconds": worker.get("process_cpu_through_report_seconds"),
            "worker_wall_seconds": worker.get("wall_including_import_seconds"),
            "parent_launch_exit_wall_seconds": parent.get("launch_through_exit_wall_seconds"),
            "worker_peak_rss_bytes": worker.get("process_peak_rss_bytes"),
            "fit_process_peak_rss_bytes": None if rss is None else numeric(rss)*1024,
            "maximum_chunk_state_tensor_bytes": max(states) if states else None,
            "max_probability_balance_error": max(balances) if balances else None,
            "test_pair_cpu_seconds": test_body.get("cpu_seconds"), "test_pair_wall_seconds": test_body.get("wall_seconds"),
            "shared_package_energy_joules_unattributed": body.get("package_energy_joules")}


def learning_gate(metrics, thresholds, available, verified):
    checks = {"final_accuracy": available and metrics["accuracy"] >= thresholds["final_accuracy"],
              "learned_over_initial": available and metrics["learned_over_initial"] >= thresholds["learned_over_initial"],
              "final_over_pre_late": available and metrics["final_over_pre_late"] >= thresholds["final_over_pre_late"]}
    passed = all(checks.values()) and verified
    return {"available": available, "evidence_verified": verified, **checks,
            "numeric_criteria_pass": all(checks.values()), "passed": passed,
            "status": "UNVERIFIED" if available and not verified else "PASS" if passed else "FAIL"}


def make_attempt(name, identity, record, worker, parent, test, thresholds, verified):
    evaluated = record.get("status") == "completed" and test.get("status") == "evaluated"
    metrics, source = {}, {}
    if evaluated:
        selected, initial = test["metrics"], test["initial_metrics"]
        metrics = {key: numeric(selected[key]) for key in
                   ("accuracy", "brier", "pre_late_accuracy", "cross_entropy", "stopping_utility") if key in selected}
        metrics["initial_accuracy"] = numeric(initial["accuracy"])
        metrics["learned_over_initial"] = metrics["accuracy"]-metrics["initial_accuracy"]
        metrics["final_over_pre_late"] = metrics["accuracy"]-metrics["pre_late_accuracy"]
        source = {str(key): numeric(value) for key, value in selected.get("source_accuracy", {}).items()}
    return {"attempt": name, "neurons": identity["neurons"], "arm": identity["arm"]["id"], "seed": identity["seed"],
            "training_status": record.get("status", "missing"), "evaluation_status": test.get("status", "missing"),
            "evaluated": evaluated, "evidence_verified": verified,
            "training_error": record.get("error"), "test_reason": test.get("reason"),
            "worker_status": worker.get("status"), "parent_returncode": parent.get("returncode"),
            "updates": record.get("updates"), "attempted_updates": record.get("attempted_updates"),
            "selected_step": record.get("selected_step"), "metrics": metrics, "source_accuracy": source,
            "learning_gate": learning_gate(metrics, thresholds, evaluated, verified),
            "costs": attempt_costs(record, worker, parent, test)}


def source_summary(rows):
    keys = sorted({key for row in rows for key in row["source_accuracy"]})
    per_source = {key: {"seed_accuracy": stats(row["source_accuracy"].get(key) for row in rows),
                        "by_seed": {str(row["seed"]): row["source_accuracy"][key] for row in rows if key in row["source_accuracy"]}}
                  for key in keys}
    return {"source_count": len(keys), "per_source": per_source,
            "distribution_of_source_seed_means": stats(v["seed_accuracy"]["mean"] for v in per_source.values()),
            "inference": "descriptive only; sources and repeated model seeds are not pooled into independent observations"}


def groups(rows, protocol, thresholds):
    output = []
    for width in protocol["independent_neurons"]:
        for arm in protocol["arms"]:
            selected = [row for row in rows if row["neurons"] == width and row["arm"] == arm["id"]]
            evaluated = [row for row in selected if row["evaluated"]]
            passing = sum(row["learning_gate"]["passed"] for row in selected)
            verified = all(row["evidence_verified"] for row in selected)
            passed = verified and passing/len(protocol["seeds"]) >= thresholds["min_fraction_seeds"]
            output.append({"neurons": width, "arm": arm["id"], "expected_seeds": len(protocol["seeds"]),
                "evaluated_seeds": len(evaluated), "failed_training_seeds": sum(row["training_status"] == "failed" for row in selected),
                "metrics": {key: stats(row["metrics"].get(key) for row in evaluated) for key in METRICS},
                "learning_passing_seeds": passing,
                "learning_pass_fraction": passing/len(protocol["seeds"]),
                "learning_group_pass": passed, "all_evidence_verified": verified,
                "learning_group_status": "UNVERIFIED" if not verified else "PASS" if passed else "FAIL",
                "selected_step_zero_evaluated": sum(row["selected_step"] == 0 for row in evaluated),
                "selected_step_zero_all_reported": sum(row["selected_step"] == 0 for row in selected),
                "selected_step": stats(row["selected_step"] for row in selected),
                "updates": stats(row["updates"] for row in selected), "source_granularity": source_summary(evaluated),
                "costs": cost_totals(selected)})
    return output


def paired(rows, protocol):
    indexed = {(r["neurons"], r["arm"], r["seed"]): r for r in rows}
    output = []
    for width in protocol["independent_neurons"]:
        for arm in protocol["arms"]:
            if arm["id"] == "qvi_full":
                continue
            pairs, missing = [], []
            for seed in protocol["seeds"]:
                full, other = indexed[width, "qvi_full", seed], indexed[width, arm["id"], seed]
                if not full["evaluated"] or not other["evaluated"]:
                    missing.append(seed)
                    continue
                delta = {key: full["metrics"][key]-other["metrics"][key] for key in METRICS
                         if key in full["metrics"] and key in other["metrics"]}
                source = {key: full["source_accuracy"][key]-other["source_accuracy"][key]
                          for key in full["source_accuracy"] if key in other["source_accuracy"]}
                pairs.append({"seed": seed, "differences_full_minus_alternative": delta, "source_differences": source})
            source_keys = sorted({key for pair in pairs for key in pair["source_differences"]})
            output.append({"neurons": width, "reference": "qvi_full", "alternative": arm["id"],
                "paired_seeds": len(pairs), "missing_seed_pairs": missing, "pairs": pairs,
                "difference": {key: stats(pair["differences_full_minus_alternative"].get(key) for pair in pairs) for key in METRICS},
                "source_difference_seed_mean": {key: stats(pair["source_differences"].get(key) for pair in pairs) for key in source_keys},
                "direction": "full minus alternative; positive accuracy/gain favors full, negative Brier/CE favors full",
                "inference": "descriptive paired differences; no p-values or confidence intervals"})
    return output


def recovery_summary(final, reader, training, protocol, seal, rows):
    binding = final.get("resume_receipt")
    if binding is None:
        return None
    if binding.get("path") != "RESUME_RECEIPT.json":
        raise ValueError("unexpected recovery receipt path")
    path = training/"RESUME_RECEIPT.json"
    receipt = reader.read(path)
    if (reader.files[str(path.resolve())]["sha256"] != binding["sha256"]
            or receipt["protocol_sha256"] != canonical_digest(protocol)
            or receipt["source_hashes"] != protocol["source_hashes"]
            or receipt["training_records"] != seal["attempts"]
            or receipt["training_seal_sha256"] != final["seal_sha256"]):
        raise ValueError("recovery receipt binding mismatch")
    before, resumed = receipt["completed_before"], receipt["resumed_names"]
    expected = {row["attempt"] for row in rows if row["training_status"] == "completed"}
    if (set(before) & set(resumed) or set(before) | set(resumed) != expected
            or len(resumed) != len(set(resumed)) or len(before) != receipt["completed_before_count"]
            or len(resumed) != receipt["resumed_count"]):
        raise ValueError("recovery attempt partition mismatch")
    for name, files in before.items():
        if set(files) != {"test_result.json", "test_predictions.json"}:
            raise ValueError("unexpected preserved artifact identity")
        for file, expected_sha in files.items():
            actual = reader.files.get(str((training/name/file).resolve()))
            if actual is not None and actual["sha256"] != expected_sha:
                raise ValueError("previously completed test changed during recovery: "+name)
    workers = [reader.read(training/name/"resume_worker_cost.json", required=False) for name in resumed]
    available = [worker for worker in workers if worker is not None]
    previous_cpu = sum(numeric(row["costs"]["test_pair_cpu_seconds"]) for row in rows if row["attempt"] in before)
    resumed_cpu = sum(numeric(row["costs"]["test_pair_cpu_seconds"]) for row in rows if row["attempt"] in resumed)
    return {"completed_before_count": len(before), "resumed_count": len(resumed), "resumed_names": resumed,
        "prior_timeout": receipt["prior_timeout"], "prior_complete_process_cpu_seconds": None,
        "previous_completed_test_pair_cpu_seconds": previous_cpu, "resumed_test_pair_cpu_seconds": resumed_cpu,
        "resume_driver_cost": receipt["resume_driver_cost"],
        "resume_driver_cpu_through_report_seconds": receipt["driver_cpu_through_report_seconds"],
        "resume_children_cpu_including_shutdown_seconds": receipt["child_cpu_including_shutdown_seconds"],
        "resume_driver_wall_including_import_seconds": receipt["driver_wall_including_import_seconds"],
        "resume_worker_cost_receipts": len(available), "resume_worker_costs": available,
        "resume_worker_parent_costs": receipt["workers_finished"], "resume_source_sha256": receipt["resume_source_sha256"],
        "scope": "prior test-pair and resumed test-pair CPU are subsets, not additions to worker CPU; original finalizer total CPU remains unknown"}


def build_summary(protocol_path, training):
    training, reader = Path(training), Receipts()
    protocol = reader.read(protocol_path)
    digest = canonical_digest(protocol)
    if not protocol.get("source_hashes") or not protocol.get("runtime"):
        raise ValueError("a frozen protocol with source/runtime binding is required")
    if not protocol["seeds"] or len(set(protocol["seeds"])) != len(protocol["seeds"]):
        raise ValueError("nonempty distinct frozen seeds required")
    arm_ids = [arm["id"] for arm in protocol["arms"]]
    if "qvi_full" not in arm_ids or len(set(arm_ids)) != len(arm_ids):
        raise ValueError("distinct arms including qvi_full required")
    if len(set(protocol["independent_neurons"])) != len(protocol["independent_neurons"]):
        raise ValueError("distinct neuron widths required")
    validation = protocol["validation"]
    thresholds = {"final_accuracy": numeric(validation["min_final_accuracy"]),
        "learned_over_initial": numeric(validation["min_learned_over_initial_accuracy"]),
        "final_over_pre_late": numeric(validation["min_final_over_pre_late_accuracy"]),
        "min_fraction_seeds": numeric(validation["min_fraction_seeds_passing_learning"])}
    if any(not 0 <= value <= 1 for value in thresholds.values()):
        raise ValueError("invalid frozen learning thresholds")
    final = reader.read(training/"FINAL_RESULTS.json")
    if final.get("protocol_sha256") != digest or final.get("experiment_id") != protocol["experiment_id"]:
        raise ValueError("FINAL_RESULTS identity differs from frozen protocol")
    expected = {f'n{n}-{a["id"]}-s{s}': {"experiment_id": protocol["experiment_id"], "protocol_sha256": digest,
                "source_hashes": protocol["source_hashes"], "neurons": n, "arm": a, "seed": s, "smoke": False}
                for n in protocol["independent_neurons"] for a in protocol["arms"] for s in protocol["seeds"]}
    tests, hashes = {}, set()
    for row in final["results"]:
        name = row["attempt"]
        if name not in expected or name in tests:
            raise ValueError("unknown or duplicate final attempt: " + name)
        if row["status"] not in ("evaluated", "unavailable"):
            raise ValueError("nonterminal final row: " + name)
        if row["status"] == "evaluated":
            identity = expected[name]
            if (row.get("neurons"), row.get("arm"), row.get("seed")) != (identity["neurons"], identity["arm"]["id"], identity["seed"]):
                raise ValueError("test identity mismatch: " + name)
            hashes.add(row.get("data_sha256"))
        tests[name] = row
    if len(hashes) > 1 or (hashes and None in hashes):
        raise ValueError("evaluated attempts do not share one identified final dataset")
    seal = reader.read(training/"SEAL.json")
    if (final.get("seal_sha256") != reader.files[str((training/"SEAL.json").resolve())]["sha256"]
            or seal.get("protocol_sha256") != digest or seal.get("source_hashes") != protocol["source_hashes"]
            or set(seal.get("attempts", {})) != set(expected)):
        raise ValueError("seal binding or roster mismatch")
    parents, shards = {}, []
    for width in protocol["independent_neurons"]:
        shard = reader.read(training/f"SHARD_n{width}.json", required=False)
        if shard is None:
            continue
        if shard.get("neurons") != width:
            raise ValueError("shard width mismatch")
        for parent in shard["attempts"]:
            name = parent["attempt"]
            if name not in expected or name in parents or expected[name]["neurons"] != width:
                raise ValueError("unknown, duplicate or wrong-width worker receipt: " + name)
            parents[name] = parent
        shards.append({key: shard.get(key) for key in ("neurons", "workers", "shard_wall_seconds",
                       "all_child_cpu_seconds_including_shutdown", "driver_cpu_seconds", "energy_joules", "energy_reason")})
    rows = []
    for name, identity in expected.items():
        path = training/name/"result.json"
        record = reader.read(path, required=False) or {}
        worker = reader.read(training/name/"worker_cost.json", required=False) or {}
        test = tests.get(name, {})
        if record:
            if any(record.get(key) != value for key, value in identity.items()) or record.get("status") not in ("completed", "failed"):
                raise ValueError("training terminal identity mismatch: " + name)
            if seal["attempts"][name] != reader.files[str(path.resolve())]["sha256"]:
                raise ValueError("sealed training result changed: " + name)
            if test.get("status") == "evaluated" and (record["status"] != "completed" or record.get("selected_step") != test.get("selected_step")):
                raise ValueError("evaluated checkpoint selection mismatch: " + name)
        else:
            reader.warnings.append("Final performance omitted because training receipt is unavailable: " + name)
        if name not in tests:
            reader.warnings.append("Missing final evaluation slot: " + name)
        verified = bool(record) and test.get("status") == "unavailable" and record.get("status") == "failed"
        if test.get("status") == "evaluated":
            individual = reader.read(training/name/"test_result.json", required=False)
            prediction_sha = reader.checksum(training/name/"test_predictions.json")
            if individual is not None and individual != test:
                raise ValueError("FINAL_RESULTS differs from test_result.json: " + name)
            if prediction_sha is not None and prediction_sha != test.get("predictions_sha256"):
                raise ValueError("test prediction hash mismatch: " + name)
            verified = bool(record) and individual is not None and prediction_sha is not None
        rows.append(make_attempt(name, identity, record, worker, parents.get(name, {}), test, thresholds, verified))
    summary = {"schema": "hcsn-training-summary-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": protocol["experiment_id"], "protocol_sha256": digest, "protocol": protocol,
        "data_sha256": next(iter(hashes), None), "expected_attempts": len(expected),
        "evaluated_attempts": sum(row["evaluated"] for row in rows),
        "verified_evaluated_attempts": sum(row["evaluated"] and row["evidence_verified"] for row in rows),
        "thresholds": thresholds,
        "groups": groups(rows, protocol, thresholds), "paired_comparisons": paired(rows, protocol), "attempts": rows,
        "costs": {"training_attempt_totals": cost_totals(rows), "shards": shards,
            "final_test_body": final.get("cost"), "seal_body": seal.get("cost"),
            "campaign_elapsed_makespan_seconds": None,
            "wall_note": "worker/parent/shard sums are work-duration totals, not campaign makespan; shards may overlap",
            "containment_note": "training CPU is contained in fit-body and worker CPU; do not add these ledgers",
            "peak_note": "RSS is the maximum individual process lifetime peak, not simultaneous aggregate host memory"},
        "integrity": {"receipts": reader.files, "warnings": reader.warnings,
            "analysis_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "seal_binding_verified": True, "all_attempt_evidence_verified": all(row["evidence_verified"] for row in rows),
            "checks": "required seal binding, frozen identities, result hashes, test_result equality, prediction SHA256",
            "checkpoint_or_prediction_metrics_recomputed": False},
        "execution_recovery": recovery_summary(final, reader, training, protocol, seal, rows),
        "inference": "sample SD across training seeds; descriptive source and seed pairing only; no p-values or confidence intervals"}
    return summary


def mean_sd(value, scale=1, decimals=3):
    if not value["n"]:
        return "—"
    mean = f'{value["mean"]*scale:.{decimals}f}'
    return mean + (f' ± {value["sample_std"]*scale:.{decimals}f}' if value["sample_std"] is not None else " (n=1)")


def render(summary):
    p, thresholds = summary["protocol"], summary["thresholds"]
    lines = ["# HCSN 独立群体训练结果", "", f'实验：`{summary["experiment_id"]}`。', "",
        f'冻结协议 SHA256：`{summary["protocol_sha256"]}`。已评测 **{summary["evaluated_attempts"]}/{summary["expected_attempts"]}** 个预定训练尝试，其中 **{summary["verified_evaluated_attempts"]}** 个评测的独立回执与预测文件哈希已核验。', "",
        "## 判定与统计口径", "",
        f'每个 seed 同时满足：最终准确率 ≥ {thresholds["final_accuracy"]:.3f}；相对该 seed 初始模型提升 ≥ {thresholds["learned_over_initial"]:.3f}；相对各样本晚信息到达前提升 ≥ {thresholds["final_over_pre_late"]:.3f}。', "",
        f'每个 N×arm 至少 {math.ceil(thresholds["min_fraction_seeds"]*len(p["seeds"]))}/{len(p["seeds"])} 个 seed 通过才通过组门槛。缺失或失败保留在预定 seed 分母中；判定使用未舍入原始值。', "",
        "表中的 ± 是训练 seed 间样本标准差，n=1 时不估计标准差；不是置信区间。性能均值仅使用已评测 seed，覆盖数另列。预测或逐项测试回执缺失时保留报告值但标记 UNVERIFIED，所在组不会判为 PASS。选中 step 0 表示开发集选择保留初始模型，不能称为学习成功。", "",
        "这些数据来自模拟的互不重叠来源族。按来源与同 seed 配对的结果仅作描述，不把样本、来源和重复训练 seed 混为独立观测，不输出 p 值。", "",
        "## 按宽度与对照汇总", "",
        "| N | arm | 已评测 | 准确率 ± SD (%) | Brier ± SD | pre-late (%) | final−pre-late (pp) | final−initial (pp) | step0/已评测 | 学习门槛 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for group in summary["groups"]:
        m = group["metrics"]
        lines.append(f'| {group["neurons"]} | {group["arm"]} | {group["evaluated_seeds"]}/{group["expected_seeds"]} | '
            + " | ".join((mean_sd(m["accuracy"], 100, 2), mean_sd(m["brier"]), mean_sd(m["pre_late_accuracy"], 100, 2),
                           mean_sd(m["final_over_pre_late"], 100, 2), mean_sd(m["learned_over_initial"], 100, 2)))
            + f' | {group["selected_step_zero_evaluated"]}/{group["evaluated_seeds"]} | {group["learning_group_status"]} ({group["learning_passing_seeds"]}/{group["expected_seeds"]}) |')
    lines += ["", "## 同 seed 配对：qvi_full 减去对照", "",
        "准确率和提升差为正有利于 full；Brier 差为负有利于 full。缺失的一侧不会被填零，配对覆盖数明确列出。", "",
        "| N | 对照 | 配对 seed | Δ准确率 (pp) | ΔBrier | Δ晚信息提升 (pp) | Δ相对初始提升 (pp) |",
        "|---:|---|---:|---:|---:|---:|---:|"]
    for pair in summary["paired_comparisons"]:
        d = pair["difference"]
        lines.append(f'| {pair["neurons"]} | {pair["alternative"]} | {pair["paired_seeds"]}/{len(p["seeds"])} | '
            + " | ".join((mean_sd(d["accuracy"], 100, 2), mean_sd(d["brier"]),
                           mean_sd(d["final_over_pre_late"], 100, 2), mean_sd(d["learned_over_initial"], 100, 2))) + " |")
    lines += ["", "## 来源层描述", "", "先在每个来源内平均已评测 seed，再描述来源均值的分布；完整来源×seed 数字与配对来源差在 SUMMARY.json。", "",
              "| N | arm | 来源数 | 来源均值均数 (%) | 来源均值 SD (pp) | 最低来源均值 (%) | 最高来源均值 (%) |",
              "|---:|---|---:|---:|---:|---:|---:|"]
    for group in summary["groups"]:
        source = group["source_granularity"]
        d = source["distribution_of_source_seed_means"]
        values = ["—" if d[k] is None else f'{100*d[k]:.2f}' for k in ("mean", "sample_std", "min", "max")]
        lines.append(f'| {group["neurons"]} | {group["arm"]} | {source["source_count"]} | ' + " | ".join(values) + " |")
    lines += ["", "## 成本与数值边界", "",
        "下列时间账本相互包含，不能相加成总训练成本。training CPU 包含实际尝试的 minibatch/前向/反向/更新及失败；fit-body 另含设置、开发集选择与 checkpoint；worker CPU 再含解释器与导入至回执时刻；parent wall 包含启动到退出。", "",
        "| 账本 | 值 | 有回执/预定尝试 |", "|---|---:|---:|"]
    totals = summary["costs"]["training_attempt_totals"]
    for key in SUM_COSTS + MAX_COSTS:
        row = totals[key]
        value = row.get("sum", row.get("max"))
        display = ("unknown" if value is None else f"{value:.3e}" if "probability" in key
                   else f"{value:.3f}" if "seconds" in key else str(int(value)))
        lines.append(f'| {key} | {display} | {row["available_attempts"]}/{row["expected_attempts"]} |')
    lines += ["", "| N | 并发 workers | SHARD wall (s) | children CPU 含退出 (s) | driver CPU (s) |",
              "|---:|---:|---:|---:|---:|"]
    for shard in summary["costs"]["shards"]:
        values = ["unknown" if shard.get(k) is None else f'{shard[k]:.3f}' for k in
                  ("shard_wall_seconds", "all_child_cpu_seconds_including_shutdown", "driver_cpu_seconds")]
        lines.append(f'| {shard["neurons"]} | {shard["workers"]} | ' + " | ".join(values) + " |")
    lines += ["", "worker/parent/SHARD wall 的合计不代表可能并发运行的整个 campaign 历时；未凭这些数值推算 makespan。RSS 是单个 worker 进程峰值的最大值，不能当同时驻留内存合计。state bytes 仅包含评测 chunk 的完整五个动态张量，不含模型、输出和 AD tape。", "",
        "**能耗未知。** 没有进程可归属的硬件读数；共享 package 计数即使存在也可能重叠，不相加，也不以 CPU 秒代替焦耳。最终测试与 seal 的独立账本保留在 SUMMARY.json，未混入训练 CPU。", "",
        "## 每个尝试与失败保留", "",
        "| 尝试 | 训练/评测状态 | 更新数 | 选中 step | 准确率 (%) | 相对初始 (pp) | 相对 pre-late (pp) | 学习 |",
        "|---|---|---:|---:|---:|---:|---:|---|"]
    failure_notes = []
    for row in summary["attempts"]:
        values = ["—" if key not in row["metrics"] else f'{100*row["metrics"][key]:.2f}' for key in
                  ("accuracy", "learned_over_initial", "final_over_pre_late")]
        lines.append(f'| {row["attempt"]} | {row["training_status"]}/{row["evaluation_status"]} | {row["updates"]} | {row["selected_step"]} | '
                     + " | ".join(values) + f' | {row["learning_gate"]["status"]} |')
        if row["training_error"] or row["test_reason"]:
            error = str(row["training_error"] or row["test_reason"]).replace("|", "/").replace("\n", " ")
            failure_notes.append(f'- `{row["attempt"]}`：{error}')
    if failure_notes:
        lines += ["", "### 失败详情", "", *failure_notes, ""]
    recovery = summary.get("execution_recovery")
    if recovery is not None:
        prior = recovery["prior_timeout"]
        lines += ["", "## 中断后的执行恢复", "",
            f'原 finalizer `{prior.get("timeout_job", "unknown")}` 为 timed_out / exit 124；含封存等待的 wall 为 {prior.get("wall_seconds_including_wait", "unknown")} 秒。完整原进程 CPU 未测到，保持 unknown。', "",
            f'原已完成 {recovery["completed_before_count"]} 个评测的 result/prediction SHA 保持一致；仅恢复缺失的 {recovery["resumed_count"]} 个槽位，没有重新训练、选模或更改评测定义。', "",
            f'恢复 driver CPU（至回执）{recovery["resume_driver_cpu_through_report_seconds"]:.3f} 秒；恢复 children CPU（含退出）{recovery["resume_children_cpu_including_shutdown_seconds"]:.3f} 秒；恢复 driver wall（含导入）{recovery["resume_driver_wall_including_import_seconds"]:.3f} 秒。', "",
            f'原已完成测试 pair CPU 之和为 {recovery["previous_completed_test_pair_cpu_seconds"]:.3f} 秒；新完成测试 pair CPU 之和为 {recovery["resumed_test_pair_cpu_seconds"]:.3f} 秒。这些是相应 worker CPU 的子集，不再重复相加。', "",
            "FINAL_RESULTS.cost 仅是恢复 driver body 的账本，不代表全部 72 项最终测试 CPU。原 timeout、原已完成行成本和本次恢复成本分列；适配测试成本也不与包含它的原 finalizer 时间重复相加。", ""]
    lines += ["", "## 可复核性", "",
        "本汇总只读已写出的回执，不导入训练代码、Torch，不读取标签重新拟合模型，不更改选择或门槛。SEAL.json 必须存在且与 FINAL_RESULTS 哈希匹配；逐项校验冻结身份、source-hash 回执、统一测试数据身份、sealed result 哈希、test_result.json 等值及 test_predictions.json SHA256。此处没有独立重算 checkpoint 或预测指标。全部输入回执 SHA256 和分析源码 SHA256 在 SUMMARY.json。", ""]
    if summary["integrity"]["warnings"]:
        lines += ["缺失回执或不完整覆盖：", ""] + ["- " + value for value in summary["integrity"]["warnings"]] + [""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or args.training
    targets = (output/"SUMMARY.json", output/"RESULTS_TRAINING.md")
    if any(path.exists() for path in targets):
        parser.error("analysis output is create-only; select a new output directory")
    try:
        summary = build_summary(args.protocol, args.training)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    text = render(summary)
    output.mkdir(parents=True, exist_ok=True)
    with targets[0].open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    with targets[1].open("x", encoding="utf-8") as handle:
        handle.write(text)
    print(json.dumps({"evaluated": summary["evaluated_attempts"], "expected": summary["expected_attempts"],
          "groups_passing": sum(g["learning_group_pass"] for g in summary["groups"]),
          "warnings": len(summary["integrity"]["warnings"]), "outputs": [str(p) for p in targets]}, sort_keys=True))


if __name__ == "__main__":
    main()
