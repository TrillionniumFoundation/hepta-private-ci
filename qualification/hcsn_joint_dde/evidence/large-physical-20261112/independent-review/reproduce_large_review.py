"""Recompute the retained large-grid array review without importing its model."""

import argparse
import ast
import hashlib
import json
import tarfile
import time
from pathlib import Path

import numpy as np


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identify(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def coordinate(index, intervals):
    active_size = (intervals - 1) * 5
    if index < active_size:
        return {"field": "active", "node": index // 5 + 1, "channel": index % 5}
    fields = (
        "upper",
        "refractory",
        "events",
        "discounted_events",
        "discounted_active_time",
        "discounted_remaining_phase",
    )
    remainder = index - active_size
    return {"field": fields[remainder // 5], "channel": remainder % 5}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    original = json.loads(args.review.read_bytes())
    evidence = (
        args.root / "qualification/hcsn_joint_dde/evidence/large-physical-20261112"
    )
    tracked = [args.review, Path(__file__), evidence / "TESTED-SOURCES.tar.gz"]
    tested = {}
    with tarfile.open(tracked[-1], "r:gz") as archive:
        for member in archive:
            require(member.isfile() and member.name not in tested, "source member")
            tested[member.name] = archive.extractfile(member).read()
    require(len(tested) == len(original["format_checks"]) == 14, "source roster")
    for row in original["format_checks"]:
        raw = tested[row["path"]]
        live = args.root / row["path"]
        tracked.append(live)
        current = live.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == row["tested_sha256"], "tested bytes")
        require(
            hashlib.sha256(current).hexdigest() == row["published_sha256"],
            "published bytes",
        )
        require(
            ast.dump(ast.parse(raw), include_attributes=False)
            == ast.dump(ast.parse(current), include_attributes=False),
            "source AST",
        )
    before = {str(path): digest(path) for path in tracked}
    grids = []
    for retained in original["grids"]:
        intervals = retained["intervals"]
        lane = evidence / f"original-n{intervals}"
        result = json.loads((lane / "RESULT.json").read_bytes())
        start = json.loads((lane / "START.json").read_bytes())
        for path in lane.iterdir():
            if path.is_file():
                before[str(path)] = digest(path)
        require(start["source_sha256"] == result["source_sha256"], "run source maps")
        require(start["input_sha256"] == result["input_sha256"], "run input maps")
        for name, expected in start["source_sha256"].items():
            relative = Path(name).relative_to(args.root).as_posix()
            require(
                hashlib.sha256(tested[relative]).hexdigest() == expected,
                "run source binding",
            )
        for name, expected in start["input_sha256"].items():
            path = args.root / name
            require(digest(path) == expected, "input hash")
            before[str(path)] = digest(path)
        meta_path = args.root / next(
            name for name in start["input_sha256"] if name.endswith(".json")
        )
        metadata = json.loads(meta_path.read_bytes())
        require(
            digest(meta_path.with_suffix(".npz"))
            == metadata["npz_sha256"]
            == metadata["previous_lost_npz_sha256"],
            "reproduced NPZ identity",
        )
        journal = Path(metadata["source_journal"])
        require(
            digest(journal) == metadata["source_journal_sha256"], "journal identity"
        )
        raw_line = journal.read_bytes().splitlines()[metadata["original_line_index"]]
        require(
            hashlib.sha256(raw_line).hexdigest() == metadata["original_line_sha256"],
            "line identity",
        )
        source = json.loads(raw_line)
        position = metadata["source_visit"]["position"]
        require(
            source["states"][position]["probability"][0]
            == metadata["source_probability"],
            "original posterior",
        )
        require(
            source["states"][position]["content_mass"][0] == metadata["source_content"],
            "original signed contents",
        )
        require(
            source["physical_parameters"] == result["physical_parameters"],
            "original physics",
        )
        require(
            source["dt"][0][position] == 0.02 and source["dt"][0][position + 1] == 0.16,
            "gap scope",
        )
        require(
            digest(lane / "ARRAYS.npz") == result["arrays_sha256"], "arrays identity"
        )
        with np.load(lane / "ARRAYS.npz", allow_pickle=False) as stored:
            arrays = {name: stored[name].copy() for name in stored.files}
        size = (intervals + 5) * 5
        require(
            len(arrays) == 37
            and all(
                value.shape == (size,)
                and value.dtype == np.float64
                and np.all(np.isfinite(value))
                for value in arrays.values()
            ),
            "array schema",
        )
        with np.load(lane / "VARIATIONAL.npz", allow_pickle=False) as stored:
            require(
                all(
                    np.array_equal(stored[name], arrays[name]) for name in stored.files
                ),
                "variational snapshot",
            )
        cases = []
        for retained_case in retained["cases"]:
            parameter = retained_case["recomputed_result"]["parameter"]
            derivative = arrays[parameter + "_variational"]
            differences, steps = [], []
            for label, step in (("coarse", 2e-4), ("fine", 1e-4)):
                plus, minus = [
                    arrays[f"{parameter}_{label}_{sign}"] for sign in ("plus", "minus")
                ]
                difference = (plus - minus) / (2 * step)
                require(
                    np.array_equal(difference, arrays[f"{parameter}_{label}_fd"]),
                    "FD arithmetic",
                )
                with np.load(
                    lane / f"FD-{parameter}-{label}.npz", allow_pickle=False
                ) as stored:
                    require(
                        np.array_equal(stored["plus"], plus)
                        and np.array_equal(stored["minus"], minus)
                        and np.array_equal(stored["fd"], difference),
                        "FD snapshot",
                    )
                error = abs(derivative - difference)
                ratio = error / (3e-6 + 4e-4 * abs(difference))
                relative = np.zeros(size)
                nonzero = np.flatnonzero(difference != 0)
                relative[nonzero] = error[nonzero] / abs(difference[nonzero])
                worst = int(relative.argmax())
                steps.append(
                    {
                        "step": step,
                        "label": label,
                        "maximum_absolute_error": float(error.max()),
                        "maximum_gate_ratio": float(ratio.max()),
                        "gate_failures": int(np.count_nonzero(ratio > 1)),
                        "pure_relative_defined_max": float(relative[worst]),
                        "pure_relative_worst": {
                            "flat_index": worst,
                            **coordinate(worst, intervals),
                            "variational": float(derivative[worst]),
                            "fd": float(difference[worst]),
                            "absolute_error": float(error[worst]),
                        },
                        "zero_fd_count": int(np.count_nonzero(difference == 0)),
                        "zero_fd_nonzero_variational_count": int(
                            np.count_nonzero((difference == 0) & (derivative != 0))
                        ),
                        "absolute_floor_dominant_count": int(
                            np.count_nonzero(4e-4 * abs(difference) < 3e-6)
                        ),
                    }
                )
                differences.append(difference)
            stable = abs(differences[0] - differences[1]) / (
                5e-6 + 6e-4 * abs(differences[1])
            )
            metrics = {
                "parameter": parameter,
                "coordinates": size,
                "maximum_absolute_error": float(
                    np.max(abs(derivative - differences[1]))
                ),
                "maximum_gate_ratio": max(row["maximum_gate_ratio"] for row in steps),
                "gate_failures": sum(row["gate_failures"] for row in steps),
                "maximum_stability_ratio": float(stable.max()),
                "stability_failures": int(np.count_nonzero(stable > 1)),
                "tiny_fine_fd_count": int(np.count_nonzero(abs(differences[1]) < 3e-6)),
                "undefined_relative_count": int(np.count_nonzero(differences[1] == 0)),
            }
            require(
                metrics == retained_case["recomputed_result"]
                and steps == retained_case["steps"],
                "independent review metrics",
            )
            require(
                metrics
                == next(
                    row for row in result["cases"] if row["parameter"] == parameter
                ),
                "producer metrics",
            )
            cases.append(metrics)
        require(
            (6 * (intervals + 5) * 5) == result["costs"][0]["augmented_state_scalars"],
            "state budget",
        )
        require(20 * (intervals + 5) ** 2 <= 12_000_000, "coefficient budget")
        grids.append(
            {
                "intervals": intervals,
                "parameter_coordinates": size * 5,
                "two_step_comparisons": size * 10,
                "case_metrics": cases,
            }
        )
    require(
        all(digest(path) == expected for path, expected in before.items()),
        "review input changed",
    )
    receipt = {
        "schema": "hcsn-large-array-review-reproducer-v1",
        "passed": True,
        "reproduced_review": identify(args.review),
        "inspector_source": identify(Path(__file__)),
        "tested_source_archive": identify(evidence / "TESTED-SOURCES.tar.gz"),
        "grids": grids,
        "tracked_files_unchanged": len(before),
        "new_kernel_model_torch_optimizer_calls": 0,
        "limitations": original["boundaries"],
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - wall,
    }
    with args.output.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "passed": True,
                "receipt": str(args.output),
                "sha256": digest(args.output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
