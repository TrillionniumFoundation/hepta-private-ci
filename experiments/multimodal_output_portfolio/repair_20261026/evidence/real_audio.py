"""Real FSDD waveform experiment for alias support and paired audio likelihoods.

Four speakers fit one fixed CNN; one speaker fits likelihoods; a sixth speaker
is a development test. Thousands of derived pairs remain one test speaker,
not thousands of independent generalization trials. This is a new source/model
experiment, not a restoration or requalification of the old audio model.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import resource
import tarfile
import time
import wave

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .joint import JointObservationLaw, PairObservation, arrived_receipts


COMMIT = "26eb9aaf76e81b692f806f9140c2d2777410d7a1"
ARCHIVE_SHA = "9a68686ad29274bd0affde81b244953e677c9d7048dfb8acaf1168d7758bafab"
TRAIN = ("george", "jackson", "lucas", "nicolas")
FIT, TEST, SEED, EPOCHS = "theo", "yweweler", 271831, 24


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write("\n")


class DigitObserver(nn.Module):
    """Fixed small closed-vocabulary classifier, never a general speech model."""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Conv2d(1, 12, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(12, 24, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((4, 4)),
            nn.Flatten(), nn.Linear(384, 64), nn.ReLU(), nn.Linear(64, 10))

    def forward(self, x):
        return self.net(x)


def extract(archive, destination):
    expected = {f"{d}_{s}_{i}.wav" for s in (*TRAIN, FIT, TEST) for d in range(10) for i in range(50)}
    destination.mkdir(exist_ok=False)
    found = {}
    with tarfile.open(archive, "r:gz") as stream:
        for entry in stream:
            parts = entry.name.split("/")
            if not entry.isfile() or len(parts) < 2:
                continue
            name = parts[-1]
            if parts[-2] == "recordings":
                if name not in expected or name in found or not re.fullmatch(r"[0-9]_[a-z]+_[0-9]+\.wav", name):
                    raise ValueError("Unexpected or duplicate pinned recording name")
                payload = stream.extractfile(entry).read()
                (destination / name).write_bytes(payload)
                found[name] = hashlib.sha256(payload).hexdigest()
            elif name in ("README.md", "LICENSE") and len(parts) == 2:
                (destination / name).write_bytes(stream.extractfile(entry).read())
    if set(found) != expected:
        raise ValueError("The exact 3000-recording pinned source census is incomplete")
    owners = {}
    for name, digest in found.items():
        speaker = name.split("_")[1]
        if digest in owners and owners[digest] != speaker:
            raise ValueError("An identical physical recording crosses speaker roles")
        owners[digest] = speaker
    return found


def spectrum(path):
    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 8000):
            raise ValueError("The frozen waveform interface requires mono PCM16 at 8 kHz")
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").copy()
    x = torch.from_numpy(samples).float() / 32768.
    if len(x) < 256:
        x = F.pad(x, (0, 256 - len(x)))
    z = torch.stft(x, n_fft=256, hop_length=64, window=torch.hann_window(256),
                   center=False, return_complex=True).abs().log1p()
    z = F.interpolate(z[None, None], size=(64, 64), mode="bilinear", align_corners=False)[0]
    return (z - z.mean()) / z.std().clamp_min(1e-6)


def load_role(root, speakers, inventory):
    names = [f"{d}_{s}_{i}.wav" for s in speakers for d in range(10) for i in range(50)]
    x = torch.stack([spectrum(root / name) for name in names])
    target = torch.tensor([int(name[0]) for name in names])
    return x, target, [{"name": name, "speaker": name.split("_")[1],
                       "target": int(name[0]), "wav_sha256": inventory[name]} for name in names]


@torch.inference_mode()
def observe(model, features, records):
    probability = torch.cat([model(chunk).softmax(-1) for chunk in features.split(64)]).double().numpy()
    return [{**record, "observation": int(p.argmax()), "probabilities": p.tolist()}
            for record, p in zip(records, probability)]


def pairs(records):
    lookup = {(r["target"], int(r["name"].rsplit("_", 1)[1].split(".")[0])): r for r in records}
    result = []
    for left in range(10):
        for right in range(10):
            for index in range(50):
                a, b = lookup[left, index], lookup[right, index if left == right else (7 * index + 11) % 50]
                result.append(PairObservation(f"{a['speaker']}:{10 * left + right}:{index}",
                    a["speaker"], 10 * left + right, (a["wav_sha256"], b["wav_sha256"]),
                    (a["observation"], b["observation"])))
    return result


def fit_laws(records):
    rows = pairs(records)
    empirical = JointObservationLaw.fit_paired(rows, alpha=0., excluded_groups=(*TRAIN, TEST))
    unique = {r["wav_sha256"]: r for r in records}
    counts = np.zeros((10, 10))
    for row in unique.values():
        counts[row["observation"], row["target"]] += 1
    # Fixed total Dirichlet mass .5 per target, distributed over its support.
    single = (counts + .05) / (counts.sum(0) + .5)
    coupling, cardinality = {}, {}
    for target in range(100):
        cardinality[target] = len({r.event_ids for r in rows if r.target == target})
        if target // 10 != target % 10:
            n = cardinality[target]
            coupling[target] = (n * empirical.likelihood[10:, target] + .005) / (n + .5)
    paired = JointObservationLaw.from_components(single, coupling)
    product = JointObservationLaw.from_components(single, {
        t: np.kron(single[:, t // 10], single[:, t % 10]) for t in coupling})
    paired.provenance.update(origin="real paired FSDD observations", fit_speaker=FIT,
                              prior_mass_per_target=.5, test_model_features_not_computed=True,
                              unique_pair_counts_by_target=cardinality)
    product.provenance.update(origin="explicit conditional-independence comparison assumption",
                               fit_speaker=FIT, prior_mass_per_target=.5)
    return single, paired, product, rows


def labels_only(law):
    matrix = law.likelihood[10:].copy()
    for label in range(10):
        matrix[11 * label] += law.likelihood[label]
    return matrix


def score(matrix, rows, identity_visible):
    results = {}
    for part in ("all", "aliased", "distinct"):
        chosen = [r for r in rows if part == "all" or (r.event_ids[0] == r.event_ids[1]) == (part == "aliased")]
        index = [r.outcome_index() if identity_visible else 10 * r.values[0] + r.values[1] for r in chosen]
        likelihood = matrix[index]
        posterior = likelihood / likelihood.sum(1, keepdims=True)  # registered uniform 100-target prior
        target = np.array([r.target for r in chosen])
        p = posterior[np.arange(len(chosen)), target]
        conditional = likelihood[np.arange(len(chosen)), target]
        if (p <= 0).any() or (conditional <= 0).any():
            raise ValueError("Actual test outcome lies outside the prospectively smoothed model support")
        confidence, selected = posterior.max(1), posterior.argmax(1)
        correct = selected == target
        ece = 0.
        bins = np.minimum((np.round(confidence, 12) * 10).astype(int), 9)
        for index in range(10):
            mask = bins == index
            if mask.any():
                ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
        results[part] = {"pair_rows": len(chosen), "conditional_observation_NLL": float(-np.log(conditional).mean()),
            "posterior_NLL": float(-np.log(p).mean()), "target_pair_accuracy": float(correct.mean()),
            "selected_ECE_10bins": float(ece), "unknown_speaker_qualification": False}
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sha(args.archive) != ARCHIVE_SHA:
        raise ValueError("Wrong fixed-commit FSDD archive")
    args.output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    registration = {"schema": "hepta.repair.fsdd-paired-development.v1", "created_ns": time.time_ns(),
        "source_url": f"https://github.com/Jakobovski/free-spoken-digit-dataset/tree/{COMMIT}",
        "source_commit": COMMIT, "archive_sha256": ARCHIVE_SHA, "license": "CC BY-SA 4.0",
        "observer_train_speakers": TRAIN, "likelihood_fit_speakers": [FIT], "development_test_speakers": [TEST],
        "seed": SEED, "epochs": EPOCHS, "batch_size": 64, "Adam_learning_rate": .001, "weight_decay": .0001,
        "pair_rule": "all ordered targets, left index k; alias k for equal digits, right (7*k+11)%50 otherwise",
        "prior": "uniform 100-target prior; exactly balanced constructed target census",
        "smoothing": "fixed total Dirichlet mass .5 per target, uniformly on structural support",
        "ECE_bins": "floor(10 * round(confidence,12)), capped at 9; boundary convention only",
        "comparators": ["naive_kron_labels", "alias_corrected_product_labels", "paired_joint_labels",
                        "alias_corrected_product_identity", "paired_joint_identity"],
        "scope": "New closed-digit source/model development task; one test speaker, no population CI or old-model qualification",
        "source_sha256": {p.name: sha(p) for p in (Path(__file__), Path(__file__).with_name("joint.py"))}}
    save(args.output / "REGISTRATION.json", registration)
    torch.set_num_threads(1); torch.set_num_interop_threads(1); torch.manual_seed(SEED)
    root = args.output / "recordings"
    inventory = extract(args.archive, root)
    save(args.output / "SOURCE_INVENTORY.json", inventory)
    x, y, _ = load_role(root, TRAIN, inventory)
    model = DigitObserver()
    optimizer = torch.optim.Adam(model.parameters(), lr=.001, weight_decay=.0001)
    losses = []
    for epoch in range(EPOCHS):
        order = torch.randperm(len(x), generator=torch.Generator().manual_seed(SEED + epoch))
        total = 0.
        for ids in order.split(64):
            optimizer.zero_grad(); loss = F.cross_entropy(model(x[ids]), y[ids]); loss.backward(); optimizer.step()
            total += float(loss.detach()) * len(ids)
        losses.append(total / len(x))
        if epoch % 6 == 5:
            print(json.dumps({"observer_epoch_completed": epoch + 1}), flush=True)
    model.eval().requires_grad_(False)
    torch.save(model.state_dict(), args.output / "observer.pt")
    save(args.output / "OBSERVER_FROZEN.json", {"sha256": sha(args.output / "observer.pt"),
        "train_recordings": len(x), "optimizer_steps": EPOCHS * math.ceil(len(x) / 64), "epoch_losses": losses,
        "likelihood_and_test_model_features_computed": False,
        "raw_source_bytes_extracted_and_hashed": True})
    fx, _, fr = load_role(root, (FIT,), inventory)
    fitted_observations = observe(model, fx, fr)
    single, paired, product, fit_rows = fit_laws(fitted_observations)
    save(args.output / "fit_observations.json", fitted_observations)
    save(args.output / "paired_joint.json", paired.export()); save(args.output / "alias_product.json", product.export())
    save(args.output / "MODELS_FROZEN.json", {"observer_sha256": sha(args.output / "observer.pt"),
        "paired_sha256": sha(args.output / "paired_joint.json"), "product_sha256": sha(args.output / "alias_product.json"),
        "fit_actual_recordings": len(fr), "fit_derived_pairs": len(fit_rows),
        "test_model_features_computed": False, "raw_test_bytes_extracted_and_hashed": True})
    tx, _, tr = load_role(root, (TEST,), inventory)
    test_observations = observe(model, tx, tr)
    save(args.output / "test_observations.json", test_observations)
    test_rows = pairs(test_observations)
    scores = {"naive_kron_labels": score(np.kron(single, single), test_rows, False),
        "alias_corrected_product_labels": score(labels_only(product), test_rows, False),
        "paired_joint_labels": score(labels_only(paired), test_rows, False),
        "alias_corrected_product_identity": score(product.likelihood, test_rows, True),
        "paired_joint_identity": score(paired.likelihood, test_rows, True)}
    checked = []
    for digit in range(10):
        row = test_rows[digit * 550]
        if row.target != 11 * digit:
            raise ValueError("Actual alias test selected the wrong fixed target")
        index = digit * 50
        with torch.inference_mode():
            repeated = model(tx[index:index + 1].repeat(2, 1, 1, 1))
        if not torch.equal(repeated[0], repeated[1]):
            raise ValueError("The same deterministic waveform observation changed on repeat")
        session = paired.start_filter(np.full(100, .01))
        receipts = arrived_receipts(row.event_ids, row.values)
        once = session.update(receipts)
        if session.update([*receipts, *receipts]) != once:
            raise ValueError("Repeated actual evidence incorrectly increased its likelihood power")
        checked.append({"target": row.target, "event_sha256": row.event_ids[0],
                        "actual_CNN_label": row.values[0], "repeat_posterior_identical": True})
    save(args.output / "ACTUAL_ALIAS_CHECKS.json", checked)
    result = {"schema": "hepta.repair.fsdd-paired-development-result.v1", "scores": scores,
        "fit_digit_accuracy": sum(r["target"] == r["observation"] for r in fitted_observations) / 500,
        "test_digit_accuracy": sum(r["target"] == r["observation"] for r in test_observations) / 500,
        "test_speakers": 1, "test_recordings": 500, "test_derived_pair_rows": len(test_rows),
        "unique_test_WAV_bytes": len({r["wav_sha256"] for r in test_observations}),
        "actual_same_WAV_repeat_checks": 10,
        "naive_impossible_alias_mass_per_target": (1 - np.square(single).sum(0)).tolist(),
        "repaired_impossible_alias_mass": 0., "wall_seconds": time.perf_counter() - start,
        "cpu_seconds": time.process_time() - cpu, "peak_RSS_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "raw_sha256": {p.name: sha(p) for p in sorted(args.output.iterdir()) if p.is_file()},
        "scope": registration["scope"], "old_audio_model_requalified": False, "production_authority": False}
    save(args.output / "RESULTS.json", result)
    print(json.dumps({"completed": True, "fit_digit_accuracy": result["fit_digit_accuracy"],
                      "test_digit_accuracy": result["test_digit_accuracy"], "output": str(args.output)}), flush=True)


if __name__ == "__main__":
    main()
