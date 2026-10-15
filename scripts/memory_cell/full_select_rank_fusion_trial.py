"""Execute the sealed, post-hoc full-SELECT rank-fusion diagnostic."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import five_causal_experiments as c
import full_select_rank_fusion as fusion


def run(archive, work, output):
    from safetensors.torch import save_file
    from reader_content_swap_trial import extract_verified

    work, output = Path(work), Path(output)
    root, verified = extract_verified(Path(archive), work,
                                      fusion.ORIGIN["artifact_sha256"])
    study, plan, index, matrices, prior = fusion.validate_origin(root)
    fused, summaries, comparisons = fusion.analyze(plan, index, matrices)
    output.mkdir(parents=True, exist_ok=False)
    config = {"schema": fusion.PROFILE + ".plan", "origin": fusion.ORIGIN,
              "base_methods": list(fusion.BASE_METHODS),
              "methods": list(fusion.FUSION_METHODS),
              "rank_definition": "descending_score_then_evidence_key",
              "fusion_scope": "global_candidate_ranks_read_out_globally_and_within_family",
              "posthoc_after_select_observation": True, "select_fit": False,
              "per_question_method_selection": False, "new_optimizer_updates": 0,
              "semantic_accuracy": None, "production_accepted": False}
    c.write_new(output / "plan.json", config)
    save_file(fused, str(output / "fusion-score-matrices.safetensors"))
    score_index = {"question_ids": index["question_ids"],
                   "evidence_keys": index["evidence_keys"],
                   "methods": list(fusion.FUSION_METHODS),
                   "matrix_file_sha256": c.file_sha(output / "fusion-score-matrices.safetensors")}
    c.write_new(output / "score-index.json", score_index)
    c.write_new(output / "prediction-seal.json", {
        "score_matrix_sha256": score_index["matrix_file_sha256"],
        "score_index_sha256": c.file_sha(output / "score-index.json"), "before_summary": True})
    report = {"schema": fusion.PROFILE + ".result", "errors": [],
              "plan_sha256": c.digest(config),
              "origin_report_sha256": c.digest(prior),
              "origin_score_matrix_sha256": prior["score_matrix_sha256"],
              "fusion_score_matrix_sha256": score_index["matrix_file_sha256"],
              "summaries": summaries, "paired_against_lexical": comparisons,
              "new_pretrained_model_loads": 0, "new_encoder_forwards": 0,
              "new_head_forwards": 0, "new_reader_calls": 0,
              "new_optimizer_updates": 0, "answer_fields_entered_scoring": False,
              "select_fit": False, "posthoc_after_select_observation": True,
              "independent_confirmation": False, "confidence_interval": None,
              "reader_call_skipping_authorized": False,
              "semantic_accuracy": None, "production_accepted": False,
              "five_experiments_completed": False,
              "artifact_verification": verified}
    c.write_new(output / "report.json", report)
    print("FULL_SELECT_RANK_FUSION_RESULT", c.canonical(report).decode(), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.archive, args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048],
                "analysis_completed": False, "production_accepted": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
