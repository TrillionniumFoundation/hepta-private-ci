"""Independently audit retained posterior laws; fail closed on missing coverage.

The 80-digit oracle integrates continuum perpetual U over each fixed basis
analytically. It assesses continuation from the *reconstructed recorded law*,
not whether neural observation filtering matches a continuum posterior. This
audit does not grant formal-study admission, FP32, or scientific benefit.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import mpmath as mp
import torch

from .contract import GridSpec, PhysicalParameters
from .operator import DifferentiableDistributionOperator
from .regenerative import basis_perpetual_value
from .training_domain import read_trace, source_hashes
from .value import perpetual_basis_value


def _reference(grid, values, active_reward, hit_reward):
    """Independent high-precision basis expectations; no Torch helper reuse."""
    boundary, mu, sigma, reset, rho = map(mp.mpf, values)
    distance = mp.log(reset) - boundary
    decay = (mu + mp.sqrt(mu**2 + 2 * rho * sigma**2)) / sigma**2
    g = mp.exp(-decay * distance)
    delay_factor = mp.exp(-rho * grid.refractory)
    reset_value = (active_reward * (1 - g) / rho + hit_reward * g) / (
        1 - delay_factor * g
    )
    multiplier = hit_reward + delay_factor * reset_value - active_reward / rho
    edges = list(map(mp.mpf, grid.active_edges))
    result = [
        active_reward / rho
        + multiplier * (mp.exp(-decay * lo) - mp.exp(-decay * hi)) / (decay * (hi - lo))
        for lo, hi in zip(edges[:-1], edges[1:])
    ]
    result.append(
        active_reward / rho
        + multiplier
        * mp.exp(-decay * grid.endpoint)
        * grid.tail_rate
        / (grid.tail_rate + decay)
    )
    edges = list(map(mp.mpf, grid.phase_edges))
    result.extend(
        reset_value * (mp.exp(-rho * lo) - mp.exp(-rho * hi)) / (rho * (hi - lo))
        for lo, hi in zip(edges[:-1], edges[1:])
    )
    return result


def _basis_gradients(grid, values, operator):
    """All basis derivatives: forward AD versus 80-digit centered differences.

    Checking every basis coefficient also covers every retained posterior and
    batch mixture at these parameters; it does not differentiate the posterior.
    """
    with torch.enable_grad():
        inputs = tuple(
            torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in values
        )

        def function(*args):
            return basis_perpetual_value(
                grid,
                PhysicalParameters(*args),
                active_reward=operator.active_reward,
                hit_reward=operator.hit_reward,
            )

        columns = torch.autograd.functional.jacobian(
            function, inputs, vectorize=True, strategy="forward-mode"
        )
    ad = torch.stack(columns, dim=-1).detach()
    columns = []
    for index, value in enumerate(values):
        h = mp.mpf("1e-25") * max(1, abs(mp.mpf(value)))
        low, high = list(values), list(values)
        low[index], high[index] = mp.mpf(value) - h, mp.mpf(value) + h
        a, b = [
            _reference(
                grid, v, mp.mpf(operator.active_reward), mp.mpf(operator.hit_reward)
            )
            for v in (low, high)
        ]
        columns.append([float((right - left) / (2 * h)) for left, right in zip(a, b)])
    reference = torch.tensor(columns, dtype=torch.float64).T
    return ad, reference


def audit_trace(path, *, max_records=256):
    if type(max_records) is not int or not 1 <= max_records <= 4096:
        raise ValueError("audit max_records must be in [1,4096]")
    header, visits, footer, trace_digest = read_trace(path)
    report = {
        "schema": "hcsn-training-domain-audit-v1",
        "trace_sha256": trace_digest,
        "data_sha256": header["data_sha256"],
        "configuration_sha256": header["configuration_sha256"],
        "trace_summary": footer,
        "reference_digits": 80,
        "formal_fits_started": 0,
        "scientific_admission": "HOLD",
        "source_matches_trace": (
            header["sources"] == source_hashes()
            and footer.get("sources_after") == header["sources"]
            and footer.get("source_unchanged") is True
        ),
        "claim": "Reconstructed retained posterior continuation only; no true-filter or whole-training bound.",
        "limits": {
            "scaled_value_error": 0.01,
            "mass_error": 5e-11,
            "event_replay_error": 5e-11,
            "scaled_continuum_gradient_error": 2e-9,
        },
        "visits": [],
    }
    cache = {}
    with mp.workdps(80), torch.no_grad():
        for visit in visits[:max_records]:
            row = {
                "index": visit["index"],
                "model_sha256": visit["model_sha256"],
                "update_index": visit["update_index"],
                "episode_id": visit["episode_id"],
            }
            try:
                grid = GridSpec(**visit["grid"])
                config = visit["operator"]
                operator = DifferentiableDistributionOperator(
                    grid,
                    active_reward=config["active_reward"],
                    hit_reward=config["hit_reward"],
                    terminal_reward=config["terminal_reward"],
                    reset_enabled=config["reset_enabled"],
                )
                if operator.configuration() != config or not operator.reset_enabled:
                    raise ValueError(
                        "oracle requires the exact recorded regenerative operator configuration"
                    )
                values = [
                    visit["parameters"][name]
                    for name in (
                        "log_boundary",
                        "mu",
                        "sigma",
                        "absolute_reset",
                        "discount",
                    )
                ]
                params = PhysicalParameters(
                    *(torch.tensor(v, dtype=torch.float64) for v in values)
                )
                prior, posterior = [
                    torch.tensor(visit[name], dtype=torch.float64)
                    for name in ("prior", "posterior")
                ]
                dt = torch.tensor(visit["dt"], dtype=torch.float64)
                expected = torch.tensor(visit["expected_events"], dtype=torch.float64)
                if (
                    prior.ndim != 2
                    or prior.shape != posterior.shape
                    or prior.shape[1] != grid.state_count
                    or dt.shape != prior.shape[:1]
                    or expected.shape != dt.shape
                    or not bool(torch.isfinite(posterior).all())
                    or bool((posterior < 0).any())
                ):
                    raise ValueError("invalid posterior geometry or probability")
                flow = operator.advance(prior, prior[..., None], dt, params)
                mass_error = float(
                    torch.cat(
                        (
                            flow.mass_residual.abs(),
                            (posterior.sum(-1) - 1).abs(),
                            (prior.sum(-1) - 1).abs(),
                        )
                    ).max()
                )
                replay_error = float((flow.expected_events - expected).abs().max())
                key = json.dumps([visit["grid"], values, config], sort_keys=True)
                if key not in cache:
                    cache[key] = {
                        "reference": _reference(
                            grid,
                            values,
                            mp.mpf(config["active_reward"]),
                            mp.mpf(config["hit_reward"]),
                        ),
                        "values": {},
                    }
                    cache[key]["gradients"] = _basis_gradients(grid, values, operator)
                item, errors, actual, refs = cache[key], [], [], []
                for p, duration in zip(posterior, dt):
                    # A zero-time observation has no unique continuation step;
                    # disclose the fixed d/2 probe used for that recorded law.
                    duration = (
                        float(duration) if float(duration) > 0 else grid.refractory / 2
                    )
                    if duration not in item["values"]:
                        item["values"][duration] = perpetual_basis_value(
                            operator, params, duration
                        ).value
                    reference = float(
                        mp.fsum(
                            mp.mpf(float(w)) * v for w, v in zip(p, item["reference"])
                        )
                    )
                    value = float(p @ item["values"][duration])
                    actual.append(value)
                    refs.append(reference)
                    errors.append(abs(value - reference) / max(1.0, abs(reference)))
                row.update(
                    maximum_mass_error=mass_error,
                    maximum_event_replay_error=replay_error,
                    maximum_scaled_value_error=max(errors),
                    projected_value=actual,
                    continuum_value=refs,
                    posterior_tail_mass=posterior[:, grid.active_cells].tolist(),
                    posterior_phase_mass=posterior[:, grid.active_count :]
                    .sum(-1)
                    .tolist(),
                    dt=visit["dt"],
                    zero_dt_continuation_probe=grid.refractory / 2,
                )
                gradient, reference_gradient = item["gradients"]
                difference = (gradient - reference_gradient).abs()
                row.update(
                    maximum_basis_gradient_absolute_error=float(difference.max()),
                    scaled_continuum_gradient_error=float(
                        (
                            (
                                posterior @ gradient - posterior @ reference_gradient
                            ).abs()
                            / (posterior @ reference_gradient).abs().clamp_min(1)
                        ).max()
                    ),
                    gradient_scope="all basis coefficients, all retained batch posteriors held fixed",
                    gradient_reference="80-digit central differences; relative parameter step 1e-25",
                    gradient_basis_count=grid.state_count,
                    gradient_posterior_count=len(posterior),
                )
                limits = report["limits"]
                passed = (
                    mass_error <= limits["mass_error"]
                    and replay_error <= limits["event_replay_error"]
                    and max(errors) <= limits["scaled_value_error"]
                    and row["scaled_continuum_gradient_error"]
                    <= limits["scaled_continuum_gradient_error"]
                    and row["maximum_basis_gradient_absolute_error"]
                    <= limits["scaled_continuum_gradient_error"]
                )
                row["status"] = "passed" if passed else "failed"
            except Exception as error:
                row.update(
                    status="error", error_type=type(error).__name__, detail=str(error)
                )
            report["visits"].append(row)
    complete = bool(visits) and not footer["truncated"] and len(visits) <= max_records
    passed = bool(report["visits"]) and all(
        r["status"] == "passed" for r in report["visits"]
    )
    report.update(
        audited_records=len(report["visits"]),
        complete_retained_coverage=complete,
        status="passed_recorded_states"
        if complete and passed and report["source_matches_trace"]
        else "HOLD",
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=256)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("retain previous evidence and select a new output path")
    started = time.perf_counter()
    torch.set_num_threads(1)
    report = audit_trace(args.trace, max_records=args.max_records)
    report.update(
        wall_seconds=time.perf_counter() - started,
        torch=torch.__version__,
        mpmath=mp.__version__,
        audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {"status": report["status"], "audited_records": report["audited_records"]}
        )
    )
    return 0 if report["status"] == "passed_recorded_states" else 1


if __name__ == "__main__":
    raise SystemExit(main())
