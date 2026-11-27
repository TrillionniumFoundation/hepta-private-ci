"""Retained-byte/arithmetic checks only; no numpy/candidate/reference imports."""

import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flatten(x):
    if isinstance(x, list):
        for v in x:
            yield from flatten(v)
    else:
        yield x


def canonical(x):
    return json.dumps(
        x, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def main():
    root = Path(__file__).resolve().parents[1]
    out = (
        root
        / "qualification/hcsn_currentstate_resume/evidence/saved-fullraw-attempt001"
    )
    old = root / "qualification/hcsn_currentstate/evidence/currentstate-attempt001"
    summary = json.loads((out / "SUMMARY.json").read_text())
    freeze = json.loads((out / "FREEZE.json").read_text())
    assert (
        freeze["identity"]
        == summary["identity"]
        == "currentstate-saved-continuation-fullraw-attempt001"
    )
    assert (
        freeze["source_commit"]
        == summary["source_freeze_commit"]
        == "9e9dc3fb698ce53046790e09497420eaaee8df5f"
    )
    assert len(freeze["source_sha256"]) == 10 and len(freeze["input_sha256"]) == 5
    before = {
        k: {p: sha(root / p) for p in freeze[k]}
        for k in ("source_sha256", "input_sha256")
    }
    assert before == summary["before"] == summary["after"]
    assert all(before[k] == freeze[k] for k in before)
    for name, metadata in summary["artifacts"].items():
        assert (out / name).stat().st_size == metadata["bytes"] and sha(
            out / name
        ) == metadata["sha256"]
    rows = json.loads((out / "ROWS.json").read_text())
    original = json.loads((old / "ROWS.json").read_text())
    assert (
        len(rows) == 10
        and len({(r["fixture"], r["mode"], r["time"]) for r in rows}) == 10
    )
    maximum = {}
    relative_maximum = {}
    eligible = 0
    nulls = 0
    scalar_rows = 0
    for row in rows:
        prior = next(
            r
            for r in original
            if r["fixture"] == row["fixture"] and r["time"] == row["time"]
        )
        assert (
            prior["reference64"] == row["retained_reference64"]
            and prior["observed"] == row["retained_warm_observed"]
        )
        snapshot_path = out / row["fixture"] / row["mode"] / row["snapshot_name"]
        assert sha(snapshot_path) == row["snapshot_sha256"]
        capsule = json.loads(snapshot_path.read_bytes())
        state = capsule["state"]
        assert canonical(capsule) == snapshot_path.read_bytes()
        assert hashlib.sha256(canonical(state)).hexdigest() == capsule["sha256"]
        for key in ("active", "upper", "M", "H", "A"):
            assert [float.fromhex(x) for x in state[key]["hex"]] == list(
                flatten(row["observed"][key])
            )
        for key, ref in row["retained_reference64"].items():
            obs = list(flatten(row["observed"][key]))
            refs = list(flatten(ref))
            errors = list(flatten(row["error"][key]["absolute"]))
            relative = list(flatten(row["error"][key]["relative_eligible"]))
            assert len(obs) == len(refs) == len(errors) == len(relative)
            for a, b, delta, rel in zip(obs, refs, errors, relative):
                assert abs(a - b) == delta
                maximum[key] = max(maximum.get(key, 0.0), delta)
                scalar_rows += 1
                if abs(b) >= 1e-12:
                    assert rel == delta / abs(b)
                    relative_maximum[key] = max(relative_maximum.get(key, 0.0), rel)
                    eligible += 1
                else:
                    assert rel is None
                    nulls += 1
    assert (scalar_rows, eligible, nulls) == (570, 510, 60)
    assert maximum == summary["max_abs_against_retained_reference"]
    assert relative_maximum == summary["max_relative_eligible_diagnostic"]
    assert all(v <= 2e-11 for v in maximum.values())
    byte_pairs = 0
    expms = 0
    segments = 0
    for name in ("mixed", "rare"):
        for label in ("INPUT", "STATE-028", "STATE-036"):
            warm = out / name / "warm" / (label + ".json")
            cold = out / name / "cold" / (label + ".json")
            assert warm.read_bytes() == cold.read_bytes()
            report = summary["comparisons"][name]["direct_cold_fullraw"][label]
            assert report == {
                "byte_equal": True,
                "warm_sha256": sha(warm),
                "cold_sha256": sha(cold),
            }
            byte_pairs += 1
        assert (out / name / "warm/INPUT.json").read_bytes() == (
            old / f"{name}.resume.json"
        ).read_bytes()
        assert (out / name / "coarse/INPUT.json").read_bytes() == (
            old / f"{name}.resume.json"
        ).read_bytes()
        assert (out / name / "warm/STATE-036.json").read_bytes() == (
            old / f"{name}.final.json"
        ).read_bytes()
        assert (
            summary["comparisons"][name][
                "new_warm_final_matches_retained_original_warm_bytes"
            ]
            is True
        )
        warm = next(
            r
            for r in rows
            if r["fixture"] == name and r["mode"] == "warm" and r["time"] == "9/25"
        )
        coarse = next(r for r in rows if r["fixture"] == name and r["mode"] == "coarse")
        schedule = {
            key: max(
                abs(a - b)
                for a, b in zip(
                    flatten(warm["observed"][key]), flatten(coarse["observed"][key])
                )
            )
            for key in warm["observed"]
        }
        assert schedule == summary["comparisons"][name]["fine_coarse_max_abs"]
        assert all(v <= 2e-11 for v in schedule.values())
        guard = json.loads((out / name / "cold/GUARD.json").read_text())
        assert (
            guard["before"] == guard["after"] == before and guard["unchanged"] is True
        )
        for mode, ledger in summary["cost"][name].items():
            assert (
                ledger["maximum"] == 100
                and ledger["expm_calls"] <= 100
                and ledger["segments"] <= 20
            )
            trajectory = json.loads((out / name / mode / "TRAJECTORY.json").read_text())
            assert (
                trajectory["ledger"] == ledger
                and trajectory["reference_evaluations"]
                == trajectory["initial_trajectory_advances"]
                == 0
            )
            expms += ledger["expm_calls"]
            segments += ledger["segments"]
    assert (byte_pairs, expms, segments) == (6, 284, 28)
    assert all(
        summary[k] == 0
        for k in (
            "reference_evaluations",
            "initial_trajectory_advances",
            "old72_kernel_replays",
            "torch",
            "training",
        )
    )
    assert summary["admission"] == "HOLD_NO_GO" and summary["all_closed"] is False
    assert {k: {p: sha(root / p) for p in freeze[k]} for k in before} == before
    print(
        json.dumps(
            {
                "read_only": True,
                "identity": summary["identity"],
                "source_files": 10,
                "inputs": 5,
                "query_rows": 10,
                "scalar_rows": scalar_rows,
                "eligible": eligible,
                "null": nulls,
                "direct_fullraw_byte_pairs": byte_pairs,
                "retained_candidate_expm": expms,
                "retained_segments": segments,
                "new_candidate_calls": 0,
                "new_reference_calls": 0,
                "new_expm_calls": 0,
                "admission": "HOLD_NO_GO",
                "all_closed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
