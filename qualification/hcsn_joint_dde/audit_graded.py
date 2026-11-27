"""Execute frozen engineering checks on every original retained source law."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from .basis import basis_values
from .graded import GradedSpatialGenerator, ShortGapKernel
from .graded_migration import migrate, migration_weights
from .model import JointModel
from .short_gap_reference import basis as continuum_basis


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    root = Path(__file__).parent
    paths = [
        root / name
        for name in (
            "audit_graded.py",
            "graded.py",
            "graded_migration.py",
            "short_gap_reference.py",
            "model.py",
            "state_io.py",
            "basis.py",
            "GRADED_PROTOCOL.json",
        )
    ]
    paths += [
        root.parent / "hcsn_boundary_audit" / name
        for name in ("spatial_generator.py", "refractory_transport.py")
    ]
    sources = {str(p): digest(p) for p in paths}
    plan = json.loads((root / "GRADED_PROTOCOL.json").read_text())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    inputs = {}

    def load(path, expected):
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError(f"original input identity mismatch: {path.name}")
        inputs[str(path)] = actual
        return data

    manifest = json.loads(
        load(
            args.input_root / "SUMMARY.json",
            plan["data"]["original_audit_summary_sha256"],
        )
    )
    roster = {
        (s, a) for s in (11, 23, 37) for a in ("c0_b0", "c0_b1", "c1_b0", "c1_b1")
    }
    if (
        len(manifest["arms"]) != 12
        or {(a["seed"], a["arm"]) for a in manifest["arms"]} != roster
    ):
        raise ValueError("full twelve-arm roster required")
    original, representatives, identities = [], [], []
    for arm_index, arm in enumerate(manifest["arms"]):
        lines = [
            json.loads(x)
            for x in load(
                args.input_root / arm["derived_trace_file"], arm["derived_trace_sha256"]
            ).splitlines()
        ]
        old = json.loads(
            load(args.input_root / arm["raw_audit_file"], arm["raw_audit_sha256"])
        )["visits"]
        visits, footer = lines[1:-1], lines[-1]
        if (
            footer["kind"] != "end"
            or footer["truncated"]
            or footer["dropped_records"] != 0
            or len(visits) != arm["expected_visits"]
            or len(old) != len(visits)
        ):
            raise ValueError("original visit denominator changed")
        representatives.append((arm_index, visits[0]))
        for v, r in zip(visits, old):
            if any(
                v[k] != r[k]
                for k in ("index", "model_sha256", "update_index", "episode_id")
            ):
                raise ValueError("original visit pairing changed")
            p = v["parameters"]
            g = v["grid"]
            op = v["operator"]
            if (
                g["active_cells"] != 16
                or g["phase_cells"] != 8
                or g["endpoint"] != 4.8
                or g["tail_rate"] != 1.0
                or g["refractory"] != 0.2
                or p["mu"] != -0.11999999999999998
                or p["sigma"] != 0.35
                or p["discount"] != 0.15
                or not op["reset_enabled"]
                or op["active_reward"] != 0.4
                or op["hit_reward"] != 1.0
                or v["dt"][0] not in plan["data"]["short_gaps"]
            ):
                raise ValueError("unexpected original physics or source basis")
            for law in ("prior", "posterior"):
                a = np.asarray(v[law])
                if (
                    a.shape != (1, 25)
                    or not np.isfinite(a).all()
                    or a.min() < 0
                    or abs(a.sum() - 1) > 5e-11
                ):
                    raise ValueError("invalid retained probability law")
            original.append((arm_index, v, r))
            identities.append(
                [
                    arm_index,
                    v["index"],
                    v["update_index"],
                    v["position"],
                    v["model_sha256"],
                ]
            )
    if len(original) != 14336:
        raise ValueError("all retained positions required")
    (args.output_dir / "IDENTITIES.json").write_text(
        json.dumps(identities, separators=(",", ":")) + "\n"
    )
    references, values = {}, {}
    reports, dde = [], []
    reference_disagreement = 0.0
    for n in plan["candidate"]["intervals"]:
        spatial = GradedSpatialGenerator(n, 8.0, -0.11999999999999998, 0.35)
        weights, migration = migration_weights(spatial.nodes)
        kernel = ShortGapKernel(spatial, 0.15)
        candidates, closures = {}, {}
        array = []
        for arm_index, v, r in original:
            t = v["dt"][0]
            p = v["parameters"]
            reset = math.log(p["absolute_reset"]) - p["log_boundary"]
            model = JointModel(spatial, reset, 0.2, 0.15)
            key = (t, reset)
            if key not in references:
                references[key] = continuum_basis(model, t)
                difference = np.max(
                    abs(references[key] - continuum_basis(model, t, order=64))
                )
                reference_disagreement = max(reference_disagreement, float(difference))
            if key not in candidates:
                candidates[key] = kernel.basis(model, weights, t)
            if reset not in closures:
                nodal, rv = model.perpetual()
                edges = np.linspace(0, 0.2, 9)
                phase = [
                    rv
                    * math.exp(-0.15 * l)
                    * -math.expm1(-0.15 * (h - l))
                    / (0.15 * (h - l))
                    for l, h in zip(edges[:-1], edges[1:])
                ]
                closures[reset] = np.r_[weights @ nodal, phase]
                if reset not in values:
                    values[reset] = basis_values(model)
            prior, posterior = np.asarray(v["prior"])[0], np.asarray(v["posterior"])[0]
            ref = float(r["continuum_value"][0])
            check = float(posterior @ values[reset]["halfline_continuum"])
            if abs(ref - check) > 5e-12 * max(1.0, abs(ref)):
                raise ArithmeticError("original continuation oracle mismatch")
            candidate = float(posterior @ closures[reset])
            finite = float(posterior @ values[reset]["finite_continuum"])
            scale = max(1.0, abs(ref))
            array.append(
                [
                    arm_index,
                    v["index"],
                    v["update_index"],
                    v["position"],
                    t,
                    reset,
                    *(prior @ references[key]),
                    *(posterior @ references[key]),
                    *(prior @ candidates[key]),
                    *(posterior @ candidates[key]),
                    candidate,
                    ref,
                    abs(candidate - ref) / scale,
                    (abs(candidate - finite) + abs(finite - ref)) / scale,
                ]
            )
        array = np.asarray(array)
        columns = [
            "arm_index",
            "visit_index",
            "update_index",
            "position",
            "dt",
            "reset",
        ]
        columns += [
            f"{which}_{law}_{metric}"
            for which in ("reference", "candidate")
            for law in ("prior", "posterior")
            for metric in ("M", "H", "A")
        ]
        columns += [
            "migrated_continuation",
            "original_continuation",
            "scaled_error",
            "noncancelling_scaled_error",
        ]
        np.savez_compressed(
            args.output_dir / f"ALL_GRADED_{n}.npz",
            rows=array,
            columns=np.asarray(columns),
        )
        report = {
            "intervals": n,
            "positions": len(array),
            "migration": migration,
            "max_scaled_continuation_error": float(array[:, 20].max()),
            "continuation_failures_at_original_1pct": int(np.sum(array[:, 20] > 0.01)),
            "max_noncancelling_scaled_error": float(array[:, 21].max()),
            "noncancelling_failures_at_original_1pct": int(np.sum(array[:, 21] > 0.01)),
            "finite": [],
        }
        for j, law in enumerate(("prior", "posterior")):
            ref = array[:, 6 + 3 * j : 9 + 3 * j]
            actual = array[:, 12 + 3 * j : 15 + 3 * j]
            error = abs(actual - ref)
            mask = ref[:, 0] >= 1e-12
            report["finite"].append(
                {
                    "law": law,
                    "max_absolute_M_H_A": np.max(error, axis=0).tolist(),
                    "max_relative_M_at_least_1e-12": float(
                        np.max(error[:, 0][mask] / ref[:, 0][mask])
                    ),
                    "relative_denominator": int(np.sum(mask)),
                    "excluded_below_relative_floor": int(np.sum(~mask)),
                }
            )
        reports.append(report)
        # These are direct JointModel executions after migration, not inferred
        # from the backward-value calculation. Every arm retains its first law.
        samples = [
            (f"arm-{i}", v, np.asarray(v["posterior"])[0]) for i, v in representatives
        ]
        for name, index in [("boundary", 0), ("tail", 16), ("phase", 17)]:
            probability = np.zeros(25)
            probability[index] = 1
            samples.append((name, representatives[0][1], probability))
        for name, v, probability in samples:
            p = v["parameters"]
            reset = math.log(p["absolute_reset"]) - p["log_boundary"]
            model = JointModel(spatial, reset, 0.2, 0.15)
            active, marks, phase, receipt = migrate(
                model,
                probability,
                np.c_[2 * probability, -3 * probability],
                weights,
                identity=name,
            )
            times = [0.0, *plan["data"]["short_gaps"]]
            result = model.solve(
                times, active, marks, phase, rtol=1e-11, atol=1e-13, max_step=0.005
            )
            errors = []
            for t, row in zip(times, result["rows"]):
                actual = np.asarray(
                    [
                        row[k][0]
                        for k in (
                            "events",
                            "discounted_events",
                            "discounted_active_time",
                        )
                    ]
                )
                expected = probability @ kernel.basis(model, weights, t)
                errors.append(float(np.max(abs(actual - expected))))
            dde.append(
                {
                    "intervals": n,
                    "sample": name,
                    "migration": receipt,
                    "internal_steps": result["internal_steps"],
                    "maximum_spectral_error": max(errors),
                    "rows": [
                        {
                            k: (
                                value.tolist()
                                if isinstance(value, np.ndarray)
                                else value
                            )
                            for k, value in row.items()
                        }
                        for row in result["rows"]
                    ],
                }
            )
            print(
                json.dumps(
                    {
                        "intervals": n,
                        "direct_dde_sample": name,
                        "maximum_spectral_error": max(errors),
                    }
                ),
                flush=True,
            )
    sources_after = {str(p): digest(p) for p in paths}
    if sources != sources_after or any(digest(Path(p)) != h for p, h in inputs.items()):
        raise ValueError("source/input mutation")
    limits = plan["evaluation"]["engineering_limits"]
    passed = (
        reference_disagreement < 1e-10
        and max(x["maximum_spectral_error"] for x in dde)
        <= limits["spectral_vs_DDE_absolute_error"]
        and all(
            r["continuation_failures_at_original_1pct"]
            == r["noncancelling_failures_at_original_1pct"]
            == 0
            and all(
                max(f["max_absolute_M_H_A"][:2]) <= limits["M_H_absolute_error"]
                and f["max_absolute_M_H_A"][2] <= limits["A_absolute_error"]
                and f["max_relative_M_at_least_1e-12"]
                <= limits["M_relative_error_where_reference_at_least_1e-12"]
                for f in r["finite"]
            )
            for r in reports
        )
    )
    (args.output_dir / "DIRECT_DDE.json").write_text(
        json.dumps(dde, separators=(",", ":"), allow_nan=False) + "\n"
    )
    result = {
        "schema": plan["schema"],
        "overall_status": "HOLD_NO_GO",
        "engineering_checks_passed": passed,
        "reports": reports,
        "direct_DDE_executions": len(dde),
        "max_spectral_DDE_error": max(x["maximum_spectral_error"] for x in dde),
        "continuum_64_128_max_difference": reference_disagreement,
        "source_before": sources,
        "source_after": sources_after,
        "input_sha256": inputs,
        "output_sha256": {p.name: digest(p) for p in args.output_dir.iterdir()},
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "model_training_calls": 0,
        "independent_future_tasks": 0,
        "not_qualified": plan["not_qualified"],
    }
    (args.output_dir / "SUMMARY.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                not in (
                    "source_before",
                    "source_after",
                    "input_sha256",
                    "output_sha256",
                )
            }
        ),
        flush=True,
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
