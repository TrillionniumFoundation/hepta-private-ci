"""Publish a detailed presentation only after the frozen test is complete.

The generator neither selects policies nor changes the frozen analysis. It reads
per-seed observed metrics only after both final result.json and analysis.json
exist and match the registered 512-source, 15-generator experiment. Raw and net
CE differences are calculated separately from their reported CE values; average
action costs are never substituted into the nonlinear risk functional.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO.parent
RUNS = WORKSPACE / "abc3-runs"
OLD = REPO / "experiments/multimodal_output_portfolio/abc_recovery"
EXPECTED_PROTOCOL = "e552230547779d3f92527d62272b115e7d940ff1b56400f5e9347dabfa16a834"
FREEZE_COMMIT = "595d6ea7d728c0d293077bdf19dde31095ab5373"
POLICIES = ("fixed", "static", "one_shot", "feedback", "legacy", "selected_nonfeedback")
ARMS = ("sft_continuation", "output_mean", "output_ndu")
SEEDS = (17, 29, 43, 59, 71)
PRIMARY_KEYS = (("output_ndu/fixed", "output_mean/fixed"),
                ("output_ndu/feedback", "output_ndu/selected_nonfeedback"))


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path, receipts):
    path = Path(path)
    raw = path.read_bytes()
    receipts.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    return json.loads(raw)


def comparison_key(row):
    return "/".join(row["candidate"]), "/".join(row["reference"])


def raw_net_differences(observer):
    result = []
    for row in observer["comparisons"]:
        candidate, reference = comparison_key(row)
        a, b = observer["cells"][candidate], observer["cells"][reference]
        result.append({"candidate": candidate, "reference": reference,
            "primary_contrast": row["primary_contrast"],
            "raw_joint_CE_difference": a["raw_utility"]["joint_ce"] - b["raw_utility"]["joint_ce"],
            "raw_joint_CE_per_seed_difference": [x - y for x, y in zip(a["raw_utility"]["joint_ce_per_seed"], b["raw_utility"]["joint_ce_per_seed"])],
            "raw_interval_reestimated_in_presentation": False,
            "net_joint_CE_difference": a["net_utility"]["joint_ce"] - b["net_utility"]["joint_ce"],
            "net_joint_CE_interval": row["net_joint_CE"]["interval"],
            "net_confidence": row["net_joint_CE"]["confidence"],
            "mean_actions_difference": a["mean_metrics"]["continuation_actions"] - b["mean_metrics"]["continuation_actions"],
            "raw_minus_net_difference_is_not_mean_action_cost": True,
            "joint_success": row["joint_success"],
            "fixed_five_seed_source_interval": row.get("fixed_five_seed_source_interval")})
    return result


def complete_inputs(protocol_path, receipts):
    if sha(protocol_path) != EXPECTED_PROTOCOL:
        raise ValueError("This main-001 renderer requires the published frozen protocol")
    protocol = read(protocol_path, receipts)
    directory = Path(protocol["test_output"])
    # Do not read intermediate model values while either final file is absent.
    if not (directory / "result.json").is_file() or not (directory / "analysis.json").is_file():
        raise RuntimeError("Both completed test result.json and analysis.json are required before opening outcomes")
    execution = read(directory / "result.json", receipts)
    interval = protocol["source_ranges"]["test"]
    if (execution["status"] != "completed" or execution["phase"] != "test"
            or execution["protocol_sha256"] != EXPECTED_PROTOCOL
            or execution["source_range"] != interval
            or interval != {"role": "test", "start": 0, "count": 512, "scenarios": 4}
            or execution["policies_refit_or_selected_here"] or not execution["observer_parameters_unchanged"]):
        raise ValueError("The complete unchanged-policy 512-source execution is not established")
    models = [(row["seed"], row["arm"]) for row in execution["models"]]
    if len(models) != 15 or set(models) != {(seed, arm) for seed in SEEDS for arm in ARMS}:
        raise ValueError("Incomplete frozen generator census")
    analysis = read(directory / "analysis.json", receipts)
    if (analysis["phase"] != "test" or not analysis.get("is_formal_test", False)
            or analysis["protocol_sha256"] != EXPECTED_PROTOCOL
            or analysis["execution_result_sha256"] != sha(directory / "result.json")
            or analysis["source_pairs"] != 512 or analysis["scenarios_per_source"] != 4
            or tuple(analysis["training_seeds"]) != SEEDS or analysis["views"] != protocol["views"]):
        raise ValueError("Final analysis is not bound to the complete frozen test")
    for observer in ("primary", "secondary"):
        cells = analysis["observers"][observer]["cells"]
        if set(cells) != {f"{arm}/{policy}" for arm in ARMS for policy in POLICIES}:
            raise ValueError("Incomplete reported training/policy matrix")
        main = [row for row in analysis["observers"][observer]["comparisons"] if row["primary_contrast"]]
        if len(main) != 2 or tuple(map(comparison_key, main)) != PRIMARY_KEYS:
            raise ValueError("The two registered primary contrasts changed")
        for row in main:
            counts = row["net_joint_CE"]["counts"]
            if counts["source_pairs"] != 512 or counts["training_seeds"] != 5 or counts["observed_rows"] != 81920:
                raise ValueError("Reported source/seed census differs")
            if row["net_joint_CE"]["confidence"] != .975 or row["fixed_five_seed_source_interval"]["confidence"] != .975:
                raise ValueError("Primary confidence levels changed")
    return protocol, execution, analysis


def per_seed_metrics(execution, analysis, controllers, receipts):
    import torch

    selected = {(row["seed"], row["arm"]): row["selection"]["selected_nonfeedback"] for row in controllers["controllers"]}
    output, work, feature_work = [], Counter(), Counter()
    census = Counter()
    for record in execution["models"]:
        seed, arm = record["seed"], record["arm"]
        directory = Path(record["directory"])
        if sha(directory / "data.pt") != record["data_sha256"] or sha(directory / "summary.json") != record["summary_sha256"]:
            raise ValueError("A completed observed model cell changed before reporting")
        summary = read(directory / "summary.json", receipts)
        for view, item in summary["views"].items():
            if not all(item[key] for key in ("actual_media_reopened_before_scoring", "first_decisions_before_children", "second_decisions_before_grandchildren")):
                raise ValueError("Causal/public-state or actual-media evidence is incomplete")
            work.update(item["generation_work"])
            feature_work.update(item["feature_work"])
            census.update({key: item[key] for key in ("node_rows", "selected_policy_rows", "selected_unique_terminal_rows")})
        data = torch.load(directory / "data.pt", weights_only=True)
        if tuple(data["policies"]) != POLICIES[:5] or tuple(data["paths"].shape) != (16384, 5):
            raise ValueError("Observed per-seed policy columns differ")
        for observer in ("primary", "secondary"):
            for policy in POLICIES:
                actual_policy = selected[seed, arm] if policy == "selected_nonfeedback" else policy
                column = POLICIES.index(actual_policy)
                cell = analysis["observers"][observer]["cells"][f"{arm}/{policy}"]
                index = SEEDS.index(seed)
                means = {key: float(values[:, column].double().mean()) for key, values in data["metrics"][observer].items()}
                counts = analysis["plan_counts"][f"{seed}/{arm}/{policy}"]
                if sum(counts) != 16384:
                    raise ValueError("Per-seed complete path census differs")
                # Plan order: stop, four single actions, sixteen double actions.
                mean_actions = (sum(counts[1:5]) + 2 * sum(counts[5:])) / 16384
                tails = cell["joint_loss_tails"]["output_level"]["per_seed"][index]
                if abs(means["joint_loss"] - tails["mean"]) > 1e-10:
                    raise ValueError("Per-seed raw observation and sealed aggregate disagree")
                output.append({"observer": observer, "seed": seed, "arm": arm, "policy": policy,
                    "executed_reference_policy": actual_policy, "raw_joint_CE": cell["raw_utility"]["joint_ce_per_seed"][index],
                    "net_joint_CE": cell["net_utility"]["joint_ce_per_seed"][index],
                    "mean_metrics": means, "mean_continuation_actions": mean_actions,
                    "semantic_then_stop_rate": counts[1] / 16384, "output_joint_loss_tail": tails,
                    "source_mean_joint_loss_tail": cell["joint_loss_tails"]["source_mean_level"]["per_seed"][index],
                    "plan_counts": counts})
        del data
    if census["selected_policy_rows"] != 1228800:
        raise ValueError("Complete observed policy-row census differs from 512-source design")
    return output, {"census": dict(census), "generation_work": dict(work), "feature_work": dict(feature_work),
                    "actual_emission_sample_examples": work["pixel_decoder_panel_examples"] // 2,
                    "scope": "batched paired causal forks and offline scoring, not serial deployment latency"}


def measured_stages(protocol, execution, architecture, controllers, sensor, qualification, receipts, timing):
    stages = []
    process_names = ("public-sensor-001", "architecture-001", "controllers-001", "qualification-001", "qualification-analysis-001", "evaluation-001", "evaluation-analysis-001") + (("timing-001",) if timing is not None else ())
    process_costs = {name: read(RUNS / f"{name}.process.json", receipts) for name in process_names}
    if any(row["exit_code"] != 0 or row["schema"] != "hepta.abc-next.process-receipt.v1" for row in process_costs.values()):
        raise ValueError("The declared completed process-cost receipts are not established")
    for name, value, scope in (
        ("new_public_sensor", sensor, "fit, temperature choice, snapshot and identity checks; entry-scope timer"),
        ("architecture_development", architecture, "new fit/selection tree collection and all four matched candidates"),
        ("all_controllers_development", controllers, "selected architecture for fifteen frozen generators; seed17 selection model reused"),
        ("once_only_qualification", qualification, "104 sources; generation, persistence, readback and both scorers"),
        ("formal_test", execution, "512 sources; batched paired causal forks, actual outputs and offline scorers")):
        stages.append({"stage": name, "wall_seconds": value["wall_ns"] / 1e9,
                       "cpu_seconds": value["cpu_ns"] / 1e9, "scope": scope})
    old_cost_path = WORKSPACE / "abc2-runs/training-001/whole-process-cost.json"
    old_cost = read(old_cost_path, receipts)
    old_training = {"wall_seconds": old_cost["wall_ns"] / 1e9,
                    "cpu_seconds": old_cost["child_cpu_seconds"] + old_cost["parent_cpu_ns"] / 1e9,
                    "scope": old_cost["includes"], "failed_attempt_cost_retained": old_cost["failed_attempt_cost_retained"],
                    "new_generator_training_updates_this_round": 0}
    if timing is not None:
        stages.append({"stage": "serial_timing_cohort", "wall_seconds": timing["total_wall_ns"] / 1e9,
            "cpu_seconds": timing["total_cpu_ns"] / 1e9,
            "scope": "19200 resident requests, archive writing/closing, readback/scoring, setup and aggregation; stage scopes remain explicit"})
    return {"new_round_stages": stages, "sum_reported_stage_wall_seconds": sum(x["wall_seconds"] for x in stages),
            "sum_reported_stage_cpu_seconds": sum(x["cpu_seconds"] for x in stages),
            "complete_process_receipts": process_costs, "process_and_entry_stage_costs_overlap": True, "rss_scope_is_wrapper_children_high_water_not_exclusive_target_peak": True,
            "sum_complete_process_wall_seconds": sum(x["wall_ns"] for x in process_costs.values()) / 1e9,
            "sum_complete_process_cpu_seconds": sum(x["child_cpu_ns"] + x["wrapper_cpu_ns"] for x in process_costs.values()) / 1e9,
            "sum_is_recorded_stage_cost_not_project_lifetime_cost": True,
            "reused_generator_training_process": old_training,
            "new_training_and_development_wall_seconds": sum(x["wall_seconds"] for x in stages[:3]),
            "new_training_and_development_cpu_seconds": sum(x["cpu_seconds"] for x in stages[:3])}


def prepare_summary(protocol_path, timing_path):
    receipts = []
    protocol, execution, analysis = complete_inputs(protocol_path, receipts)
    controllers_path = Path(protocol["controllers_directory"]) / "result.json"
    if sha(controllers_path) != protocol["controllers_result_sha256"]:
        raise ValueError("Development-selected controller census changed")
    controllers = read(controllers_path, receipts)
    architecture_path = RUNS / "architecture-001/result.json"
    if sha(architecture_path) != controllers["selection_result_sha256"]:
        raise ValueError("Architecture development record changed")
    architecture = read(architecture_path, receipts)
    sensor = read(RUNS / "public-sensor-001/result.json", receipts)
    if sensor["checkpoint_file_sha256"] != protocol["resources"]["sensor_sha256"]:
        raise ValueError("Public sensor result is not the frozen sensor")
    qualification_dir = Path(protocol["qualification_output"])
    qualification = read(qualification_dir / "result.json", receipts)
    qualification_analysis = read(qualification_dir / "analysis.json", receipts)
    if (qualification["status"] != "completed" or qualification["protocol_sha256"] != EXPECTED_PROTOCOL
            or qualification_analysis["execution_result_sha256"] != sha(qualification_dir / "result.json")
            or qualification_analysis["phase"] != "qualification" or qualification_analysis["source_pairs"] != 104):
        raise ValueError("Once-only qualification is not bound to this freeze")
    timing = None
    if timing_path is not None:
        timing = read(timing_path, receipts)
        if (timing["status"] not in {"completed", "completed_with_failures"}
                or timing["frozen_protocol_sha256"] != EXPECTED_PROTOCOL
                or timing["requests"] != 19200 or timing["source_pairs"] != 16):
            raise ValueError("Serial timing is incomplete or from another protocol")
    per_seed, work = per_seed_metrics(execution, analysis, controllers, receipts)
    old_analysis = read(OLD / "results/ab-001/summary.json", receipts)
    differences = {name: raw_net_differences(data) for name, data in analysis["observers"].items()}
    return {"schema": "hepta.abc-next.main-detailed-report.v1", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "formal_quality_complete_timing_pending" if timing is None else "formal_quality_and_timing_reported",
        "protocol_sha256": EXPECTED_PROTOCOL, "freeze_published_commit": FREEZE_COMMIT,
        "render_source_sha256": sha(Path(__file__)), "evidence_receipts": receipts,
        "protocol": protocol, "official_frozen_analysis": analysis, "raw_net_contrasts": differences,
        "per_seed_cells": per_seed, "actual_execution_work": work,
        "development": {"architecture": architecture, "controller_choices": [
            {key: item[key] for key in ("seed", "arm", "controller_sha256", "selection")} for item in controllers["controllers"]],
            "sensor_result": sensor}, "qualification": {"execution": qualification, "analysis": qualification_analysis},
        "historical_128_source_summary": old_analysis,
        "measured_costs": measured_stages(protocol, execution, architecture, controllers, sensor, qualification, receipts, timing),
        "timing": timing, "raw_data_embedded": False,
        "timing_provenance": {"prospective_profile_protocol_sha256": EXPECTED_PROTOCOL,
            "profile_was_published_before_main_test_at_commit": FREEZE_COMMIT,
            "runtime_registration_order_when_executed": "After completion of the main 512-source test",
            "runtime_registration_loaded": timing is not None,
            "runtime_false_materialization_flag_scope": "Only this timing invocation has not yet materialized its own cohort/output at its registration; it does not assert that all main-test outcomes were still unopened"},
        "verification": {"python_test_methods": 30, "breakdown": {"observability": 4, "execute": 1,
            "conditional_and_common_history": 9, "value_boundary": 6, "timing_boundary": 6, "analysis_boundary": 4},
            "native_tests_are_separate": 151, "new_tests_run_by_report_generator": False},
        "scientific_limits": {"source_groups": 512, "policy_rows_are_independent_n": False,
            "global_optimality_certified": False, "pure_CE_training_effect_isolated": False,
            "operational_risk_and_aux_treatment_only": True, "new_generator_training_this_round": False,
            "independent_sensor_causal_ablation_established": False,
            "project_wide_familywise_95_coverage_claim": False,
            "generator_encoder_initial_vs_continuous_ablation_performed": False,
            "new_90_features_alone_caused_legacy_gain": False, "real_time_utility_price_calibrated": False,
            "audio_video_or_production_claim_from_this_test": False}}


def f(value, digits=6):
    return f"{value:.{digits}f}"


def ci(values, scale=1):
    return f"[{scale * values[0]:+.6f}, {scale * values[1]:+.6f}]"


def table(lines, headings, rows):
    lines.extend(["", "| " + " | ".join(headings) + " |", "| " + " | ".join("---" for _ in headings) + " |"])
    lines.extend("| " + " | ".join(map(str, row)) + " |" for row in rows)
    lines.append("")


def render(summary, figure_name):
    official = summary["official_frozen_analysis"]
    main = [x for x in official["observers"]["primary"]["comparisons"] if x["primary_contrast"]]
    supported = [row["net_joint_CE"]["interval"][0] > 0 for row in main]
    lead = ("两个预先注册的 net joint CE 主对比均得到正的名义 97.5% 区间下界。" if all(supported)
            else "两个预先注册的 net joint CE 主对比中，" + str(sum(supported)) + " 项得到正的名义 97.5% 区间下界。")
    lines = ["# 新冻结来源：风险训练、公开状态反馈与真实成本", "", "**" + lead + "** 正式评价已完成；这项结论限于本注册任务、训练处理、效用与模型，不能替代成功率、实际成本、全模态或全局最优性的证据。", "",
        "完整数字、逐 seed 数据、逐视图分项、计划计数和输入校验在 [SUMMARY.json](SUMMARY.json)。原始媒体和大数组没有嵌入本报告。", "",
        "## 1. 主要结果与成功率取舍", "",
        "主要统计为每个已训练 seed 内对全部来源、视图和生成场景计算风险 CE，再对五个 seed 算术平均。Primary 两个预先注册对比构成本实验的主要检验家族；Secondary 使用相同区间形式检查评分器稳健性，不增加独立任务数量。", "",
        "名义 97.5% 区间对应本实验两主比较的预注册家族处理。它不提供跨历史实验、开发选择、qualification、文字/语音、原生接入及其他追加分析的全项目 95% 家族错误率保证；本实验 bootstrap 本身的有限样本覆盖也仍是近似。"]
    rows = []
    for observer in ("primary", "secondary"):
        for row in official["observers"][observer]["comparisons"]:
            if row["primary_contrast"]:
                rows.append((observer, " / ".join(comparison_key(row)), f"{row['net_joint_CE']['gain']:+.6f}",
                    ci(row["net_joint_CE"]["interval"]), ci(row["fixed_five_seed_source_interval"]["interval"]),
                    f"{row['joint_success']['gain'] * 100:+.6f}", ci(row["joint_success"]["interval"], 100)))
    table(lines, ("评分器", "比较：candidate / reference", "Net CE 差", "交叉 seed×source 97.5% CI", "固定五 seed 来源 97.5% CI", "成功率差，百分点", "成功率描述性 95% CI，百分点"), rows)
    for row in main:
        success = row["joint_success"]
        interpretation = ("任务成功率的描述性区间完全低于零，CE 改善与成功率下降并存。" if success["interval"][1] < 0
                          else "任务成功率的描述性区间完全高于零。" if success["interval"][0] > 0
                          else "任务成功率区间包含零，不能用 CE 结果替代成功率提升的证明。")
        lines.extend([f"`{' − '.join(comparison_key(row))}`：{interpretation}", ""])
    if figure_name:
        lines.extend([f"![Registered test contrast intervals]({figure_name})", "", "图直接显示已封存分析中的区间，没有重新估计主要统计量。", ""])
    lines += ["## 2. 先冻结后开启：来源和估计对象", "",
        f"最终协议 SHA256 为 `{EXPECTED_PROTOCOL}`，已在 [GitHub commit {FREEZE_COMMIT[:12]}](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/{FREEZE_COMMIT}) 发布，之后才启动正式 test。十五个生成器和控制器、逐 seed/训练臂的开发选定非反馈引用（注册三类候选）以及源身份均在开启前固定。", "",
        "正式数据是 **512 个来源对、1024 个不同 source IDs**，来自 MNIST 官方 test 分区中的冻结角色；开发/qualification 来源来自独立的官方 train 角色。五个训练 seed、八种视图和四个生成场景形成配对重复。每条件 81920 行、十五模型×五策略共 1228800 行策略结果，都不改变来源组数 512。没有可用 writer 聚类身份，不能额外宣称已控制手写者相关性。", "",
        "4000 次交叉重采样同时重采来源对和训练 seed，所有同源视图、场景与策略保持配对。固定五 seed 的区间只重采来源，其解释条件于这五个已经训练好的模型；不能把它当成对训练 seed 母体的同一推断。五个 seed 下交叉 percentile bootstrap 的覆盖率仍是有限样本近似。", "",
        "104 来源 qualification 在同一冻结后只执行一次，没有重新选架构、拟合策略或依据负结果压住 test；它与 512 来源的正式结果分开，不能合并成 616 个确认性来源。"]
    table(lines, ("用途", "来源角色和区间", "数量", "是否可选择策略"), (
        ("共同历史有限律诊断", "forecast_fit[448,480)", "32 对", "仅有限 H1 诊断，不进主 fit"),
        ("新 critic fit", "forecast_fit[480,736)", "256 对", "来源二折交叉拟合"),
        ("架构/非反馈选择", "forecast_calibration[448,576)", "128 对", "开发选择"),
        ("一次 qualification", "development[896,1000)", "104 对", "否"),
        ("正式 test", "test[0,512)", "512 对", "否")))
    lines += ["## 3. 训练处理与 raw/net 风险量", "",
        "生成器权重沿用旧十五个冻结模型，本轮没有新增生成器训练；训练轴在新来源上复验既有操作性处理的泛化差异。本轮新训练的是 public sensor 与控制器。SFT continuation 的监督系数为 1；既有 mean 与 NDU 臂分别使用 gamma→0 与 gamma=2 的实际输出目标，均保留 0.05 辅助项：", "",
        r"\[F_\gamma(\theta)=\frac{E[e^{-\gamma U_\theta}]-1}{\gamma}+0.05 A_\theta,\qquad U=1-2L_{\rm joint}.\]", "",
        "联合损失权重为文字事实 0.30、关系 0.15、图像事实 0.35、跨模态分歧 0.10、像素 MSE 0.10。两个图像识别评分器均离线冻结；它们是该领域不完美的评分器，不是人类认证的通用事实评价。", "",
        r"令 \(M_\gamma=E[e^{-\gamma U}]\)，相对于负 CE 梯度的有效辅助权重为 \(0.05/M_\gamma\)，还伴随整体梯度尺度变化。本轮识别的是该操作性目标变化，不是“纯 CE、相同有效 aux 权重”的完全分离。", "",
        r"raw joint CE 使用 \(C_2(U)\)，net joint CE 使用 \(C_2(U-0.002K)\)，其中 \(K\) 为实际后续非停止动作数。常数成本满足平移不变性；可变 \(K\) 与效用相关时，一般不能把二者差写成 \(0.002E[K]\)。本报告分别从 raw/net 统计直接计算差值。"]
    for observer in ("primary", "secondary"):
        lines.extend([f"### {observer}：全部训练 × 策略单元", ""])
        rows = []
        for arm in ARMS:
            for policy in POLICIES:
                cell = official["observers"][observer]["cells"][f"{arm}/{policy}"]
                metric = cell["mean_metrics"]
                rows.append((arm, policy, f(cell["raw_utility"]["joint_ce"]), f(cell["net_utility"]["joint_ce"]),
                    f(100 * metric["joint_fact_correct"], 4), f(100 * metric["required_output_complete"], 4),
                    f(metric["joint_loss"]), f(metric["crossmodal_disagreement"]), f(metric["continuation_actions"])))
        table(lines, ("训练臂", "策略", "Raw CE", "Net CE", "成功率 %", "完成率 %", "平均联合损失", "跨模态分歧", "平均后续步数"), rows)
    lines += ["### Raw 与 net 差值完整并列", "", "下面 raw 差值来自 raw CE 直接相减，只报点估计；其区间没有在本展示程序中重新估计。不能把 net 主区间复制给可变成本策略的 raw 差值。"]
    for observer in ("primary", "secondary"):
        rows = [(row["candidate"], row["reference"], f"{row['raw_joint_CE_difference']:+.6f}",
                 f"{row['net_joint_CE_difference']:+.6f}", ci(row["net_joint_CE_interval"]), f(row["net_confidence"], 3))
                for row in summary["raw_net_contrasts"][observer]]
        lines.extend([f"#### {observer}", ""])
        table(lines, ("Candidate", "Reference", "Raw CE 点差", "Net CE 差", "Net CI", "置信度"), rows)
    lines += ["## 4. 交互、均值与尾部", "", "交互是四格的描述性差中差；它与两个主比较不同，不以交互结果替换主门槛。"]
    table(lines, ("评分器", "交互", "差中差", "描述性 95% CI"),
          [(name, key, f"{data[key]['gain']:+.6f}", ci(data[key]["interval"]))
           for name, data in official["observers"].items() for key in ("risk_vs_mean_interaction", "risk_vs_sft_interaction")])
    lines.extend(["逐输出尾部先在每个训练 seed 内计算，再平均五个 seed 的 P95/CVaR；来源平均损失尾部先合并同源视图和场景，是另一个估计对象。它们不能被笼统合称为同一尾部风险。CVaR 使用最坏 10% 的精确分数边界质量。", ""])
    for observer in ("primary", "secondary"):
        lines.extend([f"### {observer} 尾部", ""])
        rows = []
        for arm in ARMS:
            for policy in POLICIES:
                cell = official["observers"][observer]["cells"][f"{arm}/{policy}"]
                tails = cell["joint_loss_tails"]
                a, b = tails["output_level"]["mean_across_seed_summaries"], tails["source_mean_level"]["mean_across_seed_summaries"]
                rows.append((arm, policy, f(cell["mean_metrics"]["joint_loss"]), f(a["p95"]), f(a["cvar"]),
                    f(b["p95"]), f(b["cvar"]), f(cell["net_utility"]["mean_conditional_ce"])))
        table(lines, ("训练臂", "策略", "均值损失", "逐输出 P95", "逐输出 CVaR90", "来源均值 P95", "来源均值 CVaR90", "平均 conditional net CE"), rows)
    lines += ["## 5. 分视图和缺失信息", "",
        "以下列出 NDU 的新反馈、固定、开发选定非反馈和旧反馈的全部视图，完整三训练臂×六策略×八视图数据保留在 SUMMARY.json。物理模态完成与任务事实正确分别评价；完全缺失输入不能通过 sensor 凭空恢复私有目标。"]
    for observer in ("primary", "secondary"):
        rows = []
        for view in official["views"]:
            for policy in ("fixed", "selected_nonfeedback", "feedback", "legacy"):
                data = official["observers"][observer]["cells"][f"output_ndu/{policy}"]["by_view"][view]
                rows.append((view, policy, f(data["net_joint_CE"]), f(100 * data["joint_success"], 4),
                             f(100 * data["complete"], 4), f(data["mean_loss"])))
        lines.extend([f"### {observer}", ""])
        table(lines, ("视图", "NDU 策略", "Net joint CE", "成功率 %", "完成率 %", "平均损失"), rows)
    lines += ["## 6. 开发选择与旧/新比较的归因边界", "",
        "只在 seed17 NDU 的新开发来源上选择四个匹配候选。四者共有新 fit 数据、来源二折 OOF target、相同步数与 H1 semantic 支配约束；673/763 维及 32/128 hidden 是显式轴。被选中的是 enriched-32。这是架构选择数据；独立最终 test 没有复验全部 sensor 开/关候选，因此下表不构成独立留出集上的 sensor 因果消融证明。"]
    table(lines, ("开发候选", "反馈 Net CE", "反馈成功率 %", "平均后续步数", "拟合及选择 wall 秒"),
          [(row["candidate"], f(row["selection"]["metrics"]["feedback"]["net_joint_CE"]),
            f(100 * row["selection"]["metrics"]["feedback"]["joint_success"], 4),
            f(row["selection"]["metrics"]["feedback"]["mean_actions"]), f(row["fit_and_selection_wall_ns"] / 1e9, 3))
           for row in summary["development"]["architecture"]["candidates"]])
    lines += ["新反馈相对 legacy 的同源正式对比识别的是整个控制器更新包：新训练数据、来源 OOF、H1 支配约束和公开特征改变。不能把其全部差值归因于 90 个新公开特征。one-shot 与反馈匹配 sensor、输入维度、hidden=32、来源、风险目标口径和逐 head 训练配置；不匹配总参数量或总训练计算。排除共享 sensor 后，每个 5 输出 Q head 有 24613 个参数，Q1+Q2 共 49226，21 输出 route head 有 25141；Q1 还经历 OOF/refit。one-shot 使用独立 route head，其训练没有替代或共同训练反馈 head。正式收益识别整套反馈方法，尚未单独隔离持续观测信息或 head 容量的贡献。最终 test 只运行开发选定架构，未把四候选全部在 test 重选。", "",
        "one_shot / initial-only controller 在初始公开历史一次决定完整后续路线；它检验控制器是否持续读取实际生成状态。生成器随后仍使用相同的 persistent encoder context，故这一对比不是生成器的 encoder-initial-only 与持续 Encoder 条件访问消融。本轮没有执行该生成器条件访问轴的独立消融或相应架构重训。", "",
        "public sensor 是第三个独立训练 reader，使用 train role；原始公开输入、mask、提示可靠性和实际当前草稿进入其特征。Primary/Secondary 评分器不进入在线策略。温度选择只用了 train role 尾部，它给出预测语义概率，没有形成精确 Bayesian 后验或独立目标域校准证书。", "",
        "H1 semantic 保留当前两模态输出而多支付 0.002，故新候选统一禁止该最后一步动作；H2 首步 semantic 可用于后续修正并保留。先 semantic 再 stop 仍可能是近似 Q2/Q1 联合选择的结果；其频率完整保留在 SUMMARY.json 和计划计数中。", ""]
    table(lines, ("seed", "训练臂", "开发选定非反馈", "静态计划 index", "控制器 SHA256"),
          [(row["seed"], row["arm"], row["selection"]["selected_nonfeedback"], row["selection"]["static_plan_index"], row["controller_sha256"])
           for row in summary["development"]["controller_choices"]])
    lines.extend(["### 历史 128 来源与本次 512 来源", "",
        "旧结果是已经看过的开发来源；本次是新冻结官方 test 角色，两者没有合并成新样本或做跨队列的配对差值。旧 feedback−fixed 主比较与本次 feedback−开发选定非反馈主比较的参照也不同。真正同源的旧/新控制器比较应读取本次 `feedback − legacy`。", ""])
    old = summary["historical_128_source_summary"]["scientific_support_flags"]["primary_checks"]
    table(lines, ("历史主比较", "旧128来源 Net CE差", "旧 nominal 97.5% CI"),
          [(name, f"{row['gain']:+.6f}", ci(row["interval"])) for name, row in old.items()])
    lines += ["### 104 来源 qualification，保持单列", ""]
    table(lines, ("评分器", "比较", "Net CE差", "交叉 97.5% CI"),
          [(observer, " − ".join(comparison_key(row)), f"{row['net_joint_CE']['gain']:+.6f}", ci(row["net_joint_CE"]["interval"]))
           for observer, data in summary["qualification"]["analysis"]["observers"].items()
           for row in data["comparisons"] if row["primary_contrast"]])
    lines += ["## 7. 真实计算、训练和延迟", "",
        "每步 0.002 是声明的效用代理价格。真实时间、计算和训练成本分开记录；没有外部标定的毫秒效用价格，因此 CE 过门本身不证明收益覆盖全部现实成本。主评价采取配对 causal forks 并离线评分，其批量耗时不是某个策略的独立部署延迟。"]
    costs = summary["measured_costs"]
    table(lines, ("本轮阶段", "记录 wall 秒", "记录 CPU 秒", "计时范围"),
          [(row["stage"], f(row["wall_seconds"], 3), f(row["cpu_seconds"], 3), row["scope"]) for row in costs["new_round_stages"]])
    lines += ["以下完整进程凭据覆盖 subprocess 启动、导入、退出与日志 flush，另列统计分析；不含最后 receipt 自身的写入。它们与上表入口阶段计时重叠，不能相加。CPU 分列已回收 child 的前后增量与 wrapper。RSS 字段来自 RUSAGE_CHILDREN 累计高水位，未保存前序 child 基线，保守解释为 wrapper 范围，不能声称是目标 child 独有的精确峰值。", ""]
    table(lines, ("完整进程", "Wall 秒", "Child CPU 秒", "Wrapper CPU 秒", "Wrapper children 高水位 RSS bytes"),
          [(name, f(row["wall_ns"] / 1e9, 6), f(row["child_cpu_ns"] / 1e9, 6), f(row["wrapper_cpu_ns"] / 1e9, 6), row["child_maximum_rss_bytes"]) for name, row in costs["complete_process_receipts"].items()])
    lines += [f"这 {len(costs['complete_process_receipts'])} 个已记录进程合计 wall {f(costs['sum_complete_process_wall_seconds'], 6)} 秒、child 加 wrapper CPU {f(costs['sum_complete_process_cpu_seconds'], 6)} 秒；计入的流程以上表为准，不包括报告渲染、其他实验或未保留的历史尝试。", ""]
    lines += [f"新增 sensor、架构开发和全控制器开发合计记录 wall **{f(costs['new_training_and_development_wall_seconds'], 3)} 秒**、CPU **{f(costs['new_training_and_development_cpu_seconds'], 3)} 秒**。这些阶段包含其数据生成、离线评分、训练和选择；不能再次把嵌套 head 训练时间加上造成重复计数。", "",
        f"复用的旧十五生成器训练进程另有 wall {f(costs['reused_generator_training_process']['wall_seconds'], 3)} 秒、CPU {f(costs['reused_generator_training_process']['cpu_seconds'], 3)} 秒的记录，本轮新增生成器更新为零。该旧 receipt 没有保留全部此前失败尝试成本，阶段计时范围也各自明确；上述数字不声称覆盖整个项目生命周期。", ""]
    work = summary["actual_execution_work"]
    table(lines, ("正式执行计数", "数量"), (("真正来源对", 512), ("策略结果行", work["census"]["selected_policy_rows"]),
        ("实际候选状态/终端节点行", work["census"]["node_rows"]), ("按选择去重的终端行", work["census"]["selected_unique_terminal_rows"]),
        ("实际 emission 样本", work["actual_emission_sample_examples"])))
    timing = summary["timing"]
    if timing is None:
        lines += ["**真实串行 timing 尚未执行/并入，延迟与完整质量—成本比较保持待完成。** 已冻结的 timing 队列为 test 前 16 来源、五 seed、三训练臂、八视图、两个生成场景、五策略，共 19200 次请求；应等并行重负载结束后执行。当前不使用主批量执行 wall 推断 P50/P95。", ""]
    else:
        lines += [f"真实串行队列状态：**{timing['status']}**，{timing['requests']} 次请求，失败或未评分 {timing['failed_or_unscored_requests']} 次。每次只执行自身策略路径，循环轮换策略顺序；base 无 sensor forward，enriched 计入原输入和实际草稿 sensor。", "",
            f"计时的真正事前绑定来自主 test 开启前发布的 `{EXPECTED_PROTOCOL}` 协议及其中的 TIMING_PROFILE。timing runner 的 runtime registration 在主 512 来源正式评价完成后才写入；其 `test_outcomes_materialized_before_registration=False` 仅指本次 timing 调用在登记前尚未物化自己的队列/输出，不表示整个项目或主 test 的结果此前未被读取。队列、策略与计时流程仍遵循原预冻结协议，此处只是澄清记录的时间范围。", "",
            "主请求从 owner RNG/initialize 开始，包含 encoder、实际生成、公开特征、决策及无损 NPZ 内存序列化和 SHA；模型加载、来源构造、磁盘 archive append/fsync、离线评分、聚合单独记账。主 P50/P95 不含磁盘持久化和离线评分，完整 SUMMARY 同时保留含 append 的成本及各阶段总账。"]
        table(lines, ("训练臂/策略", "Wall mean ms", "Wall P50 ms", "Wall P95 ms", "CPU mean ms", "完成率 %"),
              [(key, f(row["cost"]["wall_ms"]["point_estimates"]["mean"]), f(row["cost"]["wall_ms"]["point_estimates"]["p50"]),
                f(row["cost"]["wall_ms"]["point_estimates"]["p95"]), f(row["cost"]["cpu_ms"]["point_estimates"]["mean"]),
                f(100 * row["required_output_completion_rate"], 4)) for key, row in timing["conditions"].items()])
        lines += ["完整配对来源×seed 描述性 95% 成本区间、各对照差值及同队列质量在 SUMMARY 的 timing 部分，另见[串行计时详报](TIMING_REPORT.md)与[原始聚合摘要](TIMING_SUMMARY.json)。16 来源为同一 512 来源主 test 的预注册子集，不构成额外独立确认，也不替换主统计；所有请求与慢请求均保留，失败时受影响条件的质量推断被阻止。", ""]
        timed = timing["comparisons"]["output_ndu/feedback-minus-selected_nonfeedback"]
        lines += [f"在该计时子队列，NDU 新反馈相对开发选定非反馈的平均 Wall 增量为 {f(timed['cost_increase']['wall_ms']['point_estimates']['mean'])} ms，描述性 95% 区间 {ci(timed['cost_increase']['wall_ms']['intervals']['mean'])}；P95 增量为 {f(timed['cost_increase']['wall_ms']['point_estimates']['p95'])} ms，区间 {ci(timed['cost_increase']['wall_ms']['intervals']['p95'])}。这是真实时间成本增加，不能用主 test CE 通过直接宣称其已获补偿。", ""]
        for observer, value in timed["observers"].items():
            if not value["quality_inference_available"]: continue
            lines += [f"计时子队列 {observer}：NDU 新反馈减开发选定非反馈的 raw CE 差 {value['raw_joint_CE_gain']['gain']:+.6f}，95% 区间 {ci(value['raw_joint_CE_gain']['interval'])}；0.002 步代理 net CE 差 {value['step_proxy_net_joint_CE_gain']['gain']:+.6f}，区间 {ci(value['step_proxy_net_joint_CE_gain']['interval'])}；成功率差 {100 * value['joint_success_gain']['gain']:+.6f} 个百分点，区间 {ci(value['joint_success_gain']['interval'], 100)}。均为描述性子队列结果。", ""]
    lines += ["## 8. 范围、验证和仍未建立的结论", "",
        "本轮独立 Python 验证共 30 个测试方法：observability 4、execute 1、共同历史/数值 9、value 边界 6、timing 边界 6、analysis 边界 4。原生 151 项验证另列在原生报告，本表不合并为统计样本。报告生成器不重训、不重选，也不重跑这些测试。", "",
        "旧共同历史诊断区分了公开信息可实现选择与隐藏目标/未来 oracle 优势，并发现 H1 支配错误；它不是本次 512 来源的额外独立样本。[共同历史详报](../../design/COMMON_HISTORY_REVIEW.md) 保留其宽区间和未识别结论。", "",
        "本报告不证明神经状态充分性、正确的全部条件动力学、均匀价值误差界、H2 全局最优性或端到端联合全局训练最优性。它也不单独识别纯风险目标、aux 有效尺度和旧 v6 gate/surrogate 的全部贡献。真实文字/语音及原生 admitted tick 证据应在各自报告中审查，不能由这项图文 task 推导一般全模态或生产接入结论。", "",
        "Git 保存冻结协议、主要详细报告、聚合数据和可复核代码。原始实际媒体、source级数组和大 ledger 保留本地；大文件长期归档不是本轮 blocker。", "",
        "## 附录 A：全部五 seed × 三训练臂 × 五策略及冻结非反馈引用", "",
        "每个单元使用相同的 512 来源、八视图和四场景。尾部为该单一 seed 的逐输出联合损失，数值完整来源于已封存结果。selected_nonfeedback 是已运行策略的引用，不增加新生成或独立观察。"]
    for observer in ("primary", "secondary"):
        for arm in ARMS:
            lines.extend([f"### {observer} / {arm}", ""])
            rows = []
            for seed in SEEDS:
                for policy in POLICIES:
                    row = next(x for x in summary["per_seed_cells"] if (x["observer"], x["arm"], x["seed"], x["policy"]) == (observer, arm, seed, policy))
                    m, tail = row["mean_metrics"], row["output_joint_loss_tail"]
                    rows.append((seed, policy, row["executed_reference_policy"] if policy == "selected_nonfeedback" else "—",
                        f(row["raw_joint_CE"]), f(row["net_joint_CE"]), f(100 * m["joint_fact_correct"], 4),
                        f(100 * m["required_output_complete"], 4), f(m["joint_loss"]), f(tail["p95"]), f(tail["cvar"]), f(row["mean_continuation_actions"])))
            table(lines, ("seed", "策略", "引用", "Raw CE", "Net CE", "成功率 %", "完成率 %", "平均损失", "损失 P95", "损失 CVaR90", "平均步数"), rows)
    lines += ["## 附录 B：证据身份", "", f"报告生成器 SHA256：`{summary['render_source_sha256']}`。最终报告生成时间：`{summary['generated_at_utc']}`。", "",
        "SUMMARY.json 包含每份输入报告的完整 SHA256 和原始本地路径，以及原封存 analysis 的全部聚合字段；没有把未执行的数据、缺失结果或晚选的 oracle 填入正式结果。", ""]
    return "\n".join(lines)


def plot_primary(summary, destination):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as error:
        return {"created": False, "reason": str(error)}
    fig, ax = plt.subplots(figsize=(10.8, 4.8))
    labels = []
    for observer_index, observer in enumerate(("primary", "secondary")):
        rows = [r for r in summary["official_frozen_analysis"]["observers"][observer]["comparisons"] if r["primary_contrast"]]
        for index, row in enumerate(rows):
            y = 3 - (observer_index * 2 + index)
            for shift, data, color, style, marker in (
                (.09, row["net_joint_CE"], "#195ca8", "solid", "o"),
                (-.09, row["fixed_five_seed_source_interval"], "#d36a2d", "dashed", "s")):
                ax.hlines(y + shift, *data["interval"], color=color, linewidth=2, linestyles=style)
                ax.plot(data["gain"], y + shift, marker=marker, color=color, markersize=6)
            labels.append((y, f"{observer.title()}: " + ("NDU - mean, fixed" if index == 0 else "Feedback - development-selected nonfeedback")))
    ax.axvline(0, color="#666666", linewidth=1)
    ax.set_yticks([y for y, _ in labels], [label for _, label in labels])
    ax.set_xlabel("Net joint CE difference (higher favors candidate)")
    ax.set_title("Frozen 512-source test: registered contrasts\nNominal 97.5% intervals; 5 fitted training seeds", loc="left")
    ax.plot([], [], color="#195ca8", marker="o", label="Crossed source and seed bootstrap")
    ax.plot([], [], color="#d36a2d", marker="s", linestyle="--", label="Source bootstrap; five fitted seeds fixed")
    ax.legend(loc="best", fontsize=9)
    ax.grid(axis="x", alpha=.2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(destination, dpi=180, facecolor="white")
    plt.close(fig)
    return {"created": True, "filename": destination.name, "sha256": sha(destination),
            "reestimated_statistics": False, "source": "official frozen analysis intervals"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=RUNS / "formal-protocol-001.json")
    parser.add_argument("--timing", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results/main-001")
    args = parser.parse_args()
    summary = prepare_summary(args.protocol, args.timing)
    args.output.mkdir(parents=True, exist_ok=True)
    plot = plot_primary(summary, args.output / "primary-contrasts.png")
    summary["figure"] = plot
    report = render(summary, plot["filename"] if plot["created"] else None)
    for name, text in (("SUMMARY.json", json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"),
                       ("REPORT.md", report)):
        temporary = args.output / (name + ".new")
        temporary.write_text(text)
        temporary.replace(args.output / name)
    print(json.dumps({"status": summary["status"], "report": str(args.output / "REPORT.md"),
                      "summary_sha256": sha(args.output / "SUMMARY.json"), "test_source_pairs": 512,
                      "timing_included": summary["timing"] is not None}), flush=True)


if __name__ == "__main__":
    main()
