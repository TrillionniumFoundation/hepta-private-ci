"""Real local BGE smoke through the EXISTING audited HF loader and Cell fitter.

Data below are authored diagnostic sentences, not independently sampled tasks.
The fixed mean-pooling recipe is not BGE's standard retrieval evaluation recipe.
No hub access, random-model fallback, model selection or production promotion.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess

import torch

from development_ablation import PhaseClock
from development_learning import LearningRow, read_pinned_json, validate_rows
from development_learning_comparison import (
    ARMS, run_comparison, score_saved_predictions, write_new_json,
)
from shared_encoder_batch import FeatureRequest, FrozenLocalHfBackend, digest_ok, digest_text


# Six training and four heldout authored sentences for each of four topic families.
TEXTS = (
    (("篮球队在决赛中赢得冠军。", "前锋踢进了决定胜负的一球。", "运动员正在准备游泳比赛。",
      "教练带领球员完成赛前训练。", "网球选手击败对手进入半决赛。", "马拉松选手跑过了终点线。"),
     ("守门员扑出了点球。", "球队将在主场迎战强敌。", "乒乓球比赛进入最后一局。", "滑雪选手获得了金牌。")),
    (("银行宣布调整存款利率。", "公司公布了本季度利润。", "投资者正在分析股票价格。",
      "基金经理决定减少债券持仓。", "企业完成了新一轮融资。", "证券交易所发布市场报告。"),
     ("这家公司的股价今天上涨了。", "银行为小企业提供贷款。", "投资组合需要控制风险。", "上市公司发布年度财务报表。")),
    (("工程师发布了新的电脑处理器。", "这款手机使用了更快的芯片。", "研究人员训练了人工智能模型。",
      "软件团队修复了程序漏洞。", "服务器升级后可以处理更多请求。", "机器人利用传感器识别障碍物。"),
     ("开发者正在测试操作系统。", "新型电池提高了设备续航。", "量子计算实验取得进展。", "芯片工厂改进了生产工艺。")),
    (("气象台预计明天有大雨。", "冷空气将带来明显降温。", "沿海地区发布了台风预警。",
      "今天白天气温将升至三十度。", "山区的降雪影响了道路通行。", "天气预报提醒市民防范雷暴。"),
     ("强风预计将在今晚抵达。", "雨后天空出现了彩虹。", "周末大部分地区将持续晴朗。", "浓雾导致早晨能见度下降。")),
)


def authored_fixture(snapshot_sha256, runtime_digest):
    """All labels fixed before fitting; ordinal folds are NOT future observations."""
    if not digest_ok(snapshot_sha256) or not digest_ok(runtime_digest):
        raise ValueError("invalid fixture source identity")
    prep = digest_text("bge-zh-authored-v1:mean:padding:float32:max_tokens=128:no-truncation")
    rows, train, heldout = [], {}, {}
    partitions = ((0, 1), (0, 2), (0, 3), (0,))
    for cell in range(8):
        for split_index, split in enumerate(("train", "heldout")):
            for topic, folds in enumerate(TEXTS):
                for number, text in enumerate(folds[split_index]):
                    key = f"cell.{cell}:{split}:{topic}:{number}"
                    request = FeatureRequest(key, f"cell.{cell}", digest_text("authored-bge-smoke.v1"),
                                             1, digest_text("no-production-authority"), snapshot_sha256,
                                             prep, runtime_digest, digest_text(text), text)
                    # Correlated authored examples are conservatively ONE group per fold.
                    rows.append(LearningRow(request, f"authored-{split}-correlated", split_index + 1, split))
                    (train if split == "train" else heldout)[key] = int(topic in partitions[cell % 4])
    return tuple(rows), train, heldout


def _runtime_identity():
    import transformers
    import safetensors
    return {"torch": torch.__version__, "transformers": transformers.__version__,
            "safetensors": safetensors.__version__, "python": platform.python_version(),
            "device": "cpu", "threads": torch.get_num_threads()}


def run_study(snapshot, expected, output, *, seed=1414):
    """Save all predictions before reading the separate heldout-label file."""
    if type(seed) is not int or not 0 <= seed < 2**31 or not digest_ok(expected):
        raise ValueError("invalid real study envelope")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    runtime = _runtime_identity()
    runtime_digest = hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest()
    rows, train, heldout = authored_fixture(expected, runtime_digest)
    validate_rows(rows, train, classes=2)
    files = {"rows.json": [asdict(r) for r in rows], "train.json": train, "heldout.json": heldout}
    hashes = {name: write_new_json(output / name, data) for name, data in files.items()}
    # Remove heldout gold from this scope before loading/learning. No score-based retries.
    del heldout, files
    manifest = {"snapshot_sha256": expected, "seed": seed, "steps": 80,
                "head_kind": "swiglu", "head_hidden_size": 8, "classes": 2,
                "fixture_files": hashes, "authored_data": True,
                "topic_families": 4, "binary_task_definitions": 4, "cell_replicas_per_task": 2,
                "fold_time_domain": "synthetic_ordinals_not_observed_future",
                "independent_provenance_verified": False, "runtime": runtime,
                "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()}
    write_new_json(output / "predeclared.json", manifest)
    from model_runner import snapshot_digest
    from hf_joint_decision_runner import verify_loaded_safetensors
    clock = PhaseClock()
    backend = FrozenLocalHfBackend(Path(snapshot), expected_snapshot_digest=expected,
                                  preprocessor_digest=rows[0].request.preprocessor_digest,
                                  runtime_digest=runtime_digest, max_tokens=128, device="cpu")
    loading = clock.finish()
    if backend.simulated or backend.model.training or any(p.requires_grad for p in backend.model.parameters()):
        raise ValueError("real frozen eval-only backend required")
    observed_calls = backend.invocations
    result = run_comparison(backend, rows, train, classes=2, steps=80, seed=seed)
    if result["simulated_encoder"] or backend.invocations - observed_calls != sum(
            report["encoder_calls"] for report in result["reports"].values()):
        raise ValueError("physical Encoder call accounting mismatch")
    prediction_hashes = {}
    for name, *_ in ARMS:
        report = result["reports"][name]
        prediction_hashes[name] = write_new_json(output / f"{name}.predictions.json", report["predictions"])
        if prediction_hashes[name] != result["prediction_sha256"][name]:
            raise ValueError("prediction bytes changed while publishing")
        write_new_json(output / f"{name}.report.json", report)
    # Complete source/model immutability checks BEFORE the heldout file is read.
    verification = verify_loaded_safetensors(torch, backend.model, Path(snapshot))
    if snapshot_digest(Path(snapshot)) != expected:
        raise ValueError("snapshot changed during study")
    for name in ("rows.json", "train.json"):
        read_pinned_json(output / name, hashes[name])
    gold = read_pinned_json(output / "heldout.json", hashes["heldout.json"])
    scores = {}
    for name, *_ in ARMS:
        raw = (output / f"{name}.predictions.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != prediction_hashes[name]:
            raise ValueError("saved predictions changed before scoring")
        scores[name] = score_saved_predictions(json.loads(raw), rows, gold, classes=2)
    reports = result.pop("reports")
    result.update({"loading": loading, "verified_loading": backend.verified_loading,
                   "verified_materialization_before": backend.verified_materialization,
                   "verified_materialization_after": verification,
                   "encoder_parameters": sum(p.numel() for p in backend.model.parameters()),
                   "encoder_parameter_bytes": sum(p.numel() * p.element_size() for p in backend.model.parameters()),
                   "snapshot_sha256": expected, "scores_after_prediction_publication": scores,
                   "authored_data": True, "independent_provenance_verified": False,
                   "rss_measured": False, "energy_measured": False,
                   "arm_metrics": {name: {key: report[key] for key in (
                       "whole_call", "encoding", "encoder_calls", "encoded_input_rows", "cache_hits",
                       "peak_cache_estimated_bytes", "materialized_feature_tensor_bytes")}
                       for name, report in reports.items()}})
    write_new_json(output / "summary.json", result)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
    # Negative scores remain evidence, not failures. Numerical inequivalence IS a failed gate.
    if not result["execution_equivalent"]:
        raise ValueError("execution parity gate failed; all four reports retained")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=1414)
    args = parser.parse_args()
    run_study(args.snapshot, args.snapshot_sha256, args.output, seed=args.seed)
