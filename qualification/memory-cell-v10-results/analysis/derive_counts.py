"""Read sealed V10 evidence; derive counts without changing models or thresholds."""

import argparse
import hashlib
import json
from pathlib import Path
import time


def load(path):
    return json.loads(Path(path).read_text())


def ratio(a, b):
    return a / b if b else None


def pct(value):
    return "NA" if value is None else f"{100 * value:.2f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.run.resolve() in (args.out.resolve(), *args.out.resolve().parents):
        raise ValueError("analysis must remain outside sealed raw evidence")
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    protocol = load(args.run / "PROTOCOL.json")
    report = {"schema": "hepta.memory.v10.posthoc-counts.v1", "source": str(args.run),
              "derived_after_frozen_evaluation": True, "models_or_thresholds_changed": False,
              "content": [], "composition": [], "routing": [], "pipeline": [],
              "structure": [], "maintenance_cycles": [], "maintenance_summary": [],
              "fit_receipts": [], "input_result_sha256": {}}
    for capacity in protocol["capacities"]:
        for seed in protocol["seeds"]:
            name = f"capacity-{capacity}-seed-{seed}"
            evaluation = args.run / "evaluation" / name
            models = args.run / "models" / name
            result_path = evaluation / "RESULTS.json"
            result, fit = load(result_path), load(models / "FIT.json")
            report["input_result_sha256"][name] = hashlib.sha256(result_path.read_bytes()).hexdigest()
            identity = {"capacity": capacity, "seed": seed}
            for arm, item in result["content"].items():
                report["content"].append({**identity, "arm": arm,
                    **{key: value for key, value in item.items() if key not in ("canonical_predictions", "direct_unseen_predictions", "rows")}})
            for arm, item in result["composition"].items():
                report["composition"].append({**identity, "arm": arm,
                    **{key: value for key, value in item.items() if key != "rows"}})
            for arm, item in result["routing"].items():
                record = {**identity, "arm": arm, **{key: value for key, value in item.items() if key != "rows"}}
                record["wrong_known_accepted"] = item["known_accepted"] - item["known_correct_accepted"]
                record["all_accepted_precision"] = ratio(item["known_correct_accepted"], item["known_accepted"] + item["unknown_accepted"])
                if arm in ("learned", "nearest"):
                    selection = fit["routing"][arm + "_selection"]
                    chosen = next((row for row in selection["candidates"] if row["threshold"] == selection["threshold"]), None)
                    record["calibration_selection"] = selection
                    record["selected_calibration_counts"] = chosen
                report["routing"].append(record)
            for arm, item in result["pipeline"].items():
                report["pipeline"].append({**identity, "arm": arm, **item})
            calibration, held = result["structure_calibration"], result["structure"]
            for arm in ("dynamic_children", "fixed_experts", "rank8"):
                if arm in held["arms"]:
                    h, c = held["arms"][arm], calibration["arms"][arm]
                    report["structure"].append({**identity, "arm": arm,
                        "canonical_correct": h["canonical_correct"], "canonical_count": h["canonical_count"],
                        "calibration_worded_correct": c["worded_correct"], "calibration_worded_count": c["worded_count"],
                        "held_worded_correct": h["worded_correct"], "held_worded_count": h["worded_count"],
                        "oracle_address_condition": True, "proposal_valid": held["proposal_valid"],
                        "calibration_quality_gate": calibration.get("quality_gate"), "admitted": False,
                        "logical_unique_parameter_count": fit["structure"]["arms"][arm]["logical_unique_parameter_count"],
                        "physical_checkpoint_bytes": fit["structure"]["arms"][arm]["physical_checkpoint_bytes"]})
            if "merge" in held:
                report["structure"].append({**identity, "arm": "merge",
                    "canonical_correct": held["merge"]["canonical_correct"], "canonical_count": held["merge"]["canonical_count"],
                    "calibration_worded_correct": calibration["merge"]["worded_correct"], "calibration_worded_count": calibration["merge"]["worded_count"],
                    "held_worded_correct": held["merge"]["worded_correct"], "held_worded_count": held["merge"]["worded_count"],
                    "calibration_no_quality_regression": calibration["merge"]["no_quality_regression"],
                    "admitted": False, "sleep_wake": held["sleep_wake"], "oracle_address_condition": True})
            receipts = [(key, row["fit"]) for key, row in fit["models"].items() if row.get("fit")]
            receipts.append(("routing", fit["routing"]["fit"]))
            receipts += [("structure-" + key, row["fit"]) for key, row in fit["structure"]["arms"].items()]
            if "merge" in fit["structure"]:
                receipts.append(("merge", fit["structure"]["merge"]["fit"]))
            if "maintenance" in fit:
                maintenance = load(evaluation / "MAINTENANCE.json")
                for training_cycle, evaluated_cycle in zip(fit["maintenance"]["cycles"], maintenance["cycles"], strict=True):
                    if training_cycle["cycle"] != evaluated_cycle["cycle"]:
                        raise ValueError("cycle alignment changed")
                    for arm in ("full_replay", "reservoir16"):
                        trained, evaluated = training_cycle["arms"][arm], evaluated_cycle["arms"][arm]
                        record = {"seed": seed, "cycle": training_cycle["cycle"], "arm": arm,
                                  "event": training_cycle["event"], "index": training_cycle["index"],
                                  **{key: evaluated[key] for key in ("canonical_correct", "active_count", "retained_correct", "retained_count", "changed_record_correct", "model_reads_during_denials", "read_wall_seconds")},
                                  "fit_wall_seconds": trained["fit"]["wall_seconds"], "fit_cpu_seconds": trained["fit"]["cpu_seconds"],
                                  "checkpoint_bytes": trained["checkpoint"]["stored_bytes"],
                                  "parameter_sha256": trained["checkpoint"]["parameter_sha256"],
                                  "clean_rebuild_identity_equal": trained["clean_rebuild_identity_equal"],
                                  "lineage_contains_deleted_source": trained["lineage_contains_deleted_source"],
                                  "deleted_read": evaluated["deleted_read"], "stopped_read": evaluated["stopped_read"]}
                        report["maintenance_cycles"].append(record)
                        receipts.append((f"maintenance/{arm}/{training_cycle['cycle']}", trained["fit"]))
                for arm in ("full_replay", "reservoir16"):
                    entries = [row for row in report["maintenance_cycles"] if row["seed"] == seed and row["arm"] == arm]
                    active_correct, active_count = sum(row["canonical_correct"] for row in entries), sum(row["active_count"] for row in entries)
                    retained_correct, retained_count = sum(row["retained_correct"] for row in entries), sum(row["retained_count"] for row in entries)
                    changed = [row for row in entries if row["changed_record_correct"] is not None]
                    worst = min(entries, key=lambda row: row["retained_correct"] / row["retained_count"])
                    report["maintenance_summary"].append({"seed": seed, "arm": arm, "cycles": len(entries),
                        "active_correct_all_cycles": active_correct, "active_count_all_cycles": active_count,
                        "retained_correct_all_cycles": retained_correct, "retained_count_all_cycles": retained_count,
                        "changed_correct_cycles": sum(row["changed_record_correct"] for row in changed), "changed_cycles": len(changed),
                        "worst_cycle": worst["cycle"], "worst_retained_correct": worst["retained_correct"], "worst_retained_count": worst["retained_count"],
                        "final_retained_correct": entries[-1]["retained_correct"], "final_retained_count": entries[-1]["retained_count"],
                        "cycle31_retained_correct": entries[-2]["retained_correct"], "cycle31_retained_count": entries[-2]["retained_count"],
                        "fit_wall_seconds": sum(row["fit_wall_seconds"] for row in entries), "fit_cpu_seconds": sum(row["fit_cpu_seconds"] for row in entries),
                        "retained_checkpoint_bytes": sum(row["checkpoint_bytes"] for row in entries),
                        "denial_model_reads": sum(row["model_reads_during_denials"] for row in entries)})
            for label, receipt in receipts:
                report["fit_receipts"].append({**identity, "stage": label, **receipt})
    process_rows = load(args.run / "PROCESSES.json")
    costs = {"subprocesses": len(process_rows), "all_exit_zero": all(row["exit_code"] == 0 for row in process_rows),
             "process_wall_seconds": sum(row["wall_seconds"] for row in process_rows),
             "process_user_cpu_seconds": sum(row["child_user_cpu_seconds"] for row in process_rows),
             "process_system_cpu_seconds": sum(row["child_system_cpu_seconds"] for row in process_rows),
             "cumulative_peak_rss_kib": max(row["cumulative_child_maxrss_kib"] for row in process_rows),
             "fit_count": len(report["fit_receipts"]), "gradient_steps": sum(row["steps"] for row in report["fit_receipts"]),
             "sample_presentations": sum(row["sample_presentations"] for row in report["fit_receipts"]),
             "nested_fit_wall_seconds_do_not_add_to_process_total": sum(row["wall_seconds"] for row in report["fit_receipts"]),
             "encoder_asset_bytes_shared_once": 127536988, "categories": {}, "active_bundles": [], "stage_processes": process_rows}
    categories = {}
    for path in args.run.rglob("*"):
        if not path.is_file():
            continue
        relative, size = str(path.relative_to(args.run)), path.stat().st_size
        if path.suffix == ".f32":
            category = "all_saved_weight_bytes_including_history_and_candidates"
        elif path.suffix == ".npz":
            category = "all_cached_features_and_pair_targets_npz"
        elif "schedule" in path.name and path.suffix == ".npy":
            category = "sample_schedule_bytes"
        elif path.suffix == ".sqlite":
            category = "exact_sql_databases"
        elif relative.startswith("data/") and path.suffix == ".json":
            category = "source_and_query_json"
        elif "pipeline.jsonl" in relative:
            category = "raw_pipeline_output_jsonl"
        else:
            category = "metadata_receipts_other_targets_and_raw_outputs"
        value = categories.setdefault(category, {"files": 0, "bytes": 0})
        value["files"] += 1
        value["bytes"] += size
    costs["categories"] = categories
    costs["raw_files"] = sum(row["files"] for row in categories.values())
    costs["raw_bytes"] = sum(row["bytes"] for row in categories.values())
    for capacity in protocol["capacities"]:
        models = args.run / "models" / f"capacity-{capacity}-seed-1741"
        weight_bytes = lambda directory: sum(row["bytes"] for row in load(directory / "manifest.json")["arrays"].values())
        costs["active_bundles"].append({"capacity": capacity,
            "content_linear_weights": sum(weight_bytes(models / f"content-{kind}-linear") for kind in ("semantic", "procedure")),
            "content_residual_weights": sum(weight_bytes(models / f"content-{kind}-residual") for kind in ("semantic", "procedure")),
            "typed_composition_weights": sum(weight_bytes(models / f"composition-typed-{i}") for i in (0, 1)),
            "joint_composition_weights": weight_bytes(models / "composition-joint-0"),
            "dense_joint_weights": weight_bytes(models / "composition-dense_joint-0"),
            "learned_router_weights": weight_bytes(models / "router"),
            "canonical_features_logical_f32_bytes": 2 * capacity * 384 * 4,
            "exact_sql_file_bytes": (args.run / "data" / f"capacity-{capacity}" / "exact.sqlite").stat().st_size,
            "source_json_bytes": (args.run / "data" / f"capacity-{capacity}" / "sources.json").stat().st_size})
    costs["encoder_stages"] = {name: load(args.run / "data" / name) for name in ("TRAIN_ENCODER.json", "HELD_ENCODER.json")}
    report["cost"] = costs
    report["analysis_wall_seconds"] = time.perf_counter() - started
    (args.out / "COUNTS.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")

    lines = ["# V10 正式实验完整计数", "", "这是对已封存 raw evidence 的只读统计。模型、阈值、日程和原始证据均未修改。三次 seed 是同一人工任务上的优化重复，不能视作三个独立真实场景。", "",
             "## 参数记忆：每个 seed 与容量", "", "每格是正确数/评估数。canonical 与直接未见措辞分别报告；后者不使用地址 oracle。", "",
             "| 容量 | Seed | 语义 linear canonical | 语义 residual canonical | 程序 linear canonical | 程序 residual canonical | 语义 linear 未见措辞 | 语义 residual 未见措辞 | 程序 linear 未见措辞 | 程序 residual 未见措辞 |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for capacity in protocol["capacities"]:
        for seed in protocol["seeds"]:
            group = {row["arm"]: row for row in report["content"] if row["capacity"] == capacity and row["seed"] == seed}
            cells = []
            for metric, denominator in (("canonical_correct", "canonical_count"), ("direct_unseen_wording_correct", "direct_unseen_wording_count")):
                for kind in ("semantic", "procedure"):
                    for arm in ("linear", "residual"):
                        row = group[f"{kind}-{arm}"]
                        cells.append(f"{row[metric]}/{row[denominator]}")
            lines.append(f"| {capacity} | {seed} | " + " | ".join(cells) + " |")
    lines += ["", "untrained 与实际逐条 SELECT 的 SQL 完整计数也保存在 COUNTS.json；SQL 分别记录 value、key、source ID 一致性。", "",
              "## 新组合", "", "| 容量 | Seed | Arm | 非 hold 精确执行 | 全部精确执行 | 两种参数值都精确 |", "|---:|---:|---|---:|---:|---:|"]
    for row in report["composition"]:
        lines.append(f"| {row['capacity']} | {row['seed']} | {row['arm']} | {row['nonheld_exact']}/{row['nonheld_count']} | {row['exact']}/{row['count']} | {row['both_parameter_values_exact']}/{row['count']} |")
    lines += ["", "## 寻址", "", "已知精确率仅在已接受 known 请求中计算；若零接受则 NA。全部接受精确率还把 unknown 误接受计入分母。", "",
              "| 容量 | Seed | Router | Known 正确/接受/总数 | Known coverage | Known precision | Unknown 接受/总数 | 阈值 |", "|---:|---:|---|---:|---:|---:|---:|---:|"]
    for row in report["routing"]:
        lines.append(f"| {row['capacity']} | {row['seed']} | {row['arm']} | {row['known_correct_accepted']}/{row['known_accepted']}/{row['known_count']} | {pct(row['known_coverage'])} | {pct(row['accepted_known_precision'])} | {row['unknown_accepted']}/{row['unknown_count']} | {row['threshold']} |")
    lines += ["", "## 参数分化", "", "worded 结构读出均在 oracle-address 条件下：真 registry 地址选择保存的 cluster。各 arm 训练后已退出，以下来自 fresh reader。没有候选晋升。", "",
              "| 容量 | Seed | Arm | canonical | calibration wording | held wording |", "|---:|---:|---|---:|---:|---:|"]
    for row in report["structure"]:
        lines.append(f"| {row['capacity']} | {row['seed']} | {row['arm']} | {row['canonical_correct']}/{row['canonical_count']} | {row['calibration_worded_correct']}/{row['calibration_worded_count']} | {row['held_worded_correct']}/{row['held_worded_count']} |")
    lines += ["", "## 持续维护", "", "reservoir16 是每周期从完整 active 列表重新抽取的 16 条 replay；最后周期32是全量清洁重建，因此只看最终值会掩盖此前差异。完整192条 arm×cycle记录在 COUNTS.json。", "",
              "| Seed | Arm | 全周期 retained | 成功更正周期 | 最差 retained (cycle) | Cycle31 retained | Cycle32 retained | fit秒 | 保存checkpoint字节 |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["maintenance_summary"]:
        lines.append(f"| {row['seed']} | {row['arm']} | {row['retained_correct_all_cycles']}/{row['retained_count_all_cycles']} | {row['changed_correct_cycles']}/{row['changed_cycles']} | {row['worst_retained_correct']}/{row['worst_retained_count']} ({row['worst_cycle']}) | {row['cycle31_retained_correct']}/{row['cycle31_retained_count']} | {row['final_retained_correct']}/{row['final_retained_count']} | {row['fit_wall_seconds']:.3f} | {row['retained_checkpoint_bytes']} |")
    lines += ["", "## 成本", "", f"正式运行共{costs['subprocesses']}个子进程，全部exit0；非重叠wall合计{costs['process_wall_seconds']:.6f}s；CPU user={costs['process_user_cpu_seconds']:.6f}s，system={costs['process_system_cpu_seconds']:.6f}s；累计peak RSS={costs['cumulative_peak_rss_kib']}KiB。", "",
              f"执行{costs['fit_count']}次fit、{costs['gradient_steps']}个梯度步骤、{costs['sample_presentations']}次样本呈现。fit内部wall合计{costs['nested_fit_wall_seconds_do_not_add_to_process_total']:.6f}s已包含在上述进程成本内，不能重复相加。", "",
              "| 原始证据类别 | 文件数 | 字节 |", "|---|---:|---:|"]
    for category, row in sorted(categories.items()):
        lines.append(f"| {category} | {row['files']} | {row['bytes']} |")
    lines += ["", "共享encoder另计127,536,988字节。上表是全部候选/历史/原始输出的保留开销；下一表才是单个活动bundle的组成，仍需计来源、manifest、owner状态及共享encoder。", "",
              "| 容量 | Linear内容权重 | Residual内容权重 | Typed权重 | Joint权重 | Dense joint权重 | Learned router权重 | canonical f32缓存 | SQL文件 | 来源JSON |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in costs["active_bundles"]:
        lines.append("| " + " | ".join(str(row[key]) for key in ("capacity", "content_linear_weights", "content_residual_weights", "typed_composition_weights", "joint_composition_weights", "dense_joint_weights", "learned_router_weights", "canonical_features_logical_f32_bytes", "exact_sql_file_bytes", "source_json_bytes")) + " |")
    lines += ["", "## 解释范围", "",
              "固定typed分解在这组未见pair任务中明显优于同预算joint和更大dense joint，仍低于同信息SQL。程序执行相同也可能来自不同参数值，因此两个指标必须并列。容量增长后完整语义记忆、程序记忆和组合能力均明显下降。", "",
              "独立线性基线低于residual，只能说明给定初始化、优化器和固定步骤下的差异。因head可训练，residual仍是 affine map：H(I+BA)x+b，与一个充分训练的线性head属于同一函数族，不能据此声称更高的表达能力或Transformer微调。", "",
              "learned路由的低unknown接受率伴随几乎为零的known coverage；nearest在此冻结门槛下拒绝全部held请求。确定性词表/registry基线在这些完整显式名称和有限操作措辞上达到满分，不能外推为开放域寻址已解决。", "",
              "结构、维护guard与睡眠/唤醒的Python结果不等同于真实owner执行；后者由独立native actual证据证明。维护评估真值来自每周期保存的当前源值；没有把一个逐周期SQL更新服务的成本伪装成实测。原始文件保留，删除重建不表示历史物理抹除。安装、上传、外部host、能耗未在本研究进程计量，没有完整生命周期成本优势结论。", ""]
    (args.out / "COUNTS.md").write_text("\n".join(lines))
    print(json.dumps({"content_rows": len(report["content"]), "composition_rows": len(report["composition"]),
                      "routing_rows": len(report["routing"]), "pipeline_rows": len(report["pipeline"]),
                      "structure_rows": len(report["structure"]), "maintenance_rows": len(report["maintenance_cycles"]),
                      "fit_receipts": len(report["fit_receipts"]), "analysis_seconds": report["analysis_wall_seconds"]}))


if __name__ == "__main__":
    main()
