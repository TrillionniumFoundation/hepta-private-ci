"""Read-only NumPy verification and descriptive communication-study summary.

This postprocessor is outside the executable training closure. It never loads
Torch/checkpoints or chooses a model, and writes only a new output directory.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def description(values):
    values = [float(x) for x in values if x is not None]
    return {"count": len(values), "mean": statistics.mean(values) if values else None,
            "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
            "values": values}


def regenerate(p):
    """Independent NumPy reconstruction, executed only after all seal checks."""
    n, length = p["data"]["test_per_source"], p["data"]["length"]
    xs, labels, sources, margins, late_steps, ids = [], [], [], [], [], []
    for source in p["data"]["test_sources"]:
        rng = np.random.default_rng(20261124+1009*source)
        a, b = rng.uniform(-1, 1, (2, n))
        gain, noise = rng.uniform(.85, 1.15), rng.uniform(.08, .35)
        correlation = rng.uniform(-.5, .7)
        late = rng.integers(4, 7, n)
        x = np.zeros((length, n, 6), dtype=np.float64)
        x[0, :, 0], x[0, :, 2] = gain*a, 1
        x[late, np.arange(n), 1], x[late, np.arange(n), 3] = gain*b, 1
        x[:, :, 4] = np.arange(length)[:, None]/(length-1)
        for tick in range(length):
            x[tick, :, 5] = noise*rng.normal(size=n)
            if tick:
                x[tick, :, 5] += correlation*x[tick-1, :, 5]
        xs.append(x)
        labels.append((a+b > 0).astype(np.int64))
        sources.extend([source]*n)
        margins.append(rng.uniform(.45, .85, n))
        late_steps.append(late)
        ids.extend(f"communication-v1-test:{source}:{i}" for i in range(n))
    arrays = (np.concatenate(xs, 1).astype(np.float32), np.concatenate(labels),
              np.asarray(sources, dtype=np.int64), np.concatenate(margins).astype(np.float32), np.concatenate(late_steps))
    digest = hashlib.sha256()
    for value in arrays:
        value = np.ascontiguousarray(value)
        digest.update(str((value.dtype.str, value.shape)).encode())
        digest.update(value.tobytes())
    digest.update("\n".join(ids).encode())
    return {"data_sha256": digest.hexdigest(), "labels": arrays[1].tolist(), "source": arrays[2].tolist(),
            "initial_margin": arrays[3].tolist(), "late_step": arrays[4].tolist(), "ids": ids}


def metrics(logits, data):
    z = np.asarray(logits, dtype=np.float64)
    y, source, late = (np.asarray(data[key], dtype=np.int64) for key in ("labels", "source", "late_step"))
    if z.shape != (12, len(y), 2) or not np.isfinite(z).all():
        raise ValueError("nonfinite or incorrectly shaped all-prefix logits")
    shifted = z-z.max(-1, keepdims=True)
    denominator = np.exp(shifted).sum(-1, keepdims=True)
    probability = np.exp(shifted)/denominator
    columns, prediction = np.arange(len(y)), probability.argmax(-1)
    correct = prediction[-1] == y
    target = np.eye(2)[y]
    eligible = probability.max(-1) >= .8
    eligible[-1] = True
    stop = eligible.argmax(0)
    stopped = prediction[stop, columns] == y
    per_source = {str(s): float(correct[source == s].mean()) for s in np.unique(source)}
    result = {"accuracy": float(correct.mean()),
        "brier": float(((probability[-1]-target)**2).sum(-1).mean()),
        "cross_entropy": float((np.log(denominator[-1, :, 0])-shifted[-1, columns, y]).mean()),
        "early_accuracy": float((prediction[0] == y).mean()),
        "pre_late_accuracy": float((prediction[late-1, columns] == y).mean()),
        "stop_accuracy": float(stopped.mean()), "mean_stop_step": float(stop.mean()),
        "stopping_utility": float((stopped-.04*stop/(len(z)-1)).mean()),
        "stop_before_late_fraction": float((stop < late).mean()),
        "source_accuracy": per_source, "worst_source_accuracy": min(per_source.values()),
        "examples": len(y), "sources": len(per_source)}
    margin = np.asarray(data["initial_margin"], dtype=np.float64)
    quartiles = np.quantile(margin, [0, .25, .5, .75, 1])
    groups = {"late_parity_"+str(i): late % 2 == i for i in (0, 1)}
    groups.update({"initial_margin_quartile_"+str(i): (margin >= quartiles[i]) &
                   ((margin <= quartiles[i+1]) if i == 3 else (margin < quartiles[i+1])) for i in range(4)})
    result["subgroups"] = {name: {"examples": int(chosen.sum()), "accuracy": float(correct[chosen].mean())}
                            for name, chosen in groups.items()}
    return result


def compare(expected, reported):
    errors = []
    for key, value in expected.items():
        actual = reported[key]
        if isinstance(value, dict):
            errors.append(compare(value, actual))
        else:
            errors.append(abs(float(value)-float(actual)))
    return max(errors, default=0.)


def verify(root):
    p, seal, final = (read(root/name) for name in ("PROTOCOL.json", "SEAL.json", "FINAL_RESULTS.json"))
    pid = canonical(p)
    if (seal["protocol_sha256"] != pid or final["protocol_sha256"] != pid
            or final["seal_sha256"] != sha(root/"SEAL.json")
            or set(seal["attempts"]) != {s["id"] for s in p["slots"]}):
        raise ValueError("foreign or incomplete protocol/seal/final-results binding")
    source_root = Path(__file__).resolve().parents[2]
    for module, expected in p["source_hashes"].items():
        relative = source_root.joinpath(*(module[:-3] if module.endswith(".py") else module).split("."))
        path = relative.with_suffix(".py")
        if not path.exists():
            path = relative/"__init__.py"
        if sha(path) != expected:
            raise ValueError("training source no longer matches protocol: "+module)
    for name, files in seal["attempts"].items():
        for relative, expected in files.items():
            if sha(root/name/relative) != expected:
                raise ValueError("sealed file changed: "+name+"/"+relative)
    if read(root/"TEST_CLAIM.json") != {"seal_sha256": sha(root/"SEAL.json"), "protocol_sha256": pid}:
        raise ValueError("test claim mismatch")
    final_rows = {row["slot"]["id"]: row for row in final["results"]}
    if len(final["results"]) != 21 or set(final_rows) != set(seal["attempts"]):
        raise ValueError("final roster is incomplete or duplicated")
    if read(root/"CAMPAIGN_RECEIPT.json")["status"] != "completed":
        raise ValueError("campaign has not authoritatively completed")
    for slot in p["slots"]:
        directory = root/slot["id"]
        trained, worker, parent = (read(directory/name) for name in ("result.json", "worker_cost.json", "parent_cost.json"))
        if (trained["slot"] != slot or trained["protocol_sha256"] != pid or trained["smoke"] is not False
                or worker["status"] != trained["status"] or worker["error"] is not None or parent["error"] is not None
                or parent["returncode"] != (1 if trained["status"] == "failed" else 0)):
            raise ValueError("sealed training identity or terminal receipt mismatch")
        if read(directory/"TEST_WORKER_CLAIM.json") != {"seal_sha256": sha(root/"SEAL.json"), "protocol_sha256": pid, "slot": slot}:
            raise ValueError("per-slot test claim mismatch")
        test_worker, test_parent = (read(directory/name) for name in ("test_worker_cost.json", "test_parent_cost.json"))
        if (test_worker["status"] != final_rows[slot["id"]]["status"] or test_worker["error"] is not None
                or test_parent["returncode"] != 0 or test_parent["error"] is not None):
            raise ValueError("test child/parent did not complete successfully")
    expected_data = regenerate(p)
    checked, rows = [], []
    for slot in p["slots"]:
        name, directory = slot["id"], root/slot["id"]
        row = read(directory/"test_result.json")
        if row != final_rows[name] or row["slot"] != slot:
            raise ValueError("final row differs from original result")
        train = read(directory/"result.json")
        if row["status"] == "unavailable":
            if train["status"] != "failed":
                raise ValueError("unavailable test must correspond to preserved failed training")
            rows.append(row)
            continue
        if sha(directory/"test_predictions.json.gz") != row["predictions_sha256"]:
            raise ValueError("prediction hash mismatch")
        with gzip.open(directory/"test_predictions.json.gz", "rt") as stream:
            data = json.load(stream)
        if data["slot"] != slot or data["protocol_sha256"] != pid or row["data_sha256"] != expected_data["data_sha256"]:
            raise ValueError("prediction identity or regenerated data digest mismatch")
        for key, value in expected_data.items():
            if data[key] != value:
                raise ValueError("regenerated test field differs: "+key)
        for label in ("selected", "initial", "cpu_prefix"):
            error = compare(metrics(data["prefix_logits"][label], data), row["metrics"][label])
            checked.append({"slot": name, "model": label, "maximum_metric_error": error, "passed": error <= 1e-12})
        if any(row[key] != train[key] for key in ("updates", "selected_step", "cpu_prefix_step")):
            raise ValueError("test selection header differs from sealed training")
        gate = p["validation"]
        selected, initial = row["metrics"]["selected"], row["metrics"]["initial"]
        passed = (selected["accuracy"] >= gate["min_final_accuracy"] and
                  selected["accuracy"]-initial["accuracy"] >= gate["min_gain_over_initial"] and
                  selected["accuracy"]-selected["pre_late_accuracy"] >= gate["min_gain_over_prelate"])
        if passed != row["learning_gate"]:
            raise ValueError("recorded learning gate differs from frozen rule")
        rows.append(row)
    evidence = {"status": "verified" if all(r["passed"] for r in checked) else "failed",
                "scope": "NumPy regeneration of test data and all reported probabilistic/subgroup metrics; no Torch/model imports, no new model evaluations.",
                "records": checked, "models_verified": len(checked),
                "maximum_metric_error": max((r["maximum_metric_error"] for r in checked), default=0.),
                "protocol_sha256": pid, "seal_sha256": sha(root/"SEAL.json"),
                "test_data_sha256": expected_data["data_sha256"], "analysis_source_sha256": sha(__file__)}
    evidence["verified_training_source_files"] = len(p["source_hashes"])
    evidence["post_test_artifact_sha256"] = {slot["id"]: {name: sha(root/slot["id"]/name) for name in
        ("test_result.json", "test_worker_cost.json", "test_parent_cost.json", "MECHANISM_TEST.json")} for slot in p["slots"]}
    return p, rows, evidence


def summarize(root, p, rows, verified):
    groups, mechanisms = {}, {}
    for arm in p["arms"]:
        roster = [r for r in rows if r["slot"]["arm"] == arm]
        evaluated = [r for r in roster if r["status"] == "evaluated"]
        values = {}
        for name in ("accuracy", "brier", "pre_late_accuracy", "cross_entropy", "worst_source_accuracy"):
            values[name] = description([r["metrics"]["selected"][name] for r in evaluated])
        values["gain_over_initial"] = description([r["metrics"]["selected"]["accuracy"]-r["metrics"]["initial"]["accuracy"] for r in evaluated])
        values["gain_over_prelate"] = description([r["metrics"]["selected"]["accuracy"]-r["metrics"]["selected"]["pre_late_accuracy"] for r in evaluated])
        passed = [r["slot"]["seed"] for r in evaluated if r["learning_gate"] and r["training_status"] == "completed"
                  and r["updates"] == p["training"]["max_updates"] and
                  r["metrics"]["selected"]["max_probability_balance_error"] <= p["validation"]["max_mixed_mass_error"]]
        groups[arm] = {"registered_seeds": 3, "evaluated_seeds": len(evaluated), "passing_equal_update_seeds": passed,
            "qualification": "PASS" if verified and len(passed) >= 2 else "FAIL" if verified else "UNVERIFIED",
            "selected_step_zero_count": sum(r["selected_step"] == 0 for r in evaluated),
            "selected_steps": [r["selected_step"] for r in evaluated], "updates": [r["updates"] for r in evaluated],
            "selected_metrics": values,
            "cpu_prefix_accuracy": description([r["metrics"]["cpu_prefix"]["accuracy"] for r in evaluated]),
            "cpu_prefix_steps": [r["cpu_prefix_step"] for r in evaluated],
            "maximum_probability_balance_error": max((r["metrics"]["selected"]["max_probability_balance_error"] for r in evaluated), default=None),
            "maximum_complete_chunk_state_tensor_bytes": max((r["metrics"]["selected"]["maximum_complete_chunk_state_tensor_bytes"] for r in evaluated), default=None),
            "source_accuracy_by_seed": {str(r["slot"]["seed"]): r["metrics"]["selected"]["source_accuracy"] for r in evaluated},
            "cue_parity_by_seed": {str(r["slot"]["seed"]): {k: v for k, v in r["metrics"]["selected"]["subgroups"].items() if k.startswith("late_parity")} for r in evaluated}}
        records = []
        for row in evaluated:
            directory = root/row["slot"]["id"]
            fit = read(directory/"MECHANISM_FIT.json")["models"][0]["phases"]
            test = read(directory/"MECHANISM_TEST.json")["models"][0]["phases"]["test_selected"]
            norms = np.asarray(fit["training"]["preclip_recurrent_gradient_norm_by_update"])
            records.append({"seed": row["slot"]["seed"], "selected": test,
                            "training_recurrent_gradient_norm_mean": norms.mean(0).tolist(),
                            "training_recurrent_gradient_norm_max": norms.max(0).tolist()})
        mechanisms[arm] = records
    indexed = {(r["slot"]["arm"], r["slot"]["seed"]): r for r in rows if r["status"] == "evaluated"}
    contrasts = []
    pairs = [("unsigned_signed_raw", "signed_only"), ("unsigned_signed_centered", "unsigned_signed_raw"),
             ("unsigned_signed_centered_bounded", "unsigned_signed_centered"),
             ("boundary_accumulate", "boundary_raw"), ("boundary_hold", "boundary_raw")]
    for left, right in pairs:
        differences = [{"seed": seed, **{metric: indexed[left, seed]["metrics"]["selected"][metric]-
                        indexed[right, seed]["metrics"]["selected"][metric] for metric in ("accuracy", "brier", "pre_late_accuracy")}}
                       for seed in (18011, 28011, 38011) if (left, seed) in indexed and (right, seed) in indexed]
        contrasts.append({"left_minus_right": [left, right], "pairs": differences,
                          "accuracy_difference": description([d["accuracy"] for d in differences]),
                          "brier_difference": description([d["brier"] for d in differences]),
                          "scope": "Matched seed, fixed dataset and preset arms; descriptive only, not a p-value."})
    training = [read(root/s["id"]/"result.json") for s in p["slots"]]
    workers = [read(root/s["id"]/name) for s in p["slots"] for name in ("worker_cost.json", "test_worker_cost.json")]
    costs = {"attempted_update_cpu_seconds": sum(r["training_cpu_seconds"] for r in training),
             "fit_body_cpu_seconds": sum(r["cost"]["cpu_seconds"] for r in training),
             "worker_cpu_through_receipt_seconds": sum(r["process_cpu_through_receipt"] for r in workers),
             "maximum_single_process_peak_rss_bytes": max(r["process_peak_rss_bytes"] for r in workers),
             "fit_execution": read(root/"FIT_EXECUTION.json"), "test_execution": read(root/"TEST_EXECUTION.json"),
             "campaign": read(root/"CAMPAIGN_RECEIPT.json"), "energy_joules_process": None,
             "scope": "Nested accounting views, not additive. RSS is maximum single process, not concurrent aggregate; energy is unmeasured."}
    return {"experiment_id": p["experiment_id"], "protocol_sha256": canonical(p), "verified": verified,
            "groups": groups, "paired_contrasts": contrasts, "mechanisms": mechanisms, "costs": costs,
            "qualification_scope": "Prospective within this synthetic generator family; failures stay in three-seed denominator. No multimodal/large-model or statistical superiority claim."}


def markdown(summary):
    def fmt(value, percent=False):
        return "n/a" if value is None else f"{value*(100 if percent else 1):.3f}"+("%" if percent else "")
    lines = ["# 通信机制独立对照", "", "7 个预先指定臂 × 3 seeds，均为 N32、QVI + value/risk、uniformized mixed。前三个 unsigned 对照均禁用 boundary 消息；后三个 boundary-only 对照只改变 input-drive 的因果缓存。", "",
        "| Arm | Final accuracy mean ± SD | Brier | Pre-late | Final − pre-late | 512-step passes | Gate |",
        "|---|---:|---:|---:|---:|---:|---|"]
    for name, group in summary["groups"].items():
        m = group["selected_metrics"]
        lines.append(f"| {name} | {fmt(m['accuracy']['mean'], True)} ± {fmt(m['accuracy']['sample_sd'], True)} | {fmt(m['brier']['mean'])} | {fmt(m['pre_late_accuracy']['mean'], True)} | {fmt(m['gain_over_prelate']['mean'], True)} | {len(group['passing_equal_update_seeds'])}/3 | {group['qualification']} |")
    lines.extend(["", "门槛逐 seed 同时要求 final≥0.8、比 initial 增益≥0.1、比 pre-late 增益≥0.1，并满足原数值门与完整512更新；至少2/3 seeds通过。失败/缺失不从分母删除。初始step0也属于开发集选择候选，180 CPU前缀独立保留且不按test选择。", "",
        "## 预设配对差值", "", "| Left − right | Accuracy difference mean ± SD | Brier difference |", "|---|---:|---:|"])
    for row in summary["paired_contrasts"]:
        a, b = row["left_minus_right"]
        d = row["accuracy_difference"]
        lines.append(f"| {a} − {b} | {fmt(d['mean'], True)} ± {fmt(d['sample_sd'], True)} | {fmt(row['brier_difference']['mean'])} |")
    costs = summary["costs"]
    lines.extend(["", "差值按相同seed配对，仅为描述统计。完整每source、cue奇偶、初态分组和逐通道均值/RMS、tanh饱和、preclip梯度记录保留在JSON及原始档案。中心化参考来自不读数据的名义stationary law，不能把它称为实测零均值。", "",
        "## 费用与边界", "", f"尝试更新CPU合计 {costs['attempted_update_cpu_seconds']:.3f} 秒；fit body CPU {costs['fit_body_cpu_seconds']:.3f} 秒；全部fit/test worker到回执的CPU {costs['worker_cpu_through_receipt_seconds']:.3f} 秒。这些是嵌套口径，不相加。阶段回执另含进程shutdown；峰RSS为单进程最大值。能量未测。", "",
        "所有21训练终态与checkpoint先全局seal，之后才构造15000–15015测试source。测试数据和三份模型的全prefix概率指标以独立NumPy重算，不重新执行模型。新增source仍来自相同模拟器，不等于独立真实模态。Hold增加显式观测记忆，unsigned增加活跃参数；本实验没有把这些容量变化伪装成完全等容量。", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    p, rows, evidence = verify(args.root)
    summary = summarize(args.root, p, rows, evidence["status"] == "verified")
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (("INDEPENDENT_METRICS_VERIFICATION.json", evidence), ("SUMMARY.json", summary)):
        (args.output/name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n")
    (args.output/"RESULTS_COMMUNICATION.md").write_text(markdown(summary))
    print(json.dumps({"verified_models": evidence["models_verified"], "max_metric_error": evidence["maximum_metric_error"],
                      "groups": {name: group["qualification"] for name, group in summary["groups"].items()}}))
    return 0 if evidence["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
