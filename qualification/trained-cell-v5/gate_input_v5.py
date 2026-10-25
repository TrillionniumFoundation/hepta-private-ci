"""Bind actual frozen V5/V6 evidence to the exact converted native payloads.

This adapter never signs or accepts a candidate. Native code independently checks
the census, required completion, comparison family, aggregates and raw CPU ratios.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def build(run, protocol, report, converted, research_code, output, replay_audit=None, statistics_audit=None):
    root, protocol, report, converted, code, output = map(Path, (run, protocol, report, converted, research_code, output))
    sys.path.insert(0, str(code.resolve()))
    from cell_field_evaluate_v4 import verify_pre_label_seal

    verify_pre_label_seal(root, protocol)
    plan, evaluation = json.loads(protocol.read_bytes()), json.loads(report.read_bytes())
    conversion = json.loads((converted / "manifest.json").read_bytes())
    protocol_hash, report_hash = file_hash(protocol), file_hash(report)
    if (evaluation["protocol_sha256"] != protocol_hash or conversion["protocol_sha256"] != protocol_hash
            or conversion["schema"] != "hepta.trained-cell-parity-input.v5"
            or conversion["scientific_acceptance"] is not False or len(conversion["versions"]) != 2):
        raise ValueError("report or conversion binding mismatch")
    for index, name in enumerate(("predecessor", "candidate")):
        if conversion["versions"][index]["payload_sha256"] != file_hash(converted / f"{name}.bin"):
            raise ValueError("converted native payload changed")
    output.mkdir(parents=True, exist_ok=False)
    sources = {task: json.loads((root / task / "inputs.json").read_bytes())["input_hashes"] for task in plan["tasks"]}
    source_bytes = canonical(sources) + b"\n"
    (output / "source-datasets.json").write_bytes(source_bytes)
    definition = canonical({key: plan[key] for key in ("models", "mpc", "evaluation")})
    comparisons = {}
    for name, split, threshold in (("task", "future", -.001), ("retention", "old", 0.), ("total_cost", None, 3.)):
        frozen = {"group": name, "protocol_sha256": protocol_hash, "frozen_evaluation": plan["evaluation"],
            "aggregation": "maximum over every registered constituent; no missing values",
            "operator": "strict_less" if name == "task" else "less_equal", "threshold": threshold,
            "observation_unit": "paired timed seed runs per fixed ratio" if split is None else
                                "minimum distinct source components among constituent contrasts"}
        encoded = canonical(frozen)
        selected = (evaluation["cost_contrasts"] if split is None else
                    [row for row in evaluation["primary_contrasts"] if row["split"] == split])
        complete = (evaluation["census_complete"] and evaluation["cost_census_complete"]
                    and evaluation["required_completion_met"] and len(selected) == (8 if name == "task" else 4)
                    and all(row["status"] == "completed" for row in selected))
        if complete:
            upper = max(row["cpu_ratio"] if split is None else row["upper_bound"] for row in selected)
            estimate = upper if split is None else max(row["difference"] for row in selected)
            complete = math.isfinite(upper) and math.isfinite(estimate) and estimate <= upper
        measurement = ({"status": "measured", "upper_bound": upper, "estimate": estimate,
            "lower_bound": 0. if split is None else -710.,
            "observations": 3 if split is None else min(row["source_components"] for row in selected),
            "lower_bound_scope": "nonnegative measured CPU ratio" if split is None else
                                 "conservative NLL-difference support floor; not a bootstrap confidence endpoint"}
                       if complete else {"status": "unavailable"})
        comparisons[name] = {"definition_json": encoded.decode(), "comparison_sha256": hashlib.sha256(encoded).hexdigest(),
                             "evidence_sha256": report_hash, "measurement": measurement}
    gate = {"schema": "hepta.actual-typed-scientific-review-input.v5", "protocol_sha256": protocol_hash,
        "report_sha256": report_hash, "candidate_sha256": file_hash(converted / "candidate.bin"),
        "predecessor_sha256": file_hash(converted / "predecessor.bin"), "candidate_format": "hepta.trained-cell-bundle.v5",
        "conversion_manifest_sha256": file_hash(converted / "manifest.json"),
        "source_candidate_bundle_sha256": conversion["versions"][1]["source_bundle_sha256"],
        "source_predecessor_bundle_sha256": conversion["versions"][0]["source_bundle_sha256"],
        "candidate_definition_json": definition.decode(), "candidate_definition_sha256": hashlib.sha256(definition).hexdigest(),
        "comparisons": comparisons, "training_code_sha256": file_hash(root / "executed_source.json"),
        "runtime_sha256": file_hash(root / "run.json"), "source_dataset_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_dataset_definition_json": source_bytes.decode(),
        "pre_evaluation_seal_sha256": file_hash(root / "pre_evaluation_seal.json"),
        "all_registered_gates_met": evaluation["all_registered_gates_met"], "census_complete": evaluation["census_complete"],
        "cost_census_complete": evaluation["cost_census_complete"], "required_completion_met": evaluation["required_completion_met"],
        "production_authority": False, "trust_scope": "local research evidence adapter; no signature or production authority"}
    for kind, path in (("independent_replay", replay_audit), ("independent_statistics", statistics_audit)):
        if path is not None:
            gate[kind + "_sha256"] = file_hash(path)
    (output / "gate-input.json").write_bytes(canonical(gate) + b"\n")
    return gate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "protocol", "report", "converted", "research-code", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--replay-audit")
    parser.add_argument("--statistics-audit")
    result = build(**vars(parser.parse_args()))
    print(json.dumps({"all_registered_gates_met": result["all_registered_gates_met"],
                      "required_completion_met": result["required_completion_met"],
                      "measurements": {name: value["measurement"] for name, value in result["comparisons"].items()}}))
