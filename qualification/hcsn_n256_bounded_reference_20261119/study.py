"""One frozen authentic warm-1 bounded reference; old solvers are never called."""

from fractions import Fraction as F
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
import traceback

from inputs import archived_outputs, assemble, load_inputs, source_geometry_check
from interval import require, rounded_fraction, scalar_occupation, scaling_perturbation, uniformization
from targets import build, compare, encoded_fields


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CAP = 16*1024**2


def serializable(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, dict):
        return {k: serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    return value


def save(directory, name, value):
    payload = (json.dumps(serializable(value), sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
    current = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
    require(current+len(payload) <= CAP-65536, "artifact cap including finalization reserve")
    with (directory/name).open("xb") as stream:
        stream.write(payload)


def verify(frozen):
    require(platform.python_version() == frozen["python_version"], "frozen interpreter version")
    require(hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == frozen["python_executable_sha256"], "interpreter bytes")
    for name, record in frozen["files"].items():
        path = REPO/name
        require(path.stat().st_size == record["bytes"]
                and hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], "immutable file changed: "+name)


def operator_record(operator):
    return {"dimension": len(operator["scaled"]),
            "unscaled_rows": [[(j, str(v)) for j, v in sorted(row.items())] for row in operator["unscaled"]],
            "scaled_rows": [[(j, str(v)) for j, v in sorted(row.items())] for row in operator["scaled"]],
            "initial": [[str(v) for v in vector] for vector in operator["initial"]]}


def main(directory):
    started, cpu = time.perf_counter(), time.process_time()
    frozen = json.loads((HERE/"SOURCE_FREEZE.json").read_text())
    request = json.loads((HERE/"REQUEST.json").read_text())
    verify(frozen)
    require(sorted(os.sched_getaffinity(0)) == [7]
            and resource.getrlimit(resource.RLIMIT_AS) == (2**32, 2**32), "pre-import resource envelope")
    require(request["precision_bits"] == [256, 512, 768] and request["highest_series_index"] == 2048
            and request["maximum_reference_actions"] == 6, "fixed calculation roster")
    inputs = load_inputs(REPO)
    assembly = assemble(inputs)
    outputs = archived_outputs(REPO)
    geometry = source_geometry_check(assembly, outputs)
    save(directory, "INDEPENDENT_OPERATORS.json", {"operators": list(map(operator_record, assembly["operators"])),
        "input_geometry_check": geometry, "input_bundle_sha256": frozen["input_bundle_sha256"],
        "target": request["mathematical_target"], "duration": str(inputs["duration"]), "rho": str(inputs["rho"]),
        "active_original_upper": [str(v[-1]) for v in inputs["channels"]]})
    journal, actions, selected = [], 0, None
    for bits in request["precision_bits"]:
        action_outputs, receipts = [], []
        for index, operator in enumerate(assembly["operators"]):
            print(json.dumps({"kind": "reference_action_start", "ordinal": actions+1, "bits": bits, "dimension": len(operator["scaled"])}), flush=True)
            wall, action_cpu = time.perf_counter(), time.process_time()
            result, receipt = uniformization(operator["scaled"], operator["initial"], bits,
                    request["highest_series_index"], lambda row: print(json.dumps({"kind": "progress", **row}), flush=True))
            actions += 1
            receipt.update(wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-action_cpu,
                           ordinal=actions, scaled_rounding_perturbation=scaling_perturbation(
                               operator["unscaled"], operator["scaled"], inputs["duration"], operator["initial"], bits))
            save(directory, f"ACTION-{bits}-{index}.json", {"receipt": receipt,
                 "bounds": [[[str(a), str(b)] for a, b in vector] for vector in result]})
            action_outputs.append(result)
            receipts.append(receipt)
        occupation, scalar_receipt = scalar_occupation([v[-1] for v in inputs["channels"]], inputs["rho"], inputs["duration"], bits)
        fields, metadata = build(inputs, assembly, *action_outputs, occupation)
        report = compare(fields, metadata, outputs)
        widths = [hi-lo for field in fields for lo, hi in field["bounds"]]
        unique = sum(rounded_fraction(lo) == rounded_fraction(hi) for field in fields for lo, hi in field["bounds"])
        level = {"bits": bits, "reference_actions_so_far": actions, "unique_rounding_coordinates": unique,
                 "complete_coordinates": 69728, "maximum_interval_width": max(widths),
                 "width_gate": max(widths) <= F(1, 2**120), "all_coordinates_unique": unique == 69728,
                 "comparisons": report, "initial_upper_scalar": scalar_receipt, "reference_actions": receipts}
        save(directory, f"LEVEL-{bits}.json", level)
        journal.append(level)
        selected = fields, metadata, level
        if level["width_gate"] and level["all_coordinates_unique"]:
            break
    fields, metadata, final = selected
    save(directory, "REFERENCE_COORDINATES.json", {"packet_metadata": metadata, "fields": encoded_fields(fields),
        "all_coordinate_denominator": 69728, "correct_rounding_proven_for_all": final["all_coordinates_unique"],
        "zero_intervals_not_clipped": True, "global_enclosure_semantics": "Exact real target intervals; static point tensors are independently assembled exact binary64 values."})
    result = {"schema": "hcsn-n256-bounded-warm1-reference-result-v1", "identity": request["identity"],
        "status": "ENCLOSURES_COMPLETE_BOUNDED_FINITE_MATRIX_ERROR" if final["width_gate"] else "ENCLOSURE_WIDTH_UNRESOLVED",
        "all_coordinates_unique_rounding": final["all_coordinates_unique"],
        "precision_levels_used": [r["bits"] for r in journal], "reference_actions": actions,
        "model_calls": 0, "candidate_calls": 0, "dense_oracle_calls": 0, "optimizer_calls": 0,
        "independent_geometry_check": geometry, "final_level": final,
        "mathematical_target": request["mathematical_target"], "proof_components": request["proof_components"],
        "old_sparse_dense_bitwise_mismatches": 1291, "old_sparse_dense_bitwise_gate": "RED_UNCHANGED",
        "original_full_roster_admission": False, "continuum_qualification": False,
        "all_closed": False, "body_wall_seconds_before_final_write": time.perf_counter()-started,
        "body_cpu_seconds_before_final_write": time.process_time()-cpu,
        "cost_scope": "body includes source/input checks, independent assembly, reference actions and prior evidence writes; excludes Python imports and final result serialization/exit, charged by parent separately"}
    verify(frozen)
    save(directory, "RESULT.json", result)
    print(json.dumps({"kind": "terminal", "status": result["status"], "reference_actions": actions,
                      "precision_levels": result["precision_levels_used"], "unique": final["unique_rounding_coordinates"]}), flush=True)
    return 0 if final["width_gate"] else 2


if __name__ == "__main__":
    output = Path(sys.argv[1])
    try:
        raise SystemExit(main(output))
    except Exception as error:
        traceback.print_exc()
        save(output, "FAILURE.json", {"type": type(error).__name__, "message": str(error),
                                     "traceback": traceback.format_exc(), "all_closed": False})
        raise SystemExit(1)
