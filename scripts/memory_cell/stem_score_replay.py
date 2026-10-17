"""Independent arithmetic replay of the native selection score vectors.

The producer may store only numeric logits and SHA-bound window identities,
NEVER gold answers or evidence excerpts. This audit reconstructs top-1,
margins and residual flip infima without calling the encoder, Head or Reader.
Results are observational and cannot authorize counterfactual scaling.
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re

from native import digest
from stem_audit_archive import require, parse_json

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")


def _best(scores, identifiers):
    return (
        min(range(len(identifiers)), key=lambda i: (-scores[i], identifiers[i]))
        if identifiers
        else None
    )


def _gap(scores, identifiers):
    order = sorted(range(len(identifiers)), key=lambda i: (-scores[i], identifiers[i]))
    return scores[order[0]] - scores[order[1]] if len(order) > 1 else None


def _min_flip_scale(frozen, learned, identifiers):
    old = _best(frozen, identifiers)
    if old is None or len(identifiers) < 2:
        return None
    origin = learned[old] - frozen[old]
    require(math.isfinite(origin), "nonfinite frozen-score delta")
    candidates = []
    for i in range(len(identifiers)):
        if i == old:
            continue
        gain = (learned[i] - frozen[i]) - origin
        require(math.isfinite(gain), "nonfinite candidate rank residual")
        if gain > 0:
            gap = (frozen[old] - frozen[i]) / gain
            require(math.isfinite(gap) and gap >= 0, "unbounded flip infimum")
            candidates.append(gap)
    return min(candidates) if candidates else None


def _same(observed, expected):
    if observed is None or expected is None:
        return observed is None and expected is None
    return (
        type(observed) in (float, int)
        and math.isfinite(observed)
        and math.isclose(observed, expected, rel_tol=1e-11, abs_tol=1e-8)
    )


def replay_one(policy, raw):
    identity = (policy["stage"], policy["phase"], policy["question_id"], policy["arm"])
    require(
        identity
        == (raw.get("stage"), raw.get("phase"), raw.get("question_id"), raw.get("arm"))
        and identity[0] in STAGES
        and identity[1] in PHASES
        and identity[3] in ARMS
        and policy["cell"] == raw.get("cell")
        and policy["family"] == raw.get("source_family")
        and policy.get("selection_geometry") is not None
        and policy["selection_geometry"]["schema"] == "hepta.stem-selection-geometry.v2"
        and raw.get("schema") == "hepta.stem-selection-score-vectors.v1"
        and raw.get("answer_targets_read") is False
        and raw.get("source_excerpts_recorded") is False
        and raw.get("production_accepted") is False,
        "score record not bound to original label-free pre-Reader decision",
    )
    geom = policy["selection_geometry"]
    ids = raw.get("candidate_ids")
    old, mid, after = (
        raw.get("original_frozen_logits"),
        raw.get("post_adapter_encoder_logits"),
        raw.get("checkpoint_head_logits"),
    )
    require(
        isinstance(ids, list)
        and all(isinstance(x, str) and bool(x) for x in ids)
        and len(ids) == len(set(ids))
        and len(ids) <= 64
        and all(isinstance(x, list) and len(x) == len(ids) for x in (old, mid, after))
        and all(
            type(v) in (float, int) and math.isfinite(v)
            for vector in (old, mid, after)
            for v in vector
        )
        and isinstance(raw.get("source_pool_sha256"), str)
        and raw["source_pool_sha256"] == policy.get("pool_digest")
        and isinstance(raw.get("candidate_ids_sha256"), str)
        and raw["candidate_ids_sha256"] == digest(tuple(ids))
        and type(raw.get("null_logit")) in (int, float)
        and math.isfinite(raw["null_logit"])
        and raw.get("geometry_sha256") == digest(geom)
        and raw.get("raw_scores_sha256") == geom["raw_scores_sha256"]
        and raw["raw_scores_sha256"] == digest((tuple(ids), old, mid, after))
        and (
            raw.get("selected_index")
            == geom["selected_index"]
            == policy.get("selected")
        ),
        "misbound/malformed numeric logit vectors or score/feature source pins",
    )
    adapted = identity[3] in ("lineage_lora_gated", "independent_lora_gated")
    for key in ("original_feature_sha256", "checkpoint_feature_sha256"):
        require(
            isinstance(raw.get(key), str)
            and re.fullmatch(r"[0-9a-f]{64}", raw[key]) is not None,
            "missing immutable original/adapted feature snapshot identity",
        )
    if policy.get("feature_digest") is not None:
        require(
            raw["checkpoint_feature_sha256"] == policy["feature_digest"],
            "checkpoint feature hash differs from original policy receipt",
        )
    if not adapted:
        require(
            old == mid
            and raw["original_feature_sha256"] == raw["checkpoint_feature_sha256"],
            "nonadapted arm substituted a second Encoder representation",
        )
    if identity[3] == "frozen_rerank":
        require(after == old, "frozen baseline cannot have trained score residual")
    require(
        raw.get("encoder_adapted") is adapted and geom["encoder_adapted"] is adapted,
        "adapter-backed logits masquerade as original frozen Encoder",
    )
    bo, bm, bh = (_best(v, ids) for v in (old, mid, after))
    top = lambda index: ids[index] if index is not None else None
    require(
        top(bo) == geom["baseline_top_id"]
        and top(bm) == geom["encoder_only_top_id"]
        and top(bh) == geom["learned_top_id"]
        and bh == geom["selected_index"]
        and (bo != bm) is geom["encoder_only_changed_selected_candidate"]
        and (bm != bh) is geom["head_changed_selected_candidate"]
        and (bo != bh) is geom["changed_selected_candidate"],
        "actual winner or three-way Encoder/Head attribution disagrees",
    )
    encoder_delta = max(
        (abs(x - y) for x, y in zip(old, mid, strict=True)), default=0.0
    )
    head_delta = max((abs(x - y) for x, y in zip(mid, after, strict=True)), default=0.0)
    total_delta = max(
        (abs(x - y) for x, y in zip(old, after, strict=True)), default=0.0
    )
    gap = _gap(old, ids)
    expected = dict(
        frozen_top1_gap=gap,
        encoder_only_top1_gap=_gap(mid, ids),
        learned_top1_gap=_gap(after, ids),
        encoder_only_max_abs_score_delta=encoder_delta,
        head_conditional_max_abs_score_delta=head_delta,
        max_abs_score_delta=total_delta,
        gap_exceeds_twice_max_residual=(
            gap > 2 * total_delta if gap is not None else None
        ),
        encoder_only_flip_scale_infimum=_min_flip_scale(old, mid, ids),
        head_conditional_flip_scale_infimum=_min_flip_scale(mid, after, ids),
        joint_flip_scale_infimum=_min_flip_scale(old, after, ids),
    )
    for name, v in expected.items():
        if name == "gap_exceeds_twice_max_residual":
            require(geom.get(name) is v, "original rank stability bound changed")
        else:
            require(
                _same(geom.get(name), v),
                "original derived geometry does not match source logits: " + name,
            )
    require(
        geom["candidate_count"] == len(ids)
        and geom["label_free"] is True
        and geom["evidence_entailment_evaluated"] is False
        and geom["no_answer_policy_calibrated"] is False,
        "invalid evidence-free source geometry",
    )
    return dict(
        stage=identity[0],
        phase=identity[1],
        arm=identity[3],
        cell=raw["cell"],
        question_id=identity[2],
        candidate_count=len(ids),
        original_rank_equals_adapted=(bo == bm),
        source_rank_changed=(bo != bh),
        direction_can_flip=expected["joint_flip_scale_infimum"] is not None,
        scale_infimum=expected["joint_flip_scale_infimum"],
        source_label_correctness_known_here=False,
    )


def replay_all(predictions, journal):
    indexed = {}
    for p in predictions:
        key = (p["stage"], p["phase"], p["question_id"], p["arm"])
        require(key not in indexed, "duplicate original policy key")
        indexed[key] = p
    observed, frozen_anchor = {}, {}
    for r in journal:
        key = (r["stage"], r["phase"], r["question_id"], r["arm"])
        require(
            key in indexed and key not in observed, "extra/duplicate score-vector row"
        )
        observed[key] = replay_one(indexed[key], r)
        # All six arms and all persistent checkpoints use the SAME frozen
        # original query, source scope, candidate set and pair-Encoder bytes.
        # An internally self-consistent forged arm must not silently become
        # an independent frozen baseline for cross-arm comparisons.
        identity = (r["phase"], r["question_id"])
        anchor = (
            tuple(r["candidate_ids"]),
            tuple(r["original_frozen_logits"]),
            r["original_feature_sha256"],
            r["source_pool_sha256"],
            r["cell"],
            r["source_family"],
        )
        if identity in frozen_anchor:
            require(
                frozen_anchor[identity] == anchor,
                "original frozen source/feature candidates drifted across arms or checkpoints",
            )
        else:
            frozen_anchor[identity] = anchor
    expected = {key for key, row in indexed.items() if "selection_geometry" in row}
    require(set(observed) == expected, "missing pre-Reader score vectors")
    group = defaultdict(list)
    for item in observed.values():
        group[(item["stage"], item["phase"], item["arm"])].append(item)
    return dict(
        schema="hepta.stem-independent-raw-score-replay.v1",
        original_policy_rows=len(predictions),
        pre_reader_score_journal_rows=len(journal),
        audited_pre_reader_rows=len(observed),
        unique_observed_questions=len(frozen_anchor),
        frozen_input_crossarm_checkpoint_identity_verified=True,
        checkpoint_repeats_not_independent_questions=True,
        by_stage_phase_arm={
            "/".join(map(str, key)): dict(
                observed=len(values),
                actual_source_rank_changes=sum(
                    x["source_rank_changed"] for x in values
                ),
                unscalable_wrong_direction=sum(
                    not x["direction_can_flip"] for x in values
                ),
                direction_viable_needs_scale_above_one=sum(
                    x["scale_infimum"] is not None and x["scale_infimum"] > 1
                    for x in values
                ),
            )
            for key, values in sorted(group.items())
        },
        raw_source_excerpts_stored=False,
        target_or_semantic_gold_read=False,
        model_or_reader_executions=0,
        candidate_policy_modified=False,
        production_accepted=False,
    )


def _read_json(path, *, lines=False):
    require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size <= 64 * 1024 * 1024,
        "bounded regular file required",
    )
    data = path.read_bytes()
    if lines:
        records = [parse_json(row) for row in data.splitlines()]
        require(0 < len(records) <= 4000, "score log bound")
        return records
    return parse_json(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policies", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay_all(
        _read_json(args.policies, lines=True), _read_json(args.scores, lines=True)
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
