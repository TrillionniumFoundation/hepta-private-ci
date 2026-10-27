"""Reopen every delivery and independently recompute targets, scores and intervals.

The auditor imports neither qualification generation nor the study statistics
or observer scoring implementation. The frozen CNN remains an imperfect metric.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import zipfile

import numpy as np
from PIL import Image
import torch
from torch import nn


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit(assets, directory, output):
    torch.set_num_threads(1)
    seal = json.loads((directory / "QUALIFICATION_SEAL.json").read_text())
    result = json.loads((directory / "RESULT.json").read_text())
    protocol, contract = seal["protocol"], seal["qualification_contract"]
    if digest(directory / "QUALIFICATION_SEAL.json") != result["seal_sha256"]:
        raise ValueError("Qualification seal changed")
    for name, expected in seal["source_sha256"].items():
        if digest(directory / "executed-source" / name) != expected:
            raise ValueError("Executed qualification source changed")
    allocation = json.loads(Path(seal["allocation"]).read_text())
    if digest(Path(seal["allocation"])) != seal["allocation_sha256"]:
        raise ValueError("Qualification allocation changed")
    raw_images = assets / "ndu-data/t10k-images-idx3-ubyte.gz"
    raw_labels = assets / contract["official_label_file"]
    if digest(raw_images) != allocation["official_test_image_sha256"] or digest(raw_labels) != contract["official_label_sha256"]:
        raise ValueError("Official source bytes changed")
    images_data, labels_data = gzip.decompress(raw_images.read_bytes()), gzip.decompress(raw_labels.read_bytes())
    if struct.unpack(">IIII", images_data[:16]) != (2051, 10000, 28, 28) or struct.unpack(">II", labels_data[:8]) != (2049, 10000):
        raise ValueError("Official source headers differ")
    images = np.frombuffer(images_data, dtype=np.uint8, offset=16).reshape(10000, 28, 28)
    labels = np.frombuffer(labels_data, dtype=np.uint8, offset=8)
    identities = {}
    for split in ("test", "retention"):
        identities[split] = allocation["splits"]["joint_" + split]["source_ids"]
        for identity in identities[split]:
            index = int(identity.split(":")[2])
            if identity != f"mnist:test:{index}:{hashlib.sha256(images[index].tobytes()).hexdigest()}":
                raise ValueError("A source identity differs from official pixels")
    models = {}
    for name in ("reward", "audit"):
        path = assets / f"ndu-runs/full-002/{name}-observer.pt"
        if digest(path) != seal["observer_files"][name]:
            raise ValueError("Frozen observer bytes changed")
        model = nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2), nn.Flatten(),
            nn.Linear(32 * 7 * 7, 64), nn.ReLU(), nn.Linear(64, 10))
        model.load_state_dict({key.removeprefix("net."): value for key, value in torch.load(path, weights_only=True).items()})
        models[name] = model.eval().requires_grad_(False)
    rows, groups, keyed = [], {}, {}
    for name, expected in result["row_files"].items():
        path = directory / name
        if digest(path) != expected:
            raise ValueError("Recorded outcome rows changed")
        for line in path.read_text().splitlines():
            row = json.loads(line)
            key = tuple(row[name] for name in ("seed", "arm", "split", "condition", "pair"))
            if key in keyed:
                raise ValueError("Repeated outcome identity")
            keyed[key] = row
            rows.append(row)
            groups.setdefault(row["delivery"]["archive"], []).append(row)
    maximum_error, media_count = 0., 0
    for archive_name, batch in sorted(groups.items()):
        batch.sort(key=lambda row: row["pair"])
        split, condition, start = batch[0]["split"], batch[0]["condition"], batch[0]["pair"]
        condition_index = protocol["conditions"].index(condition)
        rng = torch.Generator().manual_seed(contract["corruption_seed_offset"] + protocol["evaluation_seed"] + start + condition_index * 10000)
        swaps = torch.randint(2, (len(batch),), generator=rng).tolist()
        pixels, targets, true_labels, captions = [], [], [], []
        with zipfile.ZipFile(directory / archive_name) as archive:
            if len(archive.namelist()) != 2 * len(batch) or archive.testzip() is not None:
                raise ValueError("Delivery container differs")
            for index, row in enumerate(batch):
                source_ids = identities[split][2 * row["pair"]:2 * row["pair"] + 2]
                if row["source_ids"] != source_ids:
                    raise ValueError("Outcome source pairing differs")
                source_indices = [int(value.split(":")[2]) for value in source_ids]
                if swaps[index]:
                    source_indices.reverse()
                target = np.concatenate([images[i] for i in source_indices], axis=1)
                truth = [int(labels[i]) for i in source_indices]
                if row["private_labels"] != truth:
                    raise ValueError("Recorded target differs from reconstructed public task")
                payload = {kind: archive.read(member) for kind, member in row["delivery"]["members"].items()}
                if {kind: hashlib.sha256(raw).hexdigest() for kind, raw in payload.items()} != row["delivery"]["sha256"]:
                    raise ValueError("Actual delivered bytes changed")
                with Image.open(io.BytesIO(payload["image"])) as image:
                    if (image.format, image.mode, image.size) != ("PNG", "L", (56, 28)):
                        raise ValueError("Actual PNG contract differs")
                    pixels.append(np.array(image))
                caption = payload["text"].decode("utf-8")
                if caption != row["caption"]:
                    raise ValueError("Actual delivered caption differs")
                captions.append(caption)
                targets.append(target)
                true_labels.append(truth)
                media_count += 2
        decoded = torch.tensor(np.array(pixels), dtype=torch.float32)[:, None] / 255
        mse = np.mean(((np.array(pixels, dtype=np.float64) - np.array(targets, dtype=np.float64)) / 255) ** 2, axis=(1, 2))
        for observer_name, model in models.items():
            with torch.inference_mode():
                predicted = torch.stack((model(decoded[:, :, :, :28]).argmax(1), model(decoded[:, :, :, 28:]).argmax(1)), dim=1).tolist()
            for index, row in enumerate(batch):
                match = re.fullmatch(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)", captions[index].strip())
                parsed = [int(match[1]), int(match[2])] if match else None
                truth, image_digits = true_labels[index], predicted[index]
                relation = "less" if truth[0] < truth[1] else "greater" if truth[0] > truth[1] else "equal"
                fields = {"text_fact": sum(a != b for a, b in zip(parsed, truth)) / 2 if match else 1.,
                    "relation": float(match[3] != relation) if match else 1.,
                    "image_fact": sum(a != b for a, b in zip(image_digits, truth)) / 2,
                    "crossmodal_disagreement": sum(a != b for a, b in zip(parsed, image_digits)) / 2 if match else 1.,
                    "pixel_mse": float(mse[index])}
                fields["joint_loss"] = .30 * fields["text_fact"] + .15 * fields["relation"] + .35 * fields["image_fact"] + .10 * fields["crossmodal_disagreement"] + .10 * fields["pixel_mse"]
                fields["utility"] = 1 - 2 * fields["joint_loss"]
                recorded = row[observer_name]
                if recorded["image_digits"] != image_digits or recorded["caption_digits"] != parsed or recorded["caption_valid"] != (match is not None):
                    raise ValueError("Independent discrete semantic scoring differs")
                error = max(abs(value - recorded[name]) for name, value in fields.items())
                maximum_error = max(maximum_error, error)
                if error > 2e-7:
                    raise ValueError("Independent delivered utility differs")
    tables = {}
    for split, count, conditions in (("test", protocol["test_pairs"], protocol["conditions"]),
                                    ("retention", protocol["retention_pairs"], ["clean"])):
        for arm in protocol["arms"]:
            tables[split, arm] = np.array([[[keyed[seed, arm, split, condition, pair]["audit"]["utility"]
                for condition in conditions] for pair in range(count)] for seed in protocol["seeds"]])
    expected_count = len(protocol["seeds"]) * len(protocol["arms"]) * (protocol["test_pairs"] * len(protocol["conditions"]) + protocol["retention_pairs"])
    if len(rows) != expected_count:
        raise ValueError("The complete qualification grid is required")
    def certainty_equivalent(table):
        return float(np.mean(-np.log(np.mean(np.exp(-protocol["gamma"] * table), axis=(1, 2))) / protocol["gamma"]))
    rng = np.random.default_rng(protocol["bootstrap_seed"])
    maximum_statistic_error = 0.
    for comparison in result["comparisons"]:
        candidate, baseline = comparison["comparison"].split("-")
        x, y = tables[comparison["split"], candidate], tables[comparison["split"], baseline]
        samples = []
        for _ in range(protocol["bootstrap_replicates"]):
            selected = rng.integers(x.shape[1], size=x.shape[1])
            samples.append(certainty_equivalent(x[:, selected]) - certainty_equivalent(y[:, selected]))
        alpha = (1 - protocol["interval"]) / 2
        values = [certainty_equivalent(x) - certainty_equivalent(y), *np.quantile(samples, [alpha, 1 - alpha])]
        expected = [comparison["ce_difference"], *comparison["paired_97_5_interval"]]
        maximum_statistic_error = max(maximum_statistic_error, float(np.max(np.abs(np.array(values) - expected))))
    if maximum_statistic_error > 1e-12:
        raise ValueError("Independent paired source inference differs")
    fallback_rows = 0
    for selected in seal["selected"]:
        if selected["kind"] != "original_fallback":
            continue
        for row in rows:
            if row["seed"] == selected["seed"] and row["arm"] == selected["arm"]:
                original = keyed[row["seed"], "original", row["split"], row["condition"], row["pair"]]
                if row["delivery"]["sha256"] != original["delivery"]["sha256"] or row["audit"] != original["audit"] or row["logical_budget"]["actor"] != 0:
                    raise ValueError("A declared original fallback changed its actual output")
                fallback_rows += 1
    record = {"status": "passed", "actual_bundles_reopened": len(rows), "actual_media_members": media_count,
        "delivery_containers_reopened": len(groups), "independent_observer_scores": 2 * len(rows),
        "maximum_independent_score_error": maximum_error, "maximum_statistic_error": maximum_statistic_error,
        "fallback_identical_output_rows": fallback_rows, "new_predictions_or_parameter_updates": 0,
        "result_sha256": digest(directory / "RESULT.json"), "audit_source_sha256": digest(Path(__file__)),
        "scope": "Official source reconstruction, all actual media, two frozen observers and fixed-seed source-pair statistics; not human semantic certification or population-of-seeds inference."}
    output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "directory", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    audit(args.assets.resolve(), args.directory.resolve(), args.output.resolve())
