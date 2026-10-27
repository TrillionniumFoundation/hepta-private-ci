"""Actual learned document-output refinement with untouched merchant holdouts."""
import argparse
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np

from ...repair_20261026.natural.document.ocr import FIELDS
from .common import freeze, read, save, sha, verify_files
from .document_decoder import candidates, field_score, fit_decoder, FieldDecoder
from .document_engine import cpu_now, episode, ocr


def score(reference, answers):
    fields = {field: field_score(field, reference[field], answers[field]) for field in FIELDS}
    observed = [r for r in fields.values() if r["observed_reference"]]
    if not observed:
        raise ValueError("No observed reference fields for scoring")
    return {"field_scores": fields, "observed_reference_fields": len(observed),
        "quality": float(np.mean([r["quality"] for r in observed])),
        "field_exact": float(np.mean([r["exact"] for r in observed])),
        "all_fields_exact": len(observed) == len(FIELDS) and all(r["exact"] for r in observed)}


def summarize(rows, arms, repetitions):
    documents = []
    for identity in sorted({r["id"] for r in rows}):
        by_arm = {}
        for arm in arms:
            group = [r for r in rows if r["id"] == identity and r["arm"] == arm]
            if len(group) != repetitions or any(r["answers"] != group[0]["answers"] for r in group):
                raise ValueError("Missing or nonidentical document repetitions")
            cpu = np.mean([r["whole_cpu_seconds"] for r in group])
            wall = np.mean([r["whole_wall_seconds"] for r in group])
            by_arm[arm] = {"quality": group[0]["quality"], "field_exact": group[0]["field_exact"],
                "document_exact": group[0]["all_fields_exact"], "cpu_seconds": float(cpu), "wall_seconds": float(wall),
                "cost_adjusted_return": float(group[0]["quality"]-.01*cpu),
                "actual_OCR_calls": group[0]["actual_OCR_calls"], "answers": group[0]["answers"]}
            by_arm[arm]["observed_reference_fields"] = group[0]["observed_reference_fields"]
        documents.append({"id": identity, "arms": by_arm})
    summary = {}
    for arm in arms:
        group = [r["arms"][arm] for r in documents]
        summary[arm] = {"independent_recorded_merchant_groups": len(group),
            **{name: float(np.mean([r[name] for r in group])) for name in
            ("quality", "field_exact", "document_exact", "cpu_seconds", "wall_seconds", "cost_adjusted_return")},
            "OCR_calls_per_repetition": sum(r["actual_OCR_calls"] for r in group)}
        summary[arm]["observed_reference_fields"] = sum(r["observed_reference_fields"] for r in group)
    comparisons = {}
    for treatment, baseline in (("learned_selective", "learned_base"), ("learned_selective", "learned_all_refine"),
            ("learned_base", "original_rules")):
        keys = ("quality", "field_exact", "cpu_seconds", "wall_seconds", "cost_adjusted_return")
        differences = np.array([[r["arms"][treatment][key]-r["arms"][baseline][key] for key in keys] for r in documents])
        rng = np.random.default_rng(2712)
        sampled = differences[rng.integers(len(documents), size=(4000, len(documents)))].mean(1)
        result = {key: {"difference": float(differences[:, i].mean()), "CI95": np.quantile(sampled[:, i], [.025, .975]).tolist()}
            for i, key in enumerate(keys)}
        if baseline == "learned_all_refine":
            accepted = result["quality"]["CI95"][0] >= -.02 and result["cpu_seconds"]["CI95"][1] < 0 and result["wall_seconds"]["CI95"][1] < 0
        else:
            accepted = result["cost_adjusted_return"]["CI95"][0] > 0
        result["acceptance_passed"] = bool(accepted)
        comparisons[treatment + " minus " + baseline] = result
    return {"summary": summary, "comparisons": comparisons}


def run(assets, output):
    source = Path(__file__).parent
    spec = read(source / "DOCUMENT_PROTOCOL.json")
    manifest = read(assets / "MANIFEST.json")
    if manifest["protocol_sha256"] != sha(source / "DOCUMENT_PROTOCOL.json"):
        amendment = read(source / "DOCUMENT_PRETEST_AMENDMENT.json")
        if amendment["original_protocol_sha256"] != manifest["protocol_sha256"] or amendment["amended_protocol_sha256"] != sha(source / "DOCUMENT_PROTOCOL.json"):
            raise ValueError("Undeclared protocol change after source selection")
    verify_files(manifest["files"])
    output.mkdir(parents=True, exist_ok=False)
    engine = Path(shutil.which("tesseract"))
    language = Path("/usr/share/tesseract-ocr/5/tessdata/eng.traineddata")
    registration = freeze(source, source / "DOCUMENT_PROTOCOL.json", assets / "MANIFEST.json", output,
        {"OCR_engine_sha256": sha(engine), "OCR_language_sha256": sha(language),
        "OCR_version": subprocess.run([str(engine), "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]})
    training_wall, training_cpu = time.perf_counter(), cpu_now()
    fit = []
    for document in (r for r in manifest["documents"] if r["role"] == "fit"):
        observed = ocr(document["path"], output / "fit" / document["id"])
        fit.append({"id": document["id"], "merchant_group": document["merchant_group"],
            "reference": document["reference"], "candidates": candidates(observed["lines"], observed["width"], observed["height"])})
    decoder, training = fit_decoder(fit, spec["decoder"])
    training.update(whole_cpu_seconds=cpu_now()-training_cpu, whole_wall_seconds=time.perf_counter()-training_wall)
    save(output / "FIT_CANDIDATES.json", fit)
    decoder.save(output / "FIELD_DECODER.npz")
    loaded = FieldDecoder.load(output / "FIELD_DECODER.npz")
    sample = [c["features"] for r in fit for field in FIELDS for c in r["candidates"][field]][:128]
    if not np.array_equal(decoder.predict(sample), loaded.predict(sample)):
        raise ValueError("Reloaded learned decoder differs")
    decoder = loaded
    training["checkpoint_sha256"] = sha(output / "FIELD_DECODER.npz")
    save(output / "TRAINING.json", training)
    validation = []
    for document in (r for r in manifest["documents"] if r["role"] == "validation"):
        for index, threshold in enumerate(spec["gates"]):
            public = episode(document["path"], decoder, "learned_selective", threshold,
                output / "validation" / document["id"] / f"gate-{index}")
            validation.append({"id": document["id"], "threshold": threshold, **public,
                **score(document["reference"], public["answers"])})
    choices = []
    for threshold in spec["gates"]:
        group = [r for r in validation if r["threshold"] == threshold]
        choices.append({"threshold": threshold, "objective": float(np.mean([r["quality"]-.01*r["whole_cpu_seconds"] for r in group]))})
    selected = min(choices, key=lambda r: (-r["objective"], r["threshold"]))
    gate = {"selected_threshold": selected["threshold"], "candidates": choices,
        "heldout_scoring_not_started": True, "frozen_ns": time.time_ns(),
        "training_checkpoint_sha256": sha(output / "FIELD_DECODER.npz")}
    save(output / "VALIDATION.json", validation)
    save(output / "GATE_FROZEN.json", gate)
    rows = []
    test = [r for r in manifest["documents"] if r["role"] == "test"]
    for repetition in range(spec["timing_repetitions"]):
        for index, document in enumerate(test):
            rotation = (index+repetition) % len(spec["test_arms"])
            order = spec["test_arms"][rotation:] + spec["test_arms"][:rotation]
            for arm in order:
                public = episode(document["path"], decoder, arm, selected["threshold"],
                    output / "test" / f"repeat-{repetition}" / document["id"] / arm)
                rows.append({"id": document["id"], "merchant_group": document["merchant_group"],
                    "repetition": repetition, **public, **score(document["reference"], public["answers"]),
                    "private_score_ns": time.time_ns()})
            print({"document_repetition": repetition, "completed": index+1, "of": len(test)}, flush=True)
    save(output / "ROWS.json", rows)
    result = {"schema": "hepta.ndu.continuation.natural.document.result.v1", "status": "completed",
        "training": training, "gate": gate, **summarize(rows, spec["test_arms"], spec["timing_repetitions"]),
        "general_complex_image_text_reasoning_proven": False, "natural_AV_synthesis": False,
        "original_Hepta_neuron_integrated": False, "source_group_scope": manifest["group_scope"]}
    save(output / "RESULT.json", result)
    for name, digest in registration["source_sha256"].items():
        if sha(source / name) != digest:
            raise ValueError("Frozen scientific source changed during execution")
    verify_files(manifest["files"])
    print(result["summary"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.assets, args.output)
    except Exception as error:
        if args.output.exists():
            save(args.output / "FAILED.json", {"error": type(error).__name__ + ": " + str(error), "partial_evidence_retained": True})
        raise
