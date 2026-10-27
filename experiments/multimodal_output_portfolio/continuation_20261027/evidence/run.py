"""Freeze on source-held-out validation, then deliver and score fresh source groups."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from ...repair_20261026.evidence.joint import JointObservationLaw, arrived_receipts
from .data import AREA, PROTOCOL, digest, observe, save
from .models import CUES, FAMILIES, fit_law, fit_prior, measured_pairs, metrics, posterior, prior_cases


def read(path):
    return json.loads(Path(path).read_text())


def fit(arguments):
    started, cpu = time.perf_counter(), time.process_time()
    protocol = read(PROTOCOL)
    arguments.output.mkdir(parents=True, exist_ok=False)
    save(arguments.output / "PROTOCOL.json", protocol)
    snapshot = arguments.output / "executed_source"
    snapshot.mkdir()
    for path in sorted(AREA.glob("*.py")):
        (snapshot / path.name).write_bytes(path.read_bytes())
    save(arguments.output / "FIT_STARTED.json", {"created_ns": time.time_ns(),
         "protocol_sha256": digest(PROTOCOL), "observer_sha256": digest(arguments.checkpoint),
         "source_manifest_sha256": digest(arguments.source / "SOURCE_MANIFEST.json"),
         "sources": {path.name: digest(path) for path in snapshot.iterdir()},
         "test_features_computed": False})
    roles = protocol["speaker_roles"]
    fit_observations = observe(arguments.source, roles["fit"], arguments.checkpoint)
    validation_observations = observe(arguments.source, roles["validation"], arguments.checkpoint)
    save(arguments.output / "observations_fit.json", fit_observations)
    save(arguments.output / "observations_validation.json", validation_observations)
    validation_pairs = measured_pairs(validation_observations)
    distinct = np.array([row["event_ids"][0] != row["event_ids"][1] for row in validation_pairs])
    candidates, selected = {}, {}
    for family in FAMILIES:
        candidates[family] = []
        best = None
        strengths = protocol["candidate_pseudocounts"] + ([] if family == "independent" else [None])
        for strength in strengths:
            began = time.process_time()
            marginal_strength = strength if family == "independent" else selected["independent"]["strength"]
            law = fit_law(fit_observations, "independent" if strength is None else family,
                          marginal_strength if strength is None else strength,
                          roles["validation"] + roles["test"], marginal_strength=marginal_strength)
            if strength is None:
                law.provenance.update(selection_family=family, explicit_independence_selected=True)
            scores = metrics(law, validation_pairs)
            score = float(scores[distinct, 0].mean())
            candidates[family].append({"strength": strength, "distinct_conditional_NLL": score,
                                       "cpu_seconds": time.process_time() - began})
            if (best is None or score < best[0] - 1e-12
                    or (strength is None and abs(score - best[0]) <= 1e-12)):
                best = score, strength, law
        selected[family] = {"strength": best[1], "validation_NLL": best[0],
                            "marginal_strength": best[1] if family == "independent" else selected["independent"]["strength"],
                            "explicit_independence_selected": best[1] is None}
        save(arguments.output / f"law_{family}.json", best[2].export())
        print(json.dumps({"family_frozen": family, **selected[family]}), flush=True)
    prior_fit = prior_cases(fit_observations, protocol["seed"])
    prior_validation = prior_cases(validation_observations, protocol["seed"])
    save(arguments.output / "prior_fit_targets.json", [
        {key: row[key] for key in ("sample_id", "speaker", "cue", "target")} for row in prior_fit])
    save(arguments.output / "prior_validation_targets.json", [
        {key: row[key] for key in ("sample_id", "speaker", "cue", "target")} for row in prior_validation])
    priors = {}
    for cue in CUES:
        priors[cue] = {}
        target = [row["target"] for row in prior_validation if row["cue"] == cue]
        for family in ("joint", "factorized"):
            options = []
            for strength in protocol["candidate_pseudocounts"]:
                probability = fit_prior(prior_fit, cue, family, strength)
                options.append((float(-np.log(probability[target]).mean()), strength, probability))
            best = min(options, key=lambda option: option[0])
            priors[cue][family] = {"probability": best[2].tolist(), "strength": best[1],
                                  "validation_NLL": best[0],
                                  "candidate_scores": [{"strength": item[1], "NLL": item[0]} for item in options]}
    save(arguments.output / "PRIORS.json", priors)
    save(arguments.output / "SELECTION.json", {"candidates": candidates, "selected": selected,
         "prior_evaluation_law": min(FAMILIES, key=lambda family: selected[family]["validation_NLL"]),
         "test_features_computed": False})
    bound = ["PROTOCOL.json", "FIT_STARTED.json", "observations_fit.json", "observations_validation.json",
             "PRIORS.json", "SELECTION.json", "prior_fit_targets.json", "prior_validation_targets.json"]
    bound += [f"law_{family}.json" for family in FAMILIES]
    save(arguments.output / "MODELS_FROZEN.json", {"created_ns": time.time_ns(),
         "sha256": {name: digest(arguments.output / name) for name in bound},
         "test_model_features_computed": False, "wall_seconds": time.perf_counter() - started,
         "cpu_seconds": time.process_time() - cpu,
         "maximum_RSS_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})


def deliver(path, law, rows, priors=None):
    """Public output writer receives event values and cue, never a target label."""
    with path.open("x") as stream:
        for row in rows:
            allowed = {"sample_id", "event_ids", "values"} | ({"cue"} if priors is not None else set())
            if set(row) != allowed:
                raise ValueError("Only target-free public events may enter the output writer")
            public = {key: row[key] for key in ("sample_id", "event_ids", "values")}
            cue = row.get("cue")
            prior = np.full(100, .01) if priors is None else np.asarray(priors[cue])
            probability, _ = posterior(law, public["event_ids"], public["values"], prior)
            selected = int(probability.argmax())
            stream.write(json.dumps({"sample_id": public["sample_id"],
                "digits": [selected // 10, selected % 10], "confidence": float(probability.max())}) + "\n")


def readback(path, rows):
    outputs = [json.loads(line) for line in path.read_text().splitlines()]
    if len(outputs) != len(rows) or [row["sample_id"] for row in outputs] != [row["sample_id"] for row in rows]:
        raise ValueError("Actual delivered outputs failed identity/readback census")
    return np.array([10 * row["digits"][0] + row["digits"][1] for row in outputs])


def grouped(scores, rows, mask=None):
    speakers = sorted({row["speaker"] for row in rows})
    groups = np.array([row["speaker"] for row in rows])
    mask = np.ones(len(rows), dtype=bool) if mask is None else mask
    return {speaker: scores[(groups == speaker) & mask].mean(0).tolist() for speaker in speakers}


def comparison(left, right, seed):
    speakers = sorted(left)
    delta = np.array([np.array(left[speaker]) - np.array(right[speaker]) for speaker in speakers])
    rng = np.random.default_rng(seed)
    draws = delta[rng.integers(len(speakers), size=(20000, len(speakers)))].mean(1)
    return {"speaker_count": len(speakers), "mean_difference": delta.mean(0).tolist(),
            "paired_97_5_percent_interval": np.quantile(draws, [.0125, .9875], axis=0).T.tolist(),
            "per_speaker_difference": {speaker: row.tolist() for speaker, row in zip(speakers, delta)},
            "unit": "fixed held-out AudioMNIST speaker; not independent derived pairs"}


def evaluate(arguments):
    started, cpu = time.perf_counter(), time.process_time()
    frozen = read(arguments.output / "MODELS_FROZEN.json")
    for name, expected in frozen["sha256"].items():
        if digest(arguments.output / name) != expected:
            raise ValueError("Frozen fitting artifact changed: " + name)
    protocol = read(arguments.output / "PROTOCOL.json")
    if digest(PROTOCOL) != read(arguments.output / "FIT_STARTED.json")["protocol_sha256"]:
        raise ValueError("Prospective protocol changed")
    for name, expected in read(arguments.output / "FIT_STARTED.json")["sources"].items():
        if digest(AREA / name) != expected:
            raise ValueError("Executable source changed after model fitting: " + name)
    save(arguments.output / "TEST_STARTED.json", {"created_ns": time.time_ns(),
         "models_frozen_sha256": digest(arguments.output / "MODELS_FROZEN.json")})
    observations = observe(arguments.source, protocol["speaker_roles"]["test"], arguments.checkpoint)
    save(arguments.output / "observations_test.json", observations)
    rows = measured_pairs(observations)
    prior_rows = prior_cases(observations, protocol["seed"])
    save(arguments.output / "PRIVATE_TEST_PAIRS.json", rows)
    save(arguments.output / "PRIVATE_PRIOR_TEST_PAIRS.json", prior_rows)
    laws = {family: JointObservationLaw.load(read(arguments.output / f"law_{family}.json")) for family in FAMILIES}
    public_rows = [{key: row[key] for key in ("sample_id", "event_ids", "values")} for row in rows]
    for family, law in laws.items():
        deliver(arguments.output / f"DELIVERED_{family}.jsonl", law, public_rows)
    priors = read(arguments.output / "PRIORS.json")
    selected = read(arguments.output / "SELECTION.json")
    law = laws[selected["prior_evaluation_law"]]
    public_prior_rows = [{key: row[key] for key in ("sample_id", "event_ids", "values", "cue")}
                         for row in prior_rows]
    for family in ("joint", "factorized"):
        deliver(arguments.output / f"DELIVERED_PRIOR_{family}.jsonl", law, public_prior_rows,
                {cue: priors[cue][family]["probability"] for cue in CUES})
    save(arguments.output / "DELIVERY_COMPLETED.json", {"created_ns": time.time_ns(),
         "files": {p.name: digest(p) for p in sorted(arguments.output.glob("DELIVERED_*.jsonl"))},
         "likelihood_deliveries": len(rows) * len(FAMILIES), "prior_deliveries": len(prior_rows) * 2})
    scores, distinct_scores, prior_scores = {}, {}, {}
    distinct = np.array([row["event_ids"][0] != row["event_ids"][1] for row in rows])
    target = np.array([row["target"] for row in rows])
    for family, law in laws.items():
        array = metrics(law, rows)
        array[:, 2] = readback(arguments.output / f"DELIVERED_{family}.jsonl", rows) == target
        scores[family], distinct_scores[family] = grouped(array, rows), grouped(array, rows, distinct)
    for family in ("joint", "factorized"):
        delivered = readback(arguments.output / f"DELIVERED_PRIOR_{family}.jsonl", prior_rows)
        prior_scores[family] = {}
        for cue in CUES:
            chosen = [row for row in prior_rows if row["cue"] == cue]
            mask = np.array([row["cue"] == cue for row in prior_rows])
            prior = np.array(priors[cue][family]["probability"])
            array = metrics(law, chosen, prior)
            targets = np.array([row["target"] for row in chosen])
            array[:, 0] = -np.log(prior[targets])
            array[:, 2] = delivered[mask] == targets
            prior_scores[family][cue] = grouped(array, chosen)
    alias_checks = []
    for family, law in laws.items():
        for row in (item for item in rows if item["target"] % 11 == 0 and item["index"] == 0):
            evidence = law.start_filter(np.full(100, .01))
            receipts = arrived_receipts(tuple(row["event_ids"]), tuple(row["values"]))
            once = evidence.update(receipts)
            if evidence.update([*receipts, *receipts]) != once:
                raise ValueError("Same actual waveform evidence was counted twice")
            alias_checks.append({"family": family, "sample_id": row["sample_id"], "idempotent": True})
    save(arguments.output / "ACTUAL_ALIAS_CHECKS.json", alias_checks)
    comparisons = {family + "_minus_independent": comparison(distinct_scores[family],
                   distinct_scores["independent"], protocol["seed"]) for family in FAMILIES[1:]}
    prior_comparisons = {cue: comparison(prior_scores["joint"][cue], prior_scores["factorized"][cue],
                                       protocol["seed"]) for cue in CUES}
    result = {"schema": "hepta.ndu.evidence.continuation.result.v1", "created_ns": time.time_ns(),
        "likelihood_metric_order": ["conditional_NLL", "posterior_NLL", "delivered_pair_accuracy", "confidence"],
        "prior_metric_order": ["target_prior_NLL", "posterior_NLL", "delivered_pair_accuracy", "confidence"],
        "all_pairs_by_speaker": scores, "distinct_pairs_by_speaker": distinct_scores,
        "likelihood_comparisons": comparisons, "prior_by_speaker": prior_scores,
        "prior_comparisons": prior_comparisons,
        "frozen_observer_digit_accuracy": {speaker: sum(row["target"] == row["observation"] for row in observations
             if row["speaker"] == speaker) / 200 for speaker in protocol["speaker_roles"]["test"]},
        "selection": selected["selected"], "selected_prior_evaluation_law": selected["prior_evaluation_law"],
        "alias_checks": len(alias_checks), "test_speakers": len(protocol["speaker_roles"]["test"]),
        "test_waveforms": len(observations), "test_pair_rows": len(rows), "test_prior_pair_rows": len(prior_rows),
        "scope": protocol["scope"], "old_FSDD_test_reused": False, "public_source_population_qualification": False,
        "likelihood_NLL_gain_gate": comparisons["speaker_mixture_minus_independent"]["paired_97_5_percent_interval"][0][1] < 0,
        "actual_output_gain_gate": comparisons["speaker_mixture_minus_independent"]["paired_97_5_percent_interval"][2][0] > 0,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
        "maximum_RSS_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save(arguments.output / "RESULTS.json", result)
    print(json.dumps({"complete": True, "comparisons": comparisons, "prior_comparisons": prior_comparisons}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("fit", "evaluate"))
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    (fit if arguments.phase == "fit" else evaluate)(arguments)
