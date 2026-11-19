"""Generate v4 data only after an explicit, source-bound protocol freeze."""

from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import argparse
import hashlib
import json

import numpy as np

from .task import FEATURES, MAX_STEPS, Oracle, Scenario, make_scenario, scenario_digest


ROOT = Path(__file__).resolve().parent
DATA_SPEC = {
    "train": {"episodes": 512, "seed": 1401001, "distribution": "train"},
    "validation": {"episodes": 128, "seed": 2401001, "distribution": "train"},
    "test": {"episodes": 256, "seed": 3401001, "distribution": "train"},
    "shift": {"episodes": 256, "seed": 4401001, "distribution": "shift"},
    "paired": {"episodes": 256, "seed": 5401001, "value_groups": 64,
               "conditions": ["A0", "A2", "B0", "B2"],
               "value_range": [.25, 1.5], "budget": 3, "refill": 1,
               "deadlines_A": [1., 1., 3., 3.], "deadlines_B": [2., 2., 2., 2.]},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_freeze(path):
    path = Path(path)
    protocol = json.loads(path.read_text())
    if protocol.get("frozen_before_data") is not True:
        raise ValueError("The protocol must explicitly precede data generation")
    if protocol.get("task_sha256") != sha(ROOT / "task.py"):
        raise ValueError("Task source changed after protocol freeze")
    if protocol.get("data_spec") != DATA_SPEC:
        raise ValueError("Data sample sizes, seed allocation or paired protocol changed")
    return protocol


def paired_scenarios(seed, groups=64):
    rng = np.random.default_rng(seed)
    scenarios = []
    metadata = []
    for group in range(groups):
        values = tuple(np.round(rng.uniform(.25, 1.5, 4), 6))
        for profile, deadlines in (("A", (1., 1., 3., 3.)), ("B", (2., 2., 2., 2.))):
            for shock in (0, 2):
                scenarios.append(Scenario(values, deadlines, 3, shock, 1,
                                          profile=profile, split="paired"))
                metadata.append({"group": group, "condition": profile+str(shock)})
    return scenarios, metadata


def make_arrays(scenarios):
    records = []
    initial_values = []
    for scenario in scenarios:
        oracle = Oracle(scenario)
        records.append(oracle.demonstration())
        initial_values.append(oracle.value(0, scenario.initial_live, scenario.budget))
    arrays = {name: np.stack([record[index] for record in records])
              for index, name in enumerate(("x", "dt", "valid", "optimal", "decision"))}
    arrays["lengths"] = np.asarray([record[-1] for record in records])
    arrays["event_mask"] = np.arange(MAX_STEPS)[None, :] < arrays["lengths"][:, None]
    arrays["oracle_utility"] = np.asarray(initial_values, dtype=np.float64)
    if not np.all(arrays["dt"][:, 0] == 0) or arrays["decision"][:, 0].any():
        raise AssertionError("Initial cue must have zero elapsed time and no task action")
    return arrays


def write_once(path, contents):
    if path.exists():
        if path.read_bytes() != contents:
            raise FileExistsError(f"Refusing to replace different frozen data: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(contents)
    temporary.replace(path)


def load_data(name, freeze_path, directory=None):
    validate_freeze(freeze_path)
    directory = Path(directory or ROOT / "data")
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["protocol_sha256"] != sha(freeze_path) or manifest["task_sha256"] != sha(ROOT / "task.py"):
        raise ValueError("Frozen protocol or task identity mismatch")
    rows = [row for row in manifest["splits"] if row["name"] == name]
    if len(rows) != 1:
        raise ValueError("Unknown or duplicate data split")
    spec = rows[0]
    for relative, expected in spec["files"].items():
        if sha(directory / relative) != expected:
            raise ValueError(f"Frozen data file changed: {relative}")
    payload = json.loads((directory / f"{name}_scenarios.json").read_text())
    scenarios = [Scenario(**row) for row in payload["scenarios"]]
    with np.load(directory / f"{name}.npz", allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in archive.files}
    if len(scenarios) != DATA_SPEC[name]["episodes"]:
        raise ValueError("Dataset episode count drift")
    return scenarios, arrays, payload["episode_metadata"], manifest


def prepare(freeze_path, directory=None):
    validate_freeze(freeze_path)
    directory = Path(directory or ROOT / "data")
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        for name in DATA_SPEC:
            load_data(name, freeze_path, directory)
        return json.loads(manifest_path.read_text())
    manifest = {"schema": "rrsnn-v4-data-1", "data_spec": DATA_SPEC,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "protocol_sha256": sha(freeze_path), "task_sha256": sha(ROOT / "task.py"),
                "generator_sha256": sha(__file__), "features": FEATURES,
                "initial_event": "cue only, dt zero, task action zero",
                "query_realizations_generated": False, "real_future_window": False,
                "splits": []}
    for name, spec in DATA_SPEC.items():
        if name == "paired":
            scenarios, metadata = paired_scenarios(spec["seed"], spec["value_groups"])
        else:
            rng = np.random.default_rng(spec["seed"])
            scenarios = [make_scenario(rng, split=spec["distribution"]) for _ in range(spec["episodes"])]
            metadata = [{"group": index, "condition": scenario.profile+str(scenario.shock_amount)}
                        for index, scenario in enumerate(scenarios)]
        arrays = make_arrays(scenarios)
        array_file = directory / f"{name}.npz"
        encoded = BytesIO()
        np.savez_compressed(encoded, **arrays)
        write_once(array_file, encoded.getvalue())
        scenario_file = directory / f"{name}_scenarios.json"
        payload = {"scenarios": [asdict(scenario) for scenario in scenarios],
                   "episode_metadata": metadata,
                   "scenario_digests": [scenario_digest(scenario) for scenario in scenarios]}
        write_once(scenario_file, (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                             allow_nan=False)+"\n").encode())
        manifest["splits"].append({"name": name, "episodes": len(scenarios),
                                   "maximum_observations": int(arrays["lengths"].max()),
                                   "files": {array_file.name: sha(array_file),
                                             scenario_file.name: sha(scenario_file)}})
        print(json.dumps({"prepared": name, "episodes": len(scenarios)}), flush=True)
    write_once(manifest_path, (json.dumps(manifest, indent=2, allow_nan=False)+"\n").encode())
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--directory", type=Path)
    arguments = parser.parse_args()
    prepare(arguments.freeze, arguments.directory)
