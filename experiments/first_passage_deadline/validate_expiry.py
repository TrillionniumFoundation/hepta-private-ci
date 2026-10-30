"""Post-failure diagnostic; never replaces the original failed endpoint gate."""

import argparse
import json
from pathlib import Path
import time
import traceback

import numpy as np

from experiments.first_passage_operator.free_boundary import NaturalSpikeSpec
from .expiry import continuum_first_layer, lattice_first_layer
from .qvi import solve_deadline
from .validate import PACKAGE, digest, source_manifest, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("the diagnostic needs a new empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    protocol_file = PACKAGE / "EXPIRY_DIAGNOSTIC_PROTOCOL.json"
    protocol = json.loads(protocol_file.read_text())
    sources = source_manifest()
    write_json(output / "SOURCE_MANIFEST.json", sources)
    write_json(output / "PROTOCOL_COPY.json", protocol)
    started = time.monotonic()
    report = {"schema": "hepta.expiry-diagnostic-result.v1", "status": "running",
              "protocol_sha256": digest(protocol_file), "rows": [], "gates": [],
              "chronology": protocol["chronology"],
              "original_result": "91/92 predeclared gates; unchanged",
              "mathematics": {
                  "continuum": "Match u and u_x at strike and free boundary for (1+q*dt)u-(sigma^2*dt/2)u_xx=g. This gives exp(-z)=q*dt*(z-1), z=kappa*(b-c).",
                  "lattice": "Geometric homogeneous solutions plus exact linear particular solution give the least J with rho^(-J)<=q*dt*(J*(rho-1)-1).",
                  "limit": "LambertW(y)=log(y)-log(log(y))+o(1), so b-c tends to zero with leading sqrt(dt)*log(1/dt). The rejected fixed sqrt(dt) envelope is not valid for this implicit first layer.",
                  "scope": "An implicit time layer is a resolvent obstacle problem, not the true finite-horizon stopping problem at that time."
              }}

    def gate(name, value, limit):
        report["gates"].append({"name": name, "observed": float(value),
                                "limit": float(limit), "passed": bool(value <= limit)})

    try:
        spec = NaturalSpikeSpec(**protocol["spec"])
        for index, grid in enumerate(protocol["grids"]):
            solution = solve_deadline(spec, grid["dt"], **grid)
            exact = lattice_first_layer(spec, grid["dt"], grid["dx"], solution.state)
            continuum = continuum_first_layer(spec, grid["dt"], [spec.spike_cost])
            lcp_index = round((solution.boundaries[1] - spec.spike_cost) / grid["dx"])
            value_error = float(np.max(np.abs(exact["value"] - solution.values[1])))
            row = {"grid": grid, "lcp_boundary": float(solution.boundaries[1]),
                   "lattice_boundary": exact["boundary"],
                   "continuum_implicit_boundary": continuum["boundary"],
                   "continuum_vs_lattice_difference": abs(continuum["boundary"] - exact["boundary"]),
                   "lcp_value_error": value_error,
                   "oracle": {k: v for k, v in exact.items() if k != "value"}}
            report["rows"].append(row)
            gate(f"level{index}.exact_lattice_boundary", abs(lcp_index - exact["index_from_strike"]), 0)
            gate(f"level{index}.lcp_value", value_error, protocol["gates"]["lcp_first_layer_value_error_max"])
            gate(f"level{index}.lattice_complementarity", exact["complementarity_residual"],
                 protocol["gates"]["oracle_lattice_complementarity_residual_max"])
            gate(f"level{index}.continuum_root", abs(continuum["root_residual"]),
                 protocol["gates"]["continuum_root_residual_max"])
            gate(f"level{index}.lower_boundary_classification", int(not exact["finite_lower_cannot_change_boundary"]), 0)
            print(json.dumps({"level": index, "boundary": row["lcp_boundary"],
                              "oracle": row["lattice_boundary"], "value_error": value_error}), flush=True)
            write_json(output / "RESULTS.json", report)
        if source_manifest() != sources:
            raise RuntimeError("diagnostic source changed during the run")
        report["status"] = "passed supplementary diagnostic only" if all(g["passed"] for g in report["gates"]) else "failed supplementary diagnostic"
        return 0 if report["status"].startswith("passed") else 1
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        traceback.print_exc()
        return 1
    finally:
        report["seconds"] = time.monotonic() - started
        write_json(output / "RESULTS.json", report)
        print(json.dumps({"status": report["status"], "seconds": report["seconds"]}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
