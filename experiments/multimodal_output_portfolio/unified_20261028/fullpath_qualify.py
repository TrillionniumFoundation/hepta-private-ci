"""One sealed qualification after development, with seed-aware source pairing."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..v6.plan_training import ControlledSnapshot
from ..continuation_20261027.joint.run import reference_observer
from .generator import file_sha, load_model
from .fullpath_protocol import P, qualification_corpus, write_json
from .fullpath_evaluate import evaluate
from .profile import NduProfile


def paired_contrast(left, right, draws=2000, gamma=2.):
    """Bootstrap sources jointly across fixed trained seeds, then average seed CEs."""
    seeds = sorted(left)
    if seeds != sorted(right):
        raise ValueError("Training-seed pairs differ")
    def group(rows):
        result = {}
        for row in rows:
            result.setdefault(row["source_cluster_id"], []).append(row["net_return"])
        return result
    a, b = {s: group(left[s]) for s in seeds}, {s: group(right[s]) for s in seeds}
    sources = sorted(a[seeds[0]])
    if any(sorted(c[s]) != sources for c in (a, b) for s in seeds):
        raise ValueError("Original source clusters differ across paired comparisons")
    aa, bb = [np.array([[c[s][i] for i in sources] for s in seeds]) for c in (a, b)]
    if aa.shape != bb.shape:
        raise ValueError("Rollout and condition counts differ")
    def ce(x):
        if gamma == 0:
            return x.mean(axis=(-1, -2))
        z = -gamma * x
        maximum = z.max(axis=(-1, -2), keepdims=True)
        return -(np.log(np.exp(z - maximum).mean(axis=(-1, -2))) + maximum[..., 0, 0]) / gamma
    difference = ce(aa) - ce(bb)
    rng, boot = np.random.default_rng(28105613), []
    for _ in range(draws):
        indices = rng.integers(len(sources), size=len(sources))
        boot.append(float((ce(aa[:, indices]) - ce(bb[:, indices])).mean()))
    return {"mean_seed_ce_difference": float(difference.mean()),
            "per_training_seed_difference": dict(zip(map(str, seeds), difference.tolist())),
            "paired_source_ci95": np.quantile(boot, [.025, .975]).tolist(),
            "distinct_source_pairs": len(sources), "fixed_trained_seeds": seeds,
            "bootstrap_draws": draws, "seed_is_risk_outcome": False,
            "writer_independence_established": False}


def verify_development(development):
    seal = json.loads((development / "DEVELOPMENT_SEAL.json").read_text())
    if seal["smoke_only"] or seal["qualification_predictions"] != 0:
        raise ValueError("Only a complete prespecified development study may qualify")
    for key, name in (("protocol_sha256", "PROTOCOL.json"), ("selection_sha256", "SELECTIONS.json"),
                      ("source_allocation_sha256", "SOURCE_ALLOCATION.json")):
        if file_sha(development / name) != seal[key]:
            raise ValueError("Development evidence changed after selection")
    runtime = json.loads((development / "RUNTIME.json").read_text())
    for name, sha in runtime["executed_source_sha256"].items():
        if file_sha(Path(__file__).parent / name) != sha:
            raise ValueError("Executed development/qualification semantics changed")
    for choice in json.loads((development / "SELECTIONS.json").read_text()):
        for candidate in choice["candidates"]:
            if candidate["path"] and file_sha(candidate["path"]) != candidate["checkpoint_sha256"]:
                raise ValueError("Scored development checkpoint changed")
    return seal


def qualify(assets, baseline, development, output):
    seal = verify_development(development)
    primary = NduProfile.from_dict(json.loads((development / "PROFILE.json").read_text()))
    mean = NduProfile.from_dict(json.loads((development / "MEAN_CONTROL_PROFILE.json").read_text()))
    semantics = json.loads((development / "SEMANTICS.json").read_text())
    if file_sha(assets / "ndu-runs/full-002/reward-observer.pt") != semantics["observer"]["weights_file_sha256"]:
        raise ValueError("Qualification reward observer changed after objective freeze")
    if primary.digest != seal["profile_sha256"] or file_sha(baseline) != P["reference_checkpoint_sha256"]:
        raise ValueError("Qualification profile or reference changed")
    output.mkdir(parents=True, exist_ok=False)
    selections = json.loads((development / "SELECTIONS.json").read_text())
    write_json(output / "QUALIFICATION_SEAL.json", {"development_seal_sha256": file_sha(development / "DEVELOPMENT_SEAL.json"),
        "profile_sha256": primary.digest, "allocation_sha256": file_sha(development / "SOURCE_ALLOCATION.json"),
        "selected": selections, "qualified_once": True,
        "qualification_source_sha256": file_sha(__file__), "target_predictions_at_seal": 0}, exclusive=True)
    corpus = qualification_corpus(assets, development / "SOURCE_ALLOCATION.json")
    reference = ControlledSnapshot.load(baseline)
    observer = reference_observer(assets, "reward")
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    arms = ("prior_strong", "stochastic_frozen", "fullpath_mean", "fullpath_risk")
    rows = {scope: {arm: {} for arm in arms} for scope in ("quality", "retention")}
    summaries, totals = [], {}
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    for seed in P["training_seeds"]:
        for arm in arms:
            deterministic = arm == "prior_strong"
            selected = None
            if arm in ("prior_strong", "stochastic_frozen"):
                model = reference._base._model
            else:
                selected = next(r["selected"] for r in selections if r["seed"] == seed and r["arm"] == arm)
                deterministic = selected["path"] is None
                model = reference._base._model if deterministic else load_model(selected["path"], mean if arm == "fullpath_mean" else primary)[0]
            path = output / f"seed-{seed}-{arm}"
            result = evaluate(model, reference, corpus, observer, primary, seed, path,
                              split="qualification", retain=True, deterministic=deterministic)
            for scope in rows:
                rows[scope][arm][seed] = result["groups"][scope]["rows"]
            summaries.append({"arm": arm, "seed": seed, "selected": selected,
                              "metrics": {scope: result["groups"][scope]["summary"] for scope in rows},
                              "timing": result["timing"], "evaluation_sha256": file_sha(path / "EVALUATION.json")})
            for key, value in result["timing"].items():
                totals[key] = totals.get(key, 0) + value
            write_json(output / "RUNNING_RECEIPTS.json", summaries)
            print(f"qualified seed={seed} arm={arm} CE={result['groups']['quality']['summary']['value']:.6f}", flush=True)
    comparisons = {}
    for scope in rows:
        comparisons[scope] = {reference_arm: paired_contrast(rows[scope]["fullpath_risk"], rows[scope][reference_arm])
                              for reference_arm in ("prior_strong", "stochastic_frozen", "fullpath_mean")}
    quality = comparisons["quality"]
    acceptance = {"risk_beats_strong": quality["prior_strong"]["paired_source_ci95"][0] > 0,
                  "risk_beats_matched_mean": quality["fullpath_mean"]["paired_source_ci95"][0] > 0,
                  "retention_within_tolerance": comparisons["retention"]["prior_strong"]["paired_source_ci95"][0] >= -P["retention_tolerance"]}
    write_json(output / "RESULT.json", {"profile_sha256": primary.digest, "comparisons": comparisons,
        "acceptance": acceptance, "per_seed_arm": summaries, "counts_and_timing": totals,
        "qualification_wall_ns": time.perf_counter_ns() - wall, "qualification_cpu_ns": time.process_time_ns() - cpu,
        "seeds_share_prior_strong_checkpoint": True, "new_source_pair_counts": {"quality": P["qualification_pairs"], "retention": P["retention_pairs"]},
        "global_optimality_established": False, "production_promotion": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "baseline", "development", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    qualify(args.assets, args.baseline, args.development, args.output)
