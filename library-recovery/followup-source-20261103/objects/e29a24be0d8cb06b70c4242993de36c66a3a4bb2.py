"""Non-authorizing, source-paired v5 output/cost attribution gate.

The scorer operates on decoded synthetic outputs and external toy truth.  It
makes no claim of natural multimodal output, physical cost parity, independent
real-world facts, or production authorization.  Only exact four-arm, per-source
comparisons are admitted; a common cost *cap* cannot certify cost matching.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any

ARMS = (
    "supervised|static",
    "supervised|ndu_contextual",
    "ndu_risk|static",
    "ndu_risk|ndu_contextual",
)
COST_BY_ACTION = {
    "EMIT": 4,
    "REFINE_TEXT": 5,
    "REFINE_AUDIO": 5,
    "REFINE_IMAGE": 5,
    "REFINE_VIDEO": 5,
    "QUERY": 7,
}


def digest(data: Any) -> str:
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def _strict_finite_real(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def audit_paired_rows(rows: list[dict], *, seeds: tuple[int, ...],
                      expected_sources: dict[int, tuple[str, ...]],
                      min_sources: int = 32, cost_tolerance: float = 0.05,
                      alpha: float = 0.05) -> dict:
    """Audit independent decoded-score rows without looking at policy internals.

    Different source groups count once, not once per output, Head or arm. The
    Hoeffding lower confidence bound is intentionally conservative for bounded
    *synthetic* loss changes in [-8,8], Bonferroni-adjusted for two arms/seeds.
    It is diagnostic, not a valid human/real-data sampling guarantee.
    """
    if (not seeds or any(type(s) is not int for s in seeds)
        or len(set(seeds)) != len(seeds) or not isinstance(rows, list)
        or type(min_sources) is not int or min_sources < 32
        or not _strict_finite_real(cost_tolerance) or not 0 <= cost_tolerance <= 0.05
        or not _strict_finite_real(alpha) or not 0 < alpha <= 0.05):
        raise ValueError("invalid preregistered audit settings")
    if type(expected_sources) is not dict or set(expected_sources) != set(seeds):
        raise ValueError("missing frozen source census")
    census = {}
    for seed in seeds:
        expected = expected_sources[seed]
        if (type(expected) is not tuple or len(expected) < min_sources
            or any(type(s) is not str or not s.startswith(f"{seed}/test/")
                   for s in expected) or len(expected) != len(set(expected))):
            raise ValueError("invalid or non-test frozen source roster")
        census[seed] = set(expected)
    seen = {}
    source_binding = {}
    for r in rows:
        if type(r) is not dict or set(r) != {
            "seed", "source", "arm", "input_digest", "raw", "truth",
            "action", "loss", "wrong", "mismatch", "cost_units",
        }:
            raise ValueError("incomplete or extended source row")
        seed, source, arm = r["seed"], r["source"], r["arm"]
        if (type(seed) is not int or seed not in census
            or type(source) is not str or source not in census[seed]
            or type(arm) is not str or arm not in ARMS):
            raise ValueError("unregistered source, split or arm")
        key = (seed, source, arm)
        if key in seen:
            raise ValueError("duplicate source-arm outcome")
        input_digest = r["input_digest"]
        if (type(input_digest) is not str or len(input_digest) != 64
            or input_digest == "0" * 64
            or any(x not in "0123456789abcdef" for x in input_digest)):
            raise ValueError("invalid immutable input reference")
        src_key = (seed, source)
        if src_key in source_binding:
            if source_binding[src_key] != (input_digest, r["truth"]):
                raise ValueError("paired arms observe different source or truth")
        else:
            source_binding[src_key] = (input_digest, r["truth"])
        action = r["action"]
        if (type(action) is not str or action not in COST_BY_ACTION
            or type(r["cost_units"]) is not int
            or r["cost_units"] != COST_BY_ACTION[action]):
            raise ValueError("unfunded or fabricated realized action cost")
        # The actual raw decoded output is re-read through a scorer that is
        # separate from the factorial's terminal loss and policy fitting.
        from independent_observer import observe
        loss, wrong, mismatch, cost = observe(r["raw"], r["truth"], action)
        if (type(r["loss"]) is not int or type(r["wrong"]) is not int
            or type(r["mismatch"]) is not int
            or (loss, wrong, mismatch, cost) !=
               (r["loss"], r["wrong"], r["mismatch"], r["cost_units"])):
            raise ValueError("decoded terminal loss or resource tampering")
        seen[key] = r
    expected_keys = {(seed, source, arm)
                     for seed in seeds for source in census[seed] for arm in ARMS}
    if set(seen) != expected_keys:
        raise ValueError("incomplete four-arm test roster")
    effect = {}
    all_refinements = 0
    for seed in seeds:
        sources = sorted(census[seed])
        for training in ("supervised", "ndu_risk"):
            static = f"{training}|static"
            dynamic = f"{training}|ndu_contextual"
            paired_quality = [seen[(seed, s, static)]["loss"]
                              - seen[(seed, s, dynamic)]["loss"] for s in sources]
            paired_cost = [seen[(seed, s, dynamic)]["cost_units"]
                           - seen[(seed, s, static)]["cost_units"] for s in sources]
            mean_gain = math.fsum(paired_quality) / len(sources)
            mean_extra = math.fsum(paired_cost) / len(sources)
            # Difference is bounded to [-8,8], not 4 independent Head samples.
            comparisons = 2 * len(seeds)
            radius = 16.0 * math.sqrt(math.log(2.0 * comparisons / alpha)
                                       / (2.0 * len(sources)))
            key = f"{seed}:{training}"
            refinements = sum(seen[(seed, s, dynamic)]["action"].startswith("REFINE_")
                              for s in sources)
            all_refinements += refinements
            effect[key] = {
                "unique_source_groups": len(sources),
                "mean_external_loss_gain_static_minus_dynamic": mean_gain,
                "mean_executed_toy_cost_dynamic_minus_static": mean_extra,
                "bonferroni_hoeffding_gain_lcb": mean_gain - radius,
                "cost_cap_same_is_not_realized_cost_match": True,
                "realized_cost_matched_at_declared_tolerance":
                    abs(mean_extra) <= cost_tolerance,
                "prospective_quality_at_cost_gate":
                    (mean_gain - radius > 0 and abs(mean_extra) <= cost_tolerance),
                "dynamic_refinement_activations": refinements,
                "dynamic_query_activations": sum(
                    seen[(seed, s, dynamic)]["action"] == "QUERY" for s in sources),
            }
    return {
        "schema": "hepta.ndu-v5.paired-cost-falsification.v1",
        "scope": "SYNTHETIC_SHADOW_NON_AUTHORIZING",
        "source_groups": len(source_binding),
        "four_arm_decoded_rows": len(seen),
        "effects_by_seed_training": effect,
        "at_least_one_modality_refinement_executed": all_refinements > 0,
        "all_cost_matched_quality_gates": all(
            v["prospective_quality_at_cost_gate"] for v in effect.values()),
        "real_encoder_decoder_observed": False,
        "physical_meter_attested": False,
        "externally_signed_independent_truth": False,
        "longitudinal_future_window_admitted": False,
        "native_cell_causal_credit_admitted": False,
        "production_blockers_closed": False,
        "selection_or_final_use_authority": False,
    }


def execute_frozen_development_audit(seeds: tuple[int, ...] = (17, 29, 43),
                                     *, ntrain: int = 768, ndev: int = 256,
                                     ntest: int = 512, steps: int = 80) -> dict:
    """Execute actual frozen synthetic Head/policy and independent raw scorer.

    Work must not be relabelled as original-weight LLM or live hardware receipt.
    Not a prospective trial: these seeds were used in prior development.
    """
    from factorial import (TRAININGS, CONTROLS, make_worlds, train, train_policies,
                           predict, choose, apply_action, decode_raw)
    from independent_observer import observe
    rows = []
    census = {}
    for seed in seeds:
        train_set = make_worlds(seed, "train", ntrain)
        dev_set = make_worlds(seed, "dev", ndev)
        test_set = make_worlds(seed, "test", ntest)
        census[seed] = tuple(w.source_id for w in test_set)
        for training in TRAININGS:
            weights, _ = train(train_set, seed, training, steps=steps)
            critic = train_policies(dev_set, weights)
            for control in CONTROLS:
                for world in test_set:
                    public = world.public
                    probabilities = predict(public, weights)
                    action = choose(public, probabilities, critic, control)
                    # No hidden truth, witness or common_flip enters choose().
                    raw = decode_raw(apply_action(probabilities, action, world.witness))
                    loss, wrong, mismatch, cost = observe(raw, world.truth, action)
                    rows.append({
                        "seed": seed, "source": world.source_id,
                        "arm": f"{training}|{control}",
                        "input_digest": digest((public.source_id, public.mode,
                                                public.signals)),
                        "raw": raw, "truth": world.truth,
                        "action": action, "loss": loss, "wrong": wrong,
                        "mismatch": mismatch, "cost_units": cost,
                    })
    result = audit_paired_rows(rows, seeds=seeds, expected_sources=census)
    result["developed_source_roster_digest"] = digest(census)
    result["decoded_evidence_rows_digest"] = digest(rows)
    return result


if __name__ == "__main__":
    print(json.dumps(execute_frozen_development_audit(), sort_keys=True, indent=2))
