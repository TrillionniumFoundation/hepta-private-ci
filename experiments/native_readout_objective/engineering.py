"""Six prespecified durable-owner replays; separate from efficacy evidence."""

import argparse
import gzip
import json
from pathlib import Path

from experiments.continuous_boundary_flow.integration import contained, require

from .common import (
    ARMS,
    PACKAGE,
    REPOSITORY,
    CostMeter,
    canonical,
    read_json,
    save_json,
    scientific_files,
    sha,
)
from .engineering_replay import replay
from .source import verify_frozen, verify_publication


def files(root):
    result = {}
    for path in sorted(root.rglob("*")):
        require(
            not path.is_symlink(), "Engineering evidence cannot contain symbolic links"
        )
        if path.is_file():
            result[str(path.relative_to(root))] = sha(path.read_bytes())
    return result


def select(root, binary, smoke):
    if smoke:
        manifest_path = root / "SUMMARY.json"
        manifest = read_json(manifest_path)
        require(
            manifest["seed"] == 991
            and manifest["registered_confirmation_accessed"] is False
            and manifest["native_binary_sha256"] == sha(binary.read_bytes()),
            "Diagnostic source/binary contract changed",
        )
        source, seed, splits = None, 991, ["diagnostic"]
        entries = [
            dict(row["shard"], arm=row["arm"], seed=991, split="diagnostic")
            for row in manifest["arms"]
            if row["arm"] in ARMS
        ]
        checkpoints = {
            row["arm"]: row["checkpoint"]
            for row in manifest["arms"]
            if row["arm"] in ARMS
        }
    else:
        source = verify_frozen(root, binary)
        manifest_path = root / "MANIFEST.json"
        manifest = read_json(manifest_path)
        expected = {
            **manifest["files"],
            "MANIFEST.json": sha(manifest_path.read_bytes()),
        }
        require(
            scientific_files(root) == expected,
            "Scientific evidence identity/roster changed",
        )
        selection = read_json(root / "SELECTION_SEAL.json")
        external = read_json(root / "EXTERNAL_SELECTION.json")
        selection_sha = sha((root / "SELECTION_SEAL.json").read_bytes())
        require(
            manifest["selection_seal_sha256"]
            == external["selection_seal_sha256"]
            == selection_sha,
            "Engineering selection/manifest binding changed",
        )
        verify_publication(
            external["selection_commit"],
            str((PACKAGE / "evidence/SELECTION_SEAL.json").relative_to(REPOSITORY)),
            (root / "SELECTION_SEAL.json").read_bytes(),
        )
        seed, splits = 3301, ["test_id", "test_ood"]
        entries = [
            row
            for row in manifest["shards"]
            if row["seed"] == seed and row["arm"] in ARMS
        ]
        checkpoints = {
            row["arm"]: row
            for row in selection["checkpoints"]
            if row["seed"] == seed and row["arm"] in ARMS
        }
    selected = {}
    for entry in entries:
        path = contained(root, entry["path"])
        raw = path.read_bytes()
        require(sha(raw) == entry["sha256"], "Engineering source shard changed")
        expanded = gzip.decompress(raw)
        require(
            sha(expanded) == entry["uncompressed_sha256"], "Source raw records changed"
        )
        records = [json.loads(line) for line in expanded.splitlines()]
        require(len(records) == entry["count"], "Source episode count changed")
        for record in records:
            if record["episode_id"] == f"{seed}.{entry['split']}.c0.p0":
                key = record["arm"], record["split"]
                require(
                    key not in selected
                    and record["train_seed"] == seed
                    and key == (entry["arm"], entry["split"]),
                    "Duplicated/misbound owner source",
                )
                selected[key] = record
    require(
        set(selected) == {(arm, split) for arm in ARMS for split in splits},
        "Fixed engineering case roster incomplete",
    )
    return selected, checkpoints, source, manifest_path


def run(root, binary, output, *, smoke=False):
    overall = CostMeter()
    root, binary, output = (
        Path(root).resolve(),
        Path(binary).resolve(),
        Path(output).resolve(),
    )
    require(
        not output.is_relative_to(root) and not root.is_relative_to(output),
        "Engineering evidence must be separate from the scientific run",
    )
    output.mkdir(parents=True, exist_ok=False)
    preparation = CostMeter()
    selected, checkpoints, source, manifest_path = select(root, binary, smoke)
    manifest_sha = sha(manifest_path.read_bytes())
    setup_cost = preparation.finish()
    save_json(
        output / "INPUT.json",
        {
            "schema": "hepta.native-readout-objective.owner-input.v1",
            "diagnostic_smoke": smoke,
            "scientific_manifest_sha256": manifest_sha,
            "native_binary_sha256": sha(binary.read_bytes()),
            "source_seal_sha256": None
            if source is None
            else sha((root / "SOURCE_SEAL.json").read_bytes()),
            "selected_cases": [
                {
                    "arm": arm,
                    "split": split,
                    "episode_id": record["episode_id"],
                    "reference_record_sha256": sha(canonical(record)),
                }
                for (arm, split), record in sorted(selected.items())
            ],
            "scope": "existing c0p0 episodes only; zero new efficacy samples; no arbitrary-duration claim",
        },
    )
    results = [
        replay(root, output, record, checkpoints[arm], manifest_sha, binary, source)
        for (arm, split), record in sorted(selected.items())
    ]
    require(
        sha(manifest_path.read_bytes()) == manifest_sha,
        "Scientific manifest changed during replay",
    )
    summary = {
        "schema": "hepta.native-readout-objective.owner-summary.v1",
        "passed": all(row["passed"] for row in results),
        "diagnostic_smoke": smoke,
        "cases": len(results),
        "results": results,
        "cold_resumes": sum(row["cold_resumes"] for row in results),
        "continued_after_resume_cases": sum(
            row["continued_after_resume"] > 0 for row in results
        ),
        "stop_guards": sum(row["stop_guards"] for row in results),
        "stop_coverage": "probe every observed STOP; zero probes means selected-case STOP behavior was not exercised",
        "setup_cost": setup_cost,
        "overall_cost": overall.finish(),
        "cost_scope": "overall window includes setup, all cases and evidence writes before summary; phase and per-PID costs are included subsets, not additive to overall",
        "independent_efficacy_samples": 0,
        "hardware_energy_measured": False,
    }
    save_json(output / "SUMMARY.json", summary)
    save_json(
        output / "ENGINEERING_MANIFEST.json",
        {
            "schema": "hepta.native-readout-objective.owner-manifest.v1",
            "scientific_manifest_sha256": manifest_sha,
            "files": files(output),
        },
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostic-smoke", action="store_true")
    args = parser.parse_args()
    summary = run(
        args.run, args.native_binary, args.output, smoke=args.diagnostic_smoke
    )
    print(
        json.dumps(
            {
                key: summary[key]
                for key in [
                    "passed",
                    "cases",
                    "cold_resumes",
                    "continued_after_resume_cases",
                    "stop_guards",
                ]
            }
        )
    )
    raise SystemExit(0 if summary["passed"] else 1)
