"""Actual read-back document qualification under the frozen residual policy."""
import argparse
from pathlib import Path
import time

from ...continuation_20261027.natural.document_decoder import FieldDecoder
from ...continuation_20261027.natural.document_engine import episode, ocr, deliver
from ...continuation_20261027.natural.document_study import score
from .common import cpu_now, freeze, read, save, sha, summarize_quality, verify_frozen
from .document_model import options, select


def run(assets, model_path, old_model_path, output):
    source = Path(__file__).parent
    spec = read(source / "DOCUMENT_PROTOCOL.json")
    manifest, frozen = read(assets / "MANIFEST.json"), read(model_path)
    if manifest["protocol_sha256"] != sha(source / "DOCUMENT_PROTOCOL.json"):
        raise ValueError("Protocol changed after new source selection")
    for row in manifest["files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Document source identity differs")
    output.mkdir(parents=True, exist_ok=False)
    registration = freeze(source, assets / "MANIFEST.json", output, spec,
        {"frozen_model_sha256": sha(model_path), "old_model_sha256": sha(old_model_path)})
    save(output / "FROZEN_MODEL.json", frozen)
    (output / "OLD_MODEL.npz").write_bytes(old_model_path.read_bytes())
    old = FieldDecoder.load(output / "OLD_MODEL.npz")
    rows = []
    old_arms = {"original_rules": "original_rules", "old_learned_base": "learned_base", "old_all_refine": "learned_all_refine"}
    for repetition in range(spec["timing_repetitions"]):
        for index, document in enumerate(manifest["documents"]):
            rotation = (index + repetition) % len(spec["test_arms"])
            arms = spec["test_arms"][rotation:] + spec["test_arms"][:rotation]
            for arm in arms:
                destination = output / "test" / f"repeat-{repetition}" / document["id"] / arm
                if arm == "rule_residual":
                    destination.mkdir(parents=True, exist_ok=False)
                    wall, cpu = time.perf_counter(), cpu_now()
                    observed = ocr(document["path"], destination / "first")
                    selected, decisions = select(options(observed), frozen["model"], frozen["choice"]["threshold"])
                    delivered = deliver(document["path"], selected, destination)
                    public = {**delivered, "decisions": decisions, "actual_OCR_calls": 1,
                        "output_directory": str(destination), "whole_cpu_seconds": cpu_now() - cpu,
                        "whole_wall_seconds": time.perf_counter() - wall}
                    save(destination / "PUBLIC_RESULT.json", public)
                else:
                    public = episode(document["path"], old, old_arms[arm], 0., destination)
                rows.append({**public, "id": document["id"], "merchant_group": document["merchant_group"],
                    "arm": arm, "repetition": repetition, **score(document["reference"], public["answers"]),
                    "cpu_seconds": public["whole_cpu_seconds"], "wall_seconds": public["whole_wall_seconds"],
                    "scored_ns": time.time_ns()})
                rows[-1]["cost_adjusted_return"] = rows[-1]["quality"] - .01 * rows[-1]["cpu_seconds"]
            print({"document_repetition": repetition, "completed": index + 1}, flush=True)
    keys = ["quality", "field_exact", "cpu_seconds", "wall_seconds", "cost_adjusted_return"]
    result = summarize_quality(rows, spec["test_arms"], keys, "merchant_group",
        [("rule_residual", arm) for arm in spec["test_arms"] if arm != "rule_residual"])
    strong = result["comparisons"]["rule_residual__minus__original_rules"]
    refinement = result["comparisons"]["rule_residual__minus__old_all_refine"]
    result.update(schema="hepta.ndu.closure-v2.natural.document.result.v1", status="completed",
        strong_baseline_gate_passed=bool(strong["cost_adjusted_return"]["CI95"][0] > 0),
        quality_cost_gate_passed=bool(refinement["quality"]["CI95"][0] >= -.02
            and refinement["cpu_seconds"]["CI95"][1] < 0 and refinement["wall_seconds"]["CI95"][1] < 0),
        original_Hepta_neuron_integrated=False, actual_deliveries=len(rows),
        changed_test_fields=sum(not d["rule_preserved"] for r in rows if r["arm"] == "rule_residual" for d in r["decisions"]),
        observed_reference_fields_per_repetition=sum(r["observed_reference_fields"] for r in rows
            if r["arm"] == "rule_residual" and r["repetition"] == 0))
    save(output / "ROWS.json", rows)
    save(output / "RESULT.json", result)
    verify_frozen(registration)
    print(result, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--old-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.model, args.old_model, args.output)
