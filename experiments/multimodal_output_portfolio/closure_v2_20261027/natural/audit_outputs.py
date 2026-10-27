"""Reopen natural deliveries and independently reconstruct scores and intervals.

No experiment engine, model, scorer, or summary function is imported.
"""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def edit_distance(left, right):
    costs = np.arange(len(right) + 1).tolist()
    for left_index, first in enumerate(left):
        previous, costs[0] = costs[0], left_index + 1
        for right_index, second in enumerate(right):
            diagonal = previous
            previous = costs[right_index + 1]
            costs[right_index + 1] = min(costs[right_index] + 1, previous + 1, diagonal + (first != second))
    return costs[-1]


def check_source(manifest):
    for row in manifest["files"]:
        path = Path(row["path"])
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("Source file identity mismatch: " + str(path))


def independent_contrast(rows, treatment, baseline, metric, source_key, seed):
    groups = sorted({r[source_key] for r in rows})
    values = []
    for group in groups:
        current = [r for r in rows if r[source_key] == group]
        values.append(np.mean([r[metric] for r in current if r["arm"] == treatment])
            - np.mean([r[metric] for r in current if r["arm"] == baseline]))
    values = np.asarray(values)
    random = np.random.default_rng(seed)
    bootstrap = np.mean(values[random.integers(len(groups), size=(5000, len(groups)))], axis=1)
    return float(np.mean(values)), np.quantile(bootstrap, [.025, .975])


def verify_contrasts(rows, result, treatment, source_key, seed=2811):
    maximum = 0.
    for key, table in result["comparisons"].items():
        baseline = key.split("__minus__")[1]
        for metric, registered in table.items():
            observed, interval = independent_contrast(rows, treatment, baseline, metric, source_key, seed)
            error = max(abs(observed - registered["difference"]), float(np.max(np.abs(interval - registered["CI95"]))))
            maximum = max(maximum, error)
            if error > 1e-10:
                raise ValueError("Independent source interval mismatch")
    return maximum


def audit_video(assets, run):
    manifest, rows, result = load(assets / "MANIFEST.json"), load(run / "ROWS.json"), load(run / "RESULT.json")
    check_source(manifest)
    originals = {(r["sequence"], r["source_index"]): r for r in manifest["files"] if "zip_member" in r}
    canonical_count = 0
    for row in manifest["files"]:
        if "canonical_resize" not in row:
            continue
        original = originals[(row["sequence"], row["source_index"])]
        with Image.open(original["path"]) as image:
            rebuilt = np.asarray(image.convert("RGB").resize(tuple(row["canonical_resize"]), Image.Resampling.BOX))
        with Image.open(row["path"]) as image:
            if not np.array_equal(rebuilt, np.asarray(image)):
                raise ValueError("Canonical frame reconstruction mismatch")
        canonical_count += 1
    for clip in manifest["clips"]:
        if set(clip["target_indices"]) & set(clip["endpoint_indices"]):
            raise ValueError("Target leaks as another public endpoint")
    samples = {r["id"]: r for r in manifest["samples"]}
    maximum = 0.
    grid = set()
    for row in rows:
        key = (row["id"], row["arm"], row["repetition"])
        if key in grid:
            raise ValueError("Duplicate video arm record")
        grid.add(key)
        if digest(row["output_path"]) != row["output_sha256"]:
            raise ValueError("Delivered video PNG hash changed")
        with Image.open(row["output_path"]) as image:
            prediction = np.asarray(image.convert("RGB"), dtype=np.float64) / 255
        with Image.open(samples[row["id"]]["private_target"]) as image:
            target = np.asarray(image.convert("RGB"), dtype=np.float64) / 255
        mse = float(np.mean(np.square(prediction - target)))
        psnr = float(-10 * np.log10(max(mse, 1e-12)))
        maximum = max(maximum, abs(mse - row["pixel_MSE"]), abs(psnr - row["PSNR"]))
        if maximum > 1e-10 or row["scored_ns"] <= row["delivered_ns"] or row["private_target_received"]:
            raise ValueError("Video scoring or chronology mismatch")
    arms = result["summary"]
    expected = {(identity, arm, repetition) for identity in samples for arm in arms for repetition in (0, 1)}
    if grid != expected:
        raise ValueError("Video experiment grid incomplete")
    error = verify_contrasts(rows, result, "efficient_learned", "source")
    return {"actual_PNGs_reopened": len(rows), "canonical_frames_reconstructed": canonical_count,
        "independent_source_clusters": len(manifest["clips"]), "maximum_score_discrepancy": maximum,
        "maximum_interval_discrepancy": error, "quality_cost_gate": result["quality_cost_gate_passed"],
        "training_attribution_gate": result["training_attribution_gate_passed"]}


def normalized(field, value):
    if field == "total":
        try:
            return str(Decimal(value.replace(",", "").strip()).normalize())
        except InvalidOperation:
            pass
    return "".join(c for c in value.upper() if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def audit_document(assets, run):
    manifest, rows, result = load(assets / "MANIFEST.json"), load(run / "ROWS.json"), load(run / "RESULT.json")
    check_source(manifest)
    documents = {r["id"]: r for r in manifest["documents"]}
    groups = [r["merchant_group"] for r in documents.values()]
    if len(groups) != len(set(groups)) or set(groups) & set(manifest["excluded_merchants"]):
        raise ValueError("Merchant source overlap")
    maximum = 0.
    for row in rows:
        item = documents[row["id"]]
        directory = Path(row["output_directory"])
        answer = load(directory / "DELIVERED.json")
        if digest(directory / "DELIVERED.json") != row["answer_sha256"] or answer["answers"] != row["answers"]:
            raise ValueError("Document answer mismatch")
        if digest(directory / "DELIVERED.jpg") != row["image_sha256"]:
            raise ValueError("Document output image changed")
        with Image.open(directory / "DELIVERED.jpg") as image:
            image.load()
            if image.size != (item["image_size"]["width"], item["image_size"]["height"]):
                raise ValueError("Document image dimensions changed")
        quality, exact = [], []
        for field, reference in item["reference"].items():
            if reference is None or not normalized(field, reference):
                continue
            a, b = normalized(field, reference), normalized(field, answer["answers"][field])
            equal = a == b
            similarity = max(0., 1 - edit_distance(a, b) / max(len(a), len(b), 1))
            quality.append((equal + similarity) / 2)
            exact.append(equal)
        maximum = max(maximum, abs(float(np.mean(quality)) - row["quality"]), abs(float(np.mean(exact)) - row["field_exact"]))
        if maximum > 1e-10 or row["scored_ns"] <= row["delivered_ns"] or answer["reference_received"]:
            raise ValueError("Document score or chronology differs")
        if len(quality) != row["observed_reference_fields"]:
            raise ValueError("Document missing-label denominator differs")
    if len(rows) != len(documents) * 4 * 2:
        raise ValueError("Document grid incomplete")
    error = verify_contrasts(rows, result, "rule_residual", "merchant_group")
    return {"actual_answer_image_pairs_reopened": len(rows), "independent_merchants": len(documents),
        "maximum_score_discrepancy": maximum, "maximum_interval_discrepancy": error,
        "quality_cost_gate": result["quality_cost_gate_passed"], "strong_baseline_gate": result["strong_baseline_gate_passed"]}


def audit_speech(assets, run):
    manifest, rows, result = load(assets / "MANIFEST.json"), load(run / "ROWS.json"), load(run / "RESULT.json")
    check_source(manifest)
    sources = {r["id"]: r for r in manifest["speech"]}
    if set(manifest["test_speakers"]) & set(manifest["excluded_speakers"]):
        raise ValueError("Speech source overlap")
    for source in sources.values():
        subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", source["path"], "-f", "null", "-"],
            check=True, capture_output=True)
    encoder = load(run / "ENCODER_MODEL.json") if (run / "ENCODER_MODEL.json").exists() else None
    for row in rows:
        transcript = Path(row["output_path"]).read_text(encoding="utf-8").strip()
        if transcript != row["transcript"] or digest(row["output_path"]) != row["output_sha256"]:
            raise ValueError("Speech delivery changed")
        truth = re.findall("[a-z0-9']+", sources[row["id"]]["reference"].lower())
        predicted = re.findall("[a-z0-9']+", transcript.lower())
        if edit_distance(truth, predicted) != row["word_errors"] or len(truth) != row["reference_words"]:
            raise ValueError("Independent WER mismatch")
        if row["scored_ns"] <= row["delivered_before_private_scoring_ns"] or row["private_reference_received"]:
            raise ValueError("Speech chronology differs")
        continued = row["arm"] in ("cached_continuation", "reencoded_continuation") and row["generations"][0]["confidence"] < result["selected_threshold"]
        if len(row["generations"]) != 1 + continued or len(row["encodings"]) != 1 + (continued and row["arm"] == "reencoded_continuation"):
            raise ValueError("Speech actual call count differs from frozen gate")
        if continued and row["arm"] == "reencoded_continuation" and row["encodings"][0]["encoded_sha256"] != row["encodings"][1]["encoded_sha256"]:
            raise ValueError("Cold versus retained encoding differs")
        if row["arm"] == "encoder_gate":
            if encoder["choice"]["kind"] == "fixed_beam5":
                if row["generations"][0]["beam"] != 5:
                    raise ValueError("Compiled fixed policy differs")
            else:
                p = encoder["model"]
                x = np.r_[1., (np.asarray(row["gate"]["features"]) - p["mean"]) / p["scale"]]
                predicted = float(x @ p["weights"])
                beam = 5 if predicted >= encoder["choice"]["threshold"] else 1
                if beam != row["generations"][0]["beam"] or row["gate"]["decoder_outputs_before_gate"] != 0:
                    raise ValueError("Public encoder-state allocation differs")
    if len(rows) != len(sources) * len(result["summary"]) * 2:
        raise ValueError("Speech grid incomplete")
    contrasts = [("cached_continuation", baseline, registered) for baseline, registered in result["comparisons"].items()]
    if "encoder_vs_fixed_beam5" in result:
        contrasts.append(("encoder_gate", "fixed_beam5", result["encoder_vs_fixed_beam5"]))
    for treatment, baseline, registered in contrasts:
        for metric, key in (("cpu_seconds", "CPU"), ("wall_seconds", "wall")):
            difference, interval = independent_contrast(rows, treatment, baseline, metric, "speaker_id", 2821)
            if max(abs(difference - registered[key]["difference"]), np.max(np.abs(interval - registered[key]["CI95"]))) > 1e-10:
                raise ValueError("Speech timing interval mismatch")
        matrix = []
        for speaker in manifest["test_speakers"]:
            a = [r for r in rows if r["speaker_id"] == speaker and r["arm"] == treatment and r["repetition"] == 0]
            b = [r for r in rows if r["speaker_id"] == speaker and r["arm"] == baseline and r["repetition"] == 0]
            matrix.append([sum(r["word_errors"] for r in a) - sum(r["word_errors"] for r in b), sum(r["reference_words"] for r in a)])
        matrix = np.asarray(matrix)
        rng = np.random.default_rng(2821)
        samples = matrix[rng.integers(len(matrix), size=(5000, len(matrix)))].sum(1)
        interval = np.quantile(samples[:, 0] / samples[:, 1], [.025, .975])
        if np.max(np.abs(interval - registered["WER_difference_CI95"])) > 1e-10:
            raise ValueError("Speech WER uncertainty mismatch")
    return {"actual_transcripts_reopened": len(rows), "full_FLACs_decoded": len(sources),
        "independent_speakers": len(manifest["test_speakers"]), "all_WER_and_interval_values_match": True,
        "fixed_beam5_gate": result["comparisons"]["fixed_beam5"]["gate_passed"],
        "same_policy_cache_gate": result["comparisons"]["reencoded_continuation"]["gate_passed"],
        "encoder_quality_cost_gate": result.get("encoder_vs_fixed_beam5", {}).get("quality_cost_gate_passed")}


def run(workspace, output):
    reports = {}
    for name, function in (("video", audit_video), ("document", audit_document), ("speech", audit_speech)):
        reports[name] = function(workspace / "natural-v2-assets" / name,
            workspace / "natural-v2-runs" / (name + "-qualification-001"))
    output.write_text(json.dumps({"status": "passed", "imports_experiment_scorer_or_model": False,
        "reports": reports}, indent=2, sort_keys=True) + "\n")
    print(reports)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace, args.output)
