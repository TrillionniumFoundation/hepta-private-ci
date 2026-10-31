"""Resolve the recorded upwind sigma-gradient error by one grid refinement.

Retains the original failed record and thresholds. No new fitted-grid claim is
made by this extension; the original fitted results remain independently named.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .renewal_resolution import METRICS, PROTOCOL, finite_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = json.loads(args.baseline.read_text())
    source = Path(__file__).parent
    if previous["protocol"] != PROTOCOL:
        raise ValueError("Original refinement protocol changed")
    for name, sha in previous["source_sha256"].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != sha:
            raise ValueError("Original refinement source changed: "+name)
    last = max((r for r in previous["rows"] if r["scheme"] == "upwind"), key=lambda r:r["intervals"])
    protocol = dict(baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        reason="The registered n=576 upwind sigma-gradient error exceeded 0.005",
        previous_intervals=last["intervals"], new_intervals=2*last["intervals"],
        maximum_final_error=PROTOCOL["maximum_final_error"]["upwind"],
        minimum_last_order=PROTOCOL["minimum_last_order"]["upwind"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_name(args.output.stem+"_protocol.json").open("x") as stream:
        json.dump(protocol, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    cpu = time.process_time()
    values = finite_count(PROTOCOL["parameters"], protocol["new_intervals"], "upwind")
    errors = {k:abs(values[k]-previous["reference"][k]) for k in METRICS}
    order = {k:float(np.log2(last["absolute_error"][k]/errors[k])) for k in METRICS}
    gates = dict(all_errors_decrease=all(errors[k] < last["absolute_error"][k] for k in METRICS),
        observed_order=min(order.values()) >= protocol["minimum_last_order"],
        final_accuracy=max(errors.values()) < protocol["maximum_final_error"])
    result = dict(schema="hcsn_round8_renewal_resolution_extension_v1", protocol=protocol,
        passed=all(gates.values()), gates=gates, values=values, absolute_error=errors,
        observed_order=order, process_cpu_seconds=time.process_time()-cpu,
        original_result_passed=previous["passed"], original_result_not_replaced=True,
        source_sha256={**previous["source_sha256"],
            Path(__file__).name:hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        limitations=previous["limitations"])
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
