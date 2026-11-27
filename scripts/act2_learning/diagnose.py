"""Replay pinned ACT2 checkpoints; retrospective diagnosis, never promotion evidence."""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import zipfile

import numpy as np


ORIGIN = "0584b3344f70ed51d9e09224e105bfa4d1a4635f"
ARMS = ("B0_workflow", "B1_macro", "B2_flat", "B3_head", "B4_gru")
SEEDS = tuple(range(700, 708))
PINS = {
    "SHA256SUMS.json": "16de01ad186843a08f115562ba6c3ade48ca43fe42b6c437399958d8cafb44df",
    "source-postimages.zip": "8b2c18bbddf915e6f143d26871864d0ef27c657738d9f19198b4859f6e46d75c",
}
MATCH = (
    "complete",
    "claimed_success",
    "decisions",
    "policy_visible_features",
    "primitive_calls",
    "duplicate_effects",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_bytes(path, expected):
    data = path.read_bytes()
    require(
        hashlib.sha256(data).hexdigest() == expected,
        f"artifact digest mismatch: {path.name}",
    )
    return data


def index_panel(rows, tasks, seeds, arms):
    expected = {
        (seed, arm, task["id"]) for seed in seeds for arm in arms for task in tasks
    }
    require(
        len({task["id"] for task in tasks}) == len(tasks), "duplicate task identity"
    )
    indexed = {(row["training_seed"], row["arm"], row["task_id"]): row for row in rows}
    require(
        len(indexed) == len(rows) and set(indexed) == expected,
        "incomplete or duplicate panel",
    )
    return indexed


def verify_replay(actual, archived):
    require(
        all(actual[key] == archived[key] for key in MATCH), "checkpoint replay mismatch"
    )


def guard_stop(action, feature):
    """Fixture-only public-state guard, shared by every policy; no success authority."""
    require(len(feature) == 10 and np.isfinite(feature).all(), "invalid ACT2 feature")
    if action != "stop" or feature[1] or feature[8] >= 1:
        return action
    return "inspect" if not feature[0] or feature[3] or feature[6] else "ensure"


def guard_action(destination, action):
    """Return (selected action, overridden) using the existing macro fallback."""
    view, last = destination.view, destination.last
    feature = [
        int(view is not None),
        int(bool(view and view["complete"])),
        0,
        int(last == "ensure"),
        int(last == "inspect"),
        int(last == "stage"),
        int(last == "apply"),
        0,
        min(destination.failed_reads, 2) / 2,
        1,
    ]
    selected = guard_stop(action, feature)
    return selected, selected != action


@contextmanager
def frozen_source(root, manifest):
    names = ("models", "sqlite_destination")
    old = {name: sys.modules.pop(name, None) for name in names}
    old_path = sys.path[:]
    try:
        with tempfile.TemporaryDirectory(prefix="act2-source-") as folder:
            with zipfile.ZipFile(root / "source-postimages.zip") as archive:
                require(
                    sorted(archive.namelist())
                    == sorted(manifest["source_files_sha256"]),
                    "unexpected source members",
                )
                for name, digest in manifest["source_files_sha256"].items():
                    require(
                        name in ("models.py", "run.py", "sqlite_destination.py"),
                        "invalid source name",
                    )
                    data = archive.read(name)
                    require(
                        hashlib.sha256(data).hexdigest() == digest,
                        "source digest mismatch",
                    )
                    (Path(folder) / name).write_bytes(data)
            sys.path.insert(0, folder)
            spec = importlib.util.spec_from_file_location(
                "_act2_frozen_run", Path(folder) / "run.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            yield module
    finally:
        sys.path[:] = old_path
        for name, module in old.items():
            sys.modules.pop(name, None)
            if module is not None:
                sys.modules[name] = module


def read_archive(root):
    for name, digest in PINS.items():
        checked_bytes(root / name, digest)
    sums = json.loads((root / "SHA256SUMS.json").read_text())
    required = [
        "RESULT.json",
        "FROZEN_MANIFEST.json",
        "confirmation-trajectories.jsonl.gz",
        "training-trajectories.jsonl.gz",
    ]
    required += [f"{arm}-seed-{seed}.npz" for arm in ARMS[3:] for seed in SEEDS]
    for name in required:
        checked_bytes(root / name, sums[name])
    manifest = json.loads((root / "FROZEN_MANIFEST.json").read_text())
    result = json.loads((root / "RESULT.json").read_text())
    require(manifest["training_seeds"] == list(SEEDS), "training seed mismatch")
    require(
        manifest["source_files_sha256"] == result["source_files_sha256"],
        "result/source mismatch",
    )
    require(len(manifest["confirmation_tasks"]) == 80, "task count mismatch")
    with gzip.open(root / "confirmation-trajectories.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    indexed = index_panel(rows, manifest["confirmation_tasks"], SEEDS, ARMS)
    for arm in ARMS:
        panel = [row for row in rows if row["arm"] == arm]
        summary = result["summary"][arm]
        require(
            (
                len(panel),
                sum(row["complete"] for row in panel),
                sum(row["primitive_calls"] for row in panel),
            )
            == (
                summary["episodes"],
                summary["actual_complete"],
                summary["primitive_calls"]["sum"],
            ),
            "result/panel mismatch",
        )
    return manifest, indexed, {name: sums[name] for name in required} | PINS


def guarded_episode(frozen, task, arm, model, directory):
    directory.mkdir()
    destination = frozen.Destination(directory / "destination.db", task)
    state = np.zeros(model.hidden) if arm == "B4_gru" else None
    claimed, overrides, selection_ns = False, 0, 0
    decisions, features = [], []
    try:
        for _ in range(2 * destination.budget):
            feature = frozen.encode(destination)
            before = time.perf_counter_ns()
            if model is not None:
                choice, state = model.choose(feature, state)
                proposal = frozen.OPTIONS[choice]
            else:
                proposal = (
                    frozen.macro(destination)
                    if arm == "B1_macro"
                    else frozen.primitive(destination)
                )
            action, overridden = guard_action(destination, proposal)
            selection_ns += time.perf_counter_ns() - before
            overrides += overridden
            decisions.append(action)
            features.append(feature)
            if action == "stop":
                current = destination.inspect()
                claimed = bool(current and current["complete"])
                break
            getattr(destination, action)()
    except frozen.BudgetExhausted:
        pass
    return destination.score(claimed) | {
        "guard_overrides": overrides,
        "selection_ns": selection_ns,
        "decisions": decisions,
        "policy_visible_features": features,
    }


class ResetEveryStep:
    def __init__(self, model):
        self.model, self.hidden = model, model.hidden

    def choose(self, feature, state):
        return self.model.choose(feature, np.zeros_like(state))


def summarize(rows):
    return {
        "episodes": len(rows),
        "actual_complete": sum(row["complete"] for row in rows),
        "primitive_calls": sum(row["primitive_calls"] for row in rows),
        "false_success": sum(
            row["claimed_success"] and not row["complete"] for row in rows
        ),
        "duplicate_effects": sum(row["duplicate_effects"] for row in rows),
        "guard_overrides": sum(row.get("guard_overrides", 0) for row in rows),
        "selection_ns": sum(
            row.get("selection_ns", row.get("inference_ns", 0)) for row in rows
        ),
        "duration_ns": sum(row["duration_ns"] for row in rows),
    }


def diagnose(root):
    manifest, indexed, provenance = read_archive(root)
    tasks = manifest["confirmation_tasks"]
    with gzip.open(root / "training-trajectories.jsonl.gz", "rt") as stream:
        training = [json.loads(line) for line in stream]
    require(len(training) == 80, "training trace count mismatch")
    unique_paths = len(
        {
            json.dumps((row["policy_visible_features"], row["decisions"]))
            for row in training
        }
    )
    report = {
        "schema_version": 1,
        "status": "POST_HOC_DIAGNOSTIC_COMPLETED",
        "origin_commit": ORIGIN,
        "promotion": False,
        "training_performed": False,
        "new_independent_tasks": 0,
        "diagnostic_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": {"python": sys.version, "numpy": np.__version__},
        "archived_training_traces": len(training),
        "unique_training_feature_action_paths": unique_paths,
        "independent_task_ids_reused": len(tasks),
        "initialization_seeds_reused": len(SEEDS),
        "fixed_skill_library_retained": True,
        "consumed_files_sha256": provenance,
        "source_files_sha256": manifest["source_files_sha256"],
        "original_gru_replays": 0,
        "replay_mismatches": 0,
        "by_seed": {},
        "paired_regressions": [],
        "scope": "Saved checkpoint and trajectory replay; no original destination archive audit, owner qualification, new holdout, or production integration.",
        "attribution": "Shared deterministic stop guard on all five labels; recoveries are not learned-policy gains. B0 and B2 share one implementation.",
    }
    all_guarded = {arm: [] for arm in ARMS}
    all_reset, all_original = [], []
    with (
        frozen_source(root, manifest) as frozen,
        tempfile.TemporaryDirectory(prefix="act2-diagnosis-") as folder,
    ):
        folder = Path(folder)
        for seed in SEEDS:
            models = {}
            for arm, kind in (("B3_head", "head"), ("B4_gru", "gru")):
                model = frozen.Model(kind, seed)
                with np.load(
                    root / f"{arm}-seed-{seed}.npz", allow_pickle=False
                ) as weights:
                    require(
                        set(weights.files) == set(model.p), "checkpoint keys mismatch"
                    )
                    require(
                        all(
                            weights[k].shape == v.shape
                            and np.isfinite(weights[k]).all()
                            for k, v in model.p.items()
                        ),
                        "checkpoint shape/value mismatch",
                    )
                    model.p = {key: weights[key].copy() for key in weights.files}
                models[arm] = model
            original, reset, guarded = [], [], {arm: [] for arm in ARMS}
            for i, task in enumerate(tasks):
                recorded = indexed[seed, "B4_gru", task["id"]]
                replay, _ = frozen.episode(
                    task,
                    "B4_gru",
                    models["B4_gru"],
                    folder / f"{seed}-original-{i}",
                    False,
                )
                verify_replay(replay, recorded)
                report["original_gru_replays"] += 1
                original.append(replay)
                row, _ = frozen.episode(
                    task,
                    "B4_gru",
                    ResetEveryStep(models["B4_gru"]),
                    folder / f"{seed}-reset-{i}",
                    False,
                )
                reset.append(row)
                for arm in ARMS:
                    row = guarded_episode(
                        frozen, task, arm, models.get(arm), folder / f"{seed}-{arm}-{i}"
                    )
                    guarded[arm].append(row)
                if (
                    not replay["complete"]
                    and indexed[seed, "B0_workflow", task["id"]]["complete"]
                ):
                    state = np.zeros(models["B4_gru"].hidden)
                    for feature in recorded["policy_visible_features"]:
                        _, state = models["B4_gru"].choose(feature, state)
                    model = models["B4_gru"]
                    _, zero = model.choose(feature, np.zeros_like(state))

                    def probabilities(hidden):
                        logits = hidden @ model.p["V"] + model.p["c"]
                        values = np.exp(logits - logits.max())
                        return (values / values.sum()).tolist()

                    report["paired_regressions"].append(
                        {
                            "seed": seed,
                            "task_id": task["id"],
                            "fault": task["fault"],
                            "composition": task["composition"],
                            "final_feature": feature,
                            "decision": recorded["decisions"][-1],
                            "probabilities_original": probabilities(state),
                            "probabilities_zero_prior_state": probabilities(zero),
                        }
                    )
            report["by_seed"][str(seed)] = {
                "original": summarize(original),
                "reset_every_step": summarize(reset),
                "shared_guard": {arm: summarize(rows) for arm, rows in guarded.items()},
            }
            all_original.extend(original)
            all_reset.extend(reset)
            for arm in ARMS:
                all_guarded[arm].extend(guarded[arm])
    report["summary"] = {
        "original": summarize(all_original),
        "reset_every_step": summarize(all_reset),
        "shared_guard": {arm: summarize(rows) for arm, rows in all_guarded.items()},
    }
    report["regression_task_ids"] = len(
        {row["task_id"] for row in report["paired_regressions"]}
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "output already exists")
    report = diagnose(args.archive.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "replays": report["original_gru_replays"],
                "new_independent_tasks": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
