"""Measure frozen policies on a separate, closed-loop development workload.

An instance is an independent policy state and task ledger in one CPU batch.
Instances share checkpoint weights and a Python process; they are not Hepta
Cells, independent servers, or biological neurons. No oracle is in the timed
path. This module does not modify the previously frozen experiment sources.
"""

from datetime import datetime, timezone
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

import numpy as np
import torch

from .evaluate import load_policy, numeric_state_storage, validate_selection
from .models import make_policy
from .task import (OutputPulseQueue, exogenous, legal_actions, make_scenario,
                   scenario_digest, settle_output_pulses, state_features, transition)


ROOT = Path(__file__).resolve().parent
VARIANTS = ("rr_full", "ctrnn_state_cpu", "alif", "resource_lif")
TRAINING_SEEDS = (101, 211, 307, 401, 503)
INSTANCE_COUNTS = (64, 256, 1024, 4096)
WARMUP_EPISODES = 2
MEASURED_EPISODES = 5
SCENARIO_SEED = 86241001
LATENT_SEED = 86242001
QUERY_SEED = 86243001
MINIMUM_FREE_BYTES = 200*1024*1024
SOURCES = ("policy_benchmark.py", "models.py", "operators.py", "baselines.py",
           "task.py", "evaluate.py", "prepare_data.py")
DESIGN_PATH = ROOT/"policy_benchmark_design.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def write_once(path, value):
    path = Path(path)
    encoded = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n").encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"Refusing to replace a different benchmark artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


def resource_snapshot():
    result = {"disk_free_bytes": shutil.disk_usage(ROOT).free,
              "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
              "cpu_affinity": sorted(os.sched_getaffinity(0))}
    for name in ("memory.current", "memory.max", "memory.events"):
        path = Path("/sys/fs/cgroup")/name
        try:
            value = path.read_text().strip()
            result[name] = ({k: int(v) for k, v in (row.split() for row in value.splitlines())}
                            if name == "memory.events" else (value if value == "max" else int(value)))
        except (OSError, ValueError) as error:
            result[name] = None
            result[name+"_error"] = str(error)
    return result


def resource_quality(before, after):
    initial, final = before.get("memory.events"), after.get("memory.events")
    if initial is None or final is None:
        return {"status": "unknown", "attributed_to_this_policy": False}
    delta = {key: final.get(key, 0)-initial.get(key, 0) for key in ("max", "oom", "oom_kill")}
    return {"status": "shared_cgroup_pressure_observed" if any(v > 0 for v in delta.values())
            else "no_new_cgroup_limit_event_observed",
            "limit_event_deltas": delta, "attributed_to_this_policy": False}


def check_disk():
    available = shutil.disk_usage(ROOT).free
    if available < MINIMUM_FREE_BYTES:
        raise RuntimeError(f"Benchmark disk guard: {available} bytes free, need {MINIMUM_FREE_BYTES}")


def source_hashes():
    return {name: sha(ROOT/name) for name in SOURCES}


def state_dict_digest(model):
    result = hashlib.sha256()
    for name, tensor in model.state_dict().items():
        array = tensor.detach().cpu().contiguous().numpy()
        result.update(name.encode())
        result.update(str(array.dtype).encode())
        result.update(json.dumps(list(array.shape)).encode())
        result.update(array.tobytes())
    return result.hexdigest()


def workload(count):
    """Prefix-stable development scenarios, never train/validation/test files."""
    if count < 1:
        raise ValueError("Positive policy instance count required")
    random = np.random.default_rng(SCENARIO_SEED)
    scenarios = [make_scenario(random, split="development") for _ in range(count)]
    schedule = [scenario.events() for scenario in scenarios]
    identity = {"scenario_seed": SCENARIO_SEED, "policy_instances": count,
                "scenario_sha256": digest([scenario_digest(scenario) for scenario in scenarios]),
                "schedule_sha256": digest(schedule),
                "observations_per_episode": sum(map(len, schedule)),
                "distinct_public_schedules": len(set(schedule)),
                "raw_input_features": 22, "actions": 81,
                "source": "Separate generated development performance workload; no task data split is loaded.",
                "causal_scope": "Exogenous values/deadlines/resource events and public observation schedules are common. Live items and remaining budget follow each policy's own actions."}
    return scenarios, schedule, identity


def distribution(samples):
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("A finite nonnegative timing sample is required")
    quantiles = np.quantile(values, [.5, .95, .99], method="linear")
    return {"samples": len(values), "mean": float(values.mean()), "minimum": float(values.min()),
            "p50": float(quantiles[0]), "p95": float(quantiles[1]), "p99": float(quantiles[2]),
            "maximum": float(values.max()), "quantile_method": "linear empirical quantile"}


@torch.no_grad()
def closed_loop(model, scenarios, schedule, *, latent_seed, query_seed, retain_outcomes=False):
    """Time a whole actor/task episode and its constituent batched model calls.

    Full-loop timing includes reset, task queues, observation construction,
    legal-action selection, actual model events, ledger transitions, delivery,
    terminal query settlement, and invariant/count checks. Source/weight hashes,
    state-storage inspection, JSON serialization, and data generation are outside
    the timed region. Internal spike timestamps are not materialized.
    """
    count = len(scenarios)
    if not count or len(schedule) != count:
        raise ValueError("Nonempty scenario/schedule batch required")
    begun_wall, begun_cpu = time.perf_counter_ns(), time.process_time_ns()
    rng = np.random.default_rng(latent_seed)
    init_wall, init_cpu = time.perf_counter_ns(), time.process_time_ns()
    state = model.initial_state(count, rng)
    initialization_wall = time.perf_counter_ns()-init_wall
    initialization_cpu = time.process_time_ns()-init_cpu
    lives = np.asarray([scenario.initial_live for scenario in scenarios], dtype=np.int64)
    budgets = np.asarray([scenario.budget for scenario in scenarios], dtype=np.int64)
    initial_budgets = budgets.copy()
    removed, added, spent, renewed, dropped = [np.zeros(count, dtype=np.int64) for _ in range(5)]
    queues = [OutputPulseQueue(scenario) for scenario in scenarios]
    last = np.zeros(count)
    latent_counts = np.zeros(count, dtype=np.int64)
    step_wall, step_cpu, step_sizes = [], [], []
    action_hash = hashlib.sha256()
    action_rows = []
    for index in range(max(map(len, schedule))):
        observations = np.zeros((count, 22), dtype=np.float32)
        elapsed = np.zeros(count, dtype=np.float32)
        mask = np.zeros(count, dtype=bool)
        legal = np.zeros((count, 81), dtype=bool)
        legal[:, 0] = True
        for row, scenario in enumerate(scenarios):
            if index >= len(schedule[row]):
                continue
            now = schedule[row][index]
            mask[row] = True
            elapsed[row], last[row] = now-last[row], now
            queues[row].advance(now)
            budgets[row], loss, refill = exogenous(scenario, now, int(budgets[row]))
            removed[row] += loss
            added[row] += refill
            observations[row] = state_features(scenario, now, int(lives[row]), int(budgets[row]))
            legal[row], _ = legal_actions(scenario, now, int(lives[row]), int(budgets[row]))
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        state, output = model.step(state, torch.from_numpy(observations), torch.from_numpy(elapsed),
                                   rng, event_mask=torch.from_numpy(mask), record_spikes=False)
        step_cpu.append((time.process_time_ns()-cpu)/1e9)
        step_wall.append((time.perf_counter_ns()-wall)/1e9)
        step_sizes.append(int(mask.sum()))
        logits = output["logits"].detach().cpu().numpy()
        counts = output["actual_counts"].detach().cpu().numpy()
        if logits.shape != (count, 81) or not np.isfinite(logits).all():
            raise ValueError("Malformed task logits")
        if (counts.shape != (count, 8) or not np.isfinite(counts).all() or (counts < 0).any()
                or not np.equal(counts, np.floor(counts)).all() or (counts[~mask] != 0).any()):
            raise ValueError("Malformed actual internal spike counts")
        latent_counts += counts.sum(axis=1).astype(np.int64)
        actions = np.argmax(np.where(legal, logits, -np.inf), axis=1)
        action_hash.update(actions.astype("<i2").tobytes())
        if retain_outcomes:
            action_rows.append(actions.copy())
        for row in np.flatnonzero(mask):
            scenario, now = scenarios[row], schedule[row][index]
            live, budget, _, info = transition(scenario, now, int(lives[row]), int(budgets[row]), int(actions[row]))
            lives[row], budgets[row] = live, budget
            queues[row].enqueue(info["outputs"])
            spent[row] += info["cost"]
            renewed[row] += info["renewals"]
            dropped[row] += info["dropped"]
    if (not np.array_equal(budgets, initial_budgets+added-removed-spent)
            or (budgets < 0).any() or any(queue.pending for queue in queues)):
        raise AssertionError("Closed-loop task conservation or delivery invariant failed")
    # The actor has finished before these observer-only outcomes are drawn.
    query_bits = np.random.default_rng(query_seed).random((count, 4)) < .75
    expected = np.empty(count)
    realized = np.empty(count)
    emissions = np.empty(count, dtype=np.int64)
    for row, scenario in enumerate(scenarios):
        settlement = settle_output_pulses(scenario, queues[row].delivered, query_bits[row])
        expected[row], realized[row] = settlement["expected_utility"], settlement["realized_utility"]
        emissions[row] = len(settlement["delivered"])
    total_cpu = (time.process_time_ns()-begun_cpu)/1e9
    total_wall = (time.perf_counter_ns()-begun_wall)/1e9
    result = {"full_episode_wall_seconds": total_wall, "full_episode_cpu_seconds": total_cpu,
              "model_initialization_wall_seconds": initialization_wall/1e9,
              "model_initialization_cpu_seconds": initialization_cpu/1e9,
              "model_step_wall_seconds": step_wall, "model_step_cpu_seconds": step_cpu,
              "model_step_active_instances": step_sizes,
              "actual_internal_spikes": int(latent_counts.sum()),
              "communication_output_pulses": int(emissions.sum()),
              "budget_spent": int(spent.sum()), "renewals": int(renewed.sum()),
              "dropped_items": int(dropped.sum()), "action_sha256": action_hash.hexdigest(),
              "outcome_sha256": digest({"expected": expected.tolist(), "realized": realized.tolist(),
                                        "emissions": emissions.tolist(), "budget": budgets.tolist(),
                                        "latent_counts": latent_counts.tolist()}),
              "state_storage": numeric_state_storage(state, count),
              "invariants_passed": True, "latent_seed": latent_seed, "query_seed": query_seed}
    if retain_outcomes:
        result["outcomes"] = {"expected_utility": expected.tolist(), "realized_utility": realized.tolist(),
                              "budget_final": budgets.tolist(), "emissions": emissions.tolist(),
                              "internal_spikes": latent_counts.tolist(),
                              "actions": np.stack(action_rows, axis=1).tolist()}
    return result


def summarize(records, count):
    walls = [sample for record in records for sample in record["model_step_wall_seconds"]]
    cpus = [sample for record in records for sample in record["model_step_cpu_seconds"]]
    active = [sample for record in records for sample in record["model_step_active_instances"]]
    full_wall = sum(record["full_episode_wall_seconds"] for record in records)
    full_cpu = sum(record["full_episode_cpu_seconds"] for record in records)
    observations = sum(active)
    return {"batch_observation_wall_seconds": distribution(walls),
            "batch_observation_cpu_seconds": distribution(cpus),
            "batch_episode_wall_seconds": distribution([r["full_episode_wall_seconds"] for r in records]),
            "batch_episode_cpu_seconds": distribution([r["full_episode_cpu_seconds"] for r in records]),
            "amortized_policy_observation_wall_seconds": distribution(np.asarray(walls)/np.asarray(active)),
            "model_only_policy_observations_per_wall_second": observations/sum(walls),
            "model_only_policy_observations_per_cpu_second": observations/sum(cpus),
            "full_loop_policy_observations_per_wall_second": observations/full_wall,
            "full_loop_policy_observations_per_cpu_second": observations/full_cpu,
            "full_loop_policy_episodes_per_wall_second": count*len(records)/full_wall,
            "measured_full_wall_seconds": full_wall, "measured_full_cpu_seconds": full_cpu,
            "actual_internal_spikes": sum(r["actual_internal_spikes"] for r in records),
            "communication_output_pulses": sum(r["communication_output_pulses"] for r in records),
            "budget_spent": sum(r["budget_spent"] for r in records),
            "actual_state_bytes_per_policy": sorted({r["state_storage"]["bytes_per_episode"] for r in records}),
            "episode_empirical_fraction_granularity": 1/len(records),
            "batched_step_empirical_fraction_granularity": 1/len(walls),
            "latency_qualification": f"p95/p99 are descriptive empirical quantiles, with only {len(records)} complete episode samples and {len(walls)} inner batched-step samples. This does not establish extreme-tail precision or an SLA. Inner steps are correlated within episodes. Amortized per-policy time is batch time divided by active instances, not a single-request latency or an independent sample."}


def measurement_design():
    return {"variants": list(VARIANTS), "training_seeds": list(TRAINING_SEEDS),
            "policy_instance_counts": list(INSTANCE_COUNTS),
            "warmup_episodes": WARMUP_EPISODES, "measured_episodes": MEASURED_EPISODES,
            "scenario_seed": SCENARIO_SEED, "latent_seed_base": LATENT_SEED, "query_seed_base": QUERY_SEED,
            "torch_threads": 1, "parallel_measurement_workers": 1,
            "order": "Counts ascending, then training seeds ascending; rotate the four variants by (count_index+seed_index) modulo four. Across the twenty count/seed groups each variant appears in each position five times.",
            "measurement_design_added_after_model_freeze": True,
            "weights_or_architectures_retuned": False,
            "units": "Independent policy states and task ledgers in one CPU batch with shared checkpoint weights; not Hepta Cells.",
            "performance_scope": "Python/PyTorch reference implementation, exact-event baseline kernels, real sampled RR events, full task loop and model-only timing separately.",
            "real_future_window": False, "task_superiority_test": False}


def freeze_design():
    """Record repeat/all-seed choices from development sizing before checkpoints."""
    sizing_path = ROOT/"policy_benchmark_sizing.json"
    sizing = json.loads(sizing_path.read_text())
    if (sizing.get("development_only") is not True
            or sizing.get("production_checkpoints_opened") is not False
            or sizing.get("production_or_holdout_data_opened") is not False
            or sizing.get("workload", {}).get("policy_instances") != 64):
        raise ValueError("Expected the declared development-only sizing evidence")
    if DESIGN_PATH.exists():
        existing = json.loads(DESIGN_PATH.read_text())
        if (existing.get("configuration") != measurement_design()
                or existing.get("sources_sha256") != source_hashes()
                or existing.get("sizing_evidence_sha256") != sha(sizing_path)):
            raise ValueError("An existing measurement design has different source or sizing identity")
        return existing
    result = {"schema": "rrsnn-v4-policy-benchmark-design-1",
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "configuration": measurement_design(), "sources_sha256": source_hashes(),
              "sizing_evidence_sha256": sha(sizing_path),
              "production_checkpoints_opened_for_design": False,
              "production_or_holdout_task_data_opened_for_design": False,
              "decision": "Retain every architecture, every training seed and all four actual scales. Use two warmup plus five measured complete episodes per condition to bound measurement runtime. No fastest-seed selection.",
              "planning_only_extrapolation": sizing["planning_only_extrapolation"],
              "tail_qualification": "Five complete-episode samples and fifty-five inner batched calls per condition provide descriptive p95/p99 values only, without precise tail or SLA inference. Every reported production scale will be actually executed; planning extrapolations are not scale measurements."}
    write_once(DESIGN_PATH, result)
    return result


def protocol_configuration(selection_path, freeze_path):
    selection_path, freeze_path = Path(selection_path).resolve(), Path(freeze_path).resolve()
    selection = json.loads(selection_path.read_text())
    training_path = ROOT/"experiment_protocol.json"
    if (selection.get("holdout_metrics_used_for_selection") is not False
            or selection.get("protocol_sha256") != sha(freeze_path)
            or selection.get("training_protocol_sha256") != sha(training_path)):
        raise ValueError("A frozen validation-only checkpoint selection is required")
    design = json.loads(DESIGN_PATH.read_text())
    if (design.get("configuration") != measurement_design()
            or design.get("sources_sha256") != source_hashes()
            or design.get("production_checkpoints_opened_for_design") is not False):
        raise ValueError("Pre-checkpoint measurement design or source identity changed")
    return {"schema": "rrsnn-v4-policy-benchmark-protocol-1",
            "selection_relative_path": str(selection_path.relative_to(ROOT)),
            "pre_data_freeze_relative_path": str(freeze_path.relative_to(ROOT)),
            "selection_sha256": sha(selection_path), "pre_data_freeze_sha256": sha(freeze_path),
            "training_protocol_sha256": sha(training_path), "sources_sha256": source_hashes(),
            "pre_checkpoint_design_sha256": sha(DESIGN_PATH), **measurement_design()}


def freeze_benchmark(selection_path, freeze_path, destination):
    configuration = protocol_configuration(selection_path, freeze_path)
    selection = json.loads(Path(selection_path).read_text())
    checkpoints = {}
    for variant in VARIANTS:
        for seed in TRAINING_SEEDS:
            checkpoint = ROOT/"results"/variant/f"seed_{seed}"/"model.pt"
            validated = validate_selection(checkpoint, selection_path, freeze_path)
            if validated != selection:
                raise ValueError("Selection changed while freezing the benchmark")
            checkpoints[str(checkpoint.relative_to(ROOT))] = sha(checkpoint)
    configuration["checkpoints_sha256"] = checkpoints
    write_once(destination, configuration)
    return configuration


def validate_benchmark_protocol(path):
    protocol = json.loads(Path(path).read_text())
    selection = ROOT/protocol["selection_relative_path"]
    freeze = ROOT/protocol["pre_data_freeze_relative_path"]
    current = protocol_configuration(selection, freeze)
    if {key: value for key, value in protocol.items() if key != "checkpoints_sha256"} != current:
        raise ValueError("Benchmark source, configuration, or selection identity drift")
    for relative, expected in protocol["checkpoints_sha256"].items():
        if sha(ROOT/relative) != expected:
            raise ValueError("Benchmark checkpoint identity drift")
    return protocol


def benchmark_one(protocol_path, variant, seed, count, destination):
    protocol = validate_benchmark_protocol(protocol_path)
    if variant not in VARIANTS or seed not in TRAINING_SEEDS or count not in INSTANCE_COUNTS:
        raise ValueError("Measurement is outside the fixed benchmark matrix")
    check_disk()
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    if len(os.sched_getaffinity(0)) != 1 or 8 in os.sched_getaffinity(0):
        raise ValueError("Run each measurement on one pinned CPU other than reserved CPU 8")
    checkpoint = ROOT/"results"/variant/f"seed_{seed}"/"model.pt"
    selection_path = ROOT/protocol["selection_relative_path"]
    freeze_path = ROOT/protocol["pre_data_freeze_relative_path"]
    validate_selection(checkpoint, selection_path, freeze_path)
    identity = {"protocol_sha256": sha(protocol_path), "variant": variant, "training_seed": seed,
                "policy_instances": count, "checkpoint_sha256": sha(checkpoint),
                "cpu_affinity": sorted(os.sched_getaffinity(0))}
    destination = Path(destination)
    if destination.exists():
        existing = json.loads(destination.read_text())
        if existing.get("identity") != identity or existing.get("status") != "completed":
            raise ValueError("Existing benchmark result has different identity")
        return existing
    model, blob = load_policy(checkpoint, protocol["training_protocol_sha256"])
    model.eval()
    initial_weights = state_dict_digest(model)
    scenarios, schedule, work = workload(count)
    before = resource_snapshot()
    warmups, records = [], []
    for index in range(WARMUP_EPISODES+MEASURED_EPISODES):
        check_disk()
        gc.collect()
        record = closed_loop(model, scenarios, schedule,
                             latent_seed=LATENT_SEED+1009*seed+100003*index,
                             query_seed=QUERY_SEED+100003*index)
        record["resources_after"] = resource_snapshot()
        (warmups if index < WARMUP_EPISODES else records).append(record)
    after = resource_snapshot()
    if initial_weights != state_dict_digest(model):
        raise AssertionError("Inference changed model weights or fixed buffers")
    validate_benchmark_protocol(protocol_path)
    metadata = model.metadata()
    declared = metadata.get("persistent_numeric_state_bytes", metadata.get("persistent_state_bytes_float32"))
    if any(record["state_storage"]["bytes_per_episode"] != declared for record in warmups+records):
        raise AssertionError("Measured numeric state differs from declared physical state")
    result = {"schema": "rrsnn-v4-policy-benchmark-result-1", "status": "completed",
              "identity": identity, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": protocol["units"], "workload": work, "metadata": metadata,
              "checkpoint_model_variant": blob["variant"], "weights_unchanged": True,
              "shared_parameter_count": sum(p.numel() for p in model.parameters()),
              "shared_parameter_bytes": sum(p.numel()*p.element_size() for p in model.parameters()),
              "shared_buffer_bytes": sum(p.numel()*p.element_size() for p in model.buffers()),
              "summary": summarize(records, count), "warmup_records": warmups, "measured_records": records,
              "resources_before": before, "resources_after": after,
              "resource_quality": resource_quality(before, after),
              "process_peak_rss_mib": after["process_peak_rss_mib"],
              "rss_scope": "Fresh measurement process high-water mark, including interpreter, PyTorch, shared weights, generated scenarios, task queues, temporary arrays, warmup, and measurements. Not per-policy memory.",
              "full_loop_scope": "Reset and all task work through terminal settlement; data generation, source/weight hashing, GC between episodes, state-byte inspection, and result serialization are excluded.",
              "model_step_scope": "Batched model.step including the action head, actual CTMC/event propagation, and spike counts; task observations, argmax, queues, and ledger work are outside this inner timer.",
              "energy_measured": False, "native_cell_scale_claim": False,
              "holdout_task_data_opened": False, "torch_version": torch.__version__,
              "torch_intraop_threads": torch.get_num_threads(),
              "torch_interop_threads": torch.get_num_interop_threads()}
    write_once(destination, result)
    return result


def run_matrix(protocol_path, directory, cpu):
    protocol = validate_benchmark_protocol(protocol_path)
    if cpu not in os.sched_getaffinity(0) or cpu == 8:
        raise ValueError("Choose an allowed CPU other than CPU 8 reserved for native integration")
    directory = Path(directory)
    receipts = []
    # A fresh, single-thread process for each condition makes peak RSS comparable.
    for count_index, count in enumerate(INSTANCE_COUNTS):
        for seed_index, seed in enumerate(TRAINING_SEEDS):
            offset = (count_index+seed_index) % len(VARIANTS)
            for variant in VARIANTS[offset:]+VARIANTS[:offset]:
                check_disk()
                destination = directory/variant/f"seed_{seed}"/f"instances_{count}.json"
                environment = os.environ.copy()
                environment.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
                command = ["taskset", "-c", str(cpu), sys.executable, "-m", "rrsnn_v4.policy_benchmark",
                           "--protocol", str(Path(protocol_path).resolve()), "--variant", variant,
                           "--seed", str(seed), "--instances", str(count), "--output", str(destination.resolve())]
                child = subprocess.run(command, cwd=ROOT.parent, env=environment)
                if child.returncode:
                    raise RuntimeError(f"Benchmark child failed: {variant}/{seed}/{count}; completed results retained")
                result = json.loads(destination.read_text())
                receipts.append({"path": str(destination.resolve().relative_to(ROOT)), "sha256": sha(destination),
                                 "identity": result["identity"], "summary": result["summary"],
                                 "process_peak_rss_mib": result["process_peak_rss_mib"],
                                 "resource_quality": result["resource_quality"]})
    validate_benchmark_protocol(protocol_path)
    result = {"schema": "rrsnn-v4-policy-benchmark-matrix-1", "all_completed": True,
              "protocol_sha256": sha(protocol_path), "expected_conditions": 80,
              "conditions": len(receipts), "measurement_cpu": cpu,
              "scope": protocol["units"], "native_cell_scale_claim": False, "receipts": receipts}
    if len(receipts) != result["expected_conditions"]:
        raise AssertionError("Incomplete policy benchmark matrix")
    write_once(directory/"matrix.json", result)
    return result


def validate_development():
    """Small development-only functional and sizing check; no checkpoints read."""
    from .evaluate import evaluate
    torch.set_num_threads(1)
    initial_sources = source_hashes()
    scenarios, schedule, work = workload(4)
    checks, results = [], {}
    resources_before = resource_snapshot()
    for variant in VARIANTS:
        torch.manual_seed(86240001)
        model = make_policy(variant)
        model.eval()
        weights_before = state_dict_digest(model)
        first = closed_loop(model, scenarios, schedule, latent_seed=86245001,
                            query_seed=86246001, retain_outcomes=True)
        second = closed_loop(model, scenarios, schedule, latent_seed=86245001,
                             query_seed=86246001, retain_outcomes=True)
        assert first["action_sha256"] == second["action_sha256"]
        assert first["outcome_sha256"] == second["outcome_sha256"]
        reference = evaluate(model, scenarios, dataset="development", latent_seed=86245001)
        for index, row in enumerate(reference["rows"]):
            assert first["outcomes"]["actions"][index] == [item["action"] for item in row["task_trace"]]
            assert first["outcomes"]["budget_final"][index] == row["budget_final"]
            assert first["outcomes"]["emissions"][index] == row["task_output_pulses"]
            assert first["outcomes"]["internal_spikes"][index] == row["internal_spikes"]
            assert abs(first["outcomes"]["expected_utility"][index]-row["expected_utility"]) < 1e-12
        metadata = model.metadata()
        expected = metadata.get("persistent_numeric_state_bytes", metadata.get("persistent_state_bytes_float32"))
        assert first["state_storage"]["bytes_per_episode"] == expected
        assert weights_before == state_dict_digest(model)
        assert sum(p.numel() for p in model.parameters()) == 977
        results[variant] = {"summary": summarize([first, second], 4),
                            "state_storage": first["state_storage"],
                            "same_seed_replay_equal": True, "independent_evaluator_equal": True}
    prefix, _, prefix_identity = workload(2)
    assert [scenario_digest(s) for s in prefix] == [scenario_digest(s) for s in scenarios[:2]]
    assert work["observations_per_episode"] == 44 and prefix_identity["observations_per_episode"] == 22
    assert initial_sources == source_hashes()
    checks.extend(["all four encoders match the existing closed-loop evaluator on every action and ledger",
                   "same-seed replay has identical actions, outcomes and actual internal event counts",
                   "allocated state equals metadata without padding", "weights and buffers unchanged",
                   "development workload is prefix-stable and common across policies",
                   "source identity unchanged during validation"])
    return {"schema": "rrsnn-v4-policy-benchmark-development-1", "all_passed": True,
            "unique_development_episodes": 4, "production_checkpoints_opened": False,
            "production_or_holdout_data_opened": False, "task_superiority_claim": False,
            "fresh_process_per_condition": False,
            "sizing_qualification": "Tiny functional probe only; its shared process RSS and 2-repeat quantiles are not production performance claims.",
            "sources_sha256": initial_sources, "checks": checks, "workload": work,
            "results": results, "resources_before": resources_before, "resources_after": resource_snapshot()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-development", action="store_true")
    parser.add_argument("--freeze-design", action="store_true")
    parser.add_argument("--freeze-benchmark", action="store_true")
    parser.add_argument("--run-matrix", action="store_true")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--freeze", type=Path, default=ROOT/"pre_data_freeze.json")
    parser.add_argument("--protocol", type=Path, default=ROOT/"policy_benchmark_protocol.json")
    parser.add_argument("--variant", choices=VARIANTS)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--instances", type=int)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.validate_development:
        result = validate_development()
        write_once(arguments.output or ROOT/"policy_benchmark_validation.json", result)
        print(json.dumps({"all_passed": result["all_passed"], "checks": result["checks"]}))
    elif arguments.freeze_design:
        result = freeze_design()
        print(json.dumps({"design_sha256": sha(DESIGN_PATH), "configuration": result["configuration"]}))
    elif arguments.freeze_benchmark and arguments.selection:
        result = freeze_benchmark(arguments.selection, arguments.freeze, arguments.protocol)
        print(json.dumps({"frozen_checkpoints": len(result["checkpoints_sha256"]), "protocol_sha256": sha(arguments.protocol)}))
    elif arguments.run_matrix:
        result = run_matrix(arguments.protocol, arguments.output or ROOT/"policy_benchmark_results", arguments.cpu)
        print(json.dumps({"all_completed": result["all_completed"], "conditions": result["conditions"]}))
    elif arguments.variant and arguments.seed is not None and arguments.instances and arguments.output:
        result = benchmark_one(arguments.protocol, arguments.variant, arguments.seed, arguments.instances, arguments.output)
        print(json.dumps({"completed": result["identity"], "summary": result["summary"]}))
    else:
        parser.error("Choose --validate-development, --freeze-design, --freeze-benchmark with --selection, --run-matrix, or one complete measurement job")
