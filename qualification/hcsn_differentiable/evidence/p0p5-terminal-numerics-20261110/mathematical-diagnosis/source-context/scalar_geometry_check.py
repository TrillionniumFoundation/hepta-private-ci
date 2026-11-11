"""One stdlib Gauss-node geometry check; no model, probability or oracle run."""

import ast
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "v8-local-validation/source/qualification/hcsn_differentiable/operator.py"
EXPECTED = "cb3eed1bcfbd3b10cc331a193a5d4b6a3d4309db899e0d8f821477f97b7dbdc1"


def main():
    started, cpu = time.monotonic(), time.process_time()
    payload = SOURCE.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == EXPECTED
    syntax = ast.parse(payload)
    function = next(n for n in syntax.body if isinstance(n, ast.FunctionDef) and n.name == "_gauss_legendre_unit")
    # Only this pinned standard-library function is compiled. The operator
    # module, Torch, all data/model loaders and probability routines stay unused.
    namespace = {"math": math, "lru_cache": lru_cache}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
    nodes, weights = namespace["_gauss_legendre_unit"](32)
    assert len(nodes) == 32 and all(0 < node < 1 for node in nodes)
    assert all(weight > 0 for weight in weights)
    width, sigma, phase_width = 4.8 / 256, .35, .2 / 16
    distance = width * min(nodes)
    crossover = distance**2 / sigma**2
    result = {
        "schema": "hcsn-short-time-node-geometry-v1",
        "scope": "Single q=32 source-node geometry calculation with named nominal sigma; no transition matrix, model, probability, oracle, pressure reproduction or parameter sweep.",
        "source": {"path": str(SOURCE), "bytes": len(payload), "sha256": EXPECTED},
        "function_source_sha256": hashlib.sha256(ast.get_source_segment(payload.decode(), function).encode()).hexdigest(),
        "quadrature_order": 32,
        "minimum_unit_node": min(nodes),
        "weights_sum": math.fsum(weights),
        "active_cell_width": width,
        "nominal_sigma_from_frozen_network_default": sigma,
        "nearest_source_node_distance_to_cell_edge": distance,
        "h_star_distance_squared_over_sigma_squared": crossover,
        "h_star_is_not_a_certified_quadrature_tolerance_threshold": True,
        "archived_pressure_step_geometry": [
            {"h": h, "h_over_h_star": h / crossover, "nearest_node_over_diffusion_length": distance / (sigma * math.sqrt(h))}
            for h in (1e-7, 8e-7)
        ],
        "pure_phase_nominal_geometry": {"width": phase_width, "number": 16, "delay": .2},
        "interpretation": "Neither archived positive gap lies in h much smaller than h_star for this nominal geometry. The fixed-node h-to-zero limit alone therefore does not identify those pressure failures. This ratio is not a quadrature-accuracy pass.",
        "source_after_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "prefix_wall_seconds": time.monotonic() - started,
        "prefix_own_CPU_seconds": time.process_time() - cpu,
        "cost_scope": "After imports through result construction, before JSON serialization and process exit; full manual/outer timing unknown.",
        "numerical_qualification_granted": False,
        "scientific_benefit_granted": False,
    }
    assert result["source_after_sha256"] == EXPECTED
    out = ROOT / "SCALAR-GEOMETRY.json"
    with out.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"path": str(out), "bytes": out.stat().st_size, "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "h_star": crossover, "geometry": result["archived_pressure_step_geometry"]}, sort_keys=True))


if __name__ == "__main__":
    main()
