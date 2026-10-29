"""Durable owner consumes real task states and resumes the complete task.

This re-executes selected existing confirmation episodes as engineering checks;
it adds zero independent scientific samples. Q24 activations/readout/actions are
compared across native execution paths, never scope-dependent checkpoint hashes.
Native logical time advances by profile.tick_micros; the task's physical windows
advance by TaskSpec.dt. They are different clocks with separate checkpoint fields.
"""

from dataclasses import asdict
import gzip
import json
import os
from pathlib import Path
import time

import numpy as np

from .common import CostWindow, canonical, save_json, sha
from .math_model import TaskSpec, build_model, sample_step, solve_dp
from .models import ActorAdapter
from .native.adapter import ACTIONS, NativeBridge, features

OWNER_ARMS = (
    "fixed_margin",
    "value_margin",
    "value_dual",
    "event_reset",
    "native_sparse",
    "generic_gate",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def contained(root, value):
    path = (root / value).resolve()
    require(
        path.is_relative_to(root.resolve()), "Artifact path escapes the frozen study"
    )
    return path


def bound_json(root, entry):
    path = contained(root, entry["path"])
    raw = path.read_bytes()
    require(
        sha(raw) == entry["sha256"], f"Frozen artifact digest mismatch: {entry['path']}"
    )
    return json.loads(raw)


def durable_json(path, value):
    """Create once, fsync data and directory; returned digest binds exact bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return sha(raw)


def restore_task_checkpoint(path, expected_sha, bindings, adapter, model, tick_micros):
    """Validate the whole task checkpoint before restoring its adapter state."""
    raw = Path(path).read_bytes()
    require(sha(raw) == expected_sha, "Complete task checkpoint file digest mismatch")
    envelope = json.loads(raw)
    payload = envelope["payload"]
    require(
        sha(canonical(payload)) == envelope["payload_sha256"],
        "Task checkpoint payload digest mismatch",
    )
    require(
        payload["schema"] == "hepta.continuous-boundary.complete-task.v1",
        "Task checkpoint schema mismatch",
    )
    for key, value in bindings.items():
        require(payload.get(key) == value, f"Task checkpoint binding mismatch: {key}")
    elapsed = payload["elapsed_completed"]
    anchor = payload["native_anchor"]
    require(
        isinstance(elapsed, int) and 1 <= elapsed <= model.spec.horizon,
        "Task checkpoint elapsed clock invalid",
    )
    require(anchor["step"] == elapsed, "Native anchor and task step disagree")
    require(
        payload["native_logical_micros"] == elapsed * tick_micros,
        "Native logical clock mismatch",
    )
    require(
        abs(payload["task_physical_time"] - elapsed * model.spec.dt) < 1e-12,
        "Physical task clock mismatch",
    )
    state = np.asarray(payload["adapter_state"], dtype=float)
    require(
        state.shape == (1, 6) and np.isfinite(state).all() and np.max(abs(state)) <= 4,
        "Complete checkpoint lacks bounded six-dimensional adapter state",
    )
    index = payload["state_idx"]
    require(
        isinstance(index, int) and -1 <= index < model.n_states,
        "Task checkpoint state index invalid",
    )
    require(
        isinstance(payload["previous_failed"], bool),
        "Task checkpoint prior event invalid",
    )
    require(
        0 <= payload["previous_action_risk"] <= 1
        and np.isfinite(payload["utility_so_far"]),
        "Task checkpoint risk/utility invalid",
    )
    adapter.reset(batch_size=1)
    adapter.state = state.copy()
    adapter._calls = elapsed
    return payload


def _selected_records(root, manifest):
    arms = [arm for arm in OWNER_ARMS if arm in manifest["arms"]]
    seeds = manifest.get("seeds", manifest.get("seed_ids"))
    splits = [split for split in ("test_id", "test_ood") if split in manifest["splits"]]
    require(arms and seeds and splits, "No scheduled owner-study cases")
    wanted = {
        (arm, int(seed), split, f"{seed}.{split}.c0.p0")
        for seed in seeds
        for split in splits
        for arm in arms
    }
    selected = {}
    for entry in manifest["records"]:
        path = contained(root, entry["path"])
        raw = path.read_bytes()
        require(
            sha(raw) == entry["sha256"], "Frozen scientific records digest mismatch"
        )
        expanded = gzip.decompress(raw) if path.suffix == ".gz" else raw
        if "uncompressed_sha256" in entry:
            require(
                sha(expanded) == entry["uncompressed_sha256"],
                "Uncompressed scientific records digest mismatch",
            )
        count = 0
        for line in expanded.splitlines():
            if not line:
                continue
            record = json.loads(line)
            count += 1
            key = (
                record["arm"],
                int(record["train_seed"]),
                record["split"],
                record["episode_id"],
            )
            if key in wanted:
                require(key not in selected, "Duplicate engineering source episode")
                selected[key] = record
        if "count" in entry:
            require(count == entry["count"], "Scientific record count mismatch")
    require(
        set(selected) == wanted,
        f"Missing selected owner episodes: {sorted(wanted - selected.keys())}",
    )
    return [selected[key] for key in sorted(wanted)]


def _primitive_reward(spec, trace):
    duration = float(trace["active_time"][0])
    production = (
        duration
        if spec.discount == 0
        else -np.expm1(-spec.discount * duration) / spec.discount
    )
    failed = bool(trace["failed"][0])
    loss = (
        spec.failure_cost * np.exp(-spec.discount * float(trace["tau_hit"][0]))
        if failed
        else 0.0
    )
    return (
        spec.production_rate * production
        - loss
        - spec.maintenance_cost * (int(trace["action"][0]) == 1)
    )


def _compare_physics(trace, reference):
    for key in ("failed", "next_state_idx"):
        require(trace[key][0] == reference[key], f"Task outcome mismatch: {key}")
    for key in ("x_after_action", "active_time", "tau_hit"):
        actual, expected = trace[key][0], reference[key]
        require(
            (actual is None and expected is None)
            or (
                actual is not None
                and expected is not None
                and abs(float(actual) - float(expected)) < 2e-12
            ),
            f"Task primitive mismatch: {key}",
        )
    actual, expected = trace["F_after_action"][0], reference["predicted_risk"]
    require(
        (actual is None and expected is None)
        or (
            actual is not None
            and expected is not None
            and abs(float(actual) - float(expected)) < 2e-12
        ),
        "Task conditional risk mismatch",
    )


def _close_bridge(bridge):
    receipt = bridge.close()
    # The frozen bridge owns stdin/stderr; close our remaining read pipe after
    # wait4 without modifying the native/scientific implementation.
    bridge.process.stdout.close()
    return receipt


def _run_episode(
    root,
    output,
    record,
    checkpoint_entry,
    manifest_sha,
    binary,
    binary_sha,
    grid,
    upper,
):
    checkpoint = bound_json(root, checkpoint_entry)
    arm, seed = record["arm"], record["train_seed"]
    require(
        checkpoint["arm"] == arm and checkpoint["seed"] == seed,
        "Actor checkpoint identity mismatch",
    )
    require(
        record["checkpoint_sha256"] == checkpoint_entry["sha256"],
        "Record/actor checkpoint mismatch",
    )
    profile_path = contained(root, checkpoint["profile_path"])
    profile_raw = profile_path.read_bytes()
    require(
        sha(profile_raw) == checkpoint["profile_sha256"],
        "Frozen profile digest mismatch",
    )
    profile = json.loads(profile_raw)
    require(
        profile["arm_id"] == arm and profile["stage"] == "act",
        "Profile arm/stage mismatch",
    )
    require(
        profile["tick_micros"] == 10000,
        "Owner logical clock must use declared 10 ms ticks",
    )
    source = {
        "seed": seed,
        "arm": arm,
        "candidate": checkpoint["candidate"],
        "boundary_weights": checkpoint["boundary_weights"],
        "encoder_seed": "common-frozen-encoder",
        "adapter_schema": "continuous-flow-adapter.v1",
    }
    require(
        profile["source_model_digest"] == sha(canonical(source)),
        "Profile/adapter model binding mismatch",
    )
    spec = TaskSpec(**record["spec"])
    prepare = CostWindow()
    model = build_model(spec, n_grid=grid, x_max=upper)
    dp = {"x": model.x} if arm == "fixed_margin" else solve_dp(model)
    preparation_cost = prepare.finish()
    make_adapter = lambda: ActorAdapter(
        spec, dp, arm, checkpoint["candidate"], seed, checkpoint["boundary_weights"]
    )
    adapter = make_adapter()
    reference_steps = record["steps"]
    require(reference_steps, "Cannot re-execute an empty scientific episode")
    case = f"owner.{record['episode_id']}.{arm}"
    directory = output / "cases" / case
    directory.mkdir(parents=True, exist_ok=False)
    bindings = {
        "episode_id": record["episode_id"],
        "arm": arm,
        "train_seed": seed,
        "manifest_sha256": manifest_sha,
        "source_record_sha256": sha(canonical(record)),
        "actor_checkpoint_sha256": checkpoint_entry["sha256"],
        "profile_sha256": checkpoint["profile_sha256"],
        "binary_sha256": binary_sha,
        "spec_sha256": sha(canonical(asdict(spec))),
        "grid_sha256": sha(canonical({"states": grid, "upper": upper})),
    }
    state = int(reference_steps[0]["state_idx"])
    previous_failed, previous_risk, utility = False, 0.0, 0.0
    cut = min(3, max(1, len(reference_steps) // 2))
    costs, rows, resumes, stop_guards = [], [], [], []
    bridge = None
    try:
        bridge = NativeBridge(
            binary, directory / "host", expected_binary_sha256=binary_sha
        )
        bridge.load_profile(profile_path, checkpoint["profile_sha256"])
        opened = bridge.open(case, seed, checkpoint["profile_sha256"])
        require(opened["status"]["step"] == 0, "Fresh owner already has state")
        for elapsed, reference in enumerate(reference_steps):
            require(
                reference["elapsed"] == elapsed and reference["state_idx"] == state,
                "Physical replay frontier mismatch",
            )
            require(
                state >= 0 and elapsed < spec.horizon,
                "Task consumer advanced after stop/deadline",
            )
            values = adapter.step(
                [state], spec.horizon - elapsed, [previous_failed], [previous_risk]
            )
            typed = features(
                values["raw"][0],
                margin=values["margin"][0],
                risk=values["risk"][0],
                flow=values["flow"][0],
            )
            require(
                typed == reference["raw_features"],
                "Fast-path/owner typed features mismatch",
            )
            evidence = sha(
                canonical(
                    {
                        **bindings,
                        "elapsed": elapsed,
                        "state_idx": state,
                        "previous_failed": previous_failed,
                        "previous_risk": previous_risk,
                    }
                )
            )
            native = bridge.tick(typed, evidence_digest=evidence)
            require(
                native["activation_q24"] == reference["activation_q24"],
                "Actual sparse activation mismatch",
            )
            require(
                native["readout"]["scores_q24"] == reference["scores_q24"],
                "Native readout scores mismatch",
            )
            effective = native["effective_action"]
            require(effective in ACTIONS, "Native owner did not select a task action")
            action = ACTIONS.index(effective)
            require(
                ("wait", "repair", "stop")[action] == reference["action"],
                "Native effective task action mismatch",
            )
            require(
                native["readout"]["action"] == effective,
                "Owner abstention changed fast-path action",
            )
            trace = sample_step(
                model,
                [state],
                [action],
                uniforms=np.asarray([reference["uniforms"][1:]]),
            )
            _compare_physics(trace, reference)
            reward = float(_primitive_reward(spec, trace))
            require(
                abs(reward - float(trace["reward"][0])) < 2e-12,
                "Primitive reward/step implementation mismatch",
            )
            utility += model.gamma**elapsed * reward
            state = int(trace["next_state_idx"][0])
            previous_failed = bool(trace["failed"][0])
            previous_risk = float(trace["F_after_action"][0] or 0.0)
            rows.append(
                {
                    "elapsed": elapsed,
                    "native_logical_micros": (elapsed + 1) * profile["tick_micros"],
                    "task_physical_time": (elapsed + 1) * spec.dt,
                    "typed_features": typed,
                    "native_output": native,
                    "physical": {key: value.tolist() for key, value in trace.items()},
                    "discounted_reward": model.gamma**elapsed * reward,
                    "utility_so_far": utility,
                }
            )
            if elapsed + 1 == cut:
                payload = {
                    "schema": "hepta.continuous-boundary.complete-task.v1",
                    **bindings,
                    "elapsed_completed": elapsed + 1,
                    "state_idx": state,
                    "adapter_state": adapter.state.tolist(),
                    "previous_failed": previous_failed,
                    "previous_action_risk": previous_risk,
                    "utility_so_far": utility,
                    "native_anchor": dict(bridge.current),
                    "native_logical_micros": (elapsed + 1) * profile["tick_micros"],
                    "task_physical_time": (elapsed + 1) * spec.dt,
                }
                packet = {"payload": payload, "payload_sha256": sha(canonical(payload))}
                packet_path = directory / "TASK_CHECKPOINT.json"
                packet_sha = durable_json(packet_path, packet)
                old_pid = bridge.process.pid
                costs.append(_close_bridge(bridge))
                bridge = None
                adapter = (
                    make_adapter()
                )  # Restore a fresh instance, not retained memory.
                saved = restore_task_checkpoint(
                    packet_path,
                    packet_sha,
                    bindings,
                    adapter,
                    model,
                    profile["tick_micros"],
                )
                state, previous_failed = saved["state_idx"], saved["previous_failed"]
                previous_risk, utility = (
                    saved["previous_action_risk"],
                    saved["utility_so_far"],
                )
                bridge = NativeBridge(
                    binary, directory / "host", expected_binary_sha256=binary_sha
                )
                bridge.load_profile(profile_path, checkpoint["profile_sha256"])
                restored = bridge.open(
                    case, seed, checkpoint["profile_sha256"], resume=True
                )
                status = restored["status"]
                require(
                    status["checkpoint"] == saved["native_anchor"]["checkpoint"]
                    and status["step"] == saved["native_anchor"]["step"],
                    "Cold native/task checkpoint frontier mismatch",
                )
                require(
                    status["case"] == case
                    and status["seed"] == seed
                    and status["arm"] == arm,
                    "Cold owner case/model identity mismatch",
                )
                require(
                    status["terminal"] == (state < 0),
                    "Cold terminal task/owner mismatch",
                )
                resumes.append(
                    {
                        "checkpoint_sha256": packet_sha,
                        "closed_pid": old_pid,
                        "new_pid": bridge.process.pid,
                        "restored": restored,
                        "adapter_state_sha256": sha(canonical(adapter.state.tolist())),
                        "native_clock_micros": saved["native_logical_micros"],
                        "task_clock": saved["task_physical_time"],
                        "continued_steps": len(reference_steps) - cut,
                    }
                )
            if state < 0:
                before = bridge.rpc({"command": "Status"})
                rejection = bridge.rpc(
                    {
                        "command": "Tick",
                        "observation": {
                            "event_id": f"{case}.after-stop",
                            "step": bridge.current["step"] + 1,
                            "checkpoint": bridge.current["checkpoint"],
                            "features": typed,
                            "evidence_digest": sha(b"forbidden-after-stop-probe"),
                        },
                    },
                    allow_error=True,
                )
                after = bridge.rpc({"command": "Status"})
                require(
                    not rejection.get("ok", True)
                    and "Terminal episode" in rejection["error"],
                    "Native owner failed to reject a post-STOP tick",
                )
                require(before == after, "Post-STOP probe mutated the durable owner")
                stop_guards.append(
                    {"before": before, "rejection": rejection, "after": after}
                )
        require(
            state < 0 or len(reference_steps) == spec.horizon,
            "Scientific source stopped before task end without STOP",
        )
        require(
            abs(utility - record["reported_utility"]) < 2e-10,
            "Owner task utility differs from scientific fast path",
        )
        result = {
            "passed": True,
            **bindings,
            "case": case,
            "steps": len(rows),
            "utility": utility,
            "reference_utility": record["reported_utility"],
            "cold_resumes": len(resumes),
            "continued_after_resume": len(reference_steps) - cut,
            "terminal_checkpoint_only": len(reference_steps) == cut,
            "stop_guards": len(stop_guards),
            "model_preparation_cost": preparation_cost,
            "scope_dependent_hash_parity_claimed": False,
        }
    except Exception as error:
        result = {
            "passed": False,
            **bindings,
            "case": case,
            "steps": len(rows),
            "error": f"{type(error).__name__}: {error}",
            "model_preparation_cost": preparation_cost,
        }
    finally:
        if bridge is not None:
            costs.append(_close_bridge(bridge))
        durable_json(directory / "PROCESS_COSTS.json", costs)
        durable_json(directory / "COLD_RESUME.json", resumes)
        durable_json(directory / "STOP_GUARDS.json", stop_guards)
        with (directory / "TASK_TRACE.jsonl").open("xb") as stream:
            for row in rows:
                stream.write(canonical(row) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    result["native_process_costs"] = costs
    durable_json(directory / "RESULT.json", result)
    return result


def run_owner_study(run_dir, binary, output):
    """Run 6 arms x 2 splits x each frozen seed; mini manifests are supported."""
    root, output = Path(run_dir).resolve(), Path(output).resolve()
    manifest_raw = (root / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    manifest_sha = sha(manifest_raw)
    require(
        manifest.get("schema") == "hepta.continuous-boundary.study.v1",
        "Unsupported frozen study manifest",
    )
    require(
        not (output / "SUMMARY.json").exists(), "Owner-study output already committed"
    )
    output.mkdir(parents=True, exist_ok=True)
    protocol = manifest
    if "protocol_sha256" in manifest:
        protocol = bound_json(
            root,
            {
                "path": manifest.get("protocol_path", "protocol.json"),
                "sha256": manifest["protocol_sha256"],
            },
        )
    grid = manifest.get("grid_states", protocol.get("grid_states"))
    upper = manifest.get("grid_upper_domain", protocol.get("grid_upper_domain"))
    require(
        isinstance(grid, int) and grid >= 8 and upper is not None,
        "Frozen task grid/domain missing",
    )
    binary = Path(binary).resolve()
    binary_sha = sha(binary.read_bytes())
    selected = _selected_records(root, manifest)
    checkpoints = {
        (entry["arm"], int(entry["train_seed"])): entry
        for entry in manifest["checkpoints"]
    }
    require(
        len(checkpoints) == len(manifest["checkpoints"]),
        "Duplicate frozen actor checkpoint",
    )
    window = CostWindow()
    results = []
    for record in selected:
        key = (record["arm"], int(record["train_seed"]))
        require(
            key in checkpoints, "Selected owner episode lacks frozen actor checkpoint"
        )
        results.append(
            _run_episode(
                root,
                output,
                record,
                checkpoints[key],
                manifest_sha,
                binary,
                binary_sha,
                grid,
                float(upper),
            )
        )
    require(
        (root / "manifest.json").read_bytes() == manifest_raw,
        "Scientific manifest changed during owner study",
    )
    receipts = [
        receipt for result in results for receipt in result["native_process_costs"]
    ]
    counters = (
        {
            key: sum(r["counters"].get(key, 0) for r in receipts)
            for key in receipts[0]["counters"]
        }
        if receipts
        else {}
    )
    summary = {
        "schema": "hepta.continuous-boundary.durable-task-study.v1",
        "passed": all(r["passed"] for r in results),
        "manifest_sha256": manifest_sha,
        "binary_sha256": binary_sha,
        "engineering_episode_count": len(results),
        "scientific_incremental_sample_count": 0,
        "selection": "each seed, test_id/test_ood, context0/path0, declared six arms",
        "cold_resumes": sum(r.get("cold_resumes", 0) for r in results),
        "continued_after_resume_episodes": sum(
            r.get("continued_after_resume", 0) > 0 for r in results
        ),
        "terminal_only_resume_episodes": sum(
            r.get("terminal_checkpoint_only", False) for r in results
        ),
        "stop_rejection_checks": sum(r.get("stop_guards", 0) for r in results),
        "native_logical_tick_micros": 10000,
        "task_clock": "elapsed decisions * TaskSpec.dt",
        "native_total_counters": counters,
        "cost": window.finish(),
        "child_cpu_seconds": sum(r["child_cpu_seconds"] for r in receipts),
        "max_child_rss_kib": max((r["child_max_rss_kib"] for r in receipts), default=0),
        "hardware_energy_measured": False,
        "results": [
            {k: v for k, v in row.items() if k != "native_process_costs"}
            for row in results
        ],
    }
    durable_json(output / "SUMMARY.json", summary)
    return summary
