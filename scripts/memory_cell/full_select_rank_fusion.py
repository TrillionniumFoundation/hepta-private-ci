"""Post-hoc, no-fit rank fusion over sealed full-SELECT score matrices.

This is an exposed-development diagnostic. It never selects a better method per
question, fits on SELECT, accesses answer bodies, loads a model, or authorizes a
Reader call to be skipped. Candidate rankings are derived only from the already
sealed cosine and lexical score matrices using a fixed evidence-key tie break.
"""
from __future__ import annotations

from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import torch

import five_causal_experiments as c
import full_select_retrieval as retrieval

PROFILE = "hepta.cell.full-select-rank-fusion-posthoc.v1"
ORIGIN = {
    "run": 38540293994,
    "source": "8e213b7585221ddf9fd279037caa4dc6f972af6c",
    "path": ".github/workflows/hepta-full-select-retrieval.yml",
    "artifact": "hepta-full-select-retrieval-development",
    "artifact_id": 11885366683,
    "artifact_sha256": "6534177c6974ee0e9fe0a331891ec5cb0b2443481198ece36cfcaf754003d436",
}
BASE_METHODS = ("cosine", "lexical_jaccard")
FUSION_METHODS = (
    "equal_reciprocal_rank",
    "rrf_k60",
    "mean_rank",
    "rank_product",
    "anti_cosine_control",
    "cyclic_cosine_control",
)


def _index(rows, key):
    c.require(isinstance(rows, list) and rows
              and all(isinstance(row, dict) and key in row for row in rows),
              "invalid rank-fusion inventory")
    result = {row[key]: row for row in rows}
    c.require(len(result) == len(rows), "duplicate rank-fusion identity")
    return result


def deterministic_ranks(values, keys):
    """Return 1-based ranks with a fixed evidence-key tie break."""
    c.require(isinstance(values, torch.Tensor) and values.ndim == 1
              and values.dtype == torch.float64 and values.device.type == "cpu"
              and isinstance(keys, list) and len(keys) == values.numel()
              and len(set(keys)) == len(keys) and all(c.sha(key) for key in keys)
              and bool(torch.isfinite(values).all()),
              "invalid rank source")
    ordered = sorted(zip(keys, values.tolist()), key=lambda item: (-item[1], item[0]))
    return {key: rank for rank, (key, _) in enumerate(ordered, 1)}


def validate_origin(root):
    """Validate immutable completed full-SELECT result bytes and denominator."""
    root = Path(root); study = root / "study"
    c.require((root / "source/tested-commit.txt").read_text().strip() == ORIGIN["source"],
              "wrong full-SELECT source")
    disposition = c.load(root / "execution-disposition.json")
    plan = c.load(study / "public-retrieval-inputs.json")
    execution = c.load(study / "execution-inputs.json")
    report = c.load(study / "report.json")
    index = c.load(study / "score-index.json")
    seal = c.load(study / "prediction-seal.json")
    c.require(disposition.get("model_execution_completed") is True
              and report.get("schema") == "hepta.cell.full-select-retrieval.v1.result"
              and report.get("errors") == [] and report.get("select_fit") is False
              and report.get("new_reader_calls") == report.get("new_head_optimizer_updates") == 0
              and report.get("answers_entered_scoring") is False
              and report.get("score_matrix_sha256") == c.file_sha(study / "score-matrices.safetensors")
              and seal == {"before_summary": True,
                           "score_index_sha256": c.file_sha(study / "score-index.json"),
                           "score_matrix_sha256": report["score_matrix_sha256"]},
              "incomplete or reinterpreted full-SELECT result")
    c.require(plan.get("schema") == "hepta.cell.full-select-retrieval.v1.inputs"
              and execution.get("schema") == "hepta.cell.full-select-retrieval.v1.inputs"
              and len(plan.get("units", [])) == len(index.get("question_ids", [])) == 296
              and len(index.get("evidence_keys", [])) == execution.get("available_evidence_candidates") == 248
              and execution.get("available_questions") == 295
              and set(BASE_METHODS) <= set(index.get("methods", [])),
              "full-SELECT denominator or matrix census changed")
    from safetensors.torch import load_file
    matrices = load_file(str(study / "score-matrices.safetensors"), device="cpu")
    c.require(set(matrices) == set(index["methods"]), "score matrix method census changed")
    expected_shape = (len(index["question_ids"]), len(index["evidence_keys"]))
    for name, matrix in matrices.items():
        c.require(matrix.shape == expected_shape and matrix.dtype == torch.float64
                  and matrix.device.type == "cpu", "score matrix geometry changed")
    # Recompute both base summaries from sealed matrices before any fusion.
    for name in BASE_METHODS:
        rows = matrix_rows(execution, index, matrices[name])
        c.require(retrieval.summarize(execution, rows) == report["summaries"][name],
                  "saved base retrieval summary changed")
    return study, execution, index, matrices, report


def matrix_rows(plan, index, matrix):
    """Restore complete score rows while preserving unavailable questions."""
    units = _index(plan["units"], "question_id")
    qids, keys = index["question_ids"], index["evidence_keys"]
    c.require(set(qids) == set(units) and matrix.shape == (len(qids), len(keys)),
              "matrix/index denominator mismatch")
    rows = []
    for i, qid in enumerate(qids):
        unit = units[qid]
        if unit.get("status", "available") != "available":
            c.require(bool(torch.isnan(matrix[i]).all()), "unavailable score row was imputed")
            rows.append({"question_id": qid, "status": unit["status"], "scores": None})
        else:
            c.require(bool(torch.isfinite(matrix[i]).all()), "available score row is nonfinite")
            rows.append({"question_id": qid, "status": "succeeded",
                         "scores": [[key, float(value)]
                                    for key, value in zip(keys, matrix[i].tolist())]})
    return rows


def fuse(plan, index, cosine, lexical):
    """Create fixed post-hoc score matrices without looking at own evidence."""
    before = c.digest([plan, index])
    qids, keys = index["question_ids"], index["evidence_keys"]
    units = _index(plan["units"], "question_id")
    shape = (len(qids), len(keys))
    for matrix in (cosine, lexical):
        c.require(isinstance(matrix, torch.Tensor) and matrix.shape == shape
                  and matrix.dtype == torch.float64 and matrix.device.type == "cpu",
                  "wrong fusion matrix geometry")
    outputs = {name: torch.full(shape, float("nan"), dtype=torch.float64)
               for name in FUSION_METHODS}
    available = [i for i, qid in enumerate(qids)
                 if units[qid].get("status", "available") == "available"]
    c.require(available and len(available) < len(qids),
              "expected fixed available/unavailable full-SELECT census")
    ranks = {}
    for i in available:
        c.require(bool(torch.isfinite(cosine[i]).all())
                  and bool(torch.isfinite(lexical[i]).all()), "nonfinite fusion base row")
        ranks[i] = (deterministic_ranks(cosine[i], keys),
                    deterministic_ranks(lexical[i], keys))
    for offset, i in enumerate(available):
        cosine_rank, lexical_rank = ranks[i]
        cycled_rank = ranks[available[(offset + 1) % len(available)]][0]
        n = len(keys)
        for j, key in enumerate(keys):
            rc, rl = cosine_rank[key], lexical_rank[key]
            outputs["equal_reciprocal_rank"][i, j] = 1.0 / rc + 1.0 / rl
            outputs["rrf_k60"][i, j] = 1.0 / (60 + rc) + 1.0 / (60 + rl)
            outputs["mean_rank"][i, j] = -0.5 * (rc + rl)
            outputs["rank_product"][i, j] = 1.0 / (rc * rl)
            outputs["anti_cosine_control"][i, j] = 1.0 / (n + 1 - rc) + 1.0 / rl
            outputs["cyclic_cosine_control"][i, j] = 1.0 / cycled_rank[key] + 1.0 / rl
    for i, qid in enumerate(qids):
        if units[qid].get("status", "available") != "available":
            c.require(all(bool(torch.isnan(value[i]).all()) for value in outputs.values()),
                      "unavailable question entered fusion")
    c.require(c.digest([plan, index]) == before, "fusion mutated upstream inputs")
    return outputs


def analyze(plan, index, matrices):
    c.require(set(BASE_METHODS) <= set(matrices), "two sealed bases required")
    fused = fuse(plan, index, matrices["cosine"], matrices["lexical_jaccard"])
    lexical_rows = matrix_rows(plan, index, matrices["lexical_jaccard"])
    summaries, comparisons = {}, {}
    for name, matrix in fused.items():
        rows = matrix_rows(plan, index, matrix)
        summaries[name] = retrieval.summarize(plan, rows)
        comparisons[name] = retrieval.compare_rankings(plan, rows, lexical_rows)
    return fused, summaries, comparisons
