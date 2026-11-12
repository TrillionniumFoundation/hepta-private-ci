"""Read-only verification of retained analytic audit; no oracle/model imports."""

from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close_serialized(actual, expected):
    # Original values are serialized at 40 significant digits; this is only
    # a decimal serialization tolerance, not a new scientific acceptance gate.
    return abs(actual - expected) <= Decimal("1e-37") * max(abs(expected), Decimal("1e-300"))


def main():
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    folder = root / "evidence/attempt001"
    summary = json.loads((folder / "SUMMARY.json").read_text())
    assert summary["status"] == "HOLD_NO_GO" and not summary["all_closed"]
    assert summary["source_sha256_before"] == summary["source_sha256_after"]
    assert summary["retained_inputs_unchanged"]
    for mapping in (summary["source_sha256_before"], summary["retained_execution_sources"],
                    summary["retained_input_sha256"]):
        for old_path, expected in mapping.items():
            path = repo / ("qualification/" + old_path.split("/qualification/", 1)[1])
            assert digest(path) == expected
    for name, expected in summary["output_sha256"].items():
        assert digest(folder / name) == expected
    references = json.loads((folder / "REFERENCE.json").read_text())
    rows = json.loads((folder / "ROWS.json").read_text())
    refmap = {(r["reset"], r["time"]): r["120_digits"] for r in references}
    assert len(rows) == 24 and len(refmap) == 12
    loaded = {}
    metric_count = 0
    with localcontext() as context:
        context.prec = 120
        floor = Decimal.from_float(1e-12)
        for row in rows:
            case = row["case"]
            if case not in loaded:
                with np.load(repo / "qualification/hcsn_dense_reproduction/evidence" / case / "RAW.npz",
                             allow_pickle=False) as archive:
                    loaded[case] = {k: archive[k].copy() for k in archive.files}
            data = loaded[case]
            i = int(np.flatnonzero(data["time"] == row["time"])[0])
            actuals = {
                "M": data["dde_events"][i, 0], "H": data["dde_discounted_events"][i, 0],
                "R": data["dde_refractory"][i, 0], "A": data["dde_discounted_active_time"][i, 0],
                "Z": data["dde_discounted_remaining_phase"][i, 0],
                "Pactive": data["dde_active"][i, :, 0].sum() + data["dde_upper"][i, 0],
            }
            actuals = {k: Decimal.from_float(float(v)) for k, v in actuals.items()}
            ref = {k: Decimal(v) for k, v in refmap[(row["reset"], row["time"])].items()}
            actuals["Z_newhit"] = actuals["Z"] - ref["Z_unreleased"]
            actuals["A_hit_loss"] = ref["A_release_only"] - actuals["A"]
            for name, q in row["quantities"].items():
                value, reference = actuals[name], ref[name]
                assert close_serialized(Decimal(q["retained"]), value)
                assert Decimal(q["continuum_reference_120"]) == reference
                error = abs(value - reference)
                assert close_serialized(Decimal(q["absolute_error"]), error)
                eligible = abs(reference) >= floor
                assert q["relative_diagnostic_eligible"] == eligible
                assert q["relative_reference_floor"] == 1e-12
                if eligible:
                    assert close_serialized(Decimal(q["relative_error"]), error / abs(reference))
                else:
                    assert q["relative_error"] is None
                metric_count += 1
            for field, expected in row["signed_mark_linearity_absolute"].items():
                value = data["dde_" + field][i]
                assert float(np.max(np.abs(value[..., 1] + 0.7 * value[..., 0]))) == expected
            t, width, discount, delay = map(Decimal.from_float, (row["time"], .025, .15, .2))
            u = max(Decimal(0), 1 - t / width)
            constraints = {
                "R_minus_unreleased_minus_M": actuals["R"] - u - actuals["M"],
                "Pactive_plus_M_minus_released": actuals["Pactive"] + actuals["M"] - (1 - u),
                "discounted_active_balance": discount * actuals["A"] - ref["K_release"] + actuals["H"]
                                            + (-discount * t).exp() * actuals["Pactive"],
                "Z_minus_initial_minus_discounted_H": actuals["Z"] - ref["Z_unreleased"]
                                                     - (-discount * (delay - t)).exp() * actuals["H"],
            }
            for name, value in constraints.items():
                assert close_serialized(Decimal(row["retained_identity_residuals"][name]), value)
        print(json.dumps({"read_only": True, "retained_runs": len(loaded),
                          "retained_query_rows": len(rows), "quantity_error_rows": metric_count,
                          "new_analytic_reference_calls": 0, "new_model_calls": 0,
                          "new_spatial_or_dde_runs": 0, "status": "HOLD_NO_GO"}))


if __name__ == "__main__":
    main()
