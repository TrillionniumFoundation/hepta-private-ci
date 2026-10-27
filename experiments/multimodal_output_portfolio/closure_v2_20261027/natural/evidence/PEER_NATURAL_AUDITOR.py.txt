"""Read-only peer reconstruction of natural outputs; imports no study engine."""

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from PIL import Image


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def distance(a, b):
    state = list(range(len(b) + 1))
    for i, first in enumerate(a, 1):
        updated = [i]
        for j, second in enumerate(b, 1):
            updated.append(min(updated[-1] + 1, state[j] + 1, state[j - 1] + (first != second)))
        state = updated
    return state[-1]


def normalize(field, text):
    if field == "total":
        try:
            return str(Decimal(text.replace(",", "").strip()).normalize())
        except InvalidOperation:
            pass
    return re.sub("[^A-Z0-9]", "", text.upper())


def paired(rows, treatment, control, metric, cluster, seed=2811, quantiles=(.025, .975)):
    cells = defaultdict(lambda: defaultdict(list))
    for row in rows:
        cells[row[cluster]][row["arm"]].append(row[metric])
    values = np.asarray([np.mean(cells[k][treatment]) - np.mean(cells[k][control]) for k in sorted(cells)])
    rng = np.random.default_rng(seed)
    samples = values[rng.integers(len(values), size=(5000, len(values)))].mean(1)
    return {"difference": float(values.mean()), "interval": np.quantile(samples, quantiles).tolist(), "clusters": len(values)}


def close(a, b):
    discrepancy = float(np.max(np.abs(np.asarray(a) - np.asarray(b))))
    if discrepancy > 1e-9:
        raise ValueError(f"Independent arithmetic differs: {discrepancy}")
    return discrepancy


def source_and_freeze(assets, run):
    manifest = read(assets / "MANIFEST.json")
    frozen = read(run / "FROZEN_REGISTRATION.json")
    if sha(assets / "MANIFEST.json") != frozen["assets_sha256"] or not frozen["heldout_generation_not_started"]:
        raise ValueError("Source/freeze binding differs")
    for entry in manifest["files"]:
        path = Path(entry["path"])
        if sha(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError("Actual source file changed: " + str(path))
    snapshot = Path(frozen["source_snapshot"])
    for entry in frozen["source_files"]:
        if sha(snapshot / Path(entry["path"]).name) != entry["sha256"]:
            raise ValueError("Executed-source snapshot differs")
    return manifest, frozen


def contrasts(rows, result, treatment, cluster):
    max_error = 0.
    for key, metrics in result["comparisons"].items():
        first, second = key.split("__minus__")
        if first != treatment:
            raise ValueError("Unexpected frozen primary treatment")
        for metric, observed in metrics.items():
            actual = paired(rows, first, second, metric, cluster)
            max_error = max(max_error, close(actual["difference"], observed["difference"]), close(actual["interval"], observed["CI95"]))
            if actual["clusters"] != observed["independent_source_clusters"]:
                raise ValueError("Pseudo-replicated interval")
    return max_error


def video(workspace):
    assets, run = workspace / "natural-v2-assets/video", workspace / "natural-v2-runs/video-qualification-001"
    manifest, frozen = source_and_freeze(assets, run)
    rows, result = read(run / "ROWS.json"), read(run / "RESULT.json")
    samples = {item["id"]: item for item in manifest["samples"]}
    targets = {item["private_target"] for item in samples.values()}
    endpoints = {item[k] for item in samples.values() for k in ("left", "right")}
    if targets & endpoints:
        raise ValueError("A video target is exposed as another public endpoint")
    maximum = 0.
    for row in rows:
        if sha(row["output_path"]) != row["output_sha256"] or row["private_target_received"]:
            raise ValueError("Video output identity/private boundary changed")
        with Image.open(row["output_path"]) as picture:
            output = np.asarray(picture.convert("RGB"), dtype=float)
        with Image.open(samples[row["id"]]["private_target"]) as picture:
            target = np.asarray(picture.convert("RGB"), dtype=float)
        mse = float(np.mean(((output - target) / 255) ** 2))
        maximum = max(maximum, close(mse, row["pixel_MSE"]), close(-10 * np.log10(max(mse, 1e-12)), row["PSNR"]))
        if not frozen["registered_ns"] < row["delivered_ns"] < row["scored_ns"]:
            raise ValueError("Video freeze/delivery/private score order differs")
    grid = {(r["id"], r["arm"], r["repetition"]) for r in rows}
    if len(grid) != len(rows) or grid != {(i, a, r) for i in samples for a in result["summary"] for r in (0, 1)}:
        raise ValueError("Video grid incomplete")
    model = read(run / "FROZEN_MODEL.json")
    if sha(run / "FROZEN_MODEL.json") != frozen["frozen_model_sha256"]:
        raise ValueError("New video solver parameters changed")
    if sha(run / "ORIGINAL_MODEL.json") != frozen["original_model_sha256"]:
        raise ValueError("Strong original video baseline changed")
    for values in model["models"].values():
        close(values["alpha"], np.clip(values["numerator"] / values["denominator"], 0, 1))
        if values["training_sources"] != ["david", "dudek", "faceocc2"] or values["private_test_pixels_received"]:
            raise ValueError("New video training used qualification sources")
    summary = model["validation_summaries"]
    eligible = [name for name, values in summary.items() if values["PSNR"] >= summary["original_flow"]["PSNR"] - .25]
    selected = min(eligible, key=lambda key: (summary[key]["cpu_seconds"], -summary[key]["PSNR"], key))
    if selected != model["selected_arm"]:
        raise ValueError("Video selection is inconsistent with old validation")
    return {"actual_PNGs": len(rows), "source_clusters": 8, "maximum_score_discrepancy": maximum,
        "maximum_contrast_discrepancy": contrasts(rows, result, "efficient_learned", "source"),
        "actual_target_endpoint_overlap": 0, "training_attribution_gate": result["training_attribution_gate_passed"],
        "quality_cost_gate": result["quality_cost_gate_passed"], "fitted_parameter_count": 1,
        "cost_scope": "After destination.mkdir: endpoint decode, two flow calls, warps, mixing, PNG readback/hash and public metadata; excludes model/process load, directory creation, network, private score; source preparation separately shared",
        "historical_scope": "David/Dudek/Faceocc2 include previously retired test material already designated development; no reuse of prior natural qualification realshort/vtest/cockatoo for new selection"}


def documents(workspace, replication=False):
    name = "document-replication" if replication else "document"
    run_name = "document-replication-001" if replication else "document-qualification-001"
    assets, run = workspace / "natural-v2-assets" / name, workspace / "natural-v2-runs" / run_name
    manifest, frozen = source_and_freeze(assets, run)
    rows, result = read(run / "ROWS.json"), read(run / "RESULT.json")
    sources = {entry["id"]: entry for entry in manifest["documents"]}
    groups = [entry["merchant_group"] for entry in sources.values()]
    if len(groups) != len(set(groups)) or set(groups) & set(manifest["excluded_merchants"]):
        raise ValueError("Declared merchant-string exclusion failed")
    maximum = 0.
    for row in rows:
        directory, source = Path(row["output_directory"]), sources[row["id"]]
        answer = read(directory / "DELIVERED.json")
        if sha(directory / "DELIVERED.json") != row["answer_sha256"] or sha(directory / "DELIVERED.jpg") != row["image_sha256"]:
            raise ValueError("Actual document output changed")
        if answer["reference_received"] or answer["answers"] != row["answers"]:
            raise ValueError("Reference contamination or answer readback mismatch")
        with Image.open(directory / "DELIVERED.jpg") as picture:
            picture.load()
            if picture.size != (source["image_size"]["width"], source["image_size"]["height"]):
                raise ValueError("Document annotation canvas differs")
        scores, exact = [], []
        for field, truth in source["reference"].items():
            if truth is None or not normalize(field, truth):
                continue
            a, b = normalize(field, truth), normalize(field, answer["answers"][field])
            similarity = 1 - distance(a, b) / max(1, len(a), len(b))
            exact.append(a == b)
            scores.append(.5 * (a == b) + .5 * max(0., similarity))
        maximum = max(maximum, close(np.mean(scores), row["quality"]), close(np.mean(exact), row["field_exact"]),
            close(row["quality"] - .01 * row["cpu_seconds"], row["cost_adjusted_return"]))
        if len(scores) != row["observed_reference_fields"] or not frozen["registered_ns"] < row["delivered_ns"] < row["scored_ns"]:
            raise ValueError("Document denominator or private-scoring chronology differs")
    arms = list(result["summary"])
    grid = {(r["id"], r["arm"], r["repetition"]) for r in rows}
    if len(grid) != len(rows) or grid != {(i, a, r) for i in sources for a in arms for r in (0, 1)}:
        raise ValueError("Document grid incomplete")
    expected_model = sha(workspace / "natural-v2-runs/document-development-001/FROZEN_MODEL.json")
    if sha(run / "FROZEN_MODEL.json") != expected_model:
        raise ValueError("Document model refit between cohorts")
    report = {"actual_JSON_JPEG_pairs": len(rows), "declared_normalized_merchant_groups": len(sources),
        "maximum_score_discrepancy": maximum, "model_sha256": expected_model,
        "group_scope": "ASCII-normalized annotated company strings; corporate entity and template independence not established",
        "cost_scope": "Both arms time OCR including child CPU, selection, JSON/JPEG delivery/readback/hash; destination mkdir and trailing PUBLIC_RESULT metadata write excluded symmetrically"}
    if replication:
        max_difference = 0.
        for metric, observed in result["primary_contrast"].items():
            # One source per merchant; reproduce the registered sorted-source
            # ordering so the finite seeded bootstrap draw is identical.
            actual = paired(rows, "rule_residual", "original_rules", metric, "id", 2832, (.0125, .9875))
            max_difference = max(max_difference, close(actual["difference"], observed["difference"]), close(actual["interval"], observed["CI97_5"]))
        if result["old24_primary_result_pooled"] or result["model_refitted"]:
            raise ValueError("Replication changed its frozen model/cohort scope")
        original = read(workspace / "natural-v2-assets/document/MANIFEST.json")
        if {s["sha256"] for s in sources.values()} & {s["sha256"] for s in original["documents"]}:
            raise ValueError("Replication repeated a first-cohort image")
        if frozen["ordered_source_ids"] != list(sources) or frozen["exact_N"] != 128:
            raise ValueError("Replication source list changed after registration")
        report.update(maximum_contrast_discrepancy=max_difference, strong_rules_replication_gate=result["strong_rules_replication_gate_passed"],
            primary_contrast=result["primary_contrast"], old_inconclusive_cohort_not_pooled=True)
    else:
        report.update(maximum_contrast_discrepancy=contrasts(rows, result, "rule_residual", "merchant_group"),
            old_all_refine_gate=result["quality_cost_gate_passed"], strong_rules_gate=result["strong_baseline_gate_passed"])
        aliases = [s for s in sources.values() if s["merchant_group"] in {"TEDHENGSTATIONERYBOOKS", "TEOHENGSTATIONERYBOOKS"}]
        if len(aliases) == 2:
            address = [normalize("address", s["reference"]["address"]) for s in aliases]
            actual_headers = [s["reference_words"][0] for s in aliases]
            if address[0] != address[1] or actual_headers[0] != actual_headers[1]:
                raise ValueError("Suspected merchant alias was not confirmed by public source annotations")
            merged = [{**r, "sensitivity_cluster": "TEO_HENG_VERIFIED_ALIAS" if r["merchant_group"] in {a["merchant_group"] for a in aliases} else r["merchant_group"]} for r in rows]
            report["confirmed_alias"] = {"ids": [s["id"] for s in aliases], "same_address": address[0], "same_source_header": actual_headers[0]}
            report["posthoc_23_cluster_sensitivity_not_new_gate"] = {key: paired(merged, "rule_residual", "original_rules", key, "sensitivity_cluster")
                for key in ("quality", "cost_adjusted_return")}
    return report


def speech(workspace):
    assets, run = workspace / "natural-v2-assets/speech", workspace / "natural-v2-runs/speech-qualification-001"
    manifest, frozen = source_and_freeze(assets, run)
    rows, result = read(run / "ROWS.json"), read(run / "RESULT.json")
    sources = {entry["id"]: entry for entry in manifest["speech"]}
    if set(manifest["test_speakers"]) & set(manifest["excluded_speakers"]):
        raise ValueError("New speech speaker overlaps prior development")
    encoder = read(run / "ENCODER_MODEL.json")
    if sha(run / "ENCODER_MODEL.json") != frozen["encoder_policy_sha256"] or sha(run / "FROZEN_MODEL.json") != frozen["continuation_sha256"]:
        raise ValueError("Speech policies changed")
    if sha(Path(manifest["model_directory"]) / "model.bin") != frozen["model_sha256"]:
        raise ValueError("Base speech generator weights changed")
    encoding_identity = defaultdict(set)
    for row in rows:
        text = Path(row["output_path"]).read_text().strip()
        if sha(row["output_path"]) != row["output_sha256"] or text != row["transcript"]:
            raise ValueError("Speech transcript identity differs")
        predicted = re.findall("[a-z0-9']+", text.lower())
        truth = re.findall("[a-z0-9']+", sources[row["id"]]["reference"].lower())
        if distance(predicted, truth) != row["word_errors"] or len(truth) != row["reference_words"]:
            raise ValueError("Speech edit-distance denominator differs")
        if row["private_reference_received"] or not frozen["registered_ns"] < row["delivered_before_private_scoring_ns"] < row["scored_ns"]:
            raise ValueError("Speech information boundary differs")
        for encoding in row["encodings"]:
            encoding_identity[row["id"]].add(encoding["encoded_sha256"])
        continue_expected = row["arm"] in {"cached_continuation", "reencoded_continuation"} and row["generations"][0]["confidence"] < result["selected_threshold"]
        if row["decoder_calls"] != 1 + continue_expected or row["encoder_calls"] != 1 + (continue_expected and row["arm"] == "reencoded_continuation"):
            raise ValueError("Actual cached/cold computation differs from declared policy")
        if row["arm"] == "encoder_gate":
            model = encoder["model"]
            standardized = (np.asarray(row["gate"]["features"]) - model["mean"]) / model["scale"]
            value = float(np.r_[1., standardized] @ model["weights"])
            if row["generations"][0]["beam"] != (5 if value >= encoder["choice"]["threshold"] else 1) or row["gate"]["decoder_outputs_before_gate"] != 0:
                raise ValueError("Predecoder beam allocation changed")
        for kind in ("cpu_seconds", "wall_seconds"):
            if row[kind] + 1e-6 < sum(part[kind] for part in row["encodings"] + row["generations"]) + row["gate"][kind]:
                raise ValueError("Full speech timer omits a charged stage")
    if any(len(values) != 1 for values in encoding_identity.values()):
        raise ValueError("Cached representations differ for identical source inputs")
    grid = {(r["id"], r["arm"], r["repetition"]) for r in rows}
    if grid != {(i, a, r) for i in sources for a in result["summary"] for r in (0, 1)} or len(grid) != len(rows):
        raise ValueError("Speech grid incomplete")
    comparisons = [("cached_continuation", b, r) for b, r in result["comparisons"].items()]
    comparisons.append(("encoder_gate", "fixed_beam5", result["encoder_vs_fixed_beam5"]))
    for treatment, baseline, observed in comparisons:
        for metric, key in (("cpu_seconds", "CPU"), ("wall_seconds", "wall")):
            actual = paired(rows, treatment, baseline, metric, "speaker_id", 2821)
            close(actual["difference"], observed[key]["difference"])
            close(actual["interval"], observed[key]["CI95"])
        matrix = []
        for speaker in sorted(manifest["test_speakers"]):
            a = [r for r in rows if r["speaker_id"] == speaker and r["arm"] == treatment and r["repetition"] == 0]
            b = [r for r in rows if r["speaker_id"] == speaker and r["arm"] == baseline and r["repetition"] == 0]
            matrix.append([sum(r["word_errors"] for r in a) - sum(r["word_errors"] for r in b), sum(r["reference_words"] for r in a)])
        matrix = np.asarray(matrix)
        rng = np.random.default_rng(2821)
        sample = matrix[rng.integers(len(matrix), size=(5000, len(matrix)))].sum(1)
        close(np.quantile(sample[:, 0] / sample[:, 1], [.025, .975]), observed["WER_difference_CI95"])
        close(matrix[:, 0].sum() / matrix[:, 1].sum(), observed["WER_difference"])
    for identity in sources:
        for repetition in (0, 1):
            group = {r["arm"]: r for r in rows if r["id"] == identity and r["repetition"] == repetition}
            if group["cached_continuation"]["output_sha256"] != group["reencoded_continuation"]["output_sha256"]:
                raise ValueError("Cache changes actual output")
    return {"actual_transcripts": len(rows), "speakers": 16, "utterances": 64,
        "same_input_cached_cold_and_all_arm_encoded_hashes_match": True,
        "all_actual_transcripts_and_source_cluster_intervals_verified": True,
        "encoder_gate": result["encoder_vs_fixed_beam5"]["quality_cost_gate_passed"],
        "same_policy_cache_gate": result["comparisons"]["reencoded_continuation"]["gate_passed"],
        "postdecoder_cache_vs_single_beam5_gate": result["comparisons"]["fixed_beam5"]["gate_passed"],
        "stronger_cheap_control_limitation": "Fixed greedy also satisfies cohort WER noninferiority and is cheaper; encoder controller superiority over every fixed policy not established",
        "cost_scope": "Full audio decode/features/encoder/gate/all decoders/transcript and public metadata readback; excludes destination mkdir and shared model loading/warmup; no neural parameter update"}


def run(workspace, output):
    reports = {"video": video(workspace), "document": documents(workspace),
        "document_replication": documents(workspace, True), "speech": speech(workspace)}
    result = {"passed": True, "read_only_peer_review": True, "generator_model_reruns": 0,
        "imports_producer_scorer_statistics_or_auditor": False, "reports": reports}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace, args.output)
