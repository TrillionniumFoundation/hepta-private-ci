"""Independent array-based reconstruction of source laws and delivered-output scores."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

import numpy as np


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reconstructed_law(observations, family, strength, marginal_strength):
    speakers = sorted({row["speaker"] for row in observations})
    histograms = []
    pair_histograms = np.zeros((110, 100))
    for speaker in speakers:
        selected = [row for row in observations if row["speaker"] == speaker]
        keys = [10 * row["observation"] + row["target"] for row in selected]
        histograms.append(np.bincount(keys, minlength=100).reshape(10, 10))
        lookup = {(row["target"], row["index"]): row for row in selected}
        for target in range(100):
            left, right = divmod(target, 10)
            for trial in range(20):
                first = lookup[left, trial]["observation"]
                second = lookup[right, trial if left == right else (trial * 7 + 11) % 20]["observation"]
                outcome = first if left == right else 10 + 10 * first + second
                pair_histograms[outcome, target] += 1
    counts = np.array(histograms, dtype=float)
    overall = counts.sum(0)
    base = (overall + marginal_strength / 10) / (overall.sum(axis=0, keepdims=True) + marginal_strength)
    result = np.zeros((110, 100))
    if family == "independent" or strength is None:
        strength = marginal_strength if strength is None else strength
        single = (overall + strength / 10) / (overall.sum(axis=0, keepdims=True) + strength)
        joint = np.kron(single, single)
    elif family == "paired":
        single = base
        joint = (pair_histograms[10:] + strength * np.kron(base, base)) / (
                 pair_histograms[10:].sum(axis=0, keepdims=True) + strength)
    else:
        components = [(histogram + strength * base) / (histogram.sum(axis=0, keepdims=True) + strength)
                      for histogram in counts]
        single = base
        joint = np.mean([np.kron(component, component) for component in components], axis=0)
    for target in range(100):
        left, right = divmod(target, 10)
        if left == right:
            result[:10, target] = single[:, left]
        else:
            column = joint[:, target].reshape(10, 10).copy()
            if family != "independent":
                for _ in range(3000):
                    column /= column.sum(axis=0, keepdims=True)
                    column *= single[:, right][None, :]
                    column /= column.sum(axis=1, keepdims=True)
                    column *= single[:, left][:, None]
                    if max(np.abs(column.sum(1) - single[:, left]).max(),
                           np.abs(column.sum(0) - single[:, right]).max()) < 1e-13:
                        break
                else:
                    raise ValueError("Independent marginal projection failed")
            result[10:, target] = column.ravel()
    return result


def independently_score(matrix, rows, outputs, prior_by_cue=None):
    indices = np.array([row["values"][0] if row["event_ids"][0] == row["event_ids"][1]
                        else 10 + 10 * row["values"][0] + row["values"][1] for row in rows])
    target = np.array([row["target"] for row in rows])
    likelihood = matrix[indices]
    prior = np.full_like(likelihood, .01) if prior_by_cue is None else np.array([
        prior_by_cue[row["cue"]] for row in rows])
    weighted = prior * likelihood
    probability = weighted / weighted.sum(axis=1, keepdims=True)
    prediction = probability.argmax(axis=1)
    if [row["sample_id"] for row in rows] != [row["sample_id"] for row in outputs]:
        raise ValueError("Delivered sample census mismatch")
    actual = np.array([10 * row["digits"][0] + row["digits"][1] for row in outputs])
    np.testing.assert_array_equal(prediction, actual)
    np.testing.assert_allclose(probability.max(axis=1), [row["confidence"] for row in outputs], rtol=0, atol=1e-13)
    positions = np.arange(len(rows))
    initial = likelihood if prior_by_cue is None else prior
    return np.column_stack((-np.log(initial[positions, target]), -np.log(probability[positions, target]),
                            prediction == target, probability.max(axis=1)))


def verify_grouped(values, rows, expected, mask=None):
    mask = np.ones(len(rows), dtype=bool) if mask is None else mask
    largest = 0.
    for speaker, saved in expected.items():
        selected = np.array([row["speaker"] == speaker for row in rows]) & mask
        value = values[selected].mean(axis=0)
        largest = max(largest, float(np.abs(value - saved).max()))
        np.testing.assert_allclose(value, saved, rtol=0, atol=2e-12)
    return largest


def audit(output, source, previous_archive):
    protocol, result = read(output / "PROTOCOL.json"), read(output / "RESULTS.json")
    frozen = read(output / "MODELS_FROZEN.json")
    for name, expected in frozen["sha256"].items():
        if sha(output / name) != expected:
            raise ValueError("Frozen model artifact changed")
    order = [read(output / name)["created_ns"] for name in (
        "FIT_STARTED.json", "MODELS_FROZEN.json", "TEST_STARTED.json", "DELIVERY_COMPLETED.json", "RESULTS.json")]
    if order != sorted(set(order)):
        raise ValueError("Fit/freeze/test/delivery/scoring chronology violated")
    manifest = read(source / "SOURCE_MANIFEST.json")
    for entry in manifest["files"]:
        if sha(source / entry["path"]) != entry["sha256"]:
            raise ValueError("Original public source bytes changed")
    with tarfile.open(previous_archive, "r:gz") as archive:
        old_hashes = set(json.load(archive.extractfile("raw/SOURCE_INVENTORY.json")).values())
    new_hashes = {row["sha256"] for row in manifest["files"] if row["path"].endswith(".wav")}
    if len(new_hashes) != 4000 or new_hashes & old_hashes:
        raise ValueError("Physical waveform overlap or source census failure")
    observations = {role: read(output / f"observations_{role}.json") for role in ("fit", "validation", "test")}
    for role, records in observations.items():
        if set(row["speaker"] for row in records) != set(protocol["speaker_roles"][role]):
            raise ValueError("Speaker roles differ from the prospective split")
    fit_observations = observations["fit"]
    rows = read(output / "PRIVATE_TEST_PAIRS.json")
    distinct = np.array([row["event_ids"][0] != row["event_ids"][1] for row in rows])
    largest_model_error = largest_score_error = 0.
    matrices = {}
    for family, selection in result["selection"].items():
        matrix = np.array(read(output / f"law_{family}.json")["likelihood_by_target"]).T
        reconstructed = reconstructed_law(fit_observations, family, selection["strength"], selection["marginal_strength"])
        largest_model_error = max(largest_model_error, float(np.abs(matrix - reconstructed).max()))
        np.testing.assert_allclose(matrix, reconstructed, rtol=0, atol=5e-12)
        matrices[family] = matrix
        outputs = [json.loads(line) for line in (output / f"DELIVERED_{family}.jsonl").read_text().splitlines()]
        scores = independently_score(matrix, rows, outputs)
        largest_score_error = max(largest_score_error,
            verify_grouped(scores, rows, result["all_pairs_by_speaker"][family]),
            verify_grouped(scores, rows, result["distinct_pairs_by_speaker"][family], distinct))
    prior_rows = read(output / "PRIVATE_PRIOR_TEST_PAIRS.json")
    priors, target_fit = read(output / "PRIORS.json"), read(output / "prior_fit_targets.json")
    for family in ("joint", "factorized"):
        by_cue = {}
        for cue, record in priors.items():
            counts = np.bincount([row["target"] for row in target_fit if row["cue"] == cue], minlength=100).reshape(10, 10)
            strength = record[family]["strength"]
            expected = (counts + strength / 100) / (counts.sum() + strength)
            if family == "factorized":
                left = (counts.sum(axis=1) + strength / 10) / (counts.sum() + strength)
                right = (counts.sum(axis=0) + strength / 10) / (counts.sum() + strength)
                expected = left[:, None] * right[None, :]
            np.testing.assert_allclose(expected.ravel(), record[family]["probability"], rtol=0, atol=1e-15)
            by_cue[cue] = record[family]["probability"]
        outputs = [json.loads(line) for line in (output / f"DELIVERED_PRIOR_{family}.jsonl").read_text().splitlines()]
        scores = independently_score(matrices[result["selected_prior_evaluation_law"]], prior_rows, outputs, by_cue)
        for cue in priors:
            mask = np.array([row["cue"] == cue for row in prior_rows])
            largest_score_error = max(largest_score_error,
                verify_grouped(scores, prior_rows, result["prior_by_speaker"][family][cue], mask))
    delivery = read(output / "DELIVERY_COMPLETED.json")
    for name, expected in delivery["files"].items():
        if sha(output / name) != expected:
            raise ValueError("Delivered bytes changed after completion")
    return {"schema": "hepta.ndu.evidence.independent-audit.v1", "passed": True,
            "new_source_waveforms_rehashed": len(new_hashes), "old_source_waveforms_compared": len(old_hashes),
            "physical_overlap_count": len(new_hashes & old_hashes),
            "speaker_identity_scope": "dataset-local speaker IDs, not globally resolved person identities",
            "selected_joint_laws_reconstructed": len(matrices), "maximum_model_error": largest_model_error,
            "actual_delivered_pair_outputs_rescored": delivery["likelihood_deliveries"] + delivery["prior_deliveries"],
            "maximum_grouped_metric_error": largest_score_error, "frozen_chronology_verified": True,
            "distinct_test_speakers": result["test_speakers"], "source_manifest_sha256": sha(source / "SOURCE_MANIFEST.json"),
            "result_sha256": sha(output / "RESULTS.json"), "audit_source_sha256": sha(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--previous-archive", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit(arguments.output, arguments.source, arguments.previous_archive)
    with (arguments.output / "INDEPENDENT_AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result))
