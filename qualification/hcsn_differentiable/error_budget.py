"""Measure independently declared QPR approximation budgets against analytic U.

Run with --output NEW.json. A missed budget returns 1, a blocked/invalid run
returns 2. No limit is fitted to the observed result. Refinement deltas are
sensitivity measurements, not a proof that their sum bounds total error.
"""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import traceback


def sources(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()
            and p.suffix in (".py", ".json", ".md")
            and "evidence" not in p.relative_to(root).parts
            and "__pycache__" not in p.parts}


def measure(spec):
    import torch
    from .contract import GridSpec, PhysicalParameters
    from .operator import DifferentiableDistributionOperator
    from .regenerative import _decay, basis_perpetual_value, perpetual_value
    from .value import perpetual_basis_value

    grid = GridSpec(**spec["grid"])
    dt = spec["duration"]
    variants = {
        "baseline": (grid, dt),
        "space": (replace(grid, active_cells=2 * grid.active_cells), dt),
        "phase": (replace(grid, phase_cells=2 * grid.phase_cells), dt),
        # Extend L at the same dx; preserve the exponential-tail rate.
        "tail": (replace(grid, endpoint=1.5 * grid.endpoint,
                         active_cells=3 * grid.active_cells // 2), dt),
        "time": (grid, dt / 2),
        "quadrature": (replace(grid, quadrature_order=64), dt),
    }
    rows = []
    for fixture in spec["fixtures"]:
        fixture_dt = fixture.get("duration", dt)
        fixture_variants = {label: (geometry, fixture_dt / 2 if label == "time" else fixture_dt)
                            for label, (geometry, _) in variants.items()}
        params = PhysicalParameters(*(torch.tensor(v, dtype=torch.float64) for v in
                                      (0.0, fixture["mu"], fixture["sigma"],
                                       math.exp(fixture["reset_margin"]), fixture["discount"])))
        # Exact exponential moment of the common conditioned Gaussian prior.
        decay = _decay(params)
        mean, std = fixture["initial_margin"], grid.initial_log_std
        log_g = (-decay * mean + 0.5 * (decay * std).square()
                 + torch.special.log_ndtr((mean - decay * std * std) / std)
                 - torch.special.log_ndtr(params.mu.new_tensor(mean / std)))
        g = torch.exp(log_g)
        reset = perpetual_value(fixture["reset_margin"], params, refractory=grid.refractory)
        reference = (0.4 * -torch.expm1(log_g) / params.discount + g
                     + g * torch.exp(-params.discount * grid.refractory) * reset.reset_value)
        scale = max(1.0, abs(float(reference)))
        values = {}
        for label, (geometry, duration) in fixture_variants.items():
            operator = DifferentiableDistributionOperator(geometry)
            prior = operator.initial_probability(math.exp(mean), params.log_boundary)
            result = perpetual_basis_value(operator, params, duration)
            basis_reference = prior @ basis_perpetual_value(geometry, params)
            table = operator(*params.tensors()[:4], duration, params.discount)
            value = float(prior @ result.value)
            values[label] = {
                "grid": asdict(geometry), "duration": duration,
                "projected_value": value, "continuum_value_of_reconstructed_prior": float(basis_reference),
                "initial_projection_error": float(basis_reference - reference),
                "combined_scaled_error": abs(value - float(reference)) / scale,
                "linear_solve_residual_estimate": float(result.residual_error_estimate),
                "probability_mass_error": float((table.matrix.sum(-1) - 1).abs().max()),
            }
        base = values["baseline"]
        observations = {"combined_value_error": base["combined_scaled_error"],
                        "linear_solve_residual_estimate": max(v["linear_solve_residual_estimate"] for v in values.values()),
                        "probability_mass_error": max(v["probability_mass_error"] for v in values.values())}
        for label in ("space", "phase", "tail", "time", "quadrature"):
            observations[label + "_refinement_delta"] = abs(values[label]["projected_value"] - base["projected_value"]) / scale
        gates = {name: {"observed": observed, "limit": spec["limits"][name],
                        "passed": math.isfinite(observed) and observed <= spec["limits"][name]}
                 for name, observed in observations.items()}
        rows.append({"fixture": fixture, "continuum_reference": float(reference),
                     "variants": values, "gates": gates,
                     "status": "passed" if all(g["passed"] for g in gates.values()) else "failed"})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output exists; retain old attempts and use a fresh path")
    root = Path(__file__).resolve().parent
    spec = json.loads((root / "error_budget.json").read_text())
    before, started = sources(root), time.perf_counter()
    report = {"schema": "hcsn-fixed-policy-error-budget-result-v1", "budget": spec,
              "source_before": before, "started_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "device": "cpu", "formal_fits_started": 0,
              "certified_bound": False, "physical_energy_joules": None,
              "claim": "Declared common-prior, perpetual fixed-policy CPU fixtures only."}
    code = 2
    try:
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        report["torch"] = torch.__version__
        with torch.no_grad():
            report["fixtures"] = measure(spec)
        passed = bool(report["fixtures"]) and all(r["status"] == "passed" for r in report["fixtures"])
        report["status"] = "passed" if passed else "failed"
        code = 0 if passed else 1
    except ImportError as error:
        report.update(status="blocked", detail=str(error))
    except Exception:
        report.update(status="error", detail=traceback.format_exc())
    finally:
        report.update(source_after=sources(root), wall_seconds=time.perf_counter() - started,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        if not report["source_unchanged"]:
            report["status"], code = "source_changed", 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
