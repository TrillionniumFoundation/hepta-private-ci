"""Negative conversion qualification against an explicitly supplied real archive."""

import argparse
import copy
import json
from pathlib import Path
import sys

import numpy as np

from export_v5 import convert, sha


def check(bundle, protocol, features, research_code):
    bundle, protocol, features, code = map(Path, (bundle, protocol, features, research_code))
    source = json.loads(bundle.read_bytes())
    plan = json.loads(protocol.read_bytes())
    protocol_hash = sha(protocol.read_bytes())
    reports = {task: json.loads((features / task / "report.json").read_bytes()) for task in plan["tasks"]}
    sys.path.insert(0, str(code.resolve()))
    from cell_field_state import _array_digest

    def invoke(value):
        return convert(value, "all12-typed-candidate-v5", 2, code, protocol_hash, plan, reports)

    invoke(source)
    changed = []
    value = copy.deepcopy(source)
    value["fits"][0]["tensors"]["theta__W"]["values"][0][0] += 0.125
    changed.append(("tensor_bytes_without_updated_commitment", value))
    value = copy.deepcopy(value)
    value["fits"][0]["checkpoint_manifest"]["tensor_sha256"]["theta__W"] = _array_digest(
        np.asarray(value["fits"][0]["tensors"]["theta__W"]["values"], dtype=np.float64))
    changed.append(("tensor_rehashed_without_complete_state_commitment", value))
    value = copy.deepcopy(source)
    value["fits"][0]["checkpoint_manifest"]["rng"]["state"]["state"] += 1
    changed.append(("rng_state_drift", value))
    value = copy.deepcopy(source)
    value["fits"][0]["checkpoint_manifest"]["step_count"] += 1
    changed.append(("optimizer_clock_drift", value))
    value = copy.deepcopy(source)
    value["fits"][0]["checkpoint_manifest"]["bindings"]["executed_code_sha256"]["cell_learning_models.py"] = "1" * 64
    changed.append(("executed_reference_source_mismatch", value))
    value = copy.deepcopy(source)
    value["fits"][0] = value["fits"][1]
    changed.append(("duplicate_fit_and_missing_fit", value))
    value = copy.deepcopy(source)
    value["fits"].pop()
    changed.append(("missing_registered_fit", value))
    value = copy.deepcopy(source)
    value["projection"][0][0] = float("nan")
    changed.append(("nonfinite_projection", value))
    value = copy.deepcopy(source)
    value["fits"][0]["checkpoint_manifest"]["head"]["mode"] = "residual"
    changed.append(("unsupported_head_semantics", value))
    result = []
    for name, value in changed:
        try:
            invoke(value)
        except ValueError as error:
            result.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise AssertionError(f"mutated archive accepted: {name}")
    return {"schema": "hepta.typed-conversion-negative-qualification.v5",
            "source_bundle_sha256": sha(bundle.read_bytes()), "protocol_sha256": protocol_hash,
            "valid_all12_conversion_passed": True, "negative_cases": result,
            "production_authority": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "protocol", "features", "research-code"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(check(**vars(parser.parse_args())), sort_keys=True, indent=2))
