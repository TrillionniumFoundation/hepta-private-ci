"""MEM-4: carry replay-order differences through complete matched trajectories.

An independently executed no-replay reference freezes public priority metadata.
Both arms pay its complete reported cost; priorities never use either arm's
outcomes. This is a restricted synthetic experiment, not a production policy.
"""

import argparse
from collections import Counter
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

from coverage_control import UPDATES, payload, replay_order
from environment import Experience, OUTPUTS, Owner, WIDTH, commitment, schedule
from run import Trial, dump

PROFILES = ("coverage_uniform", "coverage_structured")


def align_pool(actual, reference):
    """Only prediction-derived priority may differ before common replacement."""

    def facts(rows):
        return sorted(
            ({k: v for k, v in asdict(r).items() if k != "surprise"} for r in rows),
            key=lambda r: r["source"],
        )

    if facts(actual) != facts(reference):
        raise ValueError("online exposure or owner eligibility differs from reference")
    return copy.deepcopy(reference)


def teacher_cost(summary):
    keys = (
        "counts",
        "capacity_and_compute",
        "wall_ns",
        "python_cpu_ns",
        "native_child_cpu_ns",
        "native_calls",
        "native_ipc_wall_ns",
    )
    return {key: copy.deepcopy(summary[key]) for key in keys}


class ManagedTrial(Trial):
    """Close partially constructed local resources if native admission fails."""

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except Exception:
            for name in ("memory", "anchor", "raw"):
                value = getattr(self, name, None)
                if value is not None:
                    value.close()
            raise


class PriorityReference(ManagedTrial):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshots = {}

    def sleep(self, phase):
        rows = self.pool.eligible(self.owner)
        self.snapshots[phase] = copy.deepcopy(rows)
        dump(self.output / f"public-priorities-{phase}.json", [asdict(r) for r in rows])
        # The reference does no replay; its complete native trajectory is charged.


class MatchedTrajectory(ManagedTrial):
    def __init__(self, *args, profile, priorities, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile, self.priorities, self.windows = profile, priorities, []

    def sleep(self, phase):
        start = time.perf_counter_ns()
        rows = align_pool(self.pool.eligible(self.owner), self.priorities[phase])
        seed = self.seed * 100 + {"A1": 11, "B": 29}[phase]
        order = replay_order(rows, seed=seed, profile=self.profile)
        plan = {
            "phase": phase,
            "selector_seed": seed,
            "profile": self.profile,
            "step": self.step,
            "pre_state": self.memory.digest,
            "pool": [asdict(r) for r in rows],
            "pool_sha256": commitment([asdict(r) for r in rows]),
            "order": order,
        }
        dump(self.output / f"plan-{phase}.json", plan)
        before = self.memory.multiplications
        request_bytes = 0
        request_hash = hashlib.sha256()
        original_command = self.memory.command

        def metered_command(text):
            nonlocal request_bytes
            if text.startswith("update "):
                data = (text + "\n").encode()
                request_bytes += len(data)
                request_hash.update(data)
            return original_command(text)

        lineage = []
        self.memory.command = metered_command
        try:
            for index in order:
                row = rows[index]
                self.learn(row, "sleep")
                lineage.append({"source": row.source, "version": row.version})
        finally:
            self.memory.command = original_command
        anchor, state = self.memory.checkpoint()
        (self.output / f"candidate-{phase}.bin").write_bytes(bytes.fromhex(state))
        ledger = {
            "phase": phase,
            "pool_sha256": plan["pool_sha256"],
            "source_multiset": dict(
                sorted(Counter(commitment(asdict(rows[i])) for i in order).items())
            ),
            "updates": len(order),
            "replay_payload_bytes": sum(len(payload(rows[i])) for i in order),
            "replay_request_bytes": request_bytes,
            "replay_request_sha256": request_hash.hexdigest(),
            "kernel_multiplications": self.memory.multiplications - before,
            "pre_state": plan["pre_state"],
            "post_state": anchor,
            "elapsed_ns": time.perf_counter_ns() - start,
        }
        self.windows.append(ledger)
        dump(self.output / f"matching-{phase}.json", ledger)
        self.log("matched_replay", **ledger)
        dump(
            self.output / f"candidate-{phase}.json",
            {
                "kind": "private-fast-state-rehearsal-candidate",
                "sha256": anchor,
                "source_lineage": lineage,
                "updates": len(order),
                "owner_generation": self.owner.generation,
                "model_adoption": "NoUpdate",
            },
        )


def audit_trajectories(left, right, left_summary, right_summary, reference_cost):
    """Check complete exposure at both windows; later pre-states may diverge."""
    if [r["phase"] for r in left] != ["A1", "B"] or len(right) != 2:
        raise ValueError("incomplete paired replay trajectory")
    keys = (
        "phase",
        "pool_sha256",
        "source_multiset",
        "updates",
        "replay_payload_bytes",
        "replay_request_bytes",
        "kernel_multiplications",
    )
    for a, b in zip(left, right):
        if any(a[k] != b[k] for k in keys) or a["updates"] != UPDATES:
            raise ValueError("full trajectory replay exposure or compute mismatch")
    if left[0]["pre_state"] != right[0]["pre_state"]:
        raise ValueError("initial arm states differ")
    for key in left_summary["counts"]:
        if (
            key != "retired_ipc_wall_ns"
            and left_summary["counts"][key] != right_summary["counts"][key]
        ):
            raise ValueError("online/recovery operation budgets differ")
    if left_summary["native_calls"] != right_summary["native_calls"]:
        raise ValueError("native operation counts differ")
    for key in ("kernel_multiplications", "state_payload_bytes"):
        if (
            left_summary["capacity_and_compute"][key]
            != right_summary["capacity_and_compute"][key]
        ):
            raise ValueError("total native compute or state reservation differs")
    return {
        "status": "matched",
        "windows": 2,
        "updates_per_arm": 2 * UPDATES,
        "teacher_cost_per_arm": copy.deepcopy(reference_cost),
        "physical_total_cost_equalized": False,
        "initial_state_equal": True,
        "later_states_required_equal": False,
    }


def readback_trajectory(directory, reference, *, seed, profile, owner_change):
    """Reconstruct replay requests from persisted inputs and native event receipts."""
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
    ]
    owner, step, windows = Owner(seed), 0, []
    for phase, sources in schedule(seed):
        step += len(sources)
        if phase == "A2":
            continue
        if phase == "B" and owner_change:
            owner.change_rules_and_revoke()
        plan = json.loads((directory / f"plan-{phase}.json").read_text())
        public = json.loads((reference / f"public-priorities-{phase}.json").read_text())
        rows = [Experience(**{**row, "key": tuple(row["key"])}) for row in public]
        selector_seed = seed * 100 + {"A1": 11, "B": 29}[phase]
        order = replay_order(rows, seed=selector_seed, profile=profile)
        if (
            plan["pool"] != public
            or plan["order"] != order
            or plan["profile"] != profile
            or plan["selector_seed"] != selector_seed
            or plan["step"] != step
            or plan["pool_sha256"] != commitment(public)
        ):
            raise ValueError("persisted replay plan differs from frozen reference")
        observed = [
            e
            for e in events
            if e["event"] == "update" and e["kind"] == "sleep" and e["step"] == step
        ]
        if len(observed) != UPDATES:
            raise ValueError("missing or duplicate persisted sleep receipts")
        requests, request_bytes = hashlib.sha256(), 0
        for index, event in zip(order, observed):
            row = rows[index]
            support = owner.support(row)
            if (
                support is None
                or row.key != tuple(owner.features[row.source])
                or (
                    event["source"],
                    event["source_version"],
                    event["support"],
                    event["generation"],
                )
                != (row.source, row.version, support, owner.generation)
            ):
                raise ValueError("persisted replay source order or provenance differs")
            target = [float(label == row.label) for label in range(OUTPUTS)]
            data = (
                f"update {owner.generation} {support} "
                + ",".join(map(repr, row.key))
                + " "
                + ",".join(map(repr, target))
                + "\n"
            ).encode()
            requests.update(data)
            request_bytes += len(data)
        expected = {
            "phase": phase,
            "pool_sha256": commitment(public),
            "updates": UPDATES,
            "source_multiset": dict(
                sorted(Counter(commitment(asdict(rows[i])) for i in order).items())
            ),
            "replay_payload_bytes": sum(len(payload(rows[i])) for i in order),
            "replay_request_bytes": request_bytes,
            "replay_request_sha256": requests.hexdigest(),
            "kernel_multiplications": UPDATES
            * (3 * WIDTH * OUTPUTS + WIDTH + 2 * OUTPUTS),
        }
        ledger = json.loads((directory / f"matching-{phase}.json").read_text())
        if any(ledger[key] != value for key, value in expected.items()):
            raise ValueError(
                "persisted matching ledger differs from reconstructed work"
            )
        windows.append(expected)
    if (
        sum(e["event"] == "update" and e["kind"] == "sleep" for e in events)
        != 2 * UPDATES
    ):
        raise ValueError("unexpected replay outside planned boundaries")
    return windows


def run_campaign(binary, output, seeds, source_revision):
    output.mkdir(parents=True, exist_ok=False)
    roster = [
        {"condition": c, "seed": s, "profile": p, "status": "not_started"}
        for c in ("dynamic", "stationary")
        for s in seeds
        for p in ("priority_reference", *PROFILES)
    ]
    source = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    manifest = {
        "schema": "hepta-mem4-full-trajectory-order-v1",
        "source_revision": source_revision,
        "native_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        "source_sha256": source,
        "python": sys.version,
        "platform": platform.platform(),
        "planned_runs": len(roster),
        "seeds": seeds,
        "arm_execution_order": "seed-parity counterbalanced",
        "priority_source": "independent no-replay native reference, complete reported cost charged to each arm",
        "limitations": [
            "synthetic stream seeds, no real-task confirmation",
            "shared exogenous priority, not each arm's endogenous uncertainty",
            "matched logical data/native work, physical cost reported not equalized",
            "retained-input and event consistency, not execution authentication",
            "native worker restarts only; Python owner and reference remain alive, no full-owner cold recovery",
        ],
        "scientific_qualification": "HOLD",
        "production_adoption": "NoUpdate",
    }
    dump(output / "manifest.json", manifest)
    results = {"roster": roster, "pairs": []}
    dump(output / "results.json", results)
    for condition in ("dynamic", "stationary"):
        for seed in seeds:
            entries = {
                r["profile"]: r
                for r in roster
                if r["condition"] == condition and r["seed"] == seed
            }
            try:
                ref_entry = entries["priority_reference"]
                ref_entry["status"] = "running"
                dump(output / "results.json", results)
                ref = PriorityReference(
                    binary,
                    output / f"{condition}-{seed}-reference",
                    "fast",
                    seed,
                    owner_change=condition == "dynamic",
                )
                ref_summary = ref.run()
                ref_entry.update(status="completed", summary=ref_summary)
                dump(output / "results.json", results)
                summaries, windows = {}, {}
                for profile in PROFILES if seed % 2 == 0 else tuple(reversed(PROFILES)):
                    entries[profile]["status"] = "running"
                    dump(output / "results.json", results)
                    # Shared state name permits equal checkpoints without sharing mutable state.
                    trial = MatchedTrajectory(
                        binary,
                        output / f"{condition}-{seed}-{profile}",
                        "fast_uniform",
                        seed,
                        owner_change=condition == "dynamic",
                        profile=profile,
                        priorities=ref.snapshots,
                    )
                    summaries[profile] = trial.run()
                    readback = readback_trajectory(
                        trial.output,
                        ref.output,
                        seed=seed,
                        profile=profile,
                        owner_change=condition == "dynamic",
                    )
                    dump(trial.output / "independent-readback.json", readback)
                    windows[profile] = trial.windows
                    entries[profile].update(
                        status="completed",
                        summary=summaries[profile],
                        teacher_cost=teacher_cost(ref_summary),
                    )
                    dump(output / "results.json", results)
                audit = audit_trajectories(
                    windows[PROFILES[0]],
                    windows[PROFILES[1]],
                    summaries[PROFILES[0]],
                    summaries[PROFILES[1]],
                    teacher_cost(ref_summary),
                )
                results["pairs"].append(
                    {
                        "condition": condition,
                        "seed": seed,
                        "matching": audit,
                        "after_B": {
                            p: summaries[p]["panels"]["B"]["stable"] for p in PROFILES
                        },
                    }
                )
            except Exception as error:
                for row in entries.values():
                    if row["status"] == "running":
                        row.update(status="failed", error=repr(error))
                results.setdefault("failures", []).append(
                    {"condition": condition, "seed": seed, "error": repr(error)}
                )
            finally:
                dump(output / "results.json", results)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(5)))
    args = parser.parse_args()
    if (
        not args.seeds
        or len(set(args.seeds)) != len(args.seeds)
        or any(s < 0 for s in args.seeds)
    ):
        raise ValueError("empty, duplicate or negative seeds")
    if len(args.source_revision) != 40 or any(
        c not in "0123456789abcdef" for c in args.source_revision
    ):
        raise ValueError("expected exact source revision")
    result = run_campaign(args.native, args.output, args.seeds, args.source_revision)
    if result.get("failures"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
