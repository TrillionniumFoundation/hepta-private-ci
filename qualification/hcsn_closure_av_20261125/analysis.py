"""Independent NumPy postprocessing, outside the frozen training source closure.

Does not import Torch, models, training metrics, or decoder code. Reads sealed
predictions once; recomputes probabilities and both retrieval definitions.
"""

import argparse
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ident(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def classify(logits, y):
    z = np.asarray(logits, dtype=np.float64)
    if z.shape != (len(y), 6) or not np.isfinite(z).all():
        raise ValueError("invalid classification predictions")
    z = z-z.max(1, keepdims=True)
    denominator = np.exp(z).sum(1)
    probability = np.exp(z)/denominator[:, None]
    prediction = np.argmax(probability, 1)
    correct, confidence = prediction == y, probability.max(1)
    confusion = np.zeros((6, 6), dtype=np.int64)
    np.add.at(confusion, (y, prediction), 1)
    size = confusion.sum(0)+confusion.sum(1)
    macro = np.divide(2*np.diag(confusion), size, out=np.zeros(6), where=size > 0).mean()
    ece = 0.
    for index in range(10):
        chosen = (confidence >= index/10) & (confidence < (index+1)/10 if index < 9 else confidence <= 1)
        if chosen.any():
            ece += abs(correct[chosen].sum()-confidence[chosen].sum())/len(y)
    return {"accuracy": float(correct.mean()), "macro_f1": float(macro),
        "cross_entropy": float((np.log(denominator)-z[np.arange(len(y)), y]).mean()),
        "brier": float(np.square(probability-np.eye(6)[y]).sum(1).mean()), "ece_10": float(ece)}


def pair_metrics(scores, actor=None):
    matrix = scores.copy()
    if actor is not None:
        matrix[actor[:, None] != actor[None, :]] = -np.inf
    order = np.argsort(-matrix, axis=1, kind="stable")
    positions = np.nonzero(order == np.arange(len(order))[:, None])[1]+1
    return {"recall_at_1": float(np.mean(positions == 1)), "recall_at_5": float(np.mean(positions <= 5)),
        "mean_reciprocal_rank": float(np.mean(1/positions)), "mean_rank": float(np.mean(positions))}


def semantic_metrics(scores, y, actors):
    first, ap = [], []
    for index in range(len(y)):
        eligible = np.where(actors != actors[index])[0]
        order = eligible[np.argsort(-scores[index, eligible], kind="stable")]
        positive = np.flatnonzero(y[order] == y[index])
        if not len(positive):
            raise ValueError("missing cross-actor semantic positives")
        first.append(bool(positive[0] == 0))
        ap.append(float(np.mean(np.arange(1, len(positive)+1)/(positive+1))))
    return {"class_recall_at_1": float(np.mean(first)), "mean_average_precision": float(np.mean(ap)),
        "queries": len(y), "relevance": "same acted emotion; exclude all same-actor candidates"}


def metrics(arrays, name, y, actors):
    result = {modality: classify(arrays[name+"_"+modality+"_logits"], y) for modality in ("fused", "audio", "video")}
    a, v = (np.asarray(arrays[name+"_"+modality+"_embedding"], dtype=np.float64) for modality in ("audio", "video"))
    if a.shape != (len(y), 32) or v.shape != a.shape or not np.isfinite(a).all() or not np.isfinite(v).all():
        raise ValueError("invalid paired embeddings")
    a = a/np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    v = v/np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    for direction, scores in (("audio_to_video", a@v.T), ("video_to_audio", v@a.T)):
        result[direction] = pair_metrics(scores)
        result[direction+"_within_actor"] = pair_metrics(scores, actors)
        result[direction+"_cross_actor_semantic"] = semantic_metrics(scores, y, actors)
    result["actor_fused_accuracy"] = {str(actor): classify(arrays[name+"_fused_logits"][actors == actor], y[actors == actor])["accuracy"]
                                        for actor in np.unique(actors)}
    return result


def difference(expected, actual):
    errors = []
    if expected.keys() != actual.keys():
        raise ValueError("metric keys differ")
    for name, value in expected.items():
        other = actual[name]
        if isinstance(value, dict):
            errors.append(difference(value, other))
        elif isinstance(value, str):
            if value != other:
                raise ValueError("metric definition differs")
        else:
            errors.append(abs(float(value)-float(other)))
    return max(errors, default=0.)


def verify(root, source, data_override=None):
    p, seal, final = (read(root/name) for name in ("PROTOCOL.json", "SEAL.json", "FINAL_RESULTS.json"))
    if (len(p["slots"]) != 9 or len({s["id"] for s in p["slots"]}) != 9
            or seal["protocol_sha256"] != ident(p) or final["protocol_sha256"] != ident(p)
            or final["seal_sha256"] != sha(root/"SEAL.json")):
        raise ValueError("incomplete protocol/seal/final binding")
    static = read(source/"qualification/hcsn_closure_av_20261125/protocol.json")
    if any(p.get(key) != value for key, value in static.items()):
        raise ValueError("protocol fields differ from approved source")
    for module, expected in p["source_hashes"].items():
        path = source.joinpath(*module.split(".")).with_suffix(".py")
        if not path.exists():
            path = source.joinpath(*module.split("."))/"__init__.py"
        if sha(path) != expected:
            raise ValueError("frozen executable source changed")
    if set(seal["attempts"]) != {s["id"] for s in p["slots"]}:
        raise ValueError("seal missing slots")
    for slot, files in seal["attempts"].items():
        for name, expected in files.items():
            if sha(root/slot/name) != expected:
                raise ValueError("sealed artifact changed")
    claim = {"protocol_sha256": ident(p), "seal_sha256": sha(root/"SEAL.json")}
    if read(root/"TEST_CLAIM.json") != claim or read(root/"CAMPAIGN_RECEIPT.json")["status"] != "completed":
        raise ValueError("campaign incomplete or test claim invalid")
    data_root = Path(p["data_root"]) if data_override is None else Path(data_override)
    if sha(data_root/"DATASET.json") != p["dataset_sha256"] or read(data_root/"DATASET.json") != p["dataset"]:
        raise ValueError("data descriptor changed")
    test_row = p["dataset"]["splits"]["test"]
    if sha(data_root/test_row["path"]) != test_row["sha256"]:
        raise ValueError("test cache changed")
    with np.load(data_root/test_row["path"], allow_pickle=False) as stream:
        data = {k: stream[k].copy() for k in stream.files}
    canonical = np.stack((np.arange(32)/31, np.full(32, 1/32)), -1).astype(np.float32)
    if any(not np.array_equal(data[m][..., 128:], np.broadcast_to(canonical, (len(data["y"]), 32, 2))) for m in ("audio", "video")):
        raise ValueError("real timing leaked into input")
    indexed = {r["slot"]["id"]: r for r in final["results"]}
    if len(final["results"]) != 9 or set(indexed) != set(seal["attempts"]):
        raise ValueError("incomplete final result roster")
    verified, terminal = [], []
    for slot in p["slots"]:
        directory = root/slot["id"]
        fit, test = read(directory/"result.json"), read(directory/"test_result.json")
        if indexed[slot["id"]] != test or test["slot"] != slot or fit["slot"] != slot:
            raise ValueError("row identity changed")
        for phase in ("", "test_"):
            worker, parent = read(directory/(phase+"worker_cost.json")), read(directory/(phase+"parent_cost.json"))
            expected_exit = 1 if not phase and fit["status"] == "failed" else 0
            expected_status = fit["status"] if not phase else test["status"]
            if worker["error"] is not None or parent["error"] is not None or parent["returncode"] != expected_exit or worker["status"] != expected_status:
                raise ValueError("worker terminal failure or mismatch")
        if read(directory/"TEST_WORKER_CLAIM.json") != {**claim, "slot": slot}:
            raise ValueError("test worker claim mismatch")
        terminal.append({"slot": slot, "fit": fit, "test": test})
        if fit["status"] == "failed":
            if test["status"] != "skipped_failed_fit":
                raise ValueError("failed fit was evaluated")
            continue
        if test["status"] != "evaluated" or sha(directory/"predictions.npz") != test["predictions_sha256"]:
            raise ValueError("prediction identity mismatch")
        with np.load(directory/"predictions.npz", allow_pickle=False) as stream:
            arrays = {k: stream[k] for k in stream.files}
        if any(not np.array_equal(arrays[k], data[k]) for k in ("y", "actor", "clip", "elapsed_seconds", "dt_seconds")):
            raise ValueError("prediction targets/metadata differ from sealed cache")
        for name in ("selected", "initial"):
            expected = metrics(arrays, name, data["y"], data["actor"])
            error = difference(expected, test["metrics"][name])
            verified.append({"slot": slot["id"], "checkpoint": name, "maximum_metric_error": error, "passed": error <= 1e-12})
        duration = data["dt_seconds"].sum(1)
        scores = -np.abs(duration[:, None]-duration[None, :])
        negative = test["duration_only_negative_control"]
        if (difference(pair_metrics(scores), negative["all_candidates"]) > 1e-12
                or difference(pair_metrics(scores, data["actor"]), negative["within_actor"]) > 1e-12):
            raise ValueError("duration reference mismatch")
    if not all(r["passed"] for r in verified):
        raise ValueError("independent metrics failed")
    return p, terminal, {"status": "verified", "models_verified": len(verified), "records": verified,
        "maximum_metric_error": max((r["maximum_metric_error"] for r in verified), default=0.),
        "analysis_source_sha256": sha(__file__), "protocol_sha256": ident(p), "seal_sha256": sha(root/"SEAL.json"),
        "data_location_override": None if data_override is None else str(data_root),
        "scope": "Independent NumPy metric and artifact verification; relocated data allowed only with the exact original descriptor/cache SHA; no model re-execution or new model selection"}


def stats(values):
    return {"count": len(values), "mean": statistics.mean(values) if values else None,
            "sample_sd": statistics.stdev(values) if len(values) > 1 else None, "values": values}


def flatten(value, prefix=""):
    output = {}
    for key, item in value.items():
        name = prefix+key
        if isinstance(item, dict):
            output.update(flatten(item, name+"."))
        elif isinstance(item, (float, int)):
            output[name] = item
    return output


def summarize(root, p, rows, evidence):
    groups = {}
    for arm in ("hcsn", "transformer", "lif"):
        chosen = [r for r in rows if r["slot"]["arm"] == arm]
        good = [r for r in chosen if r["test"]["status"] == "evaluated"]
        maps = [flatten(r["test"]["metrics"]["selected"]) for r in good]
        groups[arm] = {"registered": 3, "evaluated": len(good), "completed_equal_updates": sum(r["fit"]["status"] == "completed" for r in chosen),
            "selected_step0": sum(r["fit"]["selected_step"] == 0 for r in chosen),
            "metrics": {k: stats([m[k] for m in maps]) for k in maps[0]} if maps else {},
            "fused_gain_over_initial": stats([r["test"]["metrics"]["selected"]["fused"]["accuracy"]-r["test"]["metrics"]["initial"]["fused"]["accuracy"] for r in good]),
            "updates": [r["fit"]["updates"] for r in chosen], "selected_steps": [r["fit"]["selected_step"] for r in chosen],
            "counts": [r["fit"]["parameter_accounting"] for r in chosen],
            "training_numerical": [r["fit"]["training_numerical"] for r in chosen]}
    contrasts = {}
    for other in ("transformer", "lif"):
        differences = []
        for seed in (31011, 41011, 51011):
            pair = [next(r for r in rows if r["slot"] == {"id": f"{arm}-s{seed}", "arm": arm, "seed": seed}) for arm in ("hcsn", other)]
            if all(r["test"]["status"] == "evaluated" for r in pair):
                left, right = [flatten(r["test"]["metrics"]["selected"]) for r in pair]
                differences.append({k: left[k]-right[k] for k in left})
        contrasts["hcsn_minus_"+other] = {k: stats([r[k] for r in differences]) for k in differences[0]} if differences else {}
    workers = [read(root/r["slot"]["id"]/name) for r in rows for name in ("worker_cost.json", "test_worker_cost.json")]
    return {"experiment_id": p["experiment_id"], "verified": evidence["status"] == "verified", "groups": groups,
        "paired_descriptive_contrasts": contrasts,
        "duration_only_negative_control": next((r["test"]["duration_only_negative_control"] for r in rows if r["test"]["status"] == "evaluated"), None),
        "costs": {"attempted_update_cpu_seconds": sum(r["fit"]["attempted_update_cpu_seconds"] for r in rows),
            "fit_body_cpu_seconds": sum(r["fit"]["cost"]["cpu_seconds"] for r in rows),
            "worker_cpu_through_receipt_seconds": sum(w["cpu_through_receipt_seconds"] for w in workers),
            "maximum_single_process_rss_bytes": max(w["process_max_rss_bytes"] for w in workers),
            "fit_execution": read(root/"FIT_EXECUTION.json"), "test_execution": read(root/"TEST_EXECUTION.json"),
            "campaign": read(root/"CAMPAIGN_RECEIPT.json"), "energy_joules": None,
            "scope": "Nested body/worker/stage views; do not add them. Feature preparation/acquisition separately retained."},
        "scope": p["scope"], "analysis_policy": p["analysis_policy"], "slots": rows}


def markdown(summary):
    lines = ["# 新演员真实 AV 确认", "", "三臂各3 seeds；统一32步离线低层特征、归一化模型时间、32维embedding和联合CE/InfoNCE。真实片长仅为审计元数据，不进入任何模型。", "",
        "| Model | Fused accuracy | Audio→video paired R@1 | Cross-actor emotion R@1 | Cross-actor mAP | 256-update completion |", "|---|---:|---:|---:|---:|---:|"]
    for name, group in summary["groups"].items():
        def cell(key):
            row = group["metrics"].get(key)
            if row is None or row["mean"] is None:
                return "n/a"
            sd = "n/a" if row["sample_sd"] is None else f"{100*row['sample_sd']:.3f}"
            return f"{100*row['mean']:.3f}% ± {sd}%"
        lines.append(f"| {name} | {cell('fused.accuracy')} | {cell('audio_to_video.recall_at_1')} | {cell('audio_to_video_cross_actor_semantic.class_recall_at_1')} | {cell('audio_to_video_cross_actor_semantic.mean_average_precision')} | {group['completed_equal_updates']}/3 |")
    lines += ["", "均值/SD跨训练seed，8位演员是另一条来源轴；不把192个clip视为192个独立演员，也不据3个seed作普遍显著性结论。所有失败/CPU截尾记录保留在3-seed分母；上表只对实际可评估模型聚合，完整计数、初始模型、每actor、两个检索方向及校准指标在JSON。", "",
        "Paired R@1寻找同一条记录；跨actor语义检索剔除查询演员的所有gallery记录，再以相同acted emotion判相关。二者不能替代彼此。输入特征来自固定音频log-mel/视频低分辨率DCT与全片重采样；此实验不能代表原始媒体端到端预训练、语言理解或全模态生成。", "",
        "同width并非同参数量：HCSN接收端物理特征为20维，其projection与8维baseline不同。完整结构活跃参数、概率/标记/phase状态、token或膜电位逻辑状态及进程峰RSS分开报告，不能把局部状态byte直接当总训练显存。", "",
        "费用见SUMMARY.costs和完整worker/stage回执。更新CPU、body、worker与stage相互包含，禁止相加。获取/解码/预检/失败和等待费用另留原件；能量未测。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    p, rows, evidence = verify(args.root, args.source, args.data_root)
    summary = summarize(args.root, p, rows, evidence)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (("SUMMARY.json", summary), ("INDEPENDENT_METRICS_VERIFICATION.json", evidence)):
        (args.output/name).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n")
    (args.output/"RESULTS_AV.md").write_text(markdown(summary))
    print(json.dumps({"models_verified": evidence["models_verified"], "maximum_metric_error": evidence["maximum_metric_error"],
        "groups": {k: v["metrics"].get("fused.accuracy") for k, v in summary["groups"].items()}}))


if __name__ == "__main__":
    main()
