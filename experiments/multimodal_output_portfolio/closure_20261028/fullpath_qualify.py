"""One source-sealed qualification after the preregistered development gate."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..v6.plan_training import ControlledSnapshot
from ..continuation_20261027.joint.data import historical_corpus, fresh_corpus
from ..continuation_20261027.joint.run import reference_observer
from ..closure_v2_20261027.allocate_admission_sources import source_ids
from ..unified_20261028.profile import NduProfile, digest
from .fullpath_evaluate import audit, evaluate
from .fullpath_model import file_sha, load_model
from .fullpath_protocol import P, profiles, qualification_corpus, write_json


def paired_contrast(left, right, gamma):
    """Original-source bootstrap; all fixed training seeds share each resample."""
    seeds = sorted(left)
    if seeds != sorted(right):
        raise ValueError("The compared fixed training seeds differ")

    def group(rows):
        grouped, seen = {}, set()
        for row in rows:
            identity = (row["context_id"], row["sample_id"])
            if identity in seen:
                raise ValueError("A paired comparison contains a repeated executed draw")
            seen.add(identity)
            grouped.setdefault(row["source_cluster_id"], []).append(row["net_return"])
        return grouped

    a, b = ({seed: group(arm[seed]) for seed in seeds} for arm in (left, right))
    sources = sorted(a[seeds[0]])
    if not sources or any(sorted(arm[seed]) != sources for arm in (a, b) for seed in seeds):
        raise ValueError("Compared arms do not use identical original-source clusters")
    aa, bb = [np.array([[arm[seed][source] for source in sources] for seed in seeds]) for arm in (a, b)]
    if aa.shape != bb.shape:
        raise ValueError("The condition and rollout multiplicities differ")

    def ce(values):
        if gamma == 0:
            return values.mean(axis=(-1, -2))
        exponent = -gamma * values
        maximum = exponent.max(axis=(-1, -2), keepdims=True)
        return -(np.log(np.exp(exponent - maximum).mean(axis=(-1, -2))) + maximum[..., 0, 0]) / gamma

    difference = ce(aa) - ce(bb)
    rng, bootstrap = np.random.default_rng(28261091), []
    gates = P["qualification_acceptance"]
    for _ in range(gates["bootstrap_draws"]):
        indices = rng.integers(len(sources), size=len(sources))
        bootstrap.append(float((ce(aa[:, indices]) - ce(bb[:, indices])).mean()))
    lower_quantile = gates["family_alpha"] / gates["one_sided_comparisons"]
    return {"mean_seed_ce_difference": float(difference.mean()),
            "per_training_seed_difference": dict(zip(map(str, seeds), difference.tolist())),
            "paired_source_ci95": np.quantile(bootstrap, [.025, .975]).tolist(),
            "familywise_one_sided_lower": float(np.quantile(bootstrap, lower_quantile)),
            "lower_quantile": lower_quantile, "distinct_source_pairs": len(sources),
            "fixed_trained_seeds": seeds, "bootstrap_draws": len(bootstrap),
            "seed_is_risk_outcome": False, "writer_independence_established": False,
            "finite_sample_coverage_proved": False,
            "coverage_scope": "approximate source-cluster percentile bootstrap; Bonferroni across four frozen acceptance claims"}


def verify_development(development):
    seal = json.loads((development / "DEVELOPMENT_SEAL.json").read_text())
    if (seal["smoke_only"] or seal["qualification_predictions"] != 0
            or not seal["qualification_admitted"] or not all(seal["admission_checks"].values())):
        raise ValueError("Qualification is blocked unless the frozen complete development gate passed")
    for key, name in (("protocol_sha256", "PROTOCOL.json"), ("selection_sha256", "SELECTIONS.json"),
                      ("source_allocation_sha256", "SOURCE_ALLOCATION.json")):
        if file_sha(development / name) != seal[key]:
            raise ValueError("Sealed development evidence was changed")
    protocol = json.loads((development / "PROTOCOL.json").read_text())
    if protocol.pop("smoke_only") or digest(protocol) != digest(P):
        raise ValueError("The preregistered study protocol changed")
    runtime = json.loads((development / "RUNTIME.json").read_text())
    for name, expected in runtime["executed_source_sha256"].items():
        if (file_sha(Path(__file__).parent / name) != expected
                or file_sha(development / "executed-source" / name) != expected):
            raise ValueError("Executed training or qualification semantics changed")
    selections = json.loads((development / "SELECTIONS.json").read_text())
    expected = {(seed, arm) for seed in P["training_seeds"] for arm in P["arms"]}
    if {(row["seed"], row["arm"]) for row in selections} != expected or len(selections) != len(expected):
        raise ValueError("A trained seed or matched arm was omitted")
    for choice in selections:
        if choice["selected"] not in choice["candidates"] or not choice["selected"]["eligible"]:
            raise ValueError("The selected candidate was not retention eligible")
        candidates = [row for row in choice["candidates"] if row["eligible"]]
        if choice["selected"] != max(candidates, key=lambda row: row["quality_ce"]):
            raise ValueError("Selection does not implement the frozen development rule")
        for candidate in choice["candidates"]:
            if candidate["path"] and file_sha(candidate["path"]) != candidate["checkpoint_sha256"]:
                raise ValueError("A scored checkpoint changed after selection")
    return seal, selections


def verify_sources(assets, development):
    allocation = json.loads((development / "SOURCE_ALLOCATION.json").read_text())
    historical = historical_corpus(assets)
    earlier = fresh_corpus(assets, historical)
    excluded = {h for corpus in (historical, earlier) for split in corpus.splits.values() for h in split.pixel_hashes}
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    excluded.update(original.get("prior_heldout_exclusion", {}).get("source_pixel_sha256", []))
    portfolio = Path(__file__).resolve().parent.parent
    for name, expected in allocation["prior_allocation_pins"].items():
        path = portfolio / name
        if file_sha(path) != expected:
            raise ValueError("A prior-source exclusion allocation changed")
        excluded.update(identity.rsplit(":", 1)[1] for identity in source_ids(json.loads(path.read_text())))
    if digest(sorted(excluded)) != allocation["excluded_pixel_hashes_sha256"]:
        raise ValueError("The complete known historical exclusion pool changed")
    corpus = qualification_corpus(assets, development / "SOURCE_ALLOCATION.json")
    expected_counts = {"test": 2 * P["qualification_pairs"], "retention": 2 * P["retention_pairs"]}
    if set(corpus.splits) != set(expected_counts):
        raise ValueError("Unexpected held-out cohort roles")
    for name, count in expected_counts.items():
        selected = corpus.splits[name].pixel_hashes
        if len(selected) != count or set(selected) & excluded:
            raise ValueError("The new cohort size or original-pixel exclusion rule was violated")
    return corpus, {"known_excluded_unique_pixels": len(excluded), "source_counts": expected_counts,
                    "known_historical_overlap": 0, "writer_independence_established": False,
                    "all_global_historical_usage_known": False, "model_predictions_during_source_audit": 0}


def qualify(assets, baseline, development, output):
    seal, selections = verify_development(development)
    primary = NduProfile.from_dict(json.loads((development / "PROFILE.json").read_text()))
    mean = NduProfile.from_dict(json.loads((development / "MEAN_CONTROL_PROFILE.json").read_text()))
    current_primary, current_mean, semantics = profiles(assets / "ndu-runs/full-002/reward-observer.pt")
    if (primary.digest != current_primary.digest or mean.digest != current_mean.digest
            or primary.digest != seal["profile_sha256"]
            or file_sha(baseline) != P["reference_checkpoint_sha256"]
            or digest(semantics) != digest(json.loads((development / "SEMANTICS.json").read_text()))):
        raise ValueError("The actual objective, emission law, observer or reference changed")
    output.mkdir(parents=True, exist_ok=False)
    claim = {"output": str(output.resolve()), "development_seal_sha256": file_sha(development / "DEVELOPMENT_SEAL.json"),
             "profile_sha256": primary.digest, "allocation_sha256": file_sha(development / "SOURCE_ALLOCATION.json"),
             "selected": selections, "qualified_once": True, "target_predictions_at_seal": 0,
             "qualification_source_sha256": file_sha(__file__)}
    write_json(development / "QUALIFICATION_CLAIM.json", claim)
    write_json(output / "QUALIFICATION_SEAL.json", claim)
    corpus, source_audit = verify_sources(assets, development)
    write_json(output / "SOURCE_AUDIT.json", source_audit)
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    reference, observer = ControlledSnapshot.load(baseline), reference_observer(assets, "reward")
    arms = ("prior_strong", "stochastic_frozen", "lax_mean", "lax_risk")
    rows = {scope: {arm: {} for arm in arms} for scope in ("quality", "retention")}
    summaries, totals, audits = [], {}, []
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    for seed in P["training_seeds"]:
        for arm in arms:
            selected, deterministic = None, arm == "prior_strong"
            model = reference._base._model
            if arm in P["arms"]:
                selected = next(row["selected"] for row in selections if row["seed"] == seed and row["arm"] == arm)
                deterministic = selected["deterministic"]
                if selected["path"] is not None:
                    model = load_model(selected["path"], mean if arm == "lax_mean" else primary)[0]
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
            check = audit(path, corpus, observer, primary)
            if check["maximum_return_discrepancy"] > 1e-6:
                raise ValueError("Archived actual outputs do not reproduce their declared primary returns")
            audits.append({"arm": arm, "seed": seed, **check})
            write_json(path / "READBACK_AUDIT.json", check)
            print(f"qualified seed={seed} arm={arm} CE={result['groups']['quality']['summary']['value']:.6f}", flush=True)
    comparisons = {scope: {arm: paired_contrast(rows[scope]["lax_risk"], rows[scope][arm], primary.gamma)
                           for arm in ("prior_strong", "stochastic_frozen", "lax_mean")} for scope in rows}
    acceptance = {f"risk_quality_beats_{arm}": comparisons["quality"][arm]["familywise_one_sided_lower"] > 0
                  for arm in P["qualification_acceptance"]["risk_quality_vs_each"]}
    acceptance["retention_within_tolerance"] = (comparisons["retention"]["prior_strong"]["familywise_one_sided_lower"]
                                               >= -P["retention_tolerance"])
    write_json(output / "RESULT.json", {"profile_sha256": primary.digest, "comparisons": comparisons,
        "acceptance": acceptance, "all_acceptance_passed": all(acceptance.values()),
        "per_seed_arm": summaries, "counts_and_timing": totals, "reopened_output_audits": audits,
        "qualification_wall_ns": time.perf_counter_ns() - wall, "qualification_cpu_ns": time.process_time_ns() - cpu,
        "seeds_share_one_strong_initialization": True, "finite_sample_coverage_proved": False,
        "soft_proxy_used_for_evaluation": False, "complete_physical_CPU_certificate": False,
        "global_optimality_established": False, "production_promotion": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "baseline", "development", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    qualify(args.assets, args.baseline, args.development, args.output)
