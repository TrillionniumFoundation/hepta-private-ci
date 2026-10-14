"""Cross-modal held-out paired ranking over *real* frozen Shadow Stem outputs.

A real local EmbeddingGemma2 encoder is required to run this evaluator. Never
constructs fake features, trains on future rows, or authorizes FinalUse.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

from embeddinggemma2_shadow import FrozenGemmaShadow, QualificationError, is_sha


def validate_pairs(rows: list[dict]) -> dict:
    if not isinstance(rows, list) or not 4 <= len(rows) <= 512:
        raise QualificationError("4..512 independent multimodal pairs required")
    required = {"case_id", "group_id", "split", "observed_utc", "text", "media"}
    cases, group_splits, media_splits, text_splits, chronology = set(), {}, {}, {}, {}
    unique_text_cohorts, unique_media_cohorts = set(), set()
    for pair in rows:
        if not isinstance(pair, dict) or set(pair) != required:
            raise QualificationError("exact pair schema required")
        cid, group, split = (pair[k] for k in ("case_id", "group_id", "split"))
        if (not isinstance(cid, str) or not cid or cid in cases
                or not isinstance(group, str) or not group
                or split not in ("test", "future")):
            raise QualificationError("invalid pair identity or split")
        cases.add(cid)
        try:
            t = datetime.fromisoformat(pair["observed_utc"].replace("Z", "+00:00"))
            if t.utcoffset() != timedelta(0):
                raise ValueError("time not UTC")
            t = t.astimezone(timezone.utc)
        except (AttributeError, ValueError, TypeError) as exc:
            raise QualificationError("UTC source timestamp required") from exc
        chronology.setdefault(split, []).append(t)
        text, media = pair["text"], pair["media"]
        if (not isinstance(text, dict) or not isinstance(media, dict)
                or not isinstance(text.get("input"), dict)
                or not isinstance(media.get("input"), dict)
                or text["input"].get("modality") not in ("text", "code")
                or media["input"].get("modality") not in ("image", "audio", "video")):
            raise QualificationError("pair needs exactly one text and one media span")
        if any(text.get(k) != media.get(k) for k in
               ("scope_id", "principal_id", "purpose_id", "generation", "authority_epoch")):
            raise QualificationError("cross-scope paired evaluation denied")
        scope = text["scope_id"]
        key = (scope, group)
        if group_splits.setdefault(key, split) != split:
            raise QualificationError("group appears in both windows")
        media_sha = media["input"].get("sha256")
        text_sha = text["input"].get("sha256")
        if not is_sha(media_sha, 64) or not is_sha(text_sha, 64):
            raise QualificationError("unbound source asset")
        if media_splits.setdefault((scope, media_sha), split) != split:
            raise QualificationError("media bytes leaked across windows")
        if text_splits.setdefault((scope, text_sha), split) != split:
            raise QualificationError("text bytes leaked across windows")
        if (scope, split, media_sha) in unique_media_cohorts:
            raise QualificationError("same media has multiple positive labels in cohort")
        if (scope, split, text_sha) in unique_text_cohorts:
            raise QualificationError("same text has multiple positive labels in cohort")
        unique_media_cohorts.add((scope, split, media_sha))
        unique_text_cohorts.add((scope, split, text_sha))
    if (not chronology.get("test") or not chronology.get("future")
            or max(chronology["test"]) >= min(chronology["future"])):
        raise QualificationError("genuine later future window is required")
    cohorts = {}
    for pair in rows:
        key = (pair["text"]["scope_id"], pair["split"])
        cohorts.setdefault(key, []).append(pair)
    if any(len({p["group_id"] for p in group}) < 2 for group in cohorts.values()):
        raise QualificationError("need two independent groups per cohort")
    return {"cohorts": cohorts, "cases": len(cases), "groups": len(group_splits)}


def paired_cosine_metrics(pairs: list[dict], vectors: dict[str, tuple[list[int], list[int]]]) -> dict:
    """Pure scoring oracle; vectors in real runs come solely from FrozenGemmaShadow."""
    validated = validate_pairs(pairs)
    out = []
    for (scope, split), cohort in sorted(validated["cohorts"].items()):
        for direction in ("text_to_media", "media_to_text"):
            hits = 0
            for pair in cohort:
                # Directional task prompts are different: a search-query
                # text is not a corpus/document text representation. Keep
                # both in an independently scored 3-vector pair.
                triplet = vectors[pair["case_id"]]
                if len(triplet) != 3:
                    raise QualificationError("both query/document text views plus media required")
                q = triplet[0 if direction == "text_to_media" else 2]
                scores = []
                for other in cohort:
                    other_triplet = vectors[other["case_id"]]
                    if len(other_triplet) != 3:
                        raise QualificationError("one-sided text prompt omitted")
                    d = other_triplet[2 if direction == "text_to_media" else 1]
                    if len(q) != 256 or len(d) != 256:
                        raise QualificationError("paired V1 requires exact 256d Q24 vectors")
                    similarity = sum(float(a) * float(b) for a, b in zip(q, d))
                    if not math.isfinite(similarity):
                        raise QualificationError("invalid numeric similarity")
                    scores.append((similarity, other["case_id"]))
                best = sorted(scores, key=lambda x: (-x[0], x[1]))[0][1]
                hits += best == pair["case_id"]
            out.append({"scope_id": scope, "split": split, "direction": direction,
                        "total": len(cohort), "top1_correct": hits,
                        "recall_at_1": hits / len(cohort)})
    return {"paired_cases": validated["cases"], "independent_groups": validated["groups"],
            "directional_text_views_per_case": 2,
            "results": out, "production_promotion": "DENY_ALL",
            "independently_authenticated_evaluation": False}


def execute_pairs(runner: FrozenGemmaShadow, pairs: list[dict], media_root: Path) -> dict:
    validate_pairs(pairs)
    if not getattr(runner, "_verified_local_weights", False):
        raise QualificationError("real locally verified weights required; test stubs cannot be scored")
    if runner.manifest["dimension"] != 256 or runner.manifest["profile"] == "text":
        raise QualificationError("this V1 paired evaluator requires 256d and multimodal profile")
    vectors = {}
    for pair in pairs:
        # Separate documented prompt names are needed for asymmetric
        # text->media and media->text retrieval. The second text view has the
        # same source bytes but a different task/prompt-bound feature key.
        query = pair["text"]
        if query["input"].get("role") != "search_query":
            raise QualificationError("paired text must declare query role")
        document = {
            **query,
            "cell_id": "paired.document",  # valid owner-private ephemeral Cell
            "input": {**query["input"], "role": "document"},
        }
        # No fake embeddings: this invokes the pinned real model under a
        # single-scope admission, and retains just the 3 directional views.
        rows = runner.encode_cells([query, document, pair["media"]], media_root=media_root)["rows"]
        vectors[pair["case_id"]] = (
            rows[0]["features_q24"], rows[1]["features_q24"], rows[2]["features_q24"]
        )
    report = paired_cosine_metrics(pairs, vectors)
    report.update({"evidence_type": "local_multimodal_weight_execution_unverified_origin",
                   "model_revision": runner.manifest["revision"],
                   "stem_pipeline_digest": runner.profile_digest,
                   "total_encode_api_calls": runner.model_encode_calls,
                   "physical_transformer_forward_calls": None})
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--pairs", type=Path, required=True)
    p.add_argument("--media-root", type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    a = p.parse_args()
    pairs = json.loads(a.pairs.read_text(encoding="utf-8"))
    print(json.dumps(execute_pairs(
        FrozenGemmaShadow(a.manifest, device=a.device), pairs, a.media_root), sort_keys=True))
