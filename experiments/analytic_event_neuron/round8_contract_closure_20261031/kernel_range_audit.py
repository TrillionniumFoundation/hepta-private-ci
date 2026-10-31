"""Post-freeze numerical range audit; never trains or changes a candidate.

For width L, a drift tilt is bounded by exp(abs(mu)*L/sigma**2). Each omitted
Gaussian image integral is bounded by a normal tail. Mills' inequality and a
geometric tail bound give 4*tilt*phi(a)/(a*(1-r)), r=exp(-a*h-h*h/2), h=2L/s.
For killed-bin total L1, a=2*M*L/s; for each exit CDF, a=(2*M+1)*L/s.
These are exact-arithmetic truncation bounds, not floating-point error bounds.
Requires mpmath, whose actual runtime version is recorded independently.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import mpmath as mp
import numpy as np
import torch

from ..round7.model import load_model
from .kernels import brownian_first_exit, brownian_killed_bins


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def truncation_log10_bounds(boundary, sigma, max_abs_drift, dt=1., terms=12):
    length, scale = 2 * boundary, sigma * math.sqrt(dt)
    step = 2 * length / scale
    result = {}
    for name, distance in (("killed_bins_total_l1", 2 * terms), ("each_exit_cdf", 2 * terms + 1)):
        a = distance * length / scale
        log_bound = (math.log(4.) + max_abs_drift * length / sigma**2 - a*a/2
                     - math.log(2 * math.pi)/2 - math.log(a)
                     - math.log(-math.expm1(-a*step-step*step/2)))
        result[name] = log_bound / math.log(10.)
    return result


def mp_row(x, edges, mu, sigma, boundary, terms=12):
    """Independent 80-digit evaluation of the same analytic image formula.

    This diagnoses arithmetic; independence of the analytic formula itself is
    supplied by kernel_audit.py's spectral-density quadrature and flux checks.
    """
    x, mu, sigma, boundary = map(mp.mpf, (x, mu, sigma, boundary))
    edges = list(map(mp.mpf, edges))
    width, u = 2 * boundary, x + boundary
    cdf = lambda z: mp.erfc(-z / mp.sqrt(2)) / 2

    def interval(a, b):
        return cdf(-a) - cdf(-b) if a >= 0 else cdf(b) - cdf(a)

    bins = []
    for low, high in zip(edges[:-1], edges[1:]):
        total = mp.mpf(0)
        for k in range(-terms, terms + 1):
            mean1, mean2 = u - 2*k*width + mu, -u - 2*k*width + mu
            first = mp.exp(-2*mu*k*width/sigma**2) * interval((low+boundary-mean1)/sigma, (high+boundary-mean1)/sigma)
            second = mp.exp(-2*mu*(u+k*width)/sigma**2) * interval((low+boundary-mean2)/sigma, (high+boundary-mean2)/sigma)
            total += first - second
        bins.append(float(total))

    def lower_exit(start, drift):
        total = mp.mpf(0)
        for k in range(-terms, terms + 1):
            d = start + 2*k*width
            distance = abs(d)
            f = cdf((-distance-drift)/sigma) + mp.exp(-2*drift*distance/sigma**2) * cdf((-distance+drift)/sigma)
            total += mp.sign(d) * mp.exp(drift*(distance-start)/sigma**2) * f
        return float(total)

    return np.array(bins + [lower_exit(boundary-x, -mu), lower_exit(x+boundary, mu)])


@torch.no_grad()
def audit(here):
    torch.set_num_threads(1)
    mp.mp.dps = 80
    started = time.perf_counter()
    freeze = json.loads((here / "FREEZE.json").read_text())
    summary_path = here / "evidence/contract_exchange_v1/summary.json"
    raw_path = here / "evidence/contract_exchange_v1/state_records.jsonl.gz"
    summary = json.loads(summary_path.read_text())
    with gzip.open(raw_path, "rt") as stream:
        raw = {r["case"]: r for r in map(json.loads, stream)}
    frozen = {}
    for name in ("kernels.py", "kernel_audit.py", "control_exchange.py", "../round7/dynamics.py", "../round7/model.py"):
        digest = sha(here / name)
        if freeze["files"].get(name) != digest:
            raise ValueError(("frozen source mismatch", name))
        frozen[name] = digest
    records = []
    for row in summary["cases"]:
        if row["law"] != "r8-brownian-images-v1" or row["contract"] != "first_passage":
            continue
        path = here.parent / "round7/evidence/fits_primary" / f"{row['anchor_mode']}_none_{row['fit_seed']}.json"
        if sha(path) != row["anchor_sha256"]:
            raise ValueError("anchor identity changed")
        model, _ = load_model(path)
        p = model.core.physical_parameters()
        sigma, boundary = p["diffusion"], p["boundary"]
        grid, edges = model.core.active_grid(), boundary * model.core.normalised_edges
        drive = torch.tensor(raw[row["case"]]["drive"], dtype=torch.float64)
        if len(drive) != summary["public_states"] or bool(torch.any(drive.abs() > 1.5)):
            raise ValueError("unexpected public-drive range")
        prefix = row["case"].split("__")[0]
        for other in raw.values():
            if other["case"].startswith(prefix + "__") and other["drive"] != drive.tolist():
                raise ValueError("shared anchor did not retain identical content drive")
        errors = {str(order): 0. for order in (8, 12, 16)}
        mass_error, minimum = 0., 1.
        for offset in range(0, len(drive), 32):
            x, mu = torch.broadcast_tensors(grid[None, :], drive[offset:offset+32, None])
            rows = {}
            for order in (8, 12, 16, 24):
                active = brownian_killed_bins(x, edges, mu, sigma, 1., boundary, image_terms=order)
                events = brownian_first_exit(x, mu, sigma, 1., boundary, image_terms=order)
                rows[order] = torch.cat((active, events), -1)
            for order in (8, 12, 16):
                errors[str(order)] = max(errors[str(order)], float((rows[order] - rows[24]).abs().max()))
            mass_error = max(mass_error, float((rows[12].sum(-1)-1).abs().max()))
            minimum = min(minimum, float(rows[12].min()))
        probes = []
        for source, state_index in ((0, int(drive.argmin())), (model.n_grid//2, int(drive.abs().argmin())),
                                    (model.n_grid-1, int(drive.argmax()))):
            x, mu = grid[source], drive[state_index]
            actual = torch.cat((brownian_killed_bins(x, edges, mu, sigma, 1., boundary),
                                brownian_first_exit(x, mu, sigma, 1., boundary))).numpy()
            reference = mp_row(float(x), edges.tolist(), float(mu), float(sigma), float(boundary))
            probes.append({"source_index": source, "public_state_index": state_index, "x": float(x), "drift": float(mu),
                           "maximum_absolute_error": float(np.abs(actual-reference).max()),
                           "actual_row": actual.tolist(), "mpmath_80_digit_row_rounded_to_f64": reference.tolist()})
        records.append({"anchor": prefix, "checkpoint_sha256": row["anchor_sha256"], "public_states": len(drive),
                        "active_sources": model.n_grid, "row_cases": len(drive)*model.n_grid,
                        "sigma": float(sigma), "boundary": float(boundary), "drive_min": float(drive.min()),
                        "drive_max": float(drive.max()), "source_min": float(grid.min()), "source_max": float(grid.max()),
                        "minimum_distance_to_boundary": float(boundary-grid.abs().max()),
                        "dt": 1., "leak": 0., "image_terms": 12,
                        "maximum_unclipped_mass_defect": mass_error, "minimum_unclipped_probability": minimum,
                        "maximum_entry_difference_from_order24": errors,
                        "exact_arithmetic_omission_log10_upper_bounds": truncation_log10_bounds(float(boundary), float(sigma), float(drive.abs().max())),
                        "high_precision_probes": probes})
        print(json.dumps({"anchor": prefix, "order12_error": errors["12"], "high_precision_error": max(p["maximum_absolute_error"] for p in probes)}), flush=True)
    for name, digest in frozen.items():
        if sha(here / name) != digest:
            raise ValueError("frozen input changed during diagnostic")
    return {"schema": "hepta.postfreeze.kernel-range-diagnostic.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
            "diagnostic_source_sha256": sha(__file__), "freeze_sha256": sha(here / "FREEZE.json"),
            "exchange_summary_sha256": sha(summary_path), "exchange_raw_sha256": sha(raw_path), "frozen_source_sha256": frozen,
            "scope": "Post-freeze diagnostics only: no candidate, training, primary endpoint or frozen source change. All original 15 anchors and 738 nominal public states; not a heldout-state certification.",
            "runtime": {"torch": torch.__version__, "numpy": np.__version__, "mpmath": mp.__version__, "mpmath_decimal_digits": mp.mp.dps, "torch_threads": 1},
            "anchors": records, "total_complete_active_rows": sum(r["row_cases"] for r in records),
            "global_model_parameter_envelope": {"boundary_min": .35, "boundary_max": 2., "sigma_min": .05, "sigma_max": .8,
                "max_abs_drive": 1.5, "dt_max": 1., "strictly_interior_start": True, "image_terms": 12,
                "exact_arithmetic_omission_log10_upper_bounds": truncation_log10_bounds(.35, .8, 1.5),
                "proof_scope": "For M=12 these bounds increase with sigma, abs(drift), and dt, and decrease with L on L>=.7, dt<=1. They bound truncation only, not FP64 arithmetic, projection, or tick semantics."},
            "maximum_order12_entry_difference": max(r["maximum_entry_difference_from_order24"]["12"] for r in records),
            "maximum_high_precision_entry_error": max(p["maximum_absolute_error"] for r in records for p in r["high_precision_probes"]),
            "warning": "The public kernel API accepts durations beyond this envelope; mass conservation alone is not an accuracy certificate. Future larger durations or unbounded drives need a new truncation/arithmetic audit.",
            "wall_seconds": time.perf_counter()-started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(Path(__file__).resolve().parent)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("total_complete_active_rows", "maximum_order12_entry_difference", "maximum_high_precision_entry_error", "wall_seconds")}))


if __name__ == "__main__":
    main()
