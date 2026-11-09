"""MEM-2: common-state, source-multiset-matched replay order experiment.

Runs actual native windows inside an unchanged MEM-1 uniform reference trajectory.
These window contrasts are not full-trajectory legacy-retention estimates.
"""

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys

from coverage_control import PROFILES, audit_pair, audit_window, execute_window
from run import Trial, dump


class SnapshotTrial(Trial):
    def __init__(self, *args, on_attempt=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.windows = []
        self.on_attempt = on_attempt

    def sleep(self, phase):
        # Fork before the reference trajectory rehearses. No fork state is adopted.
        owner = copy.deepcopy(self.owner)
        rows = self.pool.eligible(owner)
        checkpoint = self.memory.checkpoint()
        directory = self.output / f"replay-window-{phase}"
        directory.mkdir()
        (directory / "pre-state.bin").write_bytes(bytes.fromhex(checkpoint[1]))
        seed = self.seed * 100 + {"A1": 11, "B": 29}[phase]
        frozen = {
            "phase": phase,
            "seed": self.seed,
            "selector_seed": seed,
            "owner_change": self.owner_change,
            "state": self.memory.state,
            "generation": owner.generation,
            "pre_state": checkpoint[0],
            "pool": [asdict(row) for row in rows],
        }
        dump(directory / "frozen.json", frozen)
        attempts, audits = {}, {}
        for profile in PROFILES:
            result = None
            if self.on_attempt is not None:
                self.on_attempt(phase, profile, {"status": "running"})
            try:
                result = execute_window(
                    self.memory.binary,
                    self.memory.state,
                    checkpoint,
                    copy.deepcopy(owner),
                    rows,
                    seed=seed,
                    profile=profile,
                    output=directory / f"{profile}.bin",
                )
                dump(directory / f"{profile}.json", result)
                audits[profile] = audit_window(
                    result,
                    rows,
                    copy.deepcopy(owner),
                    seed=seed,
                    checkpoint_sha256=checkpoint[0],
                )
                attempts[profile] = result
            except Exception as error:
                attempts[profile] = {
                    "profile": profile,
                    "status": "failed",
                    "error": repr(error),
                    "observed_result": result,
                }
            dump(directory / "attempts.json", attempts)
            if self.on_attempt is not None:
                self.on_attempt(
                    phase,
                    profile,
                    {
                        "status": attempts[profile]["status"],
                        "error": attempts[profile].get("error"),
                    },
                )
        if any(row["status"] != "completed" for row in attempts.values()):
            raise ValueError("failed replay window retained")
        match = audit_pair(
            attempts["coverage_uniform"],
            attempts["coverage_structured"],
            audits["coverage_uniform"],
            audits["coverage_structured"],
        )
        summary = {
            "phase": phase,
            "seed": self.seed,
            "owner_change": self.owner_change,
            "matching": match,
            "profiles": {
                profile: {
                    "scores": audits[profile]["scores"],
                    "source_coverage": len(audits[profile]["source_multiset"]),
                    "selection_ns": attempts[profile]["selection_ns"],
                    "wall_ns": attempts[profile]["wall_ns"],
                }
                for profile in PROFILES
            },
        }
        dump(directory / "audit.json", summary)
        self.windows.append(summary)
        super().sleep(phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(5)))
    args = parser.parse_args()
    if not args.seeds or len(set(args.seeds)) != len(args.seeds):
        raise ValueError("empty or duplicate seed roster")
    if len(args.source_revision) != 40 or any(
        c not in "0123456789abcdef" for c in args.source_revision
    ):
        raise ValueError(
            "source revision must be the exact 40-character repository base"
        )
    args.output.mkdir(parents=True, exist_ok=False)
    files = sorted(Path(__file__).parent.glob("*.py"))
    manifest = {
        "schema": "hepta-mem2-replay-order-v1",
        "source_revision": args.source_revision,
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "native_binary_sha256": hashlib.sha256(args.native.read_bytes()).hexdigest(),
        "seeds": args.seeds,
        "conditions": ["dynamic", "stationary"],
        "profiles": PROFILES,
        "phases": ["A1", "B"],
        "planned_windows": len(args.seeds) * 2 * 2 * len(PROFILES),
        "python": sys.version,
        "platform": platform.platform(),
        "trajectory": "MEM-1 fast_uniform, forks never adopted",
        "teacher": "none",
        "scientific_qualification": "HOLD",
        "production_adoption": "NoUpdate",
        "limitations": [
            "synthetic source facts, no pretrained model",
            "conditional order effect, not causal attribution of historical coverage loss",
            "parent trajectory timings include four extra fork windows",
            "selector and IPC wall time measured, physical total cost not equalized",
            "artifact consistency, not execution authentication",
        ],
    }
    dump(args.output / "manifest.json", manifest)
    completed, failures, windows = [], [], []
    roster = {
        (condition, seed, phase, profile): {
            "condition": condition,
            "seed": seed,
            "phase": phase,
            "profile": profile,
            "status": "not_started",
        }
        for condition in manifest["conditions"]
        for seed in args.seeds
        for phase in manifest["phases"]
        for profile in PROFILES
    }
    results = {
        "completed": completed,
        "failures": failures,
        "windows": windows,
        "attempt_roster": list(roster.values()),
    }
    dump(args.output / "results.json", results)
    for owner_change in (True, False):
        condition = "dynamic" if owner_change else "stationary"
        for seed in args.seeds:
            output = args.output / f"{condition}-seed-{seed}"
            trial = None
            status = "completed"

            def on_attempt(phase, profile, record):
                roster[condition, seed, phase, profile].update(record)
                dump(args.output / "results.json", results)

            try:
                trial = SnapshotTrial(
                    args.native,
                    output,
                    "fast_uniform",
                    seed,
                    owner_change=owner_change,
                    on_attempt=on_attempt,
                )
                result = trial.run()
                completed.append(
                    {"condition": condition, "seed": seed, "status": result["status"]}
                )
            except Exception as error:
                status = "failed"
                failure = {"condition": condition, "seed": seed, "error": repr(error)}
                failures.append(failure)
                output.mkdir(exist_ok=True)
                dump(output / "failure.json", failure)
            finally:
                if trial is not None:
                    windows.extend(trial.windows)
                dump(args.output / "results.json", results)
            print(
                json.dumps({"condition": condition, "seed": seed, "status": status}),
                flush=True,
            )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
