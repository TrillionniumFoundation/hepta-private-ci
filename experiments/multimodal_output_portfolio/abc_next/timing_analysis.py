"""Complete-census resident timing, paired costs and descriptive quality."""

from collections import Counter
import math

import numpy as np

from ..abc_recovery.statistics import cost_summary, crossed_bootstrap, loss_tails, paired_comparison, rows_to_cube, summarize_utility
from .settings import ARMS, SEEDS
from ..v7.data import VIEWS
from .timing import POLICIES, TIMING_PROFILE, policy_order


def validate_rows(rows, entries, source_pairs):
    """Bind counts, source identities, paired streams and order before statistics."""
    if len(source_pairs) != 16 or any(len(pair) != 2 for pair in source_pairs) or len(set(x for pair in source_pairs for x in pair)) != 32:
        raise ValueError("Expected sixteen registered disjoint source pairs")
    seen = set()
    for row in rows:
        try:
            seed, arm, case, view, scenario, policy = (row[k] for k in ("seed", "arm", "case", "view", "scenario", "policy"))
            if type(seed) is not int or type(case) is not int or type(scenario) is not int or not 0 <= case < 16 or scenario not in (0, 1):
                raise ValueError("Out-of-census request identity")
            group = ((((SEEDS.index(seed) * len(ARMS) + ARMS.index(arm)) * len(VIEWS) + VIEWS.index(view)) * 16 + case) * 2 + scenario)
            identity = seed, arm, case, view, scenario, policy
            if identity in seen or policy not in POLICIES or row["group_ordinal"] != group or row["order_position"] != policy_order(group).index(policy):
                raise ValueError("Duplicate request or incorrect policy rotation")
            if tuple(row["source_ids"]) != tuple(source_pairs[case]) or row["stream_identity_without_arm_or_policy"] != [seed, case, view, scenario]:
                raise ValueError("Unpaired source or owner stream")
            if row["selected_nonfeedback"] != entries[seed, arm]["selection"]["selected_nonfeedback"]:
                raise ValueError("Nonfeedback reference changed after development")
            if row["status"] not in {"completed", "request_failed", "offline_scoring_failed"}:
                raise ValueError("Unregistered request status")
            if any(not math.isfinite(float(row[key])) or row[key] < 0 for key in
                   ("request_wall_ns", "request_cpu_ns", "archive_append_wall_ns", "archive_append_cpu_ns", "scoring_wall_ns", "scoring_cpu_ns")):
                raise ValueError("Missing or invalid actual cost")
            if any(type(v) is not int or v < 0 for v in row["work"].values()):
                raise ValueError("Invalid actual work count")
            seen.add(identity)
        except (KeyError, IndexError) as error:
            raise ValueError("Incomplete resident timing row") from error
    if len(seen) != len(SEEDS) * len(ARMS) * 16 * len(VIEWS) * 2 * len(POLICIES):
        raise ValueError("Incomplete frozen resident timing census")


def aggregate(rows, entries, source_pairs):
    validate_rows(rows, entries, source_pairs)
    profile = TIMING_PROFILE["bootstrap"]
    plan = crossed_bootstrap(len(SEEDS), 16, replicates=profile["replicates"], seed=profile["seed"])
    conditions = [(arm, policy) for arm in ARMS for policy in POLICIES]
    common = dict(seeds=SEEDS, cases=range(16), views=VIEWS, scenarios=range(2))
    cost_rows = [{**{key: row[key] for key in ("seed", "arm", "policy", "case", "view", "scenario")},
        "wall_ms": row["request_wall_ns"] / 1e6, "cpu_ms": row["request_cpu_ns"] / 1e6,
        "wall_with_append_ms": (row["request_wall_ns"] + row["archive_append_wall_ns"]) / 1e6,
        "cpu_with_append_ms": (row["request_cpu_ns"] + row["archive_append_cpu_ns"]) / 1e6} for row in rows]
    costs = rows_to_cube(cost_rows, conditions=conditions, metrics=("wall_ms", "cpu_ms", "wall_with_append_ms", "cpu_with_append_ms"), **common)
    details, quality = {}, {name: {} for name in ("primary", "secondary")}
    for condition in conditions:
        selected = [row for row in rows if (row["arm"], row["policy"]) == condition]
        actual_work = Counter()
        for row in selected:
            actual_work.update(row["work"])
        record = {"statuses": dict(Counter(row["status"] for row in selected)), "observed_requests": len(selected),
            "required_output_completion_rate": float(np.mean([row["required_output_complete"] for row in selected])),
            "actual_work_totals": dict(actual_work),
            "actual_work_mean_per_attempt": {key: value / len(selected) for key, value in actual_work.items()},
            "latency_scope": "all attempted requests, including failures; no outlier removal",
            "cost": {name: cost_summary(values, unit="ms", bootstrap=plan, confidence=profile["confidence"])
                     for name, values in costs[condition].items()},
            "additional_measured_cost_totals_ns": {key: sum(row.get(key, 0) for row in selected) for key in
                ("archive_append_wall_ns", "archive_append_cpu_ns", "scoring_wall_ns", "scoring_cpu_ns")},
            "serialization_totals_for_recorded_completed_serializations_ns": {key: sum(row.get(key, 0) for row in selected) for key in
                ("serialization_wall_ns", "serialization_cpu_ns")},
            "serialized_payload_bytes": sum(row.get("serialized_bytes", 0) for row in selected), "observers": {}}
        for observer in quality:
            missing = sum(row["status"] != "completed" or observer not in row["observer_scores"] for row in selected)
            if missing:
                record["observers"][observer] = {"quality_inference_available": False, "unavailable_rows": missing,
                    "reason": "No failed or unscored request is removed or imputed"}
                quality[observer][condition] = None
                continue
            qrows = [{**{key: row[key] for key in ("seed", "arm", "policy", "case", "view", "scenario")},
                **row["observer_scores"][observer],
                "net_utility": row["observer_scores"][observer]["utility"] - .002 * len(row["completed_path"])} for row in selected]
            metrics = ("utility", "net_utility", "joint_loss", "joint_fact_correct", "required_output_complete",
                       "text_fact", "relation", "image_fact", "crossmodal_disagreement", "pixel_mse")
            cubes = rows_to_cube(qrows, conditions=(condition,), metrics=metrics, **common)[condition]
            quality[observer][condition] = cubes
            record["observers"][observer] = {"quality_inference_available": True,
                "raw_utility": summarize_utility(cubes["utility"]), "step_proxy_net_utility": summarize_utility(cubes["net_utility"]),
                "mean_metrics": {key: float(values.mean()) for key, values in cubes.items()},
                "joint_loss_tails": loss_tails(cubes["joint_loss"])}
        details["/".join(condition)] = record
    comparisons = {}
    for arm in ARMS:
        for reference in ("fixed", "static", "one_shot", "legacy", "selected_nonfeedback"):
            names = [entries[seed, arm]["selection"]["selected_nonfeedback"] if reference == "selected_nonfeedback" else reference for seed in SEEDS]
            ref_cost = {name: np.stack([costs[arm, label][name][i] for i, label in enumerate(names)]) for name in costs[arm, "feedback"]}
            item = {"candidate": [arm, "feedback"], "reference": [arm, reference],
                "frozen_reference_policy_per_training_seed": dict(zip(map(str, SEEDS), names)),
                "cost_increase": {name: cost_summary(costs[arm, "feedback"][name], reference=ref_cost[name],
                    unit="ms", bootstrap=plan, confidence=profile["confidence"]) for name in ("wall_ms", "cpu_ms")}, "observers": {}}
            for observer in quality:
                a = quality[observer][arm, "feedback"]
                refs = [quality[observer][arm, label] for label in names]
                if a is None or any(r is None for r in refs):
                    item["observers"][observer] = {"quality_inference_available": False}
                    continue
                b = {metric: np.stack([ref[metric][i] for i, ref in enumerate(refs)]) for metric in a}
                item["observers"][observer] = {"quality_inference_available": True,
                    "raw_joint_CE_gain": paired_comparison(a["utility"], b["utility"], bootstrap=plan),
                    "step_proxy_net_joint_CE_gain": paired_comparison(a["net_utility"], b["net_utility"], bootstrap=plan),
                    "joint_success_gain": paired_comparison(a["joint_fact_correct"], b["joint_fact_correct"], estimand="success_rate", bootstrap=plan)}
            comparisons[f"{arm}/feedback-minus-{reference}"] = item
    failures = sum(row["status"] != "completed" for row in rows)
    return {"schema": "hepta.abc-next.resident-timing-result.v1", "status": "completed" if not failures else "completed_with_failures",
        "complete_attempt_census": True, "requests": len(rows), "failed_or_unscored_requests": failures,
        "source_pairs": 16, "training_seeds": list(SEEDS), "views": list(VIEWS), "scenarios": 2,
        "rows_are_independent_sample_size": False, "bootstrap_indices_sha256": plan.sha256,
        "inference_scope": "Descriptive paired source-by-seed bootstrap; only 16 timing sources and 5 seeds; no guaranteed coverage or main-test replacement",
        "conditions": details, "comparisons": comparisons, "real_time_utility_price_calibrated": False,
        "no_quality_cost_compensation_claim_from_step_proxy": True}


def write_report(summary, path):
    lines = ["# 新五策略真实串行成本与同源质量诊断", "",
        f"状态：**{summary['status']}**。共 {summary['requests']} 次真实请求，失败或未完成评分 {summary['failed_or_unscored_requests']} 次。",
        "", "每个条件覆盖五个训练 seed、16 个来源对、八个视图和两个生成场景。策略仅执行自己选择的路径；没有其他候选路径的规划成本混入该策略。", "",
        "主请求时间包含 owner RNG、encoder、需要的 public sensor、实际生成、特征、critic/route 与无损 terminal NPZ 序列化及 SHA。模型加载、来源构造、磁盘写入/fsync、离线评分和统计分析单独计量。主时间不含磁盘持久化；完整摘要另报逐请求 archive append 后的成本以及全部 run 成本。", "",
        "## 主请求延迟", "", "单位 ms；所有请求保留，不删除慢请求。区间及完整工作量见 `summary.json`。", "",
        "| 训练臂 / 策略 | Wall mean | Wall P50 | Wall P95 | CPU mean | 完成率 |", "|---|---:|---:|---:|---:|---:|"]
    for name, row in summary["conditions"].items():
        wall, cpu = row["cost"]["wall_ms"]["point_estimates"], row["cost"]["cpu_ms"]["point_estimates"]
        lines.append(f"| {name} | {wall['mean']:.6f} | {wall['p50']:.6f} | {wall['p95']:.6f} | {cpu['mean']:.6f} | {row['required_output_completion_rate']:.6f} |")
    lines += ["", "## 反馈与开发阶段选定最强非反馈策略", "",
        "参考策略在评价前按各 seed/训练臂冻结，当前数据不再选择参考。正的 cost difference 表示更贵；正的 CE gain 表示质量更高。下列区间均为描述性 95% 来源 × seed 配对 bootstrap；两个生成场景、八个视图和重放行数不扩增独立来源 N。", ""]
    for arm in ARMS:
        row = summary["comparisons"][f"{arm}/feedback-minus-selected_nonfeedback"]
        cost = row["cost_increase"]["wall_ms"]
        lines += [f"### {arm}", "", f"冻结参考：`{row['frozen_reference_policy_per_training_seed']}`。", "",
            f"Wall mean 差 {cost['point_estimates']['mean']:+.6f} ms，区间 {cost['intervals']['mean']}；P95 差 {cost['point_estimates']['p95']:+.6f} ms，区间 {cost['intervals']['p95']}。", ""]
        for observer, result in row["observers"].items():
            if result["quality_inference_available"]:
                q = result["raw_joint_CE_gain"]
                lines += [f"{observer} 原始 joint CE 差 {q['gain']:+.6f}，区间 {q['interval']}。", ""]
            else:
                lines += [f"{observer}：存在失败或未评分请求，本条件拒绝生成质量推断。", ""]
    lines += ["## 成本与声明范围", "",
        f"总 runner wall {summary['total_wall_ns'] / 1e9:.6f} 秒；CPU {summary['total_cpu_ns'] / 1e9:.6f} 秒。完整 setup、归档、评分及原始工作量在摘要和本地逐请求账本中。", "",
        "这是主 test 中前 16 个来源的预先注册成本队列。其质量统计不能替换 512 来源主评价。五个 seed 的 bootstrap 仍是有限样本近似；正的点估计不能自动成为优越性结论。0.002 步成本没有被当成实测墙钟价格，当前报告不声称质量收益已抵偿全部现实成本。", "",
        "base 模式不执行 public sensor；enriched 模式计入输入与实际草稿 sensor。旧 legacy 按原算法执行。所有源码、模型与策略在冻结前固定；生成后实际 NPZ 写入本地 archive，关闭并 fsync 后重开校验，才交给离线评分器。", "",
        "Git 保存本详细报告、冻结协议和主要聚合摘要。原始媒体、时钟行和大 ledger 留在本地，不作为长期归档 blocker。", ""]
    path.write_text("\n".join(lines))
