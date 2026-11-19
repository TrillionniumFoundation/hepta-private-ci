"""Describe existing probe receipts; no model, decoder or sampling execution."""

import hashlib
import json
from pathlib import Path


root = Path(__file__).resolve().parent.parent
quality_path = root / "quality-summary.json"
analysis_path = root / "analysis.json"
quality = json.loads(quality_path.read_text())
analysis = json.loads(analysis_path.read_text())
metrics = (
    "ce", "joint_success", "text_correct", "image_correct", "both_wrong",
    "wrong_agreement", "text_only_correct", "image_only_correct",
    "semantic_disagreement",
)
result = {
    "scope": "Descriptive decomposition of saved outputs only; no new gate or selection",
    "input_sha256": {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (quality_path, analysis_path)
    },
    "units": "Probabilities are absolute, not percentage points; CE uses original rho=1.5",
    "per_family_seed": {},
    "A_minus_H_by_seed": {},
    "means": {},
    "runtime_static_Q_minus_two_stage": {},
    "runtime_limitation": (
        "Original head/law/render component timer excludes guard/reference/setup and "
        "post-return receipt/export. All such CPU is in full family totals but is not "
        "separately attributable to profiles. No service rerun or retiming."
    ),
}
for family in ("H", "A"):
    result["per_family_seed"][family] = {}
    for seed in ("11", "23", "47"):
        source = quality[family][seed]
        keep = {key: source["infinity"]["means"][key] for key in metrics}
        primary = {key: source["log2"]["means"][key] for key in metrics}
        result["per_family_seed"][family][seed] = {
            "KEEP": keep,
            "log2": primary,
            "log2_minus_KEEP": {key: primary[key] - keep[key] for key in metrics},
            "greedy_KEEP": source["infinity"]["greedy_joint_success"],
            "greedy_log2": source["log2"]["greedy_joint_success"],
        }
    runtime = analysis["families"][family]["runtime"]
    static, staged = runtime["Q_log2"], runtime["T_log2"]
    result["runtime_static_Q_minus_two_stage"][family] = {
        "kernel_units_per_request": static["units_per_request"] - staged["units_per_request"],
        "component_CPU_ns_per_request": static["CPU_ns_per_request"] - staged["CPU_ns_per_request"],
        "requests_each_profile": static["observed_requests"],
        "primary_staged_repairs_on_service_cohort": 0,
    }
for seed in ("11", "23", "47"):
    values = {}
    for law in ("KEEP", "log2"):
        values[law] = {
            key: result["per_family_seed"]["A"][seed][law][key]
            - result["per_family_seed"]["H"][seed][law][key]
            for key in metrics
        }
    values["difference_in_differences"] = {
        key: values["log2"][key] - values["KEEP"][key] for key in metrics
    }
    result["A_minus_H_by_seed"][seed] = values
for law in ("KEEP", "log2", "difference_in_differences"):
    result["means"][law] = {
        key: sum(result["A_minus_H_by_seed"][seed][law][key] for seed in ("11", "23", "47")) / 3
        for key in metrics
    }
(root / "evidence/descriptive-decomposition.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n"
)
print(json.dumps(result["means"], indent=2, sort_keys=True))
