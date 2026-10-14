"""Read-only cosine comparison on exact saved crossed-gate features.

No pretrained archive, Encoder constructor, Reader call, Head fit or optimizer.
Both upstream runs must be successful AND contain complete bound model reports.
A green dependency-only run never becomes a completed feature analysis.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import five_causal_experiments as c
import shared_gate_similarity as control


def validate_crossed(root, head_public, head_archive_sha256, names):
    import shared_gate_crossed_evidence as crossed
    import shared_question_gate as gate
    root = Path(root); study = root / "study"
    c.require((root / "source/tested-commit.txt").read_text().strip() == control.ORIGINS["crossed"]["source"]
              and not (study / "failure.json").exists(), "wrong or failed crossed source")
    disposition = c.load(root / "execution-disposition.json")
    c.require(disposition.get("model_execution_completed") is True, "crossed dependency-only result is not a feature cache")
    report, plan, inputs, raw, receipt = [c.load(study / name) for name in
        ("report.json", "plan.json", "crossed-inputs.json", "raw-logits.json", "encoder-receipt.json")]
    c.require(report["schema"] == crossed.PROFILE + ".result" and report["errors"] == []
              and report["new_optimizer_updates"] == report["new_reader_calls"] == 0
              and plan["schema"] == crossed.PROFILE and plan["head_source"] == control.ORIGINS["heads"]["source"]
              and plan["head_run"] == control.ORIGINS["heads"]["run"]
              and plan["head_archive_sha256"] == head_archive_sha256
              and plan["arms"] == list(gate.ARMS) and plan["seeds"] == list(gate.SEEDS)
              and report["plan_sha256"] == c.digest(plan)
              and report["raw_sha256"] == c.file_sha(study / "raw-logits.json")
              and c.load(study / "prediction-seal.json") == {"sha256": report["raw_sha256"], "before_summary": True},
              "crossed report/plan/raw binding failed")
    c.require(inputs["schema"] == crossed.PROFILE + ".inputs"
              and inputs["score_order"] == list(control.ORDER)
              and inputs["original_public_plan_sha256"] == c.digest(head_public)
              and set(raw) == set(report["summaries"]) == set(report["replays"]) == names,
              "wrong feature plan or saved Head census")
    old = control.indexed([u for u in head_public["units"] if u["split"] == "select"])
    units = control.indexed(inputs["units"])
    c.require(set(old) == set(units), "SELECT recipients changed")
    for key, unit in units.items():
        previous = old[key]
        c.require(unit["split"] == "select" and unit["question_id"] == previous["question_id"]
                  and unit["family"] == previous["family"] and unit["status"] == previous["status"], "crossed pair identity changed")
        if unit["status"] != "available":
            c.require(not unit["variants"] and not previous["variants"], "missing source repaired")
            continue
        v = unit["variants"]
        c.require(tuple(x["role"] for x in v) == control.ORDER, "crossed order changed")
        matched, mismatched = previous["variants"]
        qa, qb, eb = mismatched["question_key"], matched["question_key"], matched["evidence_key"]
        ea = v[0]["evidence_key"]
        c.require(mismatched["evidence_key"] == eb and ea != eb and qa != qb
                  and [(x["question_key"], x["evidence_key"]) for x in v] == [(qa,ea),(qa,eb),(qb,ea),(qb,eb)],
                  "not the original two-question/two-evidence rectangle")
    for name in sorted(names):
        c.require(report["replays"][name]["all_passed"] is True
                  and c.load(study / (name + "-raw.json")) == raw[name]
                  and crossed.summarize(inputs["units"], raw[name]) == report["summaries"][name],
                  "saved crossed logits/readout changed")
    cache = study / "frozen-features.safetensors"
    c.require(c.file_sha(cache) == receipt["feature_file_sha256"], "saved feature file mismatch")
    return study, inputs, raw, receipt


def flags(units, raw):
    import shared_gate_crossed_evidence as crossed
    by_id = control.indexed(raw)
    c.require(set(by_id) == {u["pair_id"] for u in units}, "readout census changed")
    result = []
    for unit in units:
        row = by_id[unit["pair_id"]]
        f = None
        if row["status"] == "succeeded":
            d = crossed.interaction(row["logits"])
            f = {key: d[key] for key in control.FLAGS if key != "positive_interaction"}
            f["positive_interaction"] = d["interaction"] > 0
        result.append({"pair_id": unit["pair_id"], "status": row["status"], "flags": f})
    return result


def run(head_archive, cross_archive, dependency_receipt, work, output):
    import torch
    from safetensors.torch import load_file
    import shared_question_gate as gate
    import shared_gate_crossed_evidence as crossed
    from shared_gate_crossed_trial import validate_saved
    from reader_content_swap_trial import extract_verified
    from experiments.shared_stem_cell.execution import measured, tensor_digest

    c.require(dependency_receipt.get("schema") == control.PROFILE + ".dependency"
              and dependency_receipt.get("ready") is True, "successful exact upstream required")
    origins = dependency_receipt["origins"]
    c.require(set(origins) == set(control.ORIGINS), "origin census changed")
    for role, expected in control.ORIGINS.items():
        c.require(all(origins[role].get(k) == v for k, v in expected.items())
                  and origins[role].get("ready") is True
                  and origins[role].get("observed_status") == "completed"
                  and origins[role].get("observed_conclusion") == "success"
                  and c.sha(origins[role].get("artifact_sha256")), "wrong external result pin")
    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    config = {"schema": control.PROFILE + ".plan", "origins": origins,
              "baselines": ["cosine_zero", "cosine_train_threshold"],
              "score_arithmetic": "fp64_scaled_cosine_from_saved_fp32_vectors",
              "threshold_search": "TRAIN_midpoints_and_outside_endpoints_min_strict_error_then_abs_then_value",
              "candidate_comparison": "paired_binary_criteria_not_logit_scale_differences",
              "new_pretrained_model_loads": 0, "new_encoder_forwards": 0,
              "new_reader_calls": 0, "new_head_optimizer_updates": 0, "new_scalar_fits": 1,
              "semantic_accuracy": None, "production_accepted": False}
    c.write_new(output / "plan.json", config)
    with measured() as material_cost:
        hr, hv = extract_verified(Path(head_archive), work / "heads", origins["heads"]["artifact_sha256"])
        xr, xv = extract_verified(Path(cross_archive), work / "crossed", origins["crossed"]["artifact_sha256"])
        _, _, public, _ = validate_saved(hr)
        names = {a + "-" + str(s) for a in gate.ARMS for s in gate.SEEDS}
        study, inputs, candidate_raw, encoder_receipt = validate_crossed(xr, public, origins["heads"]["artifact_sha256"], names)
        features = load_file(str(study / "frozen-features.safetensors"), device="cpu")
        specs = list(public["features"]) + list(inputs["additional_features"])
        c.require(len({s["key"] for s in specs}) == len(specs) and set(features) == {s["key"] for s in specs}, "feature cache census mismatch")
        width = None
        for spec in specs:
            c.require(set(spec) == {"key", "scope", "text"}
                      and spec["key"] == c.digest([gate.REPRESENTATION, spec["scope"], spec["text"]]), "cache input identity changed")
            value = features[spec["key"]]
            c.require(value.ndim == 1 and 8 <= value.numel() <= 8192 and value.dtype == torch.float32
                      and value.device.type == "cpu" and not value.requires_grad
                      and bool(torch.isfinite(value).all())
                      and abs(float(value.double().norm())-1.0) <= 1e-5, "invalid frozen normalized feature")
            c.require(width is None or width == value.numel(), "cache width changed")
            width = value.numel()
        identity = c.digest({k: tensor_digest(v) for k, v in sorted(features.items())})
        c.require(identity == encoder_receipt["feature_tensor_sha256"], "cache tensor digest mismatch")
        vectors = {k: value.tolist() for k, value in features.items()}
    c.write_new(output / "materials.json", {"heads": hv, "crossed": xv, "feature_tensor_sha256": identity,
        "feature_file_sha256": encoder_receipt["feature_file_sha256"], "load_and_validation_cost": material_cost,
        "loaded_feature_tensor_bytes": sum(v.numel()*v.element_size() for v in features.values()),
        "python_vector_object_bytes_measured": False, "upstream_encoding_cost_not_erased": True})
    train = [u for u in public["units"] if u["split"] == "train"]
    with measured() as scoring_cost:
        train_raw = control.score_pairs(train, vectors, split="train", roles=("matched", "mismatched"))
        c.write_new(output / "train-raw.json", train_raw)
        calibration = control.fit_train_threshold(train, train_raw)
        # The scalar is frozen BEFORE any SELECT cosine is computed.
        c.write_new(output / "train-threshold.json", calibration)
        select_raw = control.score_pairs(inputs["units"], vectors, split="select", roles=control.ORDER)
        baseline_raw = {"cosine_zero": control.shift(select_raw, 0.0),
                        "cosine_train_threshold": control.shift(select_raw, calibration["threshold"])}
        c.write_new(output / "raw-logits.json", baseline_raw)
        c.write_new(output / "prediction-seal.json", {"sha256": c.file_sha(output / "raw-logits.json"), "before_summary": True})
        summaries = {name: crossed.summarize(inputs["units"], rows) for name, rows in baseline_raw.items()}
        contrasts = {name: {baseline: control.compare_flags(inputs["units"], flags(inputs["units"], candidate_raw[name]),
                        flags(inputs["units"], rows)) for baseline, rows in baseline_raw.items()} for name in sorted(names)}
    c.require(identity == c.digest({k: tensor_digest(v) for k, v in sorted(features.items())}), "readout modified cached vectors")
    report = {"schema": control.PROFILE + ".result", "errors": [], "analysis_completed": True,
              "plan_sha256": c.digest(config), "raw_sha256": c.file_sha(output / "raw-logits.json"),
              "threshold_sha256": c.file_sha(output / "train-threshold.json"), "train_calibration": calibration,
              "summaries": summaries, "paired_candidate_criteria": contrasts, "arithmetic_cost": scoring_cost,
              "cosine_computations": sum(len(r["logits"] or []) for r in train_raw+select_raw),
              "new_pretrained_model_loads": 0, "new_encoder_forwards": 0, "new_reader_calls": 0,
              "new_optimizer_updates": 0, "new_scalar_parameters_fitted": 1, "new_independent_tasks": 0,
              "saved_head_logits_reused_unchanged": True, "raw_model_scales_compared": False,
              "independent_confirmation": False, "semantic_accuracy": None, "compute_matched": False,
              "production_accepted": False, "reader_adequacy_established": False}
    c.write_new(output / "report.json", report)
    print("SAVED_FEATURE_SIMILARITY_RESULT", c.canonical(report).decode(), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dependency", "run"))
    for name in ("head-run-json", "head-artifacts-json", "cross-run-json", "cross-artifacts-json", "head-archive", "cross-archive", "dependency-json", "work"):
        parser.add_argument("--"+name, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "dependency":
        paths = (args.head_run_json, args.head_artifacts_json, args.cross_run_json, args.cross_artifacts_json)
        c.require(all(p is not None for p in paths), "four authenticated metadata files required")
        d = control.dependency(*(c.load(p) for p in paths))
        c.write_new(args.output, d)
        print(c.canonical(d).decode(), flush=True)
        return 0 if d["ready"] else 3
    c.require(all(p is not None for p in (args.head_archive, args.cross_archive, args.dependency_json, args.work)), "saved artifacts/dependency/work required")
    try:
        run(args.head_archive, args.cross_archive, c.load(args.dependency_json), args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048], "analysis_completed": False, "production_accepted": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
