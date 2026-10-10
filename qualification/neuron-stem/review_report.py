#!/usr/bin/env python3
"""Mandatory one-page Cell Stem review table from measured shadow receipts.

Never substitutes offline classification for causal NDU, a group-bootstrap
result for signed utility, or research backend traces for real Worker proof.
Missing independent evidence produces '待测/未判定', not manufactured numbers.
"""
import argparse
import json
import math
from pathlib import Path
import re

from jina_v5 import sha256_record
from qualified_eval import write_json


QUALITY_SCHEMA = "hepta.neuron-stem-paired-statistical-gate.v1"
RESOURCE_SCHEMA = "hepta.neuron-research-paired-resource-gate.v1"
REPORT_SCHEMA = "hepta.neuron-stem-review-report.v1"


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        result = json.load(handle)
    if not isinstance(result, dict):
        raise ValueError("evidence must be JSON object")
    return result


def resolve_manifest_receipt(base_path, value):
    if not isinstance(value, str) or not value:
        raise ValueError("receipt path must be a nonempty relative JSON path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".json":
        raise ValueError("receipt path escapes frozen review input scope")
    approved_root = Path(base_path).resolve(strict=True)
    exact = (approved_root / relative).resolve(strict=True)
    if not exact.is_relative_to(approved_root) or not exact.is_file():
        raise ValueError("receipt path escapes approved review input scope")
    return load_json(exact)


def positive_number(v):
    return type(v) in (int, float) and math.isfinite(v) and v > 0


def valid_revision(revision):
    return isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{40}", revision)


def make_quality_summary(model_id, receipt):
    if not isinstance(receipt, dict) or receipt.get("schema") != QUALITY_SCHEMA:
        raise ValueError("expected independent grouped quality gate")
    if receipt.get("candidate_model") != model_id:
        raise ValueError("wrong quality model identity")
    if not valid_revision(receipt.get("candidate_revision")):
        raise ValueError("unpinned quality model revision")
    if (receipt.get("production_promotion_permitted") is not False
            or receipt.get("ndu_independent_signature_verified") is not False):
        raise ValueError("offline quality cannot claim production/NDU authority")
    if type(receipt.get("offline_quality_gate_passed")) is not bool or type(
            receipt.get("cell_learning_gate_passed")) is not bool:
        raise ValueError("required learning gate statuses missing")
    if not isinstance(receipt.get("evaluation"), dict):
        raise ValueError("missing quality evidence")
    future = receipt["evaluation"].get("future", {})
    statistic = future.get("paired_group_bootstrap")
    if not isinstance(statistic, dict):
        raise ValueError("missing paired future source-group confidence")
    gain = statistic.get("accuracy_gain", {}).get("estimate")
    lower = statistic.get("accuracy_gain", {}).get("ci_95", [None])[0]
    upper_brier = statistic.get("brier_delta", {}).get("ci_95", [None, None])[-1]
    if not all(type(v) in (int, float) and math.isfinite(v)
               for v in (gain, lower, upper_brier)):
        raise ValueError("invalid confidence interval")
    if type(future.get("independent_groups")) is not int or future["independent_groups"] < 1:
        raise ValueError("no independent future groups")
    transfers = receipt.get("task_regressions")
    frozen_transfers = receipt.get("frozen_head_regressions")
    if not isinstance(transfers, list) or not isinstance(frozen_transfers, list):
        raise ValueError("missing task regression disclosure")
    if receipt.get("cell_learning_gate_passed") and (
            not receipt.get("offline_quality_gate_passed")
            or receipt.get("matched_frozen_head_present") is not True
            or transfers or frozen_transfers or lower <= 0 or upper_brier >= 0):
        raise ValueError("claimed learned gain violates independent gate conditions")
    return {
        "model_revision": receipt["candidate_revision"],
        "offline_accuracy_gain": gain,
        "accuracy_gain_lower95": lower,
        "brier_delta_upper95": upper_brier,
        "independent_future_groups": future["independent_groups"],
        "negative_transfer_regressions": len(transfers),
        "frozen_head_regressions": len(frozen_transfers),
        "offline_quality_gate_passed": receipt["offline_quality_gate_passed"],
        "cell_learning_gate_passed": receipt["cell_learning_gate_passed"],
        "receipt_digest_unverified": sha256_record(receipt),
    }


def make_resource_summary(model_id, revision, receipt):
    if not isinstance(receipt, dict) or receipt.get("schema") != RESOURCE_SCHEMA:
        raise ValueError("expected paired research resource budget gate")
    if receipt.get("candidate_model") != model_id:
        raise ValueError("wrong resource model identity")
    if receipt.get("candidate_revision") != revision:
        raise ValueError("research resource revision differs from quality revision")
    if (receipt.get("production_promotion_permitted") is not False
            or receipt.get("independent_ndu_signature_verified") is not False
            or receipt.get("production_microbatch_qualified") is not False
            or receipt.get("production_recovery_qualified") is not False):
        raise ValueError("research performance cannot grant production authority")
    if type(receipt.get("research_resource_gate_passed")) is not bool:
        raise ValueError("missing actual resource gate status")
    scale = receipt.get("scale")
    m = receipt.get("metrics")
    if not isinstance(scale, dict) or not isinstance(m, dict):
        raise ValueError("missing measured resource scale")
    cells, covered = scale.get("logical_cells"), scale.get("distinct_ticked_cells")
    active = scale.get("active_heads")
    if (cells not in (64, 256, 1024, 4096) or type(covered) is not int
            or type(active) is not int or covered < 1 or active < 1
            or active > cells or covered > active):
        raise ValueError("invalid actual Cell measurement coverage")
    if scale.get("measured_active_cell_coverage") is not True or covered != active:
        raise ValueError("only complete active-set throughput can be reported")
    rss, p99, rate = (m.get("candidate_rss_bytes"),
                      m.get("candidate_max_stage_p99_ms"),
                      m.get("candidate_throughput_rps"))
    if not all(positive_number(x) for x in (rss, p99, rate)):
        raise ValueError("unmeasured or invalid resource values")
    return {
        "logical_cells": cells,
        "distinct_ticked_cells": covered,
        "peak_rss_bytes": rss,
        "max_stage_p99_ms": p99,
        "measured_research_throughput_rps": rate,
        "research_resource_gate_passed": receipt["research_resource_gate_passed"],
        "receipt_digest_unverified": sha256_record(receipt),
    }


def review_report(registry, manifest, base_path):
    if not isinstance(registry, dict) or not isinstance(manifest, dict):
        raise ValueError("registry and manifest are required")
    if manifest.get("schema") != "hepta.neuron-stem-review-input.v1":
        raise ValueError("unregistered review input manifest")
    registered = {item["id"] for group in ("models", "jina_v5_models")
                  for item in registry[group]}
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("candidate evidence list required")
    provided = {}
    for item in candidates:
        if not isinstance(item, dict) or item.get("model_id") not in registered:
            raise ValueError("unknown candidate model identity")
        ident = item["model_id"]
        if ident in provided:
            raise ValueError("duplicate candidate entry")
        if set(item) - {"model_id", "quality_receipt", "resource_receipt"}:
            raise ValueError("unrecognized evidence input")
        provided[ident] = item
    rows = [{
        "model_id": "no-change",
        "future_ndu_gain": "基准",
        "future_offline_accuracy_gain": None,
        "negative_transfer": "基准",
        "peak_rss_bytes": None, "research_p99_ms": None,
        "research_4096_throughput_rps": None,
        "decision": "保留",
        "production_promotion_permitted": False,
    }]
    for model_id in sorted(registered):
        item = provided.get(model_id, {})
        quality, resource = None, None
        if item.get("quality_receipt"):
            quality = make_quality_summary(
                model_id, resolve_manifest_receipt(base_path, item["quality_receipt"]))
        if item.get("resource_receipt"):
            if quality is None:
                raise ValueError("resource receipt cannot be matched without model quality revision")
            resource = make_resource_summary(
                model_id, quality["model_revision"],
                resolve_manifest_receipt(base_path, item["resource_receipt"]))
        if quality is None:
            decision = "未判定"
        elif not quality["offline_quality_gate_passed"] or not quality["cell_learning_gate_passed"]:
            decision = "学习门禁未通过"
        elif resource is None:
            decision = "待资源实测"
        elif not resource["research_resource_gate_passed"]:
            decision = "资源门禁未通过"
        elif resource["logical_cells"] != 4096:
            decision = "待4096 Cell实测"
        else:
            decision = "Shadow研究通过；NDU与生产待证"
        rows.append({
            "model_id": model_id,
            "future_ndu_gain": "待独立因果证据" if quality else "待测",
            "future_offline_accuracy_gain": (
                quality["offline_accuracy_gain"] if quality else None),
            "future_accuracy_gain_lower95": (
                quality["accuracy_gain_lower95"] if quality else None),
            "independent_future_groups": (
                quality["independent_future_groups"] if quality else None),
            "negative_transfer": (
                quality["negative_transfer_regressions"] if quality else None),
            "peak_rss_bytes": (resource["peak_rss_bytes"] if resource else None),
            "research_p99_ms": (resource["max_stage_p99_ms"] if resource else None),
            "research_4096_throughput_rps": (
                resource["measured_research_throughput_rps"]
                if resource and resource["logical_cells"] == 4096 else None),
            "resource_scale": (resource["logical_cells"] if resource else None),
            "resource_active_heads": (
                resource["distinct_ticked_cells"] if resource else None),
            "cell_learning_gate_passed": (
                quality["cell_learning_gate_passed"] if quality else False),
            "research_resource_gate_passed": (
                resource["research_resource_gate_passed"] if resource else False),
            "evidence_digests_unverified": {
                "quality": quality["receipt_digest_unverified"] if quality else None,
                "resource": resource["receipt_digest_unverified"] if resource else None,
            },
            "decision": decision,
            "production_promotion_permitted": False,
        })
    return {
        "schema": REPORT_SCHEMA,
        "rows": rows,
        "status": "shadow_research_report_not_a_production_selection",
        "no_change_retained": True,
        "evaluator_signatures_verified": False,
        "independent_ndu_signature_verified": False,
        "production_worker_batch_verified": False,
        "physical_crash_recovery_verified": False,
        "production_promotion_permitted": False,
        "provenance": {
            "candidate_manifest_digest_unverified": sha256_record(manifest),
            "model_registry_digest_unverified": sha256_record(registry),
        },
    }


def markdown_report(report):
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError("unknown review report schema")
    def fmt(v, suffix=""):
        if v is None:
            return "待测"
        if isinstance(v, (int, float)) and type(v) is not bool:
            return f"{v:,.3f}{suffix}"
        return str(v).replace("|", "\\|")
    body = [
        "# Hepta Neuron Stem 最终研究评审主报告（Shadow）",
        "",
        "> 本表中的研究版资源吞吐不是生产 Worker 吞吐；未来分类准确率收益不是独立 NDU 因果效用。",
        "",
        "| 候选 | 未来NDU效用 | 未来准确率变化 | 负迁移项 | 峰值RSS (MiB) | 研究p99 (ms) | 4096逻辑Cell研究吞吐（req/s及活跃数） | 结论 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        rss = row["peak_rss_bytes"]
        body.append("| " + " | ".join([
            fmt(row["model_id"]), fmt(row["future_ndu_gain"]),
            fmt(row["future_offline_accuracy_gain"]), fmt(row["negative_transfer"]),
            fmt(rss / (1024 * 1024) if rss is not None else None),
            fmt(row["research_p99_ms"]),
            (fmt(row["research_4096_throughput_rps"])
             + f"（活跃{row['resource_active_heads']}）"
             if row["research_4096_throughput_rps"] is not None else "待测"),
            fmt(row["decision"]),
        ]) + " |")
    body.extend([
        "",
        "本报告永不授予生产晋升权。任何候选仍需独立签名 NDU、真实 Worker Batch、目标硬件、故障恢复和 Selector/Executor 分离验收。",
        "",
    ])
    return "\n".join(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True, help="new JSON path; also writes sibling .md")
    a = parser.parse_args()
    out = Path(a.out)
    markdown_path = out.with_suffix(".md")
    if out == markdown_path or out.exists() or markdown_path.exists():
        raise ValueError("refusing to overwrite a prior reviewed artifact")
    registry = load_json(a.models)
    manifest = load_json(a.manifest)
    report = review_report(registry, manifest, Path(a.manifest).resolve().parent)
    write_json(out, report)
    markdown_path.write_text(markdown_report(report), encoding="utf-8")


if __name__ == "__main__":
    main()
