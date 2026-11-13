"""Audit retained MEM-1 v1 call rosters and bytes without rerunning the kernel.

These are reference accounting checks, not authenticated execution receipts or
an independent task evaluator. V1 did not retain every owner call or pool size.
"""

import hashlib
import json
from pathlib import Path

from environment import OUTPUTS, WIDTH, panels, schedule

ARMS = {
    "rag",
    "rag_replay",
    "recurrent",
    "fast",
    "fast_uniform",
    "fast_structured",
    "fast_stabilized",
}
SLEEP_ARMS = {"rag_replay", "fast_uniform", "fast_structured", "fast_stabilized"}
COST_KEYS = {
    "kernel_multiplications",
    "state_payload_bytes",
    "pool_payload_bytes",
    "owner_checks",
}


def nonnegative_int(value):
    if type(value) is not int or value < 0:
        raise ValueError("costs and counters must be nonnegative integers")
    return value


def binary_identity(path, expected):
    """Bind the supplied artifact bytes; this does not prove they were executed."""
    size = 0
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    actual = digest.hexdigest()
    if not size or actual != expected:
        raise ValueError("native binary bytes differ from frozen manifest")
    return {
        "sha256": actual,
        "bytes": size,
        "verified": True,
        "scope": "supplied artifact bytes; not execution attestation",
    }


def operation_roster(arm, plan, owner_change):
    """Freeze operation order, including work at the same stream step."""
    roster, offset = [], 0
    # The A1 pool keeps the last occurrence of each source, in that order.
    last = {source: i for i, source in enumerate(plan[0][1])}
    rebuild = [
        source
        for source in sorted(last, key=last.get)
        if source in {f"A:{i}" for i in range(8)}
    ]
    for phase, sources in plan:
        generation = 2 if owner_change and phase != "A1" else 1
        base = {"generation": generation}
        if phase == "B":
            if owner_change and arm != "rag":
                roster.extend(
                    {
                        **base,
                        "event": "update",
                        "step": offset,
                        "kind": "rebuild",
                        "source": source,
                    }
                    for source in rebuild
                )
            roster.append(
                {
                    **base,
                    "event": "owner_change" if owner_change else "owner_stationary",
                    "step": offset,
                }
            )
        for i, source in enumerate(sources):
            step = offset + i + 1
            if arm != "rag":
                roster.append(
                    {
                        **base,
                        "event": "update",
                        "step": step,
                        "kind": "online",
                        "source": source,
                    }
                )
            roster.append(
                {
                    **base,
                    "event": "prequential",
                    "step": step,
                    "phase": phase,
                    "sources": [source],
                    "before_update": True,
                }
            )
            if i == len(sources) // 2:
                roster.append(
                    {**base, "event": "recovery", "step": step, "phase": phase}
                )
        offset += len(sources)
        if phase != "A2" and arm in SLEEP_ARMS:
            roster.extend(
                {**base, "event": "update", "step": offset, "kind": "sleep"}
                for _ in range(64)
            )
            roster.append(
                {**base, "event": "sleep_candidate", "step": offset, "phase": phase}
            )
        roster.extend(
            {
                **base,
                "event": "probe",
                "step": offset,
                "phase": phase,
                "panel": panel,
                "sources": list(query),
            }
            for panel, queries in panels().items()
            for query in queries
        )
    return roster


def audit_candidates(folder, events, arm):
    phases = ("A1", "B") if arm in SLEEP_ARMS else ()
    expected_files = {
        f"candidate-{phase}.{suffix}" for phase in phases for suffix in ("json", "bin")
    }
    if {path.name for path in folder.glob("candidate-*")} != expected_files:
        raise ValueError("candidate artifact roster differs from the frozen plan")
    for event in (row for row in events if row["event"] == "sleep_candidate"):
        path = folder / f"candidate-{event['phase']}"
        candidate = json.loads(path.with_suffix(".json").read_text())
        payload = {
            key: value
            for key, value in event.items()
            if key not in {"event", "arm", "seed", "step", "generation", "phase"}
        }
        if (
            candidate != payload
            or hashlib.sha256(path.with_suffix(".bin").read_bytes()).hexdigest()
            != candidate["sha256"]
        ):
            raise ValueError("candidate bytes, receipt and event disagree")
        if (
            candidate["model_adoption"] != "NoUpdate"
            or candidate["selected_shared_model_changed"] is not False
            or candidate["capacity_expansion"] is not False
        ):
            raise ValueError("unqualified shared-model adoption or capacity expansion")
        lineage = [
            {"source": row["source"], "version": row["source_version"]}
            for row in events
            if row["event"] == "update"
            and row.get("kind") == "sleep"
            and row["step"] == event["step"]
        ]
        if (
            len(lineage) != 64
            or candidate["updates"] != 64
            or candidate["owner_generation"] != event["generation"]
            or candidate["source_lineage"] != lineage
        ):
            raise ValueError("candidate lineage differs from retained sleep updates")


def audit_run(folder, manifest, result, events, frozen_input):
    arm, seed = result["arm"], result["seed"]
    if type(seed) is not int or any(
        type(row["step"]) is not int or type(row["generation"]) is not int
        for row in events
    ):
        raise ValueError("event steps and generations must be integers")
    plan = schedule(seed)
    if frozen_input["schedule"] != [[phase, sources] for phase, sources in plan]:
        raise ValueError("frozen schedule differs from the MEM-1 v1 roster")
    expected_operations = operation_roster(arm, plan, manifest["owner_change"])
    if len(events) != len(expected_operations) or any(
        any(row.get(key) != value for key, value in expected.items())
        for row, expected in zip(events, expected_operations)
    ):
        raise ValueError("raw operation roster differs from the frozen plan")
    audit_candidates(folder, events, arm)
    stream = [row for row in events if row["event"] == "prequential"]
    if any(row["before_update"] is not True for row in stream):
        raise ValueError("prequential labels must record before_update=true")
    probes = [row for row in events if row["event"] == "probe"]
    if result["owner_change"] is not manifest["owner_change"]:
        raise ValueError("result owner mode differs from the frozen plan")
    recoveries = [row for row in events if row["event"] == "recovery"]
    if any(row["matched"] is not True for row in recoveries):
        raise ValueError("recovery event roster is incomplete or inconsistent")
    flags = result["native_recoveries"]
    if (
        not isinstance(flags, list)
        or len(flags) != len(plan)
        or any(flag is not True for flag in flags)
    ):
        raise ValueError(
            "native recovery summary must contain the exact nonempty roster"
        )
    phases = [phase for phase, _ in plan]
    if {p.name for p in folder.glob("restart-*")} != {
        f"restart-{phase}" for phase in phases
    } or {p.name for p in folder.glob("working-*.json")} != {
        f"working-{phase}.json" for phase in phases
    }:
        raise ValueError(
            "retained recovery artifact roster differs from the frozen plan"
        )
    state_sizes, pool_sizes = [], []
    for row in recoveries:
        phase = row["phase"]
        state = (folder / f"restart-{phase}" / "state.bin").read_bytes()
        witness = (
            (folder / f"restart-{phase}" / "owner-witness.txt").read_text().strip()
        )
        if (
            not state
            or hashlib.sha256(state).hexdigest() != row["state"]
            or witness != row["state"]
        ):
            raise ValueError("recovery state bytes, owner witness and event disagree")
        state_sizes.append(len(state))
        working = json.loads((folder / f"working-{phase}.json").read_text())
        if not isinstance(working["pool"], list) or len(working["h"]) != WIDTH:
            raise ValueError("invalid retained working-state snapshot")
        pool_sizes.append(
            len(json.dumps(working["pool"], sort_keys=True, allow_nan=False).encode())
        )
    if len(set(state_sizes)) != 1:
        raise ValueError("native state payload size changed within the v1 run")
    predicts, updates = 2 * len(recoveries), 0
    for row in events:
        event = row["event"]
        if event in {"probe", "prequential"}:
            if arm != "rag":
                predicts += len(row["sources"]) + int(event == "prequential")
        elif event == "update":
            updates += 1
            # The teacher starts after the frozen A1 boundary, after rebuild.
            if arm == "fast_stabilized" and row["step"] > len(plan[0][1]):
                predicts += 1
    recomputed = {
        "kernel_multiplications": predicts * WIDTH * OUTPUTS
        + updates * (3 * WIDTH * OUTPUTS + WIDTH + 2 * OUTPUTS),
        "state_payload_bytes": 3 * state_sizes[0] + WIDTH * 8,
        "recovery_checkpoint_operations": len(recoveries),
        "recovery_checkpoint_bytes": sum(state_sizes),
        "encoder_multiplications": (
            sum(len(r["sources"]) for r in stream + probes) + len(stream)
        )
        * WIDTH
        if arm == "recurrent"
        else 0,
    }
    capacity = result["capacity_and_compute"]
    if (
        set(capacity) != COST_KEYS
        or set(manifest["budget"]) != COST_KEYS
        or result["common_budget_cap"] != manifest["budget"]
    ):
        raise ValueError("resource accounting keys or caps differ from the frozen plan")
    for key, value in recomputed.items():
        recorded = capacity[key] if key in capacity else result["counts"][key]
        if nonnegative_int(recorded) != value:
            raise ValueError(f"{key} differs from retained event/state evidence")
    for key, value in capacity.items():
        if nonnegative_int(value) > nonnegative_int(manifest["budget"][key]):
            raise ValueError("budget exceeded")
    if result["budget_passed"] is not True or capacity[
        "owner_checks"
    ] != nonnegative_int(result["counts"]["owner_checks"]):
        raise ValueError("resource summary is inconsistent")
    pool_lower_bound = max(pool_sizes)
    if capacity["pool_payload_bytes"] < pool_lower_bound:
        raise ValueError("reported pool peak is below a retained snapshot")
    return {
        "arm": arm,
        "seed": seed,
        "recomputed": recomputed,
        "pool_payload_observed_lower_bound": pool_lower_bound,
        "reported_only": {
            key: capacity[key] for key in ("owner_checks", "pool_payload_bytes")
        },
    }
