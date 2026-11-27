"""Frozen identity, paired data, and scheduling for the separate mechanism pilot."""

import hashlib
import json
import math
import os
import time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np


ARMS = ("regenerative_dual", "smooth_dual", "margin_only", "call_only", "risk_only",
        "endpoint", "no_reset", "no_refractory", "uniform_tick", "conditional_boundary")
TASKS = ("delayed_recall", "adding")
DT = (.025, .05, .075, .1)
STATE_COUNT = 81
EXPECTED_PARAMETERS = 34 * STATE_COUNT + 136
RUNNER_FILES = ("mechanism_contract.py", "mechanism_model.py", "mechanism_worker.py",
                "mechanism_training.py", "__init__.py")
ENVIRONMENT_KEYS = ("python", "numpy", "torch", "cuda_build", "device", "cpu_threads", "deterministic_algorithms")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.with_name(path.name + f".tmp-{os.getpid()}-{time.monotonic_ns()}")
    try:
        with target.open("x") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(target, path)
        else:
            os.link(target, path)  # Atomic publication and exclusive destination creation.
    finally:
        target.unlink(missing_ok=True)


def seed_for(*parts):
    return int.from_bytes(hashlib.sha256(canonical(parts)).digest()[:8], "little")


def ordered_roster(plan):
    """PCG64 arm shuffle per task/fit seed; both LRs remain consecutive."""
    rows = []
    for task in plan["tasks"]:
        for seed in plan["training_seeds"]:
            rng = np.random.Generator(np.random.PCG64(seed_for(plan["schedule_seed"], task, seed, "arm-order")))
            for arm in rng.permutation(plan["arms"]).tolist():
                for lr_index, lr in enumerate(plan["learning_rates"]):
                    index = len(rows)
                    rows.append(dict(index=index, fit_id=f"fit-{index:03d}", task=task,
                                     training_seed=seed, arm=arm, learning_rate=lr, lr_index=lr_index,
                                     group_id=f"{task}-seed-{seed}"))
    return rows


def verify_sources(pins, root=None):
    root = Path(root or Path(__file__).resolve().parents[2]).resolve()
    if not isinstance(pins, dict) or not pins:
        raise ValueError("Missing frozen source pins")
    observed = {}
    for name, expected in pins.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Invalid source pin path: " + name)
        observed[name] = file_sha(path)
        if observed[name] != expected:
            raise ValueError("Source drift: " + name)
    return observed


def validate_plan(plan):
    expected = dict(schema="hcsn-mechanism-pilot-plan-v1", status="FROZEN", arms=list(ARMS),
                    tasks=list(TASKS), training_seeds=[1103, 2207, 3301, 4409],
                    learning_rates=[.001, .003], test_episode_seeds=[4703, 5801],
                    sequence_length=64, batch_size=64, train_updates=400, train_count=2048,
                    validation_count=512, test_count=1024, split_seed=20261107,
                    max_fit_wall_seconds=480, mass_tolerance=5e-5, schedule_seed=78137,
                    state_count=STATE_COUNT, expected_parameter_count=EXPECTED_PARAMETERS,
                    latency_warmup=10, latency_repeats=100, throughput_batch=64, throughput_repeats=20)
    for key, value in expected.items():
        if plan.get(key) != value:
            raise ValueError("Frozen pilot contract mismatch: " + key)
    if not isinstance(plan.get("study_id"), str) or not plan["study_id"]:
        raise ValueError("Missing independent study identity")
    roster = ordered_roster(plan)
    if plan.get("ordered_fit_roster_sha256") != digest(roster):
        raise ValueError("Ordered 160-fit roster hash mismatch")
    for name in RUNNER_FILES:
        if "qualification/hcsn_regenerative/" + name not in plan.get("source_pins", {}):
            raise ValueError("Runner source not pinned: " + name)
    if not set(plan["training_seeds"]).isdisjoint(plan["test_episode_seeds"]):
        raise ValueError("Training and episode seeds are distinct identities")
    expected_environment = plan.get("execution_environment")
    if not isinstance(expected_environment, dict) or any(key not in expected_environment for key in ENVIRONMENT_KEYS):
        raise ValueError("Missing qualified frozen execution environment")
    construction = plan.get("bundle_construction_environment")
    if not isinstance(construction, dict) or any(key not in construction for key in ("schema", "python", "numpy", "scipy")):
        raise ValueError("Missing frozen bundle construction environment")
    return roster


def validate_execution_environment(plan, observed, metadata):
    """A provider/lease change cannot silently introduce a different environment."""
    expected = plan.get("execution_environment")
    if not isinstance(expected, dict):
        raise ValueError("Missing frozen execution environment")
    for key in ENVIRONMENT_KEYS:
        if key not in expected or observed.get(key) != expected[key]:
            raise ValueError("Execution environment mismatch: " + key)
    if str(observed["device"]).startswith("cuda"):
        expected_gpu, actual_gpu = expected.get("gpu", {}), observed.get("gpu", {})
        for key in ("name", "total_memory", "compute_capability"):
            if key not in expected_gpu or actual_gpu.get(key) != expected_gpu[key]:
                raise ValueError("Execution GPU mismatch: " + key)
        policy = expected.get("gpu_uuid_policy")
        if policy == "pinned":
            if not expected.get("allowed_gpu_uuids") or actual_gpu.get("uuid") not in expected["allowed_gpu_uuids"]:
                raise ValueError("Execution GPU UUID is not frozen/allowed")
        elif policy != "same_model_new_lease":
            raise ValueError("GPU UUID change requires an explicit frozen lease policy")
    elif expected.get("gpu_uuid_policy") != "not_applicable":
        raise ValueError("CPU execution requires the explicit not_applicable GPU UUID policy")
    construction = plan.get("bundle_construction_environment", {})
    for key in ("schema", "python", "numpy", "scipy"):
        if key not in construction or metadata.get(key) != construction[key]:
            raise ValueError("Bundle construction environment mismatch: " + key)
    return dict(matched=True, execution_environment=expected,
                observed_device_uuid=observed.get("gpu", {}).get("uuid"),
                bundle_construction_environment=construction,
                scope="Exact qualified software/device class; new lease UUID only under the frozen policy")


def load_contract(bundle_path, plan_path):
    bundle_path, plan_path = Path(bundle_path), Path(plan_path)
    metadata_path = bundle_path.with_suffix(".json")
    plan, metadata = read_json(plan_path), read_json(metadata_path)
    roster = validate_plan(plan)
    bundle_sha, metadata_sha = file_sha(bundle_path), file_sha(metadata_path)
    if plan.get("bundle_sha256") != bundle_sha or plan.get("bundle_metadata_sha256") != metadata_sha:
        raise ValueError("Bundle or metadata hash mismatch")
    if (metadata.get("schema") != "hcsn-mechanism-operator-bundle-v1"
            or metadata.get("state_count") != plan["state_count"] or metadata.get("dt_choices") != list(DT)
            or set(metadata.get("arms", {})) != set(ARMS)
            or metadata.get("bundle_sha256") != bundle_sha):
        raise ValueError("Incomplete ten-arm bundle")
    verify_sources(plan["source_pins"])
    verify_sources(metadata["source_pins"])
    arrays = {}
    state_count = plan["state_count"]
    shapes = {"matrix": (2, 4, state_count, state_count), "first_step": (2, 4, state_count), "features": (2, 4, state_count, 3)}
    with np.load(bundle_path, allow_pickle=False) as archive:
        required = {arm + "__" + kind for arm in ARMS for kind in shapes}
        if set(archive.files) != required:
            raise ValueError("Bundle array roster differs from all ten arms")
        for arm in ARMS:
            channel = {"margin_only": "margin", "call_only": "call", "risk_only": "risk"}.get(arm, "dual")
            if metadata["arms"][arm].get("channel") != channel:
                raise ValueError("Mechanism channel mismatch: " + arm)
            for kind, shape in shapes.items():
                key = arm + "__" + kind
                value = archive[key]
                if value.dtype != np.float32 or value.shape != shape or not np.isfinite(value).all() or np.any(value < 0):
                    raise ValueError("Invalid FP32 operator: " + key)
                if hashlib.sha256(value.tobytes()).hexdigest() != metadata.get("array_sha256", {}).get(key):
                    raise ValueError("Unbound array: " + key)
                if kind in ("matrix", "first_step") and np.max(np.abs(value.astype(np.float64).sum(-1) - 1)) > plan["mass_tolerance"]:
                    raise ValueError("Unconditioned operator mass defect: " + key)
                if kind == "features" and np.max(value[..., 2]) > 1 + plan["mass_tolerance"]:
                    raise ValueError("Risk outside probability domain")
                if arm != "conditional_boundary" and not np.array_equal(value[0], value[1]):
                    raise ValueError("Unregistered cohort dependence: " + key)
                arrays[key] = value.copy()
    identity = dict(study_id=plan["study_id"], plan_sha256=file_sha(plan_path),
                    bundle_sha256=bundle_sha, bundle_metadata_sha256=metadata_sha,
                    source_pins=plan["source_pins"], ordered_fit_roster_sha256=digest(roster),
                    state_count=state_count, expected_parameter_count=plan["expected_parameter_count"],
                    registered_fit_count=len(roster), registered_training_updates=len(roster) * plan["train_updates"],
                    original_campaign_completion_credit=0)
    return plan, metadata, arrays, roster, identity


def make_data(plan, task, split, episode_seed=None):
    """Common independent split data; no model or training seed enters this RNG."""
    if task not in TASKS or split not in ("train", "validation", "test"):
        raise ValueError("Unknown task/split")
    if (split == "test") != (episode_seed is not None):
        raise ValueError("Only test data requires an evaluation episode seed")
    count = plan[{"train": "train_count", "validation": "validation_count", "test": "test_count"}[split]]
    length = plan["sequence_length"]
    content_rng = np.random.default_rng(seed_for(plan["split_seed"], task, split, episode_seed, "content"))
    time_rng = np.random.default_rng(seed_for(plan["split_seed"], task, split, episode_seed, "time"))
    x = np.zeros((count, length, 3), dtype=np.float32)
    x[..., 0] = content_rng.uniform(-1 if task == "delayed_recall" else 0, 1, (count, length))
    if task == "delayed_recall":
        x[:, 0, 1] = 1
        y = x[:, 0, :1].copy()
    else:
        first = content_rng.integers(0, length // 2, count)
        second = content_rng.integers(length // 2, length, count)
        row = np.arange(count)
        x[row, first, 1] = 1
        x[row, second, 1] = 1
        y = (x[row, first, 0] + x[row, second, 0])[:, None]
    indices = time_rng.integers(0, len(DT), (count, length), dtype=np.int64)
    x[..., 2] = np.asarray(DT, dtype=np.float32)[indices]
    arrays = dict(x=x, y=y, dt_indices=indices)
    hashes = {name: hashlib.sha256(value.tobytes()).hexdigest() for name, value in arrays.items()}
    receipt = dict(task=task, split=split, episode_seed=episode_seed, split_seed=plan["split_seed"],
                   count=count, sequence_length=length, array_sha256=hashes,
                   shapes={k: list(v.shape) for k, v in arrays.items()},
                   dtypes={k: str(v.dtype) for k, v in arrays.items()},
                   physical_time_min=float((indices + 1).sum(-1).min() / 40),
                   physical_time_max=float((indices + 1).sum(-1).max() / 40),
                   physical_time_definition="Exact duration indices: sum(dt_index + 1) / 40 seconds",
                   represented_feature_sum_min=float(x[..., 2].sum(-1).min()),
                   represented_feature_sum_max=float(x[..., 2].sum(-1).max()))
    receipt["data_identity_sha256"] = digest(receipt)
    return arrays, receipt


def batch_order(plan, fit):
    rng = np.random.default_rng(seed_for(plan["split_seed"], fit["task"], fit["training_seed"], "batch-order"))
    pending = np.empty(0, dtype=np.int64)
    for _ in range(plan["train_updates"]):
        while len(pending) < plan["batch_size"]:
            pending = np.concatenate((pending, rng.permutation(plan["train_count"])))
        yield pending[:plan["batch_size"]]
        pending = pending[plan["batch_size"]:]


def select_group(plan, fits, terminals, identity):
    """Produce one lock before any test, retaining incomplete tuning pairs."""
    selected, missing = {}, {}
    for arm in plan["arms"]:
        pair = sorted((fit for fit in fits if fit["arm"] == arm), key=lambda x: x["lr_index"])
        valid = [fit for fit in pair if terminals.get(fit["fit_id"], {}).get("status") == "COMPLETED"
                 and terminals[fit["fit_id"]].get("optimizer_updates_completed") == plan["train_updates"]
                 and (terminals[fit["fit_id"]].get("validation") or {}).get("count") == plan["validation_count"]
                 and math.isfinite(terminals[fit["fit_id"]]["validation"].get("mse", math.nan))]
        if len(pair) != len(plan["learning_rates"]) or len(valid) != len(pair):
            missing[arm] = [dict(fit_id=fit["fit_id"], status=terminals.get(fit["fit_id"], {}).get("status", "UNSTARTED")) for fit in pair]
            continue
        best = min(valid, key=lambda f: (terminals[f["fit_id"]]["validation"]["mse"], f["lr_index"]))
        terminal = terminals[best["fit_id"]]
        selected[arm] = dict(fit_id=best["fit_id"], learning_rate=best["learning_rate"],
                             validation_mse=terminal["validation"]["mse"], checkpoint_sha256=terminal["checkpoint_sha256"],
                             terminal_sha256=digest(terminal))
    candidates = [arm for arm in plan["arms"] if arm != "regenerative_dual" and arm in selected]
    best_other = min(candidates, key=lambda a: (selected[a]["validation_mse"], plan["arms"].index(a))) if candidates else None
    complete = not missing and len(selected) == len(plan["arms"])
    return dict(schema="hcsn-mechanism-selection-lock-v1", identity=identity,
                group_id=fits[0]["group_id"], task=fits[0]["task"], training_seed=fits[0]["training_seed"],
                selected=selected, incomplete_tuning_pairs=missing,
                strongest_registered_comparator=best_other if complete else None,
                best_available_comparator=best_other, strongest_full_registered_set_eligible=complete,
                all_registered_arms_selected=complete,
                selection_basis="validation MSE only; ties: registered arm order, then LR order",
                episode_seeds=plan["test_episode_seeds"], test_has_started=False)
