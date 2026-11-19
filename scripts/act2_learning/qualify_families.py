"""Frozen controlled tool-family probes; existing models, shared legality guard."""

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import time

import numpy as np

from diagnose import guard_action, read_archive, require
from file_family import FileDestination
from models import Model
from run import OPTIONS, compressed_jsonl, encode, macro
from sqlite_destination import BudgetExhausted


def tasks(families):
    records = []
    for family in families:
        for version in (1, 2):
            for length in (3, 5):
                for fault in (
                    "normal",
                    "lost_reply",
                    "partial_failure",
                    "opaque_after_apply",
                ):
                    identity = f"act3/{family}/v{version}/n{length}/{fault}"
                    records.append(
                        {
                            "id": identity,
                            "family": family,
                            "version": version,
                            "fault": fault,
                            "goals": [
                                hashlib.sha256(f"{identity}:{i}".encode()).hexdigest()
                                for i in range(length)
                            ],
                        }
                    )
    return records


def source_identity(families):
    names = [
        "qualify_families.py",
        "diagnose.py",
        "models.py",
        "run.py",
        "sqlite_destination.py",
        "file_family.py",
    ]
    if set(families) - {"filesystem"}:
        names.append("browser_family.py")
    if "composition" in families:
        names.append("composite_family.py")
    return {
        name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in names
    }


def episode(task, arm, model, path, browser=None):
    if task["family"] == "filesystem":
        destination = FileDestination(path, task)
    elif task["family"] == "browser":
        from browser_family import BrowserDestination

        destination = BrowserDestination(path, task, browser)
    else:
        from composite_family import CompositeDestination

        destination = CompositeDestination(path, task, browser)
    state = np.zeros(12) if model is not None and model.kind == "gru" else None
    decisions, claimed, overrides, selection_ns = [], False, 0, 0
    try:
        try:
            for _ in range(2 * destination.budget):
                feature = encode(destination)
                start = time.perf_counter_ns()
                if arm == "fixed":
                    proposed = macro(destination)
                else:
                    choice, state = model.choose(feature, state)
                    proposed = OPTIONS[choice]
                selected, overridden = guard_action(destination, proposed)
                selection_ns += time.perf_counter_ns() - start
                overrides += int(overridden)
                decisions.append(
                    {"feature": feature, "proposed": proposed, "selected": selected}
                )
                if selected == "stop":
                    current = destination.inspect()
                    claimed = bool(current and current["complete"])
                    break
                getattr(destination, selected)()
        except BudgetExhausted:
            pass
        result = destination.score(claimed)
        return {
            **result,
            "task_id": task["id"],
            "family": task["family"],
            "version": task["version"],
            "fault": task["fault"],
            "arm": arm,
            "guard_overrides": overrides,
            "selection_ns": selection_ns,
            "decisions": decisions,
            "budget": destination.budget,
        }
    finally:
        destination.close()


def replay_identity(directory):
    declared = json.loads((directory / "SHA256SUMS.json").read_text())
    names = ["FROZEN_MANIFEST.json", "RESULT.json", "SHA256SUMS.json"] + [
        f"{order}-seed-{seed}.npz"
        for order in ("ordered", "shuffled")
        for seed in range(700, 708)
    ]
    actual = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in names
    }
    require(
        all(
            declared.get(name) == digest
            for name, digest in actual.items()
            if name != "SHA256SUMS.json"
        ),
        "replay artifact checksum mismatch",
    )
    return actual


def qualify(archive, output, families, executable, replay_models=None):
    require(
        bool(families)
        and len(set(families)) == len(families)
        and set(families) <= {"filesystem", "browser", "composition"},
        "invalid family panel",
    )
    require(not output.exists(), "output already exists")
    output.mkdir(parents=True)
    _, _, inputs = read_archive(archive)
    sources = source_identity(families)
    cohort, arms = tasks(families), ["fixed", "head", "gru"]
    replay_inputs = replay_identity(replay_models) if replay_models else {}
    if replay_models:
        arms.extend(("ordered_replay", "shuffled_replay"))
    frozen = {
        "tasks": cohort,
        "seeds": list(range(700, 708)),
        "arms": arms,
        "source_sha256": sources,
        "archive_inputs_sha256": inputs,
        "replay_inputs_sha256": replay_inputs,
        "shared_guard": True,
        "training_performed": False,
        "gate": "Report paired task quality and all measured costs; no field promotion from fixtures.",
        "scope": "New generated probe IDs; same normalized ACT2 features; no independent real tasks.",
    }
    (output / "FROZEN_MANIFEST.json").write_text(json.dumps(frozen, indent=2) + "\n")
    rows, launch_ns, close_ns = [], 0, 0
    started = time.perf_counter_ns()
    with ExitStack() as stack:
        work = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="act3-families-"))
        )
        browser = None
        if set(families) - {"filesystem"}:
            from playwright.sync_api import sync_playwright

            playwright = stack.enter_context(sync_playwright())
            before = time.perf_counter_ns()
            browser = playwright.chromium.launch(
                **({"executable_path": executable} if executable else {})
            )
            launch_ns = time.perf_counter_ns() - before
            stack.callback(browser.close)
        for seed in frozen["seeds"]:
            models = {}
            specifications = [
                (kind, kind, archive / f"{label}-seed-{seed}.npz")
                for kind, label in (("head", "B3_head"), ("gru", "B4_gru"))
            ]
            if replay_models:
                specifications.extend(
                    (
                        f"{order}_replay",
                        "gru",
                        replay_models / f"{order}-seed-{seed}.npz",
                    )
                    for order in ("ordered", "shuffled")
                )
            for arm, kind, checkpoint in specifications:
                model = Model(kind, seed)
                with np.load(checkpoint, allow_pickle=False) as saved:
                    require(set(saved.files) == set(model.p), "checkpoint parameters")
                    for key, value in model.p.items():
                        require(
                            saved[key].shape == value.shape
                            and np.isfinite(saved[key]).all(),
                            "checkpoint values",
                        )
                        model.p[key] = saved[key].copy()
                models[arm] = model
            for index, task in enumerate(cohort):
                offset = (index + seed) % len(arms)
                for arm in arms[offset:] + arms[:offset]:
                    path = work / str(seed) / str(index) / arm
                    try:
                        row = episode(task, arm, models.get(arm), path, browser)
                    except Exception as error:
                        compressed_jsonl(output / "episodes.partial.jsonl.gz", rows)
                        with tarfile.open(
                            output / "destination-bytes.partial.tar.xz", "w:xz"
                        ) as failed_archive:
                            failed_archive.add(work, arcname="destinations")
                        (output / "FAILURE.json").write_text(
                            json.dumps(
                                {
                                    "status": "ENGINEERING_FAIL",
                                    "task_id": task["id"],
                                    "seed": seed,
                                    "arm": arm,
                                    "recorded_episodes": len(rows),
                                    "error": str(error),
                                    "production_adoption": False,
                                },
                                indent=2,
                            )
                            + "\n"
                        )
                        raise
                    row.update(
                        seed=seed, destination_member=str(path.relative_to(work))
                    )
                    rows.append(row)
        if browser is not None:
            before = time.perf_counter_ns()
            browser.close()
            close_ns = time.perf_counter_ns() - before
        with tarfile.open(output / "destination-bytes.tar.xz", "w:xz") as archive_file:
            archive_file.add(work, arcname="destinations")
    require(source_identity(families) == sources, "source changed during qualification")
    read_archive(archive)  # Detect model/archive drift, not a second evaluation.
    if replay_models:
        require(
            replay_identity(replay_models) == replay_inputs,
            "replay artifacts changed during qualification",
        )
    compressed_jsonl(output / "episodes.jsonl.gz", rows)
    summary = {}
    for family in families:
        summary[family] = {}
        for arm in arms:
            panel = [r for r in rows if r["family"] == family and r["arm"] == arm]
            metrics = (
                "primitive_calls",
                "owner_requests",
                "selection_ns",
                "duration_ns",
                "guard_overrides",
            )
            summary[family][arm] = {
                "episodes": len(panel),
                "complete": sum(r["complete"] for r in panel),
                "claimed_success": sum(r["claimed_success"] for r in panel),
                "false_success": sum(
                    r["claimed_success"] and not r["complete"] for r in panel
                ),
                "duplicate_effects": sum(r["duplicate_effects"] for r in panel),
                **{m: sum(r.get(m, 0) for r in panel) for m in metrics},
            }
    paired = []
    for task in cohort:
        panel = {(r["seed"], r["arm"]): r for r in rows if r["task_id"] == task["id"]}
        for arm in arms[1:]:
            delta = [
                int(panel[s, arm]["complete"]) - int(panel[s, "fixed"]["complete"])
                for s in frozen["seeds"]
            ]
            paired.append(
                {
                    "task_id": task["id"],
                    "arm": arm,
                    "mean_completion_delta": sum(delta) / len(delta),
                    "regressing_seeds": sum(d < 0 for d in delta),
                }
            )
    expected = {
        (seed, arm, task["id"])
        for seed in frozen["seeds"]
        for arm in arms
        for task in cohort
    }
    observed = [(row["seed"], row["arm"], row["task_id"]) for row in rows]
    require(
        len(observed) == len(expected) and set(observed) == expected,
        "incomplete or duplicate family panel",
    )
    unsafe = any(
        r["duplicate_effects"] or (r["claimed_success"] and not r["complete"])
        for r in rows
    )
    result = {
        "status": "ENGINEERING_FAIL"
        if unsafe
        else "CONTROLLED_FAMILY_PROBES_COMPLETED",
        "unsafe_effect_observed": unsafe,
        "controlled_probe_tasks": len(cohort),
        "episodes": len(rows),
        "new_independent_real_tasks": 0,
        "summary": summary,
        "paired_task_deltas": paired,
        "shared_browser_launch_ns": launch_ns,
        "shared_browser_close_ns": close_ns,
        "campaign_wall_ns": time.perf_counter_ns() - started,
        "production_adoption": False,
        "learning_gain_qualified": False,
        "fixed_reference_retained": True,
        "full_operational_cost_qualified": False,
        "source_stable": True,
        "limitations": [
            "controlled fixtures",
            "same normalized observation vocabulary",
            "same UID",
            "no production Cell/FinalUse owner",
            "not open-web tasks",
            "no total lifetime cost claim",
        ],
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    require(
        not unsafe,
        "false success or duplicate effect observed; raw failed results retained",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "tasks": len(cohort),
                "episodes": len(rows),
                "promotion": False,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--families",
        nargs="+",
        choices=("filesystem", "browser", "composition"),
        default=["filesystem"],
    )
    parser.add_argument("--browser-executable")
    parser.add_argument("--replay-models", type=Path)
    args = parser.parse_args()
    require(len(set(args.families)) == len(args.families), "duplicate family")
    qualify(
        args.archive.resolve(),
        args.output.resolve(),
        args.families,
        args.browser_executable,
        args.replay_models.resolve() if args.replay_models else None,
    )
