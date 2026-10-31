"""One frozen scanned-receipt fit/test experiment with an explicit strong baseline."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import subprocess
import time

from PIL import Image

from .ocr import FIELDS, infer


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")


def normalize(field, value):
    if field == "total":
        try:
            return str(Decimal(value.replace(",", "").strip()).normalize())
        except InvalidOperation:
            pass
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def score(reference, observed):
    exact = {field: bool(normalize(field, reference[field])) and normalize(field, reference[field]) == normalize(field, observed[field]) for field in FIELDS}
    return {"field_exact": exact, "field_fraction": sum(exact.values())/len(FIELDS), "document_exact": all(exact.values())}


def run(assets, output):
    source = Path(__file__).parent
    spec = json.loads((source/"PROTOCOL.json").read_text())
    manifest = json.loads((assets/"MANIFEST.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    source_pins = {p.name: sha(p) for p in source.glob("*.py")}
    source_pins["PROTOCOL.json"] = sha(source/"PROTOCOL.json")
    engine = Path(shutil.which("tesseract"))
    language = Path("/usr/share/tesseract-ocr/5/tessdata/eng.traineddata")
    engine_pins = {str(p): sha(p) for p in (engine, language)}
    if any(sha(r["path"]) != r["sha256"] for r in manifest["files"]):
        raise ValueError("Scanned source/annotation metadata changed")
    save(output/"FROZEN_REGISTRATION.json", {"registered_ns": time.time_ns(), "protocol": spec,
        "source_pins": source_pins, "engine_pins": engine_pins, "asset_manifest_sha256": sha(assets/"MANIFEST.json"),
        "tesseract_version": subprocess.run([str(engine), "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0],
        "neural_parameters_will_change": False, "test_execution_has_not_started": True})
    started = time.perf_counter_ns()
    fit = []
    for document in (r for r in manifest["documents"] if r["role"] == "fit"):
        outputs = {}
        for mode, settings in spec["ocr_arms"].items():
            observation = infer(document["path"], settings, output/"fit"/document["id"]/mode)
            outputs[mode] = {**observation, **score(document["reference"], observation["answers"])}
        fit.append({"id": document["id"], "merchant_group": document["merchant_group"], "outputs": outputs})
    candidates = []
    for threshold in spec["gate_candidates"]:
        rewards = []
        for row in fit:
            first, more = row["outputs"]["base"], row["outputs"]["enhanced"]
            proceed = first["mean_word_confidence"] < threshold
            chosen = more if proceed else first
            rewards.append(chosen["field_fraction"]-.01*(first["wall_seconds"]+proceed*more["wall_seconds"]))
        candidates.append({"threshold": threshold, "fit_objective": sum(rewards)/len(rewards)})
    chosen = min(candidates, key=lambda r: (-r["fit_objective"], r["threshold"]))
    gate = {"selected_threshold": chosen["threshold"], "candidates": candidates, "test_has_not_started": True,
            "fitted_parameters": 1, "parser_and_OCR_model_frozen": True}
    save(output/"FIT.json", fit)
    save(output/"GATE_FROZEN.json", gate)
    rows = []
    for i, document in enumerate(r for r in manifest["documents"] if r["role"] == "test"):
        arms = spec["test_arms"][i%3:] + spec["test_arms"][:i%3]
        for arm in arms:
            root = output/"test"/document["id"]/arm
            start = time.perf_counter_ns()
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            mode = "enhanced" if arm == "fixed_enhanced" else "base"
            observed = infer(document["path"], spec["ocr_arms"][mode], root/"first")
            calls, selected_root = 1, root/"first"
            if arm == "dynamic" and observed["mean_word_confidence"] < chosen["threshold"]:
                observed = infer(document["path"], spec["ocr_arms"]["enhanced"], root/"continued")
                calls, selected_root = 2, root/"continued"
            shutil.copy2(selected_root/"ANSWERS.json", root/"DELIVERED.json")
            shutil.copy2(selected_root/"ANNOTATED.png", root/"DELIVERED.png")
            delivered = json.loads((root/"DELIVERED.json").read_text(encoding="utf-8"))
            with Image.open(root/"DELIVERED.png") as image:
                image.load()
                if image.size != (document["image_size"]["width"], document["image_size"]["height"]):
                    raise ValueError("Actual delivered PNG has wrong dimensions")
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            public = {"id": document["id"], "merchant_group": document["merchant_group"], "arm": arm,
                "answers": delivered["answers"], "actual_OCR_calls": calls,
                "whole_wall_seconds": (time.perf_counter_ns()-start)/1e9,
                "subprocess_CPU_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                "delivered_json_sha256": sha(root/"DELIVERED.json"), "delivered_png_sha256": sha(root/"DELIVERED.png"),
                "reference_entities_supplied_to_inference": False, "public_readback_completed_before_scoring": True}
            save(root/"PUBLIC_RESULT.json", public)
            rows.append({**public, **score(document["reference"], public["answers"])})
        print(json.dumps({"document_test_completed": i+1, "of": 12}), flush=True)
    summary = {}
    for arm in spec["test_arms"]:
        group = [r for r in rows if r["arm"] == arm]
        summary[arm] = {"documents": len(group), "merchant_groups": len({r["merchant_group"] for r in group}),
            "exact_match_by_field": {f: sum(r["field_exact"][f] for r in group)/len(group) for f in FIELDS},
            "macro_field_exact_match": sum(r["field_fraction"] for r in group)/len(group),
            "all_fields_document_rate": sum(r["document_exact"] for r in group)/len(group),
            "actual_OCR_calls": sum(r["actual_OCR_calls"] for r in group),
            "whole_wall_seconds": sum(r["whole_wall_seconds"] for r in group),
            "subprocess_CPU_seconds": sum(r["subprocess_CPU_seconds"] for r in group)}
    unchanged = all(sha(source/k) == v for k,v in source_pins.items()) and all(sha(p) == v for p,v in engine_pins.items())
    result = {"schema": "hepta.repair.natural.document.result.v1", "status": "completed", "gate": gate,
        "summary": summary, "source_and_model_unchanged": unchanged, "wall_seconds": (time.perf_counter_ns()-started)/1e9,
        "neural_parameter_updates": False, "general_complex_image_text_reasoning_proven": False,
        "native_neuron_integration": False, "all_blockers_closed": False, "source_scope": manifest["scope"]}
    save(output/"ROWS.json", rows)
    save(output/"RESULT.json", result)
    if not unchanged:
        raise ValueError("Frozen source or OCR model changed")
    print(json.dumps({"status": "completed", "gate": chosen["threshold"], "summary": summary}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.assets, args.output)
    except Exception as error:
        if args.output.exists():
            save(args.output/"FAILED.json", {"error": f"{type(error).__name__}: {error}", "partial_evidence_retained": True})
        raise
