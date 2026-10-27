"""Read-only peer reconstruction of native semantic feedback and output scores."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct

import numpy as np
from PIL import Image
import torch
from torch import nn


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FrozenObserver(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2), nn.Flatten(),
            nn.Linear(1568, 64), nn.ReLU(), nn.Linear(64, 10))

    def forward(self, value):
        return self.net(value)


def run(workspace, output):
    root = workspace / "native_semantic_20261027/qualification-001"
    data = workspace / "ndu-original-assets/restored"
    records = [json.loads(line) for line in (root / "ROWS.jsonl").read_text().splitlines()]
    seal, result = read(root / "QUALIFICATION_SEAL.json"), read(root / "RESULT.json")
    if sha(root / "ROWS.jsonl") != result["rows_sha256"]:
        raise ValueError("Native raw rows changed")
    private = torch.load(root / "inputs/PRIVATE.pt", weights_only=True)
    public = torch.load(root / "inputs/PUBLIC.pt", weights_only=True)
    sources = read(root / "inputs/SOURCES.json")
    if set(public) != {"pixels", "mask", "tokens", "noise_seeds"} or not torch.all(public["tokens"][:, 1] == 9):
        raise ValueError("Public input contract differs")
    image_blob = gzip.decompress((data / "ndu-data/t10k-images-idx3-ubyte.gz").read_bytes())
    label_blob = gzip.decompress((data / "ndu-data/t10k-labels-idx1-ubyte.gz").read_bytes())
    if struct.unpack_from(">IIII", image_blob) != (2051, 10000, 28, 28):
        raise ValueError("Official image dimensions differ")
    originals = np.frombuffer(image_blob, dtype=np.uint8, offset=16).reshape(10000, 28, 28)
    labels = np.frombuffer(label_blob, dtype=np.uint8, offset=8)
    for index, source in enumerate(sources):
        indices = [int(s.split(":")[2]) for s in source["source_ids"]]
        wanted = labels[indices].copy()
        pixels = originals[indices].copy()
        if private["preferences"][index]:
            wanted, pixels = wanted[::-1].copy(), pixels[::-1].copy()
        if not np.array_equal(wanted, private["labels"][index].numpy()):
            raise ValueError("Private preference truth differs from original source labels")
        expected = torch.from_numpy(np.concatenate([pixels[0], pixels[1]], axis=1)).float() / 255
        if not torch.equal(expected, private["pixels"][index, 0]):
            raise ValueError("Private pixel target differs from source/preference")
    observer_path = data / "ndu-runs/full-002/audit-observer.pt"
    restoration = read(data / "RESTORATION.json")
    expected_hash = next(r["sha256"] for r in restoration["selected_files"] if r["path"].endswith("audit-observer.pt"))
    if sha(observer_path) != expected_hash:
        raise ValueError("Independent observer changed")
    torch.set_num_threads(1)
    observer = FrozenObserver().eval().requires_grad_(False)
    observer.load_state_dict(torch.load(observer_path, weights_only=True))
    parser = re.compile(r"left (\d) right (\d) relation (less|equal|greater)")
    cache, checked_files, max_utility, checked_feedback = {}, set(), 0., {-1: 0, 0: 0, 1: 0}
    updated = []
    for row in records:
        index = row["index"]
        truth = private["labels"][index].tolist()
        expected_relation = "less" if truth[0] < truth[1] else "greater" if truth[0] > truth[1] else "equal"
        for name in ("initial", "final"):
            delivery = row[name]
            for kind in ("image", "text"):
                if sha(delivery["paths"][kind]) != delivery["sha256"][kind]:
                    raise ValueError("Actual native media changed")
                checked_files.add(delivery["paths"][kind])
            caption = Path(delivery["paths"]["text"]).read_text()
            match = parser.fullmatch(caption.strip())
            parsed = [int(match[1]), int(match[2])] if match else None
            identity = delivery["sha256"]["image"]
            if identity not in cache:
                with Image.open(delivery["paths"]["image"]) as image:
                    if image.mode != "L" or image.size != (56, 28):
                        raise ValueError("Native output image contract changed")
                    pixels = torch.from_numpy(np.asarray(image).copy()).float()[None, None] / 255
                with torch.inference_mode():
                    inferred = observer(torch.cat([pixels[:, :, :, :28], pixels[:, :, :, 28:]], axis=0)).argmax(1).tolist()
                cache[identity] = pixels, inferred
            pixels, inferred = cache[identity]
            mismatch = lambda a, b: sum(x != y for x, y in zip(a, b)) / 2
            text_error = mismatch(parsed, truth) if parsed else 1.
            relation_error = float(match[3] != expected_relation) if match else 1.
            image_error = mismatch(inferred, truth)
            disagreement = mismatch(parsed, inferred) if parsed else 1.
            mse = float((pixels - private["pixels"][index:index + 1]).square().mean())
            utility = 1 - 2 * (.3 * text_error + .15 * relation_error + .35 * image_error + .1 * disagreement + .1 * mse)
            strict = int(text_error == 0 and relation_error == 0 and image_error == 0)
            reported = row[name + "_score"]
            max_utility = max(max_utility, abs(utility - reported["utility"]))
            if max_utility > 1e-7 or inferred != reported["image_digits"] or strict != reported["strict_success"]:
                raise ValueError("Independent native media score differs")
            if name == "initial":
                feedback = 0
                if parsed:
                    relation = "less" if parsed[0] < parsed[1] else "greater" if parsed[0] > parsed[1] else "equal"
                    if match[3] == relation:
                        feedback = 1 if parsed == truth else -1 if parsed == truth[::-1] else 0
                if feedback != row["true_feedback"]:
                    raise ValueError("Wrong/unknown feedback conflated")
                checked_feedback[feedback] += 1
        ticks = row["actual_ticks"]
        if ticks[1]["feedback_q24"] != 0 or ticks[2]["feedback_q24"] != 0:
            raise ValueError("Late decision received another scalar")
        admitted = row["proposed"] and row["expires"] >= 7 and row["budget"] >= 2
        charge = .0001 * 50 + .01 + .002 + admitted * (.01 + .002) + (row["proposed"] and not admitted) * .005
        if admitted != row["admitted"] or abs(charge - row["task_charge"]) > 1e-12 or row["actual_original_kernel_executions"] != 50:
            raise ValueError("Native permission/resource/cost mismatch")
        chronology = row["chronology"]
        sequence = [chronology[k] for k in ("initial_delivery", "feedback", "process_restart", "late_decision")]
        if admitted:
            sequence.append(chronology["correction_delivery"])
        sequence.append(chronology["private_final_scoring"])
        if sequence != sorted(sequence) or len(sequence) != len(set(sequence)):
            raise ValueError("Native feedback order differs")
        updated.append({"index": index, "arm": row["arm"], "strict": strict, "net": utility - charge,
            "admitted": admitted, "final_hash": row["final"]["sha256"]})
    arms = seal["protocol"]["arms"]
    by_arm = {a: sorted([r for r in updated if r["arm"] == a], key=lambda r: r["index"]) for a in arms}
    native = by_arm["native_numeric"]
    equivalence = {}
    for arm in ("history", "linear_memory"):
        equivalence[arm] = all(a["admitted"] == b["admitted"] and a["final_hash"] == b["final_hash"] for a, b in zip(native, by_arm[arm]))
        if not equivalence[arm]:
            raise ValueError("Same-information control differs")
    calibration = {}
    native_rows = sorted([r for r in records if r["arm"] == "native_numeric"], key=lambda r: r["index"])
    for when in ("before", "after"):
        probabilities = np.asarray([r["prediction_" + when]["strict_probability"] for r in native_rows])
        outcomes = np.asarray([r["strict"] for r in native])
        ece = 0.
        for lo in range(10):
            chosen = (probabilities >= lo / 10) & (probabilities < (lo + 1) / 10 if lo < 9 else probabilities <= 1)
            if chosen.any():
                ece += chosen.mean() * abs(probabilities[chosen].mean() - outcomes[chosen].mean())
        accepted = probabilities >= .75
        false = float(np.mean(accepted & (outcomes == 0)))
        calibration[when] = {"ECE": float(ece), "coverage": float(accepted.mean()), "false_acceptance_per_all": false,
            "error_among_accepted": float(np.mean(outcomes[accepted] == 0)),
            "strict_point_gate_passed": bool(ece <= .03 and false <= .004999 and accepted.mean() >= .2)}
        reported = result["semantic_calibration"][when]
        if abs(ece - reported["ece"]) > 1e-12 or abs(false - reported["false_acceptance_per_all_cases"]) > 1e-12:
            raise ValueError("Semantic calibration arithmetic differs")
    report = {"status": "passed", "independent_scorer_and_observer_class": True,
        "rows_sha256": sha(root / "ROWS.jsonl"), "qualification_seal_sha256": sha(root / "QUALIFICATION_SEAL.json"),
        "observer_sha256": expected_hash, "actual_episodes": len(records), "distinct_media_paths_reopened": len(checked_files),
        "distinct_actual_images_recognized": len(cache), "source_pairs_checked_against_official_MNIST": len(sources),
        "maximum_utility_discrepancy": max_utility, "feedback_histogram_over_all_arms": checked_feedback,
        "same_information_controls": equivalence, "semantic_calibration": calibration,
        "interpretive_limits": ["Zero intervention is not an independently optimized no-feedback policy",
            "Same50kernel burden is a budget-matching diagnostic, not cheapest history implementation",
            "Permutation contrast is conditional on the realized donor graph; cross-pair donor dependence remains",
            "Native domain qualification is not semantic production calibration; FAR gates fail",
            "Existing learned recognizer is imperfect; no human or cryptographic isolation claim"]}
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace, args.output)
