"""Read completed, frozen policy evidence; never fit or select a controller."""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


FAMILIES, SEEDS = ("ordinary", "analytic"), (11, 23, 37)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path, inputs):
    inputs[str(path)] = sha(path)
    return json.loads(Path(path).read_text())


def mean(values):
    return float(np.mean(values)) if values else None


def scan_actual(path, config, inputs):
    """Independently aggregate saved execution costs and elementary ledger checks."""
    inputs[str(path)] = sha(path)
    result, worlds, issues, maximum = {}, {}, [], 0.
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            name, execution, source = row["controller"], row["execution"], row["source"]
            key = source["world_id"]
            if key in worlds and worlds[key] != source:
                issues.append([line_number, "paired_world_changed"])
            worlds[key] = source
            fee, reads, skips = 0., [], 0
            for step in execution["steps"]:
                action, slot = step["executed"], step["slot"]
                fee += step["fee"]
                if step["raw_accessed"] != (action == "READ"):
                    issues.append([line_number, "raw_access_does_not_match_action"])
                if action == "READ":
                    reads.append(slot)
                    if step["raw_outcome_index"] != source["outcomes_evaluator_only"][slot]:
                        issues.append([line_number, "read_wrong_raw_outcome"])
                    if step["budget_after"] != step["budget_before"] - 1 or step["pending_dt_after"] != 0:
                        issues.append([line_number, "read_state_contract"])
                elif action == "SKIP":
                    skips += 1
                    if step["budget_after"] != step["budget_before"]:
                        issues.append([line_number, "skip_changed_budget"])
                    maximum = max(maximum, abs(step["pending_dt_after"] -
                        step["pending_dt_before"] - config["dts"][slot]))
                elif step["state_after_sha256"] != step["state_before_sha256"]:
                    issues.append([line_number, "stop_changed_state"])
            correct = float(execution["prediction"] == source["hidden_label_evaluator_only"])
            maximum = max(maximum, abs(correct - execution["correct"]),
                          abs(fee - execution["fee"]), abs(correct - fee - execution["return"]))
            if reads != execution["raw_accesses"]:
                issues.append([line_number, "read_access_log"])
            aggregate = result.setdefault(name, {"executions": 0, "cpu": 0., "wall": 0.,
                "return_sum": 0., "fee_sum": 0., "reads": 0, "skips": 0,
                "phase_cpu": {}, "phase_wall": {}})
            aggregate["executions"] += 1
            aggregate["cpu"] += execution["total_cpu_seconds"]
            aggregate["wall"] += execution["total_wall_seconds"]
            aggregate["return_sum"] += execution["return"]
            aggregate["fee_sum"] += execution["fee"]
            aggregate["reads"] += len(reads); aggregate["skips"] += skips
            for kind in ("cpu", "wall"):
                for phase, value in execution[f"phase_{kind}_seconds"].items():
                    aggregate[f"phase_{kind}"][phase] = aggregate[f"phase_{kind}"].get(phase, 0.) + value
    if set(result) != {"stop", "fixed", "confidence", "value", "oracle"}:
        issues.append([0, "missing_controller"])
    if any(v["executions"] != 128 for v in result.values()):
        issues.append([0, "unexpected_world_count"])
    return {"controllers": result, "unique_worlds": len(worlds),
            "ledger_issues": issues, "maximum_ledger_arithmetic_error": maximum}


def matrix_metrics(cell):
    a, b = cell["ordinary_lightweight"], cell["ordinary_value"]
    c, d = cell["analytic_lightweight"], cell["analytic_value"]
    return {**cell, "backbone_with_lightweight": c - a, "backbone_with_value": d - b,
            "controller_with_ordinary": b - a, "controller_with_analytic": d - c,
            "interaction": (d - c) - (b - a)}


def collect(base, deployed_path):
    inputs, evaluations, cases, boundaries = {}, {}, [], []
    for family in FAMILIES:
        for seed in SEEDS:
            tag = f"{family}_s{seed}"
            folder = base / "evidence/policy/evals" / tag
            evaluation = read_json(folder / "EVALUATION.json", inputs)
            assert evaluation["model_family"] == family and evaluation["model_seed"] == seed
            assert evaluation["model_width"] == 16 and len(evaluation["heldout"]) == 4
            evaluations[tag] = evaluation
            for row in evaluation["heldout"]:
                config = row["config"]
                actual = scan_actual(folder / f"{config['name']}_paired.jsonl.gz", config, inputs)
                controls = {}
                for name, values in row["exact"].items():
                    if name == "oracle":
                        controls[name] = dict(values)
                        continue
                    read_fee = config["read_cost"] * values["expected_reads"]
                    skip_fee = config["skip_cost"] * values["expected_skips"]
                    controls[name] = {**values, "expected_read_fee": read_fee,
                        "expected_skip_fee": skip_fee, "expected_total_fee": read_fee + skip_fee,
                        "expected_correctness": values["return"] + read_fee + skip_fee}
                cases.append({"family": family, "seed": seed, "config": config,
                    "controls": controls, "optimal_target_calibration": row["value_calibration"],
                    "actual": actual, "paired_summary": row["paired_execution"],
                    "task_value_boundaries": row["task_value_boundaries"],
                    "selected_kind": evaluation["selected_lightweight"]["kind"]})
            side_audit = evaluation["independent_exhaustive_execution"]["boundary_sides"]
            for side in side_audit.get("sides", []):
                q = side["oracle_root_q"]
                boundaries.append({"family": family, "seed": seed, "root": side_audit["root"],
                    **side, "learned_first_action_oracle_regret":
                    max(q.values()) - q[side["learned_root_action"]]})
    candidates = {e["candidate_commit"] for e in evaluations.values()}
    assert len(candidates) == 1
    deployed = read_json(deployed_path, inputs)
    assert deployed["candidate_commit"] == next(iter(candidates))
    assert {(m["family"], m["seed"]) for m in deployed["models"]} == {
        (f, s) for f in FAMILIES for s in SEEDS}
    audit_cases = {(m["family"], m["seed"], c["config"]["name"]): c
                   for m in deployed["models"] for c in m["cases"]}
    for case in cases:
        audit = audit_cases[(case["family"], case["seed"], case["config"]["name"])]
        case["deployed_value_audit"] = audit
        assert abs(case["controls"]["value"]["return"] - audit["root_policy_value"]) < 2e-10
    lookup = {(c["family"], c["seed"], c["config"]["name"]): c for c in cases}
    names = sorted({c["config"]["name"] for c in cases})
    per_seed_config = []
    for seed in SEEDS:
        for name in names:
            cell = {f"{f}_{label}": lookup[f, seed, name]["controls"][control]["return"]
                    for f in FAMILIES for label, control in
                    (("lightweight", "selected_lightweight"), ("value", "value"))}
            per_seed_config.append({"seed": seed, "config": name, **matrix_metrics(cell)})
    metric_keys = list(matrix_metrics({"ordinary_lightweight": 0., "ordinary_value": 0.,
                                     "analytic_lightweight": 0., "analytic_value": 0.}))
    per_seed = [{"seed": seed, **{key: mean([r[key] for r in per_seed_config if r["seed"] == seed])
                                 for key in metric_keys}} for seed in SEEDS]
    per_config = [{"config": name, **{key: mean([r[key] for r in per_seed_config if r["config"] == name])
                                     for key in metric_keys}} for name in names]
    overall = {key: mean([r[key] for r in per_seed]) for key in metric_keys}
    receipts = []
    for path in sorted((base / "evidence/execution").glob("*.json")):
        item = json.loads(path.read_text())
        if item.get("phase", "").startswith("policy_") or any(
                "deployed_value_audit.py" in str(x) for x in item.get("command", [])):
            inputs[str(path)] = sha(path)
            receipts.append({**item, "full_child_cpu_seconds":
                             item["child_user_seconds"] + item["child_system_seconds"]})
    return {"schema": "hcsn.policy-summary.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
            "candidate_commit": next(iter(candidates)), "deployed_audit_commit": deployed["audit_commit"],
            "summarizer_sha256": sha(Path(__file__)), "input_sha256": inputs,
            "overall": overall, "per_seed": per_seed, "per_config": per_config,
            "per_seed_config": per_seed_config, "cases": cases,
            "boundary_sides": boundaries, "evaluations": evaluations,
            "process_receipts": receipts, "deployed_audit": deployed}


def checks(report):
    cases, evaluations = report["cases"], report["evaluations"]
    exhaustive = [audit for e in evaluations.values()
                  for name, audit in e["independent_exhaustive_execution"].items() if name != "boundary_sides"]
    forced = [a for m in report["deployed_audit"]["models"] for c in m["cases"]
              for a in c.get("forced_first_actual_execution", {}).values()]
    surfaces = [b for c in cases for b in c["task_value_boundaries"]]
    residuals = [abs(b["residual"]) for b in surfaces if b["residual"] is not None]
    curve = [c["root_cost_ray"] for m in report["deployed_audit"]["models"]
             for c in m["cases"] if "root_cost_ray" in c]
    return {"paired_executions": sum(c["paired_summary"]["actual_executions"] for c in cases),
        "exhaustive_executions": sum(a["worlds"] for a in exhaustive),
        "forced_first_executions": sum(a["worlds"] for a in forced),
        "guard_fallbacks": sum(c["paired_summary"]["guard_fallbacks"] for c in cases),
        "ledger_issue_count": sum(len(c["actual"]["ledger_issues"]) for c in cases),
        "ledger_maximum_error": max(c["actual"]["maximum_ledger_arithmetic_error"] for c in cases),
        "state_maximum_error": max([c["paired_summary"]["max_graph_state_error"] for c in cases]
                                    + [a["max_state_error"] for a in exhaustive + forced]),
        "exhaustive_maximum_error": max(a["absolute_error"] for a in exhaustive),
        "forced_first_qpi_maximum_error": max(a["q_deployed_absolute_error"] for a in forced),
        "regret_identity_maximum_error": max(v["performance_identity_error"] for c in cases
            for v in c["controls"].values() if "performance_identity_error" in v),
        "surface_count": len(surfaces), "surfaces_with_crossing": len(residuals),
        "boundary_maximum_residual": max(residuals, default=None),
        "nonmonotone_optimal_cost_rays": sum(not b["nonincreasing"] for b in surfaces),
        "learned_boundary_side_errors": sum(b["learned_first_action_oracle_regret"] > 2e-10
                                            for b in report["boundary_sides"]),
        "deployed_nonmonotone_cost_rays": sum(not c["nonincreasing"]["deployed_continuation_advantage"] for c in curve),
        "predicted_nonmonotone_cost_rays": sum(not c["nonincreasing"]["predicted_continuation_advantage"] for c in curve),
        "positive_prediction_negative_deployed_points": sum(
            r["predicted_continuation_advantage"] > 0 and r["deployed_continuation_advantage"] < 0
            for c in curve for r in c["rows"]),
        "failed_process_phases": [r["phase"] for r in report["process_receipts"] if r["exit_code"] != 0]}


def markdown(report):
    o, c = report["overall"], report["checks"]
    lines = ["# 内容骨干 × 任务价值控制：完整冻结结果", "",
        "本报告区分因果实现正确性、最优教师目标 Q* 的拟合，以及真实部署策略续行 Qπ 的校准。"
        "所有结果来自同一批已冻结权重；汇总器没有训练、重选阈值或读取未完成阶段。", "",
        f"候选提交：`{report['candidate_commit']}`；部署价值审计：`{report['deployed_audit_commit']}`。", "",
        "## 1. 预先指定的 2×2", "",
        "每格为三 seed、四 heldout 参数配置等权的精确有限过程期望。配置不是四个独立自然任务，"
        "精确求期望也不消除训练 seed 不确定性。没有据这三个 seed 宣称显著优效。", "",
        "| 内容骨干 | Dev 选定轻量控制 | 学得任务价值控制 | 控制器效应 |", "|---|---:|---:|---:|"]
    for family in FAMILIES:
        lines.append(f"| {family} | {o[family+'_lightweight']:.9f} | {o[family+'_value']:.9f} | {o['controller_with_'+family]:+.9f} |")
    lines += ["", f"骨干效应：轻量控制下 **{o['backbone_with_lightweight']:+.9f}**；"
        f"任务价值控制下 **{o['backbone_with_value']:+.9f}**。交互效应 D−C−B+A 为 **{o['interaction']:+.9f}**。", "",
        "| Seed | Ordinary/light | Ordinary/value | Analytic/light | Analytic/value | 交互 |",
        "|---:|---:|---:|---:|---:|---:|"]
    for row in report["per_seed"]:
        lines.append(f"| {row['seed']} | {row['ordinary_lightweight']:.9f} | {row['ordinary_value']:.9f} | {row['analytic_lightweight']:.9f} | {row['analytic_value']:.9f} | {row['interaction']:+.9f} |")
    lines += ["", "| Heldout 配置 | Ordinary/light | Ordinary/value | Analytic/light | Analytic/value | 交互 |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in report["per_config"]:
        lines.append(f"| {row['config']} | {row['ordinary_lightweight']:.9f} | {row['ordinary_value']:.9f} | {row['analytic_lightweight']:.9f} | {row['analytic_value']:.9f} | {row['interaction']:+.9f} |")
    lines += ["", "### 全部 seed × 配置，不筛除负结果", "",
        "| Seed | 配置 | Ordinary 控制器效应 | Analytic 控制器效应 | Light 下骨干效应 | Value 下骨干效应 |",
        "|---:|---|---:|---:|---:|---:|"]
    for r in report["per_seed_config"]:
        lines.append(f"| {r['seed']} | {r['config']} | {r['controller_with_ordinary']:+.9f} | {r['controller_with_analytic']:+.9f} | {r['backbone_with_lightweight']:+.9f} | {r['backbone_with_value']:+.9f} |")
    lines += ["", "## 2. 质量、读取、费用和 oracle 差距", "",
        "READ/SKIP 是固定抽象 tariff。下表明确加回费用得到分类正确率；费用下降不能被称作"
        "实际 CPU 或能耗下降。每个表格值等权平均十二个 seed×配置。", "",
        "| 骨干 | 控制 | 正确率 | 净回报 | E[READ] | E[SKIP] | READ 费 | SKIP 费 | Oracle gap |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for family in FAMILIES:
        selected = [x for x in report["cases"] if x["family"] == family]
        for control in ("stop", "fixed", "confidence", "selected_lightweight", "value"):
            vals = [x["controls"][control] for x in selected]
            keys = ("expected_correctness", "return", "expected_reads", "expected_skips",
                    "expected_read_fee", "expected_skip_fee", "gap")
            lines.append(f"| {family} | {control} | " + " | ".join(f"{mean([v[k] for v in vals]):.6f}" for k in keys) + " |")
    lines += ["", "## 3. Q* 与真实 Qπ 的校准分别报告", "",
        "Q* 假设后续最优控制；Qπ 假设第一动作之后始终执行同一冻结 learned policy。"
        "原 ridge 训练目标属于前者。以下是逐配置 RMSE 和 sign accuracy 的等权均值，"
        "不是把各配置 RMSE 冒充全局 pooled RMSE。Uniform 指合法 state-action 对均匀，"
        "occupancy 指实际 π 到达该历史的权重；JSON 保留每个 READ/SKIP 头及分母。", "",
        "| 骨干 | 目标 | 权重 | 平均 RMSE | 平均 sign accuracy |",
        "|---|---|---|---:|---:|"]
    for family in FAMILIES:
        rows = [x["deployed_value_audit"]["calibration"]["advantage_calibration"] for x in report["cases"] if x["family"] == family]
        for target in ("optimal", "deployed"):
            for weighting in ("uniform", "pi_occupancy"):
                values = [x[target][weighting]["all"] for x in rows]
                lines.append(f"| {family} | {'Q*' if target=='optimal' else 'Qπ'} | {weighting} | {mean([v['rmse'] for v in values]):.6f} | {mean([v['sign_accuracy'] for v in values]):.6f} |")
    lines += ["", "## 4. 因果执行与独立枚举", "",
        f"配对实际执行 **{c['paired_executions']:,}** 次；主独立完整世界执行 **{c['exhaustive_executions']:,}** 次；"
        f"forced-first STOP/READ/SKIP 后续同 π 执行 **{c['forced_first_executions']:,}** 次。"
        "这些是执行次数，不能当作彼此独立的训练 seed 或来源样本。", "",
        "| 核对项 | 结果 |", "|---|---:|"]
    for key in ("guard_fallbacks", "ledger_issue_count", "ledger_maximum_error", "state_maximum_error",
                "exhaustive_maximum_error", "forced_first_qpi_maximum_error", "regret_identity_maximum_error"):
        lines.append(f"| {key} | {c[key]} |")
    lines += ["", "实现核对通过只支持所实现合同的一致性；不意味着 learned value 已校准、"
        "学得策略接近 oracle 或解析骨干创造独立净收益。失败阶段：" +
        (", ".join(c["failed_process_phases"]) if c["failed_process_phases"] else "已收集 phase receipts 中没有非零退出。"), "",
        "## 5. 任务价值边界与学得错误", "",
        f"共 {c['surface_count']} 条预定 history 成本射线，{c['surfaces_with_crossing']} 条有严格异号 crossing；"
        f"零点最大残差 {c['boundary_maximum_residual']}。这是 continuation-minus-STOP 的数值零点，"
        "不代表经典 smooth-pasting、唯一膜阈值或连续 PDE 已求解。", "",
        f"边界两侧 learned 第一动作相对 Q* 的错误数：{c['learned_boundary_side_errors']}。"
        f"补充 Qπ 审计的实际续行成本射线非单调数：{c['deployed_nonmonotone_cost_rays']}；"
        f"预测成本射线非单调数：{c['predicted_nonmonotone_cost_rays']}。"
        f"预测续行为正而真实 Qπ 续行为负的网格点：{c['positive_prediction_negative_deployed_points']}。", "",
        "| 骨干/seed | 一侧 | 成本 | Oracle 动作 | Learned 动作 | 第一动作 Q* regret | Learned 完整 gap |",
        "|---|---|---:|---|---|---:|---:|"]
    for b in report["boundary_sides"]:
        lines.append(f"| {b['family']}/{b['seed']} | {b['side']} | {b['read_cost']:.9f} | {b['oracle_root_action']} | {b['learned_root_action']} | {b['learned_first_action_oracle_regret']:.9f} | {b['learned_exact_policy']['gap']:.9f} |")
    lines += ["", "## 6. 实际 CPU 与完整进程成本", "",
        "下表 Python actor 计时含内容 step、控制、guard、实际 raw access、读出、评分及证据 hash，"
        "不含外层 raw-world 生成和 gzip 写出。完整子进程账本另包含 imports、DP 构图、拟合、"
        "独立枚举及序列化；它不是单次生产部署延迟。", "",
        "| 骨干 | 控制 | Actor CPU ms/轨迹 | Controller CPU ms/轨迹 | Content CPU ms/轨迹 |",
        "|---|---|---:|---:|---:|"]
    for family in FAMILIES:
        for control in ("selected_lightweight", "value"):
            rows = [x for x in report["cases"] if x["family"] == family]
            data = [x["actual"]["controllers"][x["selected_kind"] if control == "selected_lightweight" else "value"] for x in rows]
            total = sum(x["executions"] for x in data)
            lines.append(f"| {family} | {control} | {1000*sum(x['cpu'] for x in data)/total:.6f} | {1000*sum(x['phase_cpu'].get('controller',0) for x in data)/total:.6f} | {1000*sum(x['phase_cpu'].get('content_step',0) for x in data)/total:.6f} |")
    lines += ["", "| 完整 phase | 退出码 | Child CPU s | Wall s |", "|---|---:|---:|---:|"]
    for r in report["process_receipts"]:
        lines.append(f"| {r['phase']} | {r['exit_code']} | {r['full_child_cpu_seconds']:.6f} | {r['wall_seconds']:.6f} |")
    lines += ["", "## 7. 证据与适用范围", "",
        "机器可读结果见 [policy_results.json](analysis/policy_results.json)，其中保存每个 seed×配置、"
        "所有负差值、费用、真实执行 phase、Q*/Qπ 双口径、完整成本射线和输入文件 SHA256。"
        "原始轨迹在 evidence/policy/evals 与 evidence/deployed_value 下。", "",
        "这批数据是已知有限双模态生成任务、冻结 width-16 内容模型和小型控制器。"
        "历史 oracle 比压缩 hidden policy 有更多可用的已观测历史表示；其优势不能直接归咎于优化。"
        "内部解析 gate 的期望计数、外部 READ 事件与真实连续 spike/reset 路径保持不同语义。"
        "本报告不把因果一致性升级为大模型能力、Transformer 胜负、能耗或自由边界训练的证明。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--deployed", default="evidence/deployed_value/formal_01/SUMMARY.json")
    args = parser.parse_args()
    base = Path(args.root).resolve()
    report = collect(base, base / args.deployed)
    report["checks"] = checks(report)
    text = markdown(report)
    folder = base / "analysis"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "policy_results.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    with (base / "POLICY_RESULTS.md").open("x") as stream:
        stream.write(text)
    print(json.dumps({"completed": True, "overall": report["overall"], "checks": report["checks"]}))


if __name__ == "__main__":
    main()
