"""A single fixed-model, fixed-N replication against original strong rules."""
import argparse
from pathlib import Path
import time

import numpy as np

from ...continuation_20261027.natural.document_engine import deliver, episode, ocr
from ...continuation_20261027.natural.document_study import score
from .common import cpu_now, freeze, read, save, sha, verify_frozen
from .document_model import options, select


def analyze(rows, protocol):
    identities = sorted({r["id"] for r in rows})
    metrics = ["quality", "field_exact", "cpu_seconds", "wall_seconds", "cost_adjusted_return"]
    differences, summaries = [], {}
    source_rows = []
    for identity in identities:
        selected = [r for r in rows if r["id"] == identity]
        paired = {}
        for arm in protocol["arms"]:
            current = [r for r in selected if r["arm"] == arm]
            if len(current) != 2 or current[0]["answers"] != current[1]["answers"]:
                raise ValueError("Incomplete or nonidentical fixed-model repetition")
            paired[arm] = {key: float(np.mean([r[key] for r in current])) for key in metrics}
        differences.append([paired["rule_residual"][key] - paired["original_rules"][key] for key in metrics])
        source_rows.append({"id": identity, "merchant_group": selected[0]["merchant_group"],
            "upstream_split": selected[0]["upstream_split"], "arms": paired})
    for arm in protocol["arms"]:
        summaries[arm] = {key: float(np.mean([r["arms"][arm][key] for r in source_rows])) for key in metrics}
    matrix = np.asarray(differences)
    configuration = protocol["bootstrap"]
    random = np.random.default_rng(configuration["seed"])
    bootstrap = matrix[random.integers(len(matrix), size=(configuration["draws"], len(matrix)))].mean(1)
    intervals = np.quantile(bootstrap, [configuration["lower_quantile"], configuration["upper_quantile"]], axis=0)
    contrasts = {key: {"difference": float(matrix[:, i].mean()), "CI97_5": intervals[:, i].tolist()}
        for i, key in enumerate(metrics)}
    subgroup = {}
    for split in sorted({r["upstream_split"] for r in source_rows}):
        selected = [r for r in source_rows if r["upstream_split"] == split]
        subgroup[split] = {"merchants": len(selected), "quality_difference": float(np.mean([
            r["arms"]["rule_residual"]["quality"] - r["arms"]["original_rules"]["quality"] for r in selected])),
            "role": "descriptive, not a separately selected acceptance test"}
    return {"summary": summaries, "primary_contrast": contrasts, "upstream_subgroups": subgroup,
        "independent_normalized_merchants": len(identities), "actual_output_pairs": len(rows),
        "strong_rules_replication_gate_passed": bool(contrasts["cost_adjusted_return"]["CI97_5"][0] > 0),
        "changed_fields_per_repetition": sum(not d["rule_preserved"] for r in rows
            if r["arm"] == "rule_residual" and r["repetition"] == 0 for d in r["decisions"]),
        "observed_reference_fields_per_repetition": sum(r["observed_reference_fields"] for r in rows
            if r["arm"] == "rule_residual" and r["repetition"] == 0),
        "old24_primary_result_pooled": False, "model_refitted": False}


def run(assets, model_path, first_qualification, output):
    source = Path(__file__).parent
    protocol = read(source / "DOCUMENT_REPLICATION_PROTOCOL.json")
    manifest, frozen = read(assets / "MANIFEST.json"), read(model_path)
    if sha(source / "DOCUMENT_REPLICATION_PROTOCOL.json") != manifest["protocol_sha256"]:
        raise ValueError("Replication protocol changed after source freeze")
    if sha(model_path) != sha(first_qualification / "FROZEN_MODEL.json"):
        raise ValueError("Replication changed a previously frozen parameter or validation choice")
    if frozen["choice"]["regularization"] != 100. or frozen["choice"]["threshold"] != .1:
        raise ValueError("Replication cannot retune the original model")
    original_registration = read(first_qualification / "FROZEN_REGISTRATION.json")
    original_model_source = next(r["sha256"] for r in original_registration["source_files"] if Path(r["path"]).name == "document_model.py")
    if sha(source / "document_model.py") != original_model_source:
        raise ValueError("Residual inference code changed since the first qualification")
    if len(manifest["documents"]) != manifest["actual_N"]:
        raise ValueError("Frozen source count differs")
    for row in manifest["files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Replication source changed")
    output.mkdir(parents=True, exist_ok=False)
    registration = freeze(source, assets / "MANIFEST.json", output, protocol,
        {"exact_N": manifest["actual_N"], "ordered_source_ids": [r["id"] for r in manifest["documents"]],
        "model_sha256": sha(model_path), "residual_source_sha256": original_model_source,
        "old_qualification_sha256": sha(first_qualification / "RESULT.json"),
        "upstream_split_counts": manifest["upstream_split_counts"], "additional_replications_permitted": 0})
    save(output / "FROZEN_MODEL.json", frozen)
    rows = []
    for repetition in range(protocol["timing_repetitions"]):
        for index, document in enumerate(manifest["documents"]):
            rotation = (index + repetition) % 2
            order = protocol["arms"][rotation:] + protocol["arms"][:rotation]
            for arm in order:
                destination = output / "test" / f"repeat-{repetition}" / document["id"] / arm
                if arm == "original_rules":
                    public = episode(document["path"], None, "original_rules", 0., destination)
                else:
                    destination.mkdir(parents=True, exist_ok=False)
                    wall, cpu = time.perf_counter(), cpu_now()
                    observed = ocr(document["path"], destination / "first")
                    selected, decisions = select(options(observed), frozen["model"], .1)
                    delivered = deliver(document["path"], selected, destination)
                    public = {**delivered, "decisions": decisions, "actual_OCR_calls": 1,
                        "output_directory": str(destination), "whole_cpu_seconds": cpu_now() - cpu,
                        "whole_wall_seconds": time.perf_counter() - wall}
                    save(destination / "PUBLIC_RESULT.json", public)
                row = {**public, "id": document["id"], "merchant_group": document["merchant_group"],
                    "upstream_split": document["upstream_split"], "arm": arm, "repetition": repetition,
                    **score(document["reference"], public["answers"]), "cpu_seconds": public["whole_cpu_seconds"],
                    "wall_seconds": public["whole_wall_seconds"], "scored_ns": time.time_ns()}
                row["cost_adjusted_return"] = row["quality"] - .01 * row["cpu_seconds"]
                rows.append(row)
            if (index + 1) % 16 == 0:
                print({"replication_repetition": repetition, "completed": index + 1,
                    "fixed_N": len(manifest["documents"]), "interim_metrics_not_printed": True}, flush=True)
    result = {"schema": "hepta.ndu.closure-v2.natural.document.replication.result.v1", "status": "completed",
        **analyze(rows, protocol), "frozen_registration_sha256": sha(output / "FROZEN_REGISTRATION.json"),
        "source_manifest_sha256": sha(assets / "MANIFEST.json"), "model_sha256": sha(model_path)}
    save(output / "ROWS.json", rows)
    save(output / "RESULT.json", result)
    verify_frozen(registration)
    print(result, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "model", "first-qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.model, args.first_qualification, args.output)
