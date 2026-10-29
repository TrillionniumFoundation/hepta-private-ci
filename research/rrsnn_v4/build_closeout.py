"""Read-only evidence checks and descriptive reporting after complete execution."""

from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import statistics

ROOT = Path(__file__).resolve().parent
DATASETS = ("test", "shift", "paired")
LABELS = {
    "rr_full": "完整 RR-SNN", "fp_no_rollover": "删除续约反馈",
    "rr_mean_maturity": "合并期限", "rr_shuffle_maturity": "打乱期限",
    "rr_fixed_boundary": "固定边界", "rr_frozen_resource": "冻结资源",
    "lif": "LIF", "alif": "ALIF", "resource_lif": "资源受限 LIF",
    "ctrnn": "CT-RNN，1 模式", "ctrnn_state": "CT-RNN，8 模式",
    "ctrnn_upper_state": "CT-RNN，20 模式", "alif_analog": "ALIF，连续读出",
    "ctrnn_analog": "CT-RNN，连续读出",
    "ctrnn_state_cpu": "CT-RNN，状态及 CPU 对照",
    "ctrnn_analog_cpu": "CT-RNN，连续读出及 CPU 对照",
}
PATHS = {
    "training": "results/training_summary.json",
    "evaluation": "results/evaluation_matrix_status.json",
    "aggregate": "results/aggregate.json",
    "mechanisms": "results/mechanism_contrasts.json",
    "original_status": "results/numerical_matrix_status.json",
    "repair_status": "results/precision_repair_matrix_status.json",
    "repair": "results/precision_repair_report.json",
    "calibration": "results/probability_calibration/summary.json",
    "behavior": "results/delivery_behavior_diagnostic.json",
    "policy": "policy_benchmark_results/matrix.json",
    "policy_summary": "policy_benchmark_results/summary.json",
    "native": "hepta/r5_local_status.json",
    "bridge": "hepta/rr_bridge_results/trained_latest.json",
    "bootstrap": "hepta/bootstrap_repair_results/proof_latest.json",
    "ci": "hepta/ci_observation/observation.json",
}

def read(name):
    return json.loads((ROOT/name).read_text())

def sha(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()

def ci(value, scale=1, digits=2):
    lo, hi = value["ci95"]
    return f"{value['mean']*scale:.{digits}f} [{lo*scale:.{digits}f}, {hi*scale:.{digits}f}]"

def table(headers, rows):
    return "\n".join(["| "+" | ".join(headers)+" |",
        "| "+" | ".join("---" for _ in headers)+" |",
        *["| "+" | ".join(str(x) for x in row)+" |" for row in rows]])

def load_complete():
    frozen = read("pre_data_freeze.json")
    for name, expected in frozen["source_sha256"].items():
        if sha(name) != expected:
            raise ValueError("Frozen source changed: "+name)
    e = {key: read(name) for key, name in PATHS.items()}
    status = e["evaluation"]
    outputs = [o for run in status["completed"] for o in run["outputs"]]
    if e["training"]["total_completed"] != 80 or not status["all_completed"] or len(status["completed"]) != 80 or len(outputs) != 960:
        raise ValueError("Training/evaluation matrix incomplete")
    for item in outputs:
        if sha(item["path"]) != item["sha256"]:
            raise ValueError("Evaluation raw changed")
    for name, expected in e["aggregate"]["sources_sha256"].items():
        if sha(name) != expected:
            raise ValueError("Aggregate evidence changed: "+name)
    if e["mechanisms"]["main_aggregate_sha256"] != sha(PATHS["aggregate"]):
        raise ValueError("Mechanism source differs")
    if e["behavior"]["aggregate_sha256"] != sha(PATHS["aggregate"]):
        raise ValueError("Behavior diagnostic source differs")
    if not e["original_status"]["all_completed"] or not e["repair"]["all_completed"] or len(e["repair_status"]["outputs"]) != 60:
        raise ValueError("Numerical coverage incomplete")
    if e["repair"]["repair_matrix_status_sha256"] != sha(PATHS["repair_status"]):
        raise ValueError("Repair report source differs")
    p = e["policy"]
    if not p["all_completed"] or p["conditions"] != 80 or len(p["receipts"]) != 80:
        raise ValueError("Resource matrix incomplete")
    for item in p["receipts"]:
        if sha(item["path"]) != item["sha256"]:
            raise ValueError("Resource raw changed")
    if e["aggregate"]["primary_comparator"] != frozen["selection"]["primary_comparator"]:
        raise ValueError("Primary comparator changed")
    return e

def build():
    e = load_complete()
    a, m, repair = e["aggregate"], e["mechanisms"], e["repair"]
    data = a["datasets"]
    primary = a["primary_comparator"]
    gains = {ds: data[ds]["against_primary"]["rr_full"] for ds in DATASETS}
    utility_pass = all(gains[ds]["normalized_expected_gain_percentage_points"]["ci95"][0] > 0 for ds in ("test", "shift"))
    original_pass = repair["totals"]["original"]["event_time_tolerance_failure_rows"] == 0
    repair_pass = repair["all_comparisons_passed"]
    training = {r["variant"]: r for r in e["training"]["variants"]}
    pressure = [r for r in e["policy"]["receipts"] if r["resource_quality"]["status"] != "no_new_cgroup_limit_event_observed"]
    train_pressure = [{"variant": name, "seed": seed, "quality": q}
        for name, row in training.items() for seed, q in zip(row["seeds"], row["resource_quality"])
        if q["status"] != "no_new_cgroup_limit_event_observed"]
    tokens = {}
    tokens["OUTCOME"] = "通过冻结的合成效用主验收，但尚不具备生产资格" if utility_pass else "没有通过冻结的合成效用主验收，应拒绝当前候选晋级"
    tokens["MAIN_GAIN"] = table(["数据集", "RR−主对照效用百分点 [95% CI]", "逐路径负迁移 % [95% CI]"],
        [[ds, ci(gains[ds]["normalized_expected_gain_percentage_points"]),
          ci(gains[ds]["expected_pathwise_negative_transfer_fraction"],100)] for ds in DATASETS])
    tokens["TRAINING"] = table(["模型", "数值状态 B/实例", "验证 NLL", "训练 CPU 秒范围", "更新次数范围"],
        [[LABELS[n], ",".join(str(x) for x in data["test"]["models"][n]["state_numeric_bytes_per_episode"]),
          f"{r['mean_best_validation_nll']:.6f}", f"{min(r['train_cpu_seconds']):.2f}–{max(r['train_cpu_seconds']):.2f}",
          f"{min(r['updates'])}–{max(r['updates'])}"] for n,r in training.items()])
    tokens["UTILITY"] = table(["模型","test % [95% CI]","shift % [95% CI]","paired % [95% CI]"],
        [[LABELS[n],*[ci(data[ds]["models"][n]["normalized_expected_utility"],100) for ds in DATASETS]] for n in LABELS])
    tokens["RAW_GAIN"] = table(["数据集","raw 期望效用差","实际查询效用差","路径×查询负迁移 %"],
        [[ds,ci(gains[ds]["expected_utility_gain"],digits=4),ci(gains[ds]["realized_query_utility_gain"],digits=4),
          ci(gains[ds]["realized_path_query_negative_transfer_fraction"],100)] for ds in DATASETS])
    tokens["BEHAVIOR"] = table(["数据集","RR 内部脉冲/路径","RR 实际输出/路径","主对照输出/路径","RR 零输出路径 %","有脉冲但零输出 %","零输出且终点预算为正 %"],
        [[r["dataset"],f"{r['rr_spikes_vs_semantic_output_means'][0]:.4f}",
          f"{r['rr_spikes_vs_semantic_output_means'][1]:.4f}",f"{r['primary_semantic_output_mean']:.4f}",
          f"{100*r['rr_zero_output_fraction']:.3f}",f"{100*r['rr_spiking_without_output_fraction']:.3f}",
          f"{100*r['rr_zero_output_positive_final_budget_fraction']:.3f}"] for r in e["behavior"]["observed_conclusions"]])
    cf = data["paired"]["counterfactual"]
    tokens["COUNTERFACTUAL"] = table(["模型","A0","A2","B0","B2","交互 (B2−B0)−(A2−A0)"],
        [[LABELS[n],*[ci(cf[n]["expected_utility_by_condition"][c],digits=4) for c in ("A0","A2","B0","B2")],
          ci(cf[n]["shock_interaction_B_minus_A"],digits=4)] for n in ("rr_full",primary,a["secondary_comparator"])])
    tokens["INTERACTION_GAIN"] = ci(data["paired"]["rr_full_shock_interaction_gain_vs_primary"],digits=4)
    tokens["PRE_SHOCK"] = table(["模型","A0 冲击前输出","A2","B0","B2"],
        [[LABELS[n],*[f"{cf[n]['pre_shock_output_count_by_condition'][c]:.4f}" for c in ("A0","A2","B0","B2")]] for n in ("rr_full",primary)])
    ablations = m["all_predeclared_ablations_reported"]
    tokens["ABLATIONS"] = table(["消融","test [95% CI]","shift [95% CI]","paired [95% CI]"],
        [[LABELS[n],*[ci(m["datasets"][ds]["full_minus_ablation"][n]["normalized_expected_gain_percentage_points"]) for ds in DATASETS]] for n in ablations])
    tokens["ABLATION_INTERACTION"] = table(["消融","交互：完整 RR−消融 [95% CI]"],
        [[LABELS[n],ci(m["datasets"]["paired"]["shock_interaction_full_minus_ablation"][n],digits=4)] for n in ablations])
    metrics = [
        ("event_time_tolerance_failure_rows","事件类型／时间合同失败的路径"),
        ("count_disagreement_rows","总内部脉冲 count 不同的路径"),
        ("per_neuron_count_disagreement_rows","逐神经元 count 不同的路径"),
        ("event_type_disagreement_rows","事件类型序列不同的路径"),
        ("action_disagreement_rows","任务行动不同的路径"),
        ("delivered_pulse_disagreement_rows","交付不同的路径"),
        ("budget_disagreement_rows","预算／续约不同的路径")]
    tokens["NUMERIC"] = table(["检查","原始实现","隔离精度修复"],
        [[label,repair["totals"]["original"][key],repair["totals"]["repair"][key]] for key,label in metrics])
    tokens["NUMERIC_SPLITS"] = table(["数据集","原始合同失败路径","修复合同失败路径","修复最大类型对齐时间差"],
        [[ds,repair["by_dataset"][ds]["original"]["event_time_tolerance_failure_rows"],
          repair["by_dataset"][ds]["repair"]["event_time_tolerance_failure_rows"],
          repair["by_dataset"][ds]["repair"]["maximum_type_aligned_event_time_difference"]] for ds in DATASETS])
    tokens["REPAIR_PASS"],tokens["ORIGINAL_PASS"] = str(repair_pass),str(original_pass)
    pooled = e["calibration"]["pooled"]
    tokens["CALIBRATION"] = table(["内部条件发放概率指标","实测"],[
        ["区间×单元预测",pooled["interval_unit_predictions"]],
        ["实际事件／预测总数",f"{pooled['observed_events']} / {pooled['predicted_events']:.6f}"],
        ["无发放右删失区间",pooled["no_spike_right_censored_intervals"]],
        ["Brier／模型条件期望",f"{pooled['brier']:.8f} / {pooled['expected_brier_under_declared_model']:.8f}"],
        ["固定 10 箱 ECE",f"{pooled['ece_10_equal_width_bins']:.8f}"],
        ["标准化条件残差",f"{pooled['martingale_residual_standardized']:.6f}"],
        ["确定概率矛盾",pooled["deterministic_probability_contradictions"]]])
    rows = []
    for count in (64,256,1024,4096):
        for variant in ("rr_full","alif","resource_lif","ctrnn_state_cpu"):
            runs = [r for r in e["policy"]["receipts"] if r["identity"]["variant"] == variant and r["identity"]["policy_instances"] == count]
            if len(runs) != 5:
                raise ValueError("Resource group must retain five seeds")
            med = lambda key: statistics.median(r["summary"][key] for r in runs)
            q = lambda key: statistics.median(r["summary"]["batch_observation_wall_seconds"][key] for r in runs)
            rss = [r["process_peak_rss_mib"] for r in runs]
            npressure = sum(r["resource_quality"]["status"] != "no_new_cgroup_limit_event_observed" for r in runs)
            rows.append([count,LABELS[variant],f"{1000*q('p95'):.3f}",f"{1000*q('p99'):.3f}",
                f"{med('model_only_policy_observations_per_wall_second'):,.1f}",
                f"{med('full_loop_policy_episodes_per_wall_second'):,.1f}",
                f"{statistics.median(rss):.2f} [{min(rss):.2f}, {max(rss):.2f}]",npressure])
    tokens["POLICY_COSTS"] = table(["实例数","策略","批模型步 p95 ms","p99 ms","模型观察/秒","完整回合/秒","进程峰值 RSS MiB 中位 [min,max]","压力数"],rows)
    tokens["NATIVE_COSTS"] = table(["owner 数","实测 tick","tick p95 ms","p99 ms","tick/秒","进程 VmHWM MiB","排队 p95 s","批 p99 s"],
        [[r["instances"],r["actual_owner_ticks_measured"],f"{r['owner_p95_us']/1000:.3f}",
          f"{r['owner_p99_us']/1000:.3f}",f"{r['owner_ticks_per_second']:.2f}",f"{r['peak_rss_bytes']/1048576:.3f}",
          f"{r['queue_p95_us']/1e6:.4f}",f"{r['batch_p99_ms']/1000:.4f}"] for r in e["native"]["component_rows"]])
    tokens["TRAIN_PRESSURE"],tokens["POLICY_PRESSURE"] = str(len(train_pressure)),str(len(pressure))
    tokens["UTILITY_GATE"] = "通过冻结主验收" if utility_pass else "执行完成，拒绝当前候选晋级"
    closeout = {
        "schema":"rrsnn-v4-complete-evidence-closeout-1",
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "report_builder_sha256":sha("build_closeout.py"),
        "template_sha256":sha("REPORT_TEMPLATE.zh-CN.md"),
        "source_evidence":{k:{"path":n,"sha256":sha(n)} for k,n in PATHS.items()},
        "frozen_source_files_verified":len(read("pre_data_freeze.json")["source_sha256"]),
        "execution":{"training_checkpoints":80,"evaluation_files":960,"original_numerical_comparisons":60,
            "repair_comparisons":60,"resource_conditions":80,"all_declared_matrices_completed":True},
        "primary_comparator":primary,"secondary_comparator":a["secondary_comparator"],
        "primary_utility_acceptance_passed":utility_pass,"primary_acceptance_rule_changed":False,
        "original_numerical_gate_passed":original_pass,
        "original_predeclared_engineering_acceptance_passed":original_pass,
        "isolated_precision_repair_stored_path_comparisons_passed":repair_pass,
        "repair_replaces_original_evidence":False,"repair_full_state_rng_equivalence_established":False,
        "internal_probability_sanity_passed":e["calibration"]["all_predeclared_sanity_checks_passed"],
        "external_predictive_calibration_established":False,
        "training_pressure_windows":train_pressure,
        "resource_pressure_windows":[{"identity":r["identity"],"path":r["path"],"sha256":r["sha256"],"quality":r["resource_quality"]} for r in pressure],
        "conditional_bootstrap_repair_passed":e["bootstrap"]["all_passed"],
        "conditional_trained_feature_bridge_passed":e["bridge"]["all_passed"],
        "production_owner_lifecycle_qualified":False,"independent_production_future_window":False,
        "full_cell_scale_qualified":False,"dot_identity_verified":False,
        "full_repository_ci_green":e["ci"]["full_repository_gate_green"],
        "global_resource_maturity_qvi_solved":False,"scientific_novelty_established":False,
        "all_blockers_closed":False,"production_activation_allowed":False,
        "candidate_disposition":"utility_supported_but_not_production_qualified" if utility_pass else "reject_current_frozen_candidate_for_promotion",
        "scope":"Complete fixed synthetic comparison and scoped repair. Negative evidence decides this candidate; unavailable theory and production qualifications remain unestablished."}
    (ROOT/"results/closeout.json").write_text(json.dumps(closeout,indent=2,ensure_ascii=False)+"\n")
    text = (ROOT/"REPORT_TEMPLATE.zh-CN.md").read_text()
    for key,value in tokens.items():
        text = text.replace("@@"+key+"@@",value)
    if "@@" in text:
        raise ValueError("Unfilled report token")
    (ROOT/"REPORT.zh-CN.md").write_text(text)
    print(json.dumps({"report_sha256":sha("REPORT.zh-CN.md"),"closeout_sha256":sha("results/closeout.json"),
        "primary_utility_passed":utility_pass,"original_numerical_gate_passed":original_pass,
        "isolated_repair_passed":repair_pass,"policy_pressure_windows":len(pressure),"all_blockers_closed":False}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        load_complete()
        print(json.dumps({"read_only_evidence_verification": "passed", "reports_rewritten": False}))
    else:
        build()
