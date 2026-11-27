"""Read-only standard-library arithmetic verification. No candidate imports."""

import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flat(x):
    if isinstance(x, list):
        for v in x:
            yield from flat(v)
    else:
        yield x


def canonical(x):
    return json.dumps(
        x, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def main():
    root = Path(__file__).resolve().parents[1]
    evidence = root / "qualification/hcsn_currentstate/evidence/currentstate-attempt001"
    summary = json.loads((evidence / "SUMMARY.json").read_text())
    freeze = json.loads((evidence / "FREEZE.json").read_text())
    assert (
        summary["source_freeze_commit"]
        == freeze["source_commit"]
        == "de3d9372d8bd53bb4c523c6f1a43e3e213d33790"
    )
    actual = {p: digest(root / p) for p in freeze["source_sha256"]}
    assert (
        actual
        == freeze["source_sha256"]
        == summary["source_sha256_before"]
        == summary["source_sha256_after"]
    )
    for name, metadata in summary["artifacts"].items():
        p = evidence / name
        assert p.stat().st_size == metadata["bytes"] and digest(p) == metadata["sha256"]
    rows = json.loads((evidence / "ROWS.json").read_text())
    assert len(rows) == 18
    assert len({(r["fixture"], r["time"]) for r in rows}) == 18
    maximum = {}
    relative_maximum = {}
    order_maximum = {}
    eligible_count = 0
    null_count = 0
    conserved = {}
    for row in rows:
        for key in row["reference64"]:
            obs = list(flat(row["observed"][key]))
            refs = list(flat(row["reference64"][key]))
            refs32 = list(flat(row["reference32"][key]))
            errors = row["error"][key]
            absolute = list(flat(errors["absolute"]))
            relative = list(flat(errors["relative_eligible"]))
            order = list(flat(errors["reference_order_delta"]))
            assert (
                len(obs)
                == len(refs)
                == len(refs32)
                == len(absolute)
                == len(relative)
                == len(order)
            )
            for value, ref, low, error, rel, delta in zip(
                obs, refs, refs32, absolute, relative, order
            ):
                assert abs(value - ref) == error and abs(low - ref) == delta
                maximum[key] = max(maximum.get(key, 0.0), error)
                order_maximum[key] = max(order_maximum.get(key, 0.0), delta)
                if abs(ref) >= 1e-12:
                    assert rel == error / abs(ref)
                    relative_maximum[key] = max(relative_maximum.get(key, 0.0), rel)
                    eligible_count += 1
                else:
                    assert rel is None
                    null_count += 1
        physical = [
            sum(flat(a)) + sum(u) + sum(r)
            for a, u, r in zip(
                row["observed"]["active"],
                row["observed"]["upper"],
                row["observed"]["R"],
            )
        ]
        if row["time"] == "0":
            conserved[row["fixture"]] = physical
        # summation association differs from numpy; preserve the recorded error
        # and verify conservation independently within the frozen tolerance.
        assert (
            max(abs(a - b) for a, b in zip(physical, conserved[row["fixture"]]))
            <= 2e-11
        )
        assert row["channel_conservation_error"] <= 2e-11
    assert (
        maximum == summary["max_abs"]
        and relative_maximum == summary["max_relative_eligible_diagnostic"]
    )
    assert order_maximum == summary["max_reference_order_delta"]
    assert eligible_count == summary["eligible_scalar_rows"] == 629
    assert null_count == summary["ineligible_relative_scalar_rows"] == 397
    assert all(v <= 2e-11 for v in maximum.values())
    assert all(v <= 2e-11 for v in order_maximum.values())
    expms = 0
    segments = 0
    refs = 0
    gl = 0
    rejects = 0
    for name, cost in summary["cost"].items():
        for label in ("fine", "coarse", "cold"):
            expms += cost[label]["expm_calls"]
            segments += cost[label]["segments"]
            assert cost[label]["expm_calls"] <= 500 and cost[label]["segments"] <= 20
        for ref in cost["reference"]:
            refs += ref["expm_calls"]
            gl += ref["gl_nodes"]
        for control in cost["reject_controls"]:
            assert control["rejected"] is True
            rejects += 1
        assert all(v <= 2e-11 for v in cost["schedule_errors"].values())
        # Coarse per-coordinate raw was not retained by attempt001; this checks
        # only its guarded summary receipt, not an independent reconstruction.
        cold = json.loads((evidence / f"{name}.cold.json").read_text())
        assert (
            cold["restored_snapshot_exact"] is True and cold["start_time"] == "201/1000"
        )
        assert cold["final_snapshot_sha256"] == digest(evidence / f"{name}.final.json")
        for label in ("resume", "final"):
            raw = (evidence / f"{name}.{label}.json").read_bytes()
            capsule = json.loads(raw)
            assert (
                hashlib.sha256(canonical(capsule["state"])).hexdigest()
                == capsule["sha256"]
            )
            assert canonical(capsule) == raw
        for row in cold["rows"]:
            fine = next(
                r for r in rows if r["fixture"] == name and r["time"] == row["time"]
            )
            for key in row["observed"]:
                assert (
                    max(
                        abs(a - b)
                        for a, b in zip(
                            flat(row["observed"][key]), flat(fine["observed"][key])
                        )
                    )
                    <= 2e-11
                )
    assert (expms, segments, refs, gl, rejects) == (392, 44, 19008, 1728, 26)
    rare = next(r for r in rows if r["fixture"] == "rare" and r["time"] == "201/1000")
    assert 0 < rare["observed"]["M"][0][1] < 1e-12
    assert rare["error"]["M"]["relative_eligible"][0][1] is None
    resume = json.loads((evidence / "rare.resume.json").read_text())["state"]
    assert any(p["origin"] == 2 for p in resume["pending"])
    negative = json.loads((evidence / "NEGATIVE_CONTROL.json").read_text())
    assert [r["dps"] for r in negative] == [80, 120]
    for r in negative:
        assert float(r["future_active_A"]) == 0 < float(r["future_active_B"])
        assert float(r["equal_Z_residual"]) < 10.0 ** (-r["dps"] + 4)
    assert summary["admission"] == "HOLD_NO_GO" and summary["all_closed"] is False
    assert all(
        summary[k] == 0 for k in ("old_kernels", "old_refs", "training", "torch")
    )
    assert {p: digest(root / p) for p in actual} == actual
    print(
        json.dumps(
            {
                "read_only": True,
                "source_files": len(actual),
                "query_rows": len(rows),
                "scalar_rows": eligible_count + null_count,
                "eligible": eligible_count,
                "ineligible": null_count,
                "retained_candidate_expm": expms,
                "retained_reference_expm": refs,
                "retained_GL_nodes": gl,
                "snapshot_rejections": rejects,
                "cold_resumes": 2,
                "new_candidate_calls": 0,
                "new_reference_calls": 0,
                "new_expm_calls": 0,
                "coarse_summary_only": True,
                "admission": "HOLD_NO_GO",
                "all_closed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
