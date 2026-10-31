"""Independent synthetic checks of audiovisual evaluation and uncertainty.

No cohort tensor, model checkpoint, validation outcome, or heldout prediction
is loaded. Retrieval is compared with explicit lexicographic ranking. An exact
finite convolution gives the bootstrap distribution for an additive 8x8 case.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp, softmax

from ..av.analysis import crossed_interval
from ..av.metrics import derangement, evaluation_arrays, retrieval_ranks


def run(output):
    start = time.process_time()
    checks, details = [], {}

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    rng = np.random.default_rng(541782)
    actors = np.repeat(np.arange(3), 4)
    examples = (
        ("random", rng.normal(size=(12, 5)), rng.normal(size=(12, 5))),
        ("all_ties", np.zeros((12, 5)), np.zeros((12, 5))),
    )
    for name, audio, video in examples:
        ranks, counts = retrieval_ranks(audio, video, actors)
        a = audio / np.maximum(np.linalg.norm(audio, axis=1, keepdims=True), 1e-12)
        v = video / np.maximum(np.linalg.norm(video, axis=1, keepdims=True), 1e-12)
        similarity = a @ v.T
        for direction, scores in (("audio_to_video", similarity), ("video_to_audio", similarity.T)):
            for scope in ("whole", "same_actor"):
                expected = []
                for index, row in enumerate(scores):
                    candidates = np.arange(len(actors)) if scope == "whole" else np.flatnonzero(actors == actors[index])
                    ordered = candidates[np.lexsort((candidates, -row[candidates]))]
                    expected.append(int(np.flatnonzero(ordered == index)[0]) + 1)
                check(name + "/" + direction + "/" + scope,
                      np.array_equal(expected, ranks[direction + "_" + scope]))
        check(name + "/same_actor_candidate_counts", np.array_equal(counts, np.full(12, 4)))
    for seed in range(882901, 882906):
        for scope in (None, actors):
            indices = derangement(len(actors), seed, scope)
            check("derangement/" + str(seed) + ("/whole" if scope is None else "/same_actor"),
                  np.all(indices != np.arange(len(actors))) and len(np.unique(indices)) == len(actors)
                  and (scope is None or np.array_equal(actors, actors[indices])))

    a, v = rng.normal(size=(12, 5)), rng.normal(size=(12, 5))
    weight, bias = rng.normal(size=(5, 6)), rng.normal(size=6)
    la, lv = a @ weight + bias, v @ weight + bias
    labels = np.arange(12) % 6
    outputs = dict(audio_embedding=a, video_embedding=v, audio_logits=la,
                   video_logits=lv, fused_logits=.5 * (la + lv))
    arrays, result = evaluation_arrays(outputs, labels, actors.astype(str),
                                      np.array([f"fixture-{i}" for i in range(12)]), "synthetic")
    for scope, key in (("global", "global_derangement"), ("same_actor", "same_actor_derangement")):
        recomputed = (.5 * (a + v[arrays[key]])) @ weight + bias
        error = float(np.max(np.abs(recomputed - arrays["fused_" + scope + "_derangement_logits"])))
        check(scope + "/embedding_and_shared_linear_head_intervention", error < 5e-14, error)
    for channel, summary in result["classification"].items():
        logits = arrays[channel + "_logits"]
        probabilities = softmax(logits, axis=1)
        expected_ce = float(np.mean(logsumexp(logits, axis=1) - logits[np.arange(12), labels]))
        expected_brier = float(np.mean(np.sum((probabilities - np.eye(6)[labels]) ** 2, axis=1)))
        correct, confidence = np.argmax(logits, axis=1) == labels, probabilities.max(axis=1)
        bin_index = np.minimum(9, np.floor(10 * confidence).astype(int))
        expected_ece = sum(float(np.mean(bin_index == index)) *
            abs(float(np.mean(correct[bin_index == index])) - float(np.mean(confidence[bin_index == index])))
            for index in range(10) if np.any(bin_index == index))
        check(channel + "/independent_FP64_classification_calibration", max(
            abs(summary["cross_entropy"] - expected_ce), abs(summary["brier"] - expected_brier),
            abs(summary["ece"] - expected_ece), abs(summary["accuracy"] - float(np.mean(correct)))) < 5e-14)

    # For M[s,a]=(s-3.5)/100+(a-3.5)/25, bootstrap means equal
    # (sum(seed_indices)+4*sum(actor_indices)-140)/800. Eight independent
    # uniform categorical draws per dimension have exactly computable PMFs.
    pmf = np.array([1.0])
    for _ in range(8):
        pmf = np.convolve(pmf, np.full(8, 1 / 8))
    actor_pmf = np.zeros(4 * (len(pmf) - 1) + 1)
    actor_pmf[::4] = pmf
    joint_pmf = np.convolve(pmf, actor_pmf)
    support = (np.arange(len(joint_pmf)) - 140) / 800
    exact = support[np.searchsorted(np.cumsum(joint_pmf), [.025, .975, .05 / 8])]
    matrix = (np.arange(8)[:, None] - 3.5) / 100 + (np.arange(8)[None, :] - 3.5) / 25
    measured = crossed_interval(matrix, 883901, repetitions=20000, family_size=8)
    observed = np.array([*measured["percentile95"], measured["one_sided_bonferroni_lower"]])
    details["exact_crossed_additive_case"] = dict(exact_quantiles=exact.tolist(),
        monte_carlo_quantiles=observed.tolist(), absolute_errors=np.abs(observed - exact).tolist(),
        permitted_grid_steps=3, grid_step=1 / 800, repetitions=20000,
        interpretation="Monte Carlo approximation test for this known empirical resampling distribution, not a coverage theorem for real actors")
    check("crossed_bootstrap_against_exact_finite_convolution", np.max(np.abs(observed - exact)) <= 3 / 800,
          details["exact_crossed_additive_case"])
    constant = crossed_interval(np.full((8, 8), .125), 883902)
    check("constant_seed_actor_effect", constant["mean"] == .125
          and constant["percentile95"] == [.125, .125] and constant["one_sided_bonferroni_lower"] == .125)
    base = Path(__file__).resolve().parents[1]
    sources = {str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in [base / "av" / name for name in ("study.py", "model.py", "metrics.py", "analysis.py", "AV_DESIGN.json")]
               + [Path(__file__).resolve()]}
    report = dict(schema="hcsn-independent-av-math-metrics-review.v1", passed=all(row["passed"] for row in checks),
        checks=checks, details=details, source_sha256=sources, cpu_seconds=time.process_time() - start,
        real_data_loaded=False, model_training=False,
        limitations=["Only synthetic evaluation and bootstrap mathematics checked here",
                     "Pair-shuffle degradation alone does not prove complementary cross-modal reasoning",
                     "The model has additive late fusion; no cross-attention or joint content interaction is introduced",
                     "Crossed bootstrap coverage remains approximate with only eight heldout actors"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps(dict(passed=report["passed"], checks=len(report["checks"]), cpu_seconds=report["cpu_seconds"])))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
