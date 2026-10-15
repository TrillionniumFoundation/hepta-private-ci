"""Execute exact residual directions on the sealed full-SELECT feature pool."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import five_causal_experiments as c
import full_select_rank_fusion as full
import full_select_residual_transfer as transfer
import full_select_retrieval as retrieval
import shared_gate_cosine_residual as residual
import shared_gate_residual_shrinkage as shrink


def run(full_archive, v3_archive, crossed_archive, work, output):
    from safetensors.torch import load_file, save_file
    from reader_content_swap_trial import extract_verified
    from experiments.shared_stem_cell.execution import parameters

    work, output = Path(work), Path(output)
    full_root, full_verified = extract_verified(Path(full_archive), work / "full",
                                                transfer.FULL_ORIGIN["artifact_sha256"])
    v3_root, v3_verified = extract_verified(Path(v3_archive), work / "v3",
                                            transfer.V3_ORIGIN["artifact_sha256"])
    crossed_root, crossed_verified = extract_verified(
        Path(crossed_archive), work / "crossed", transfer.CROSSED_ORIGIN["artifact_sha256"])
    full_study, plan, index, base_matrices, full_report = full.validate_origin(full_root)
    v3_study, train, select, v3_report, v3_raw, names = shrink.validate_completed(
        v3_root, crossed_root)
    output.mkdir(parents=True, exist_ok=False)
    config = {"schema": transfer.PROFILE + ".plan",
              "full_origin": transfer.FULL_ORIGIN,
              "v3_origin": transfer.V3_ORIGIN,
              "crossed_origin": transfer.CROSSED_ORIGIN,
              "alphas": list(transfer.ALPHAS),
              "alpha_names": list(transfer.ALPHA_NAMES),
              "checkpoint_names": sorted(names),
              "methods": transfer.method_census(names),
              "operation": "sealed_full_select_cosine_plus_fixed_scalar_times_saved_residual",
              "posthoc_after_select_observation": True,
              "full_select_fit": False, "seed_selection": False,
              "checkpoint_selection": False, "alpha_selection_from_full_select": False,
              "new_optimizer_updates": 0, "semantic_accuracy": None,
              "production_accepted": False}
    c.write_new(output / "plan.json", config)
    full_features = load_file(str(full_study / "frozen-features.safetensors"), device="cpu")
    paired_features = load_file(str(v3_study / "frozen-features.safetensors"), device="cpu")
    models, checkpoints = {}, {}
    width = next(iter(full_features.values())).numel()
    for name in sorted(names):
        model = residual.ResidualGate(width)
        model.load_state_dict(load_file(str(v3_study / "heads" / name / "head.safetensors"),
                                        device="cpu"), strict=True)
        model.eval().requires_grad_(False)
        c.require(parameters(model) == v3_report["head_parameters"][name],
                  "full-pool checkpoint identity changed")
        models[name] = model
        checkpoints[name] = v3_report["head_parameters"][name]
    rule = transfer.paired_train_rule(train, select, paired_features,
                                      v3_report, v3_raw, models)
    c.write_new(output / "paired-train-only-rule.json", rule)
    matrices, summaries, versus_cosine, versus_lexical = {}, {}, {}, {}
    cosine = base_matrices["cosine"]
    cosine_rows = full.matrix_rows(plan, index, cosine)
    lexical_rows = full.matrix_rows(plan, index, base_matrices["lexical_jaccard"])
    pair_scores = 0
    for name in sorted(names):
        model = models[name]
        direction = transfer.residual_matrix(plan, index, full_features, model)
        pair_scores += int((~direction.isnan()).sum().item())
        for method, matrix in transfer.scaled_matrices(cosine, direction, name).items():
            matrices[method] = matrix
            rows = full.matrix_rows(plan, index, matrix)
            summaries[method] = retrieval.summarize(plan, rows)
            versus_cosine[method] = retrieval.compare_rankings(plan, rows, cosine_rows)
            versus_lexical[method] = retrieval.compare_rankings(plan, rows, lexical_rows)
    c.require(set(matrices) == set(config["methods"]), "full-pool method census changed")
    save_file(matrices, str(output / "score-matrices.safetensors"))
    score_index = {"question_ids": index["question_ids"],
                   "evidence_keys": index["evidence_keys"],
                   "methods": config["methods"],
                   "matrix_file_sha256": c.file_sha(output / "score-matrices.safetensors")}
    c.write_new(output / "score-index.json", score_index)
    c.write_new(output / "prediction-seal.json", {
        "score_matrix_sha256": score_index["matrix_file_sha256"],
        "score_index_sha256": c.file_sha(output / "score-index.json"),
        "before_summary": True})
    report = {"schema": transfer.PROFILE + ".result", "errors": [],
              "plan_sha256": c.digest(config),
              "score_matrix_sha256": score_index["matrix_file_sha256"],
              "full_origin_score_matrix_sha256": full_report["score_matrix_sha256"],
              "v3_origin_raw_sha256": v3_report["raw_sha256"],
              "checkpoint_parameters": checkpoints,
              "paired_train_only_rule": rule,
              "paired_train_only_rule_sha256": c.file_sha(output / "paired-train-only-rule.json"),
              "summaries": summaries,
              "paired_against_cosine": versus_cosine,
              "paired_against_lexical": versus_lexical,
              "new_pretrained_model_loads": 0, "new_encoder_forwards": 0,
              "new_head_checkpoint_loads": len(names),
              "new_residual_matrix_evaluations": len(names),
              "new_residual_pair_scores": pair_scores,
              "new_optimizer_updates": 0, "new_reader_calls": 0,
              "full_select_fit": False, "seed_selection": False,
              "checkpoint_selection": False,
              "alpha_selection_from_full_select": False,
              "posthoc_after_select_observation": True,
              "independent_confirmation": False, "confidence_interval": None,
              "reader_call_skipping_authorized": False,
              "semantic_accuracy": None, "production_accepted": False,
              "five_experiments_completed": False,
              "artifact_verification": {"full": full_verified, "v3": v3_verified,
                                        "crossed": crossed_verified}}
    c.write_new(output / "report.json", report)
    print("FULL_SELECT_RESIDUAL_TRANSFER_RESULT", c.canonical(report).decode(), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-archive", type=Path, required=True)
    parser.add_argument("--v3-archive", type=Path, required=True)
    parser.add_argument("--crossed-archive", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.full_archive, args.v3_archive, args.crossed_archive,
            args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048],
                "analysis_completed": False, "production_accepted": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
