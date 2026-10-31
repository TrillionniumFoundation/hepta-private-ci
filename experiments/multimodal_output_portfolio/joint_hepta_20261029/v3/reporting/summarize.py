"""Readable views of the complete retained matrix; no endpoint selection."""

import hashlib
import json
from pathlib import Path

from ..diagnostics import paired_ce_difference


ROOT = Path(__file__).parents[1]


def read(path):
    return json.loads(path.read_text())


def main():
    matrix = ROOT / "evidence/matrix_frozen_20261030"
    complete = read(matrix / "SUMMARY.json")
    if complete["cells"] != 6:
        raise ValueError("Do not summarize a selected subset")
    cells = []
    for path in sorted(matrix.glob("seed-*-width-*/RESULT.json")):
        source = read(path)
        cell = {"seed": source["seed"], "width": source["width"],
                "original_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "profile_sha256": source["profile_sha256"], "arms": {}, "controls": {},
                "comparisons": source["comparisons"], "phase_costs": source["phase_costs"]}
        for name, arm in source["arms"].items():
            training, evaluation = arm["training"], arm["evaluation"]
            cell["arms"][name] = {"checkpoint": arm["checkpoint"],
                "initial_group_hashes": training["initial_group_hashes"],
                "final_group_hashes": training["final_group_hashes"],
                "initial_stop_training_samples": training["initial_stop_samples"],
                "initial_decisions": training["initial_decisions"],
                "stop_output_row_score_gradient_l1": training["score_only_gradient_max_l1"].get("initial_stop_actor_output_row_max_l1", 0),
                **{key: evaluation[key] for key in ("population_ce_plugin", "mean_net_return", "mean_cost", "mean_utility", "initial_stop_rate", "mean_content_updates", "failures")}}
        for mode, controls in source["inference_controls"].items():
            cell["controls"][mode] = {}
            baseline = controls["encoder_only"]["rows"]
            for name, result in controls.items():
                rows = result["rows"]
                if [(r["source"], r["draw"]) for r in rows] != [(r["source"], r["draw"]) for r in baseline]:
                    raise ValueError("Control sources do not pair")
                cell["controls"][mode][name] = {
                    **{key: result[key] for key in ("population_ce_plugin", "mean_cost", "mean_utility", "initial_stop_rate", "mean_content_updates", "failures")},
                    "minus_encoder_only": paired_ce_difference([r["return"] for r in rows], [r["return"] for r in baseline],
                        source_ids=[r["source"] for r in rows], bootstrap=1000, seed=source["seed"])}
        cells.append(cell)
    report = {"schema": "hepta.v3.readable-complete-matrix", "complete_matrix": complete, "cells": cells,
              "control_contrasts": "Descriptive paired source-bootstrap contrasts of preregistered inference controls, not confirmatory tests.",
              "global_aggregation": "No mean of cell certainty equivalents is reported as a global certainty equivalent.",
              "evidence_restore": "The exact large RESULT.json files, checkpoints and every raw trajectory are in the lossless chunked evidence bundles."}
    path = ROOT / "evidence/MATRIX_READABLE.json"
    path.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    lines = ["# V3 全量开发实验结果", "", "本轮完成预先固定的 3 个随机种子 × 2 个宽度 × 8 个训练组合；以下没有筛除负结果。所有数据属于开发实验，保留确认数据消耗为 0。", "",
        "## 1. 初始 STOP 与四种推理方式", "", "下表每行使用同一个 dual/joint/dynamic 训练模型，仅改变推理策略。数值为实际媒体写出、读回、独立评分并扣除完整单次推理成本后的 gamma=2 确定性等价；越高越好。", "",
        "| 种子 | 宽度 | Encoder-only / STOP | 一次共享更新 | 固定五次更新 | 动态多步 |", "|---:|---:|---:|---:|---:|---:|"]
    for cell in cells:
        c = cell["controls"]["dual"]
        values = [c[name]["population_ce_plugin"] for name in ("encoder_only", "one_shared_update", "fixed_multi", "dynamic_multi")]
        lines.append(f"| {cell['seed']} | {cell['width']} | " + " | ".join(f"{v:.6f}" for v in values) + " |")
    wins = sum(c["controls"]["dual"]["encoder_only"]["population_ce_plugin"] > c["controls"]["dual"]["dynamic_multi"]["population_ce_plugin"] for c in cells)
    lines.extend(["", f"初始 STOP 在训练中被真实采样 **{complete['initial_stop_training_samples']} 次**。同一模型下，encoder-only 的净风险效用在 **{wins}/6** 个端点高于动态策略；这说明继续生成计算需要证明其边际贡献，当前控制器尚未稳定学会在合适时机停止。", "",
        "## 2. 内容训练 × 控制策略 × 普通核心对照", "", "主比较为各自训练后的 dual/joint/dynamic 减 dual/joint/fixed。两臂从同一预训练内容参数出发；联合训练阶段的监督辅助权重为 0。下列区间按 24 个来源成对重采样，每个来源保留两个实际续行，未做多重比较调整。", "",
        "| 种子 | 宽度 | 动态减固定 CE | 来源 bootstrap 95% 区间 |", "|---:|---:|---:|---:|"])
    for row in complete["primary_endpoints"]:
        low, high = row["ce_delta_percentile_95"]
        lines.append(f"| {row['seed']} | {row['width']} | {row['ce_delta']:+.6f} | [{low:+.6f}, {high:+.6f}] |")
    lines.extend(["", "六个端点没有形成稳定增益。完整的 frozen/joint × fixed/dynamic × dual/ordinary 结果、内容冻结哈希、初始 STOP 梯度、每项成本及训练成本摊销，见 `evidence/MATRIX_READABLE.json`。固定策略是预注册的共享、图像、音频、视频、文字各一次更新，未宣称它是搜索过的最强固定策略。", "",
        "## 3. 实际执行规模与成本", "",
        f"- 训练实际轨迹：{complete['training_trajectories']:,}。",
        f"- 主分析实际轨迹：{complete['analysis_trajectories']:,}。",
        f"- 四种推理控制实际轨迹：{complete['inference_control_trajectories']:,}。",
        f"- 六个 cell 进程内全阶段：wall {complete['outer_phase_cost']['wall_seconds']:.3f} 秒，CPU {complete['outer_phase_cost']['cpu_seconds']:.3f} 秒。",
        "- 最终矩阵的编码、策略计算、状态更新、发射、codec、独立评分、账本收尾至 seal 采用连续 CPU/wall 计量；最后一个 sidecar 的写出和训练优化器、归档等由外层阶段账本覆盖。",
        "- 这里的 tariff 是预先定义的抽象计算成本，不是货币报价；共享 CPU 主机的 wall time 不是生产延迟资格。",
        "- 早先中断的 pilot 保留在独立证据包。原因是记录模块拆分期间的源码身份不一致以及复核发现的收尾计量缺口；冻结后完整重跑，未用 pilot 调整训练超参数或筛选端点。", "",
        "## 4. 配对动作价值、验证与独立 critic 校准", "",
        "见 `evidence/diagnostics_frozen_20261030/DIAGNOSTIC_FINDINGS.md` 与 `evidence/diagnostics_frozen_20261030/STUDY_SUMMARY.json`。2,048 条续行从相同冻结前缀、预算和成对未来随机数分支，保存实际四模态文件及独立读回。比较使用 CE(A) − CE(STOP)，不是 CE(A − STOP)。critic 采用 proper conditional exponential-moment loss，并只用独立 fit 来源训练；分析来源不选择参数。", "",
        "## 5. 自由文字与真实 Rust 内容状态", "",
        "`open_domain_notes.md` 给出本轮真实文本解码、内容梯度和独立事实评价。12 条 completion 共 544 个新 token，但正常/零状态/打乱状态三臂的完整事实通过率均为 0/4。自然音频和视频未实现，不能从小型合成媒体结果外推。", "",
        "`native_generation/README.md` 和 `INTEGRATION.md` 给出最终同一训练 checkpoint 的完整 Rust 状态/heads 对照、实际媒体读回、流式前缀和跨进程恢复。该研究后端尚未接入既有 Agentd owner；prefix 已持久化也不等于 actor 已学习流式内容一致性。", "",
        "## 结论范围", "", "本轮建立并执行了可判别的训练、推理、独立评价和原生内容机制。当前证据不支持稳定的动态策略优势、开放域语义资格或一般 NDU 的全局最优解。所有不通过项继续保留为不通过。", ""])
    (ROOT / "RESULTS.zh-CN.md").write_text("\n".join(lines))
    print(json.dumps({"cells": len(cells), "encoder_above_dynamic": wins, "readable_bytes": path.stat().st_size}))


if __name__ == "__main__":
    main()
