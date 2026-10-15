"""Replay exact residual checkpoints over a fixed, no-fit shrinkage grid."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import five_causal_experiments as c
import shared_gate_cosine_residual as residual
import shared_gate_residual_shrinkage as shrink


def run(v3_archive, crossed_archive, work, output):
    from safetensors.torch import load_file, save_file
    import shared_gate_similarity as similarity
    import shared_gate_similarity_trial as similarity_trial
    from reader_content_swap_trial import extract_verified
    from experiments.shared_stem_cell.execution import parameters

    work, output = Path(work), Path(output)
    v3, v3_verified = extract_verified(Path(v3_archive), work / "v3",
                                       shrink.ORIGIN["artifact_sha256"])
    crossed, crossed_verified = extract_verified(Path(crossed_archive), work / "crossed",
                                                  shrink.CROSSED["artifact_sha256"])
    study, train, select, prior, prior_raw, names = shrink.validate_completed(v3, crossed)
    output.mkdir(parents=True, exist_ok=False)
    config = {"schema": shrink.PROFILE + ".plan", "origin": shrink.ORIGIN,
              "crossed_origin": shrink.CROSSED,
              "alphas": list(shrink.ALPHAS), "alpha_names": list(shrink.ALPHA_NAMES),
              "checkpoint_names": sorted(names),
              "operation": "fixed_scalar_times_saved_residual_about_frozen_cosine",
              "posthoc_after_select_observation": True, "select_fit": False,
              "seed_selection": False, "alpha_selection_from_select": False,
              "train_only_rule_evaluated": True,
              "new_optimizer_updates": 0, "semantic_accuracy": None,
              "production_accepted": False}
    c.write_new(output / "plan.json", config)
    features = load_file(str(study / "frozen-features.safetensors"), device="cpu")
    raw, summaries, comparisons, checkpoints = {}, {}, {}, {}
    baseline = prior_raw["cosine_frozen"]
    baseline_flags = similarity_trial.flags(select["units"], baseline["select"])
    residual_calls = 0
    for name in sorted(names):
        model = residual.ResidualGate(next(iter(features.values())).numel())
        model.load_state_dict(load_file(str(study / "heads" / name / "head.safetensors"),
                                        device="cpu"), strict=True)
        model.eval().requires_grad_(False)
        c.require(parameters(model) == prior["head_parameters"][name],
                  "saved shrinkage checkpoint identity changed")
        checkpoints[name] = prior["head_parameters"][name]
        for alpha in shrink.ALPHAS:
            scale = shrink.name_alpha(alpha)
            key = name + "@" + scale
            train_rows = shrink.scaled_predict(train["units"], features,
                                               prior["fixed_threshold"], model, alpha)
            select_rows = shrink.scaled_predict(select["units"], features,
                                                prior["fixed_threshold"], model, alpha)
            if alpha == 0.0:
                c.require(shrink.exact_rows_equal(train_rows, baseline["train"])
                          and shrink.exact_rows_equal(select_rows, baseline["select"]),
                          "zero shrinkage does not reproduce frozen cosine")
            if alpha == 1.0:
                c.require(shrink.exact_rows_equal(train_rows, prior_raw[name]["train"])
                          and shrink.exact_rows_equal(select_rows, prior_raw[name]["select"]),
                          "unit shrinkage does not reproduce saved residual")
            raw[key] = {"train": train_rows, "select": select_rows}
            summaries[key] = {
                "train": residual.summarize(train["units"], train_rows),
                "select": residual.summarize(select["units"], select_rows)}
            comparisons[key] = similarity.compare_flags(
                select["units"], similarity_trial.flags(select["units"], select_rows),
                baseline_flags)
            if alpha:
                residual_calls += sum(u["status"] == "available" for u in train["units"])
                residual_calls += sum(u["status"] == "available" for u in select["units"])
    train_only_rule = shrink.select_train_alpha(summaries, names)
    c.write_new(output / "train-only-selection.json", train_only_rule)
    c.write_new(output / "raw-logits.json", raw)
    c.write_new(output / "prediction-seal.json",
                {"sha256": c.file_sha(output / "raw-logits.json"), "before_summary": True})
    report = {"schema": shrink.PROFILE + ".result", "errors": [],
              "plan_sha256": c.digest(config),
              "raw_sha256": c.file_sha(output / "raw-logits.json"),
              "origin_raw_sha256": prior["raw_sha256"],
              "checkpoint_parameters": checkpoints,
              "summaries": summaries, "paired_against_cosine_frozen": comparisons,
              "train_only_shrinkage_rule": train_only_rule,
              "train_only_selection_sha256": c.file_sha(output / "train-only-selection.json"),
              "new_pretrained_model_loads": 0, "new_encoder_forwards": 0,
              "new_head_checkpoint_loads": len(names),
              "new_residual_forward_batches": residual_calls,
              "new_optimizer_updates": 0, "new_reader_calls": 0,
              "select_fit": False, "seed_selection": False,
              "alpha_selection_from_select": False,
              "posthoc_after_select_observation": True,
              "independent_confirmation": False, "confidence_interval": None,
              "reader_call_skipping_authorized": False,
              "semantic_accuracy": None, "production_accepted": False,
              "five_experiments_completed": False,
              "artifact_verification": {"v3": v3_verified, "crossed": crossed_verified}}
    c.write_new(output / "report.json", report)
    print("COSINE_RESIDUAL_SHRINKAGE_RESULT", c.canonical(report).decode(), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-archive", type=Path, required=True)
    parser.add_argument("--crossed-archive", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.v3_archive, args.crossed_archive, args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048],
                "analysis_completed": False, "production_accepted": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
