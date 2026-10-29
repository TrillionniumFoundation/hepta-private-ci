"""Closed-loop v4 evaluation with real delivery queues and post-path queries."""

from pathlib import Path
import argparse
import gzip
import hashlib
import json
import time

import numpy as np
import torch

from .prepare_data import load_data, sha, validate_freeze
from .task import (ACTION_DIGITS, Oracle, OutputPulseQueue, exogenous, legal_actions,
                   scenario_digest, settle_output_pulses, state_features, transition)


ROOT = Path(__file__).resolve().parent
QUERY_BASE = {"train": 11401001, "validation": 12401001, "test": 13401001,
              "shift": 14401001, "paired": 15401001, "development": 19401001}
LATENT_BASE = {"train": 21401001, "validation": 22401001, "test": 23401001,
               "shift": 24401001, "paired": 25401001, "development": 29401001}
REPLAYS = 4
QUERY_DRAWS = 4


def numpy(value):
    return value.detach().cpu().numpy() if torch.is_tensor(value) else np.asarray(value)


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def initial_state_rows(state, batch_size):
    """Capture pre-cue physical state without assuming deterministic reset."""
    def capture(value, row):
        if torch.is_tensor(value) or isinstance(value, np.ndarray):
            array = numpy(value)
            if array.ndim and array.shape[0] == batch_size:
                array = array[row]
            return {"dtype": str(array.dtype), "shape": list(array.shape), "value": array.tolist()}
        if isinstance(value, dict):
            return {key: capture(child, row) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [capture(child, row) for child in value]
        if hasattr(value, "__dict__"):
            return {key: capture(child, row) for key, child in vars(value).items()}
        if isinstance(value, np.generic):
            return value.item()
        return value
    return [capture(state, row) for row in range(batch_size)]


def evaluate_paired_stochastic(model, scenarios, oracle_values, metadata, training_seed,
                               latent_replay, base_seed, keep_trace, query_draws, query_seed_base):
    """Same initial state and RNG for all four conditions within each value group."""
    outputs = []
    group_receipts = {}
    for row, (scenario, item_meta, oracle) in enumerate(zip(scenarios, metadata, oracle_values)):
        group = int(item_meta["group"])
        actor_seed = int(base_seed)+100003*group
        result = evaluate(model, [scenario], oracle_values=[oracle], episode_metadata=[item_meta],
                          dataset="paired", training_seed=training_seed, latent_replay=latent_replay,
                          latent_seed=actor_seed, keep_trace=keep_trace, query_draws=query_draws,
                          query_seed_base=query_seed_base)
        result["rows"][0]["scenario_index"] = row
        result["rows"][0]["actor_seed"] = actor_seed
        witness = {"initial_state_sha256": result["rows"][0]["initial_state_sha256"],
                   "initial_rng_sha256": result["initial_rng_sha256"],
                   "post_initialization_rng_sha256": result["post_initialization_rng_sha256"]}
        if group not in group_receipts:
            group_receipts[group] = {"group": group, "actor_seed": actor_seed,
                                     "conditions": [], "witness": witness,
                                     "initial_state_snapshot": result["initial_state_snapshots"][0]}
        receipt = group_receipts[group]
        if receipt["witness"] != witness:
            raise AssertionError("Paired conditions do not share the exact pre-cue state and RNG")
        receipt["conditions"].append(item_meta["condition"])
        outputs.append(result)
    for receipt in group_receipts.values():
        if sorted(receipt["conditions"]) != ["A0", "A2", "B0", "B2"]:
            raise ValueError("A paired group must contain each of A0/A2/B0/B2 exactly once")
    rows = [result["rows"][0] for result in outputs]
    merged = {key: value for key, value in outputs[0].items()
              if key not in {"rows", "initial_state_snapshots", "initial_rng_sha256",
                             "post_initialization_rng_sha256"}}
    merged.update(episodes=len(rows), latent_seed=base_seed, rows=rows,
                  expected_utility_mean=float(np.mean([r["expected_utility"] for r in rows])),
                  normalized_utility_mean=float(np.mean([r["normalized_utility"] for r in rows])),
                  realized_query_utility_mean=float(np.mean([r["realized_query_utility"] for r in rows])),
                  oracle_expected_mean=float(np.mean(oracle_values)),
                  high_value_delivery_mean=float(np.mean([r["high_value_delivery_fraction"] for r in rows])),
                  zero_oracle_episodes=int(np.sum(np.asarray(oracle_values) <= 1e-12)),
                  model_step_cpu_seconds=sum(r["model_step_cpu_seconds"] for r in outputs),
                  model_batch_step_seconds=[t for r in outputs for t in r["model_batch_step_seconds"]],
                  elapsed_seconds_including_task=sum(r["elapsed_seconds_including_task"] for r in outputs),
                  paired_initial_state_receipts=list(group_receipts.values()),
                  paired_initial_state_equal=True,
                  execution_batching="Stochastic paired conditions execute as separate one-row paths with the same group actor seed. Future streams evolve under each condition's own observed controls.")
    return merged


def numeric_state_storage(state, batch_size):
    """Count resident numeric state; identify shared storages without padding."""
    rows = []
    seen = set()
    def visit(value, path):
        if torch.is_tensor(value):
            storage = value.untyped_storage()
            identity = ("torch", storage.data_ptr(), storage.nbytes())
            amount = storage.nbytes()
        elif isinstance(value, np.ndarray):
            base = value
            while isinstance(base.base, np.ndarray):
                base = base.base
            identity = ("numpy", base.__array_interface__["data"][0], base.nbytes)
            amount = base.nbytes
        elif isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}")
            return
        elif isinstance(value, (tuple, list)):
            for index, child in enumerate(value):
                visit(child, f"{path}.{index}")
            return
        elif hasattr(value, "__dict__"):
            for key, child in vars(value).items():
                visit(child, f"{path}.{key}")
            return
        else:
            return
        if identity not in seen:
            seen.add(identity)
            rows.append({"field": path, "bytes": int(amount)})
    visit(state, "state")
    total = sum(row["bytes"] for row in rows)
    return {"resident_numeric_bytes": total, "bytes_per_episode": total/batch_size,
            "fields": rows, "batch_size": batch_size,
            "excluded": "model weights, RNG object, Python containers/scalars, task queues, temporary working arrays and process/framework overhead"}


@torch.no_grad()
def evaluate(model, scenarios, *, oracle_values=None, episode_metadata=None,
             dataset="development", training_seed=0, latent_replay=0,
             latent_seed=None, keep_trace=False, query_draws=QUERY_DRAWS, query_seed_base=None):
    """Model sees only causal observations; oracle/query values enter scoring."""
    if not scenarios or dataset not in QUERY_BASE or query_draws != QUERY_DRAWS:
        raise ValueError("Nonempty declared dataset and four query draws required")
    if not 0 <= latent_replay < REPLAYS:
        raise ValueError("Latent replay index outside frozen range")
    count = len(scenarios)
    metadata = episode_metadata or [{"group": i, "condition": s.profile+str(s.shock_amount)}
                                    for i, s in enumerate(scenarios)]
    if len(metadata) != count:
        raise ValueError("Scenario metadata length mismatch")
    if oracle_values is None:
        oracle_values = np.asarray([Oracle(s).value(0, s.initial_live, s.budget) for s in scenarios])
    oracle_values = np.asarray(oracle_values, dtype=float)
    if oracle_values.shape != (count,) or not np.isfinite(oracle_values).all():
        raise ValueError("Invalid expected oracle values")
    selected_seed = (LATENT_BASE[dataset] + 1009*int(training_seed) + 1000003*latent_replay
                     if latent_seed is None else int(latent_seed))
    if dataset == "paired" and count > 1 and bool(getattr(model, "is_stochastic", False)):
        return evaluate_paired_stochastic(model, scenarios, oracle_values, metadata, training_seed,
                                          latent_replay, selected_seed, keep_trace, query_draws, query_seed_base)
    rng = np.random.default_rng(selected_seed)
    initial_rng_digest = canonical_digest(rng.bit_generator.state)
    model.eval()
    state = model.initial_state(count, rng)
    initial_snapshots = initial_state_rows(state, count)
    after_initial_rng_digest = canonical_digest(rng.bit_generator.state)
    initial_witnesses = []
    if dataset == "paired" and count > 1:
        for group in sorted({int(m["group"]) for m in metadata}):
            indices = [i for i, m in enumerate(metadata) if int(m["group"]) == group]
            digests = {canonical_digest(initial_snapshots[i]) for i in indices}
            if len(digests) != 1 or sorted(metadata[i]["condition"] for i in indices) != ["A0", "A2", "B0", "B2"]:
                raise AssertionError("Deterministic paired pre-cue state or condition set differs")
            initial_witnesses.append({"group": group, "conditions": [metadata[i]["condition"] for i in indices],
                                      "initial_state_sha256": next(iter(digests)),
                                      "initial_state_snapshot": initial_snapshots[indices[0]]})
    times = [scenario.events() for scenario in scenarios]
    lives = np.asarray([s.initial_live for s in scenarios], dtype=np.int64)
    budgets = np.asarray([s.budget for s in scenarios], dtype=np.int64)
    removed = np.zeros(count, dtype=np.int64)
    added, spent, renewed, dropped = [removed.copy() for _ in range(4)]
    last = np.zeros(count)
    queues = [OutputPulseQueue(scenario) for scenario in scenarios]
    traces = [[] for _ in scenarios]
    internal_events = [[] for _ in scenarios]
    internal_counts = np.zeros(count, dtype=np.int64)
    per_neuron_counts = None
    cpu_nanoseconds = 0
    step_nanoseconds = []
    begun = time.perf_counter()
    for index in range(max(map(len, times))):
        observations = np.zeros((count, 22), dtype=np.float32)
        elapsed = np.zeros(count, dtype=np.float32)
        mask = np.zeros(count, dtype=bool)
        legal = np.zeros((count, 81), dtype=bool)
        legal[:, 0] = True
        arrivals = [[] for _ in scenarios]
        for row, scenario in enumerate(scenarios):
            if index >= len(times[row]):
                continue
            now = times[row][index]
            mask[row] = True
            elapsed[row], last[row] = now-last[row], now
            arrivals[row] = queues[row].advance(now)
            budgets[row], remove, add = exogenous(scenario, now, int(budgets[row]))
            removed[row] += remove
            added[row] += add
            observations[row] = state_features(scenario, now, int(lives[row]), int(budgets[row]))
            legal[row], _ = legal_actions(scenario, now, int(lives[row]), int(budgets[row]))
        wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
        state, output = model.step(state, torch.from_numpy(observations), torch.from_numpy(elapsed),
                                   rng, event_mask=torch.from_numpy(mask), record_spikes=keep_trace)
        cpu_nanoseconds += time.process_time_ns()-cpu_start
        step_nanoseconds.append(time.perf_counter_ns()-wall_start)
        logits = numpy(output["logits"])
        if logits.shape != (count, 81) or not np.isfinite(logits).all():
            raise ValueError("Nonfinite or malformed task logits")
        raw_counts = output.get("actual_counts", output.get("spikes"))
        if raw_counts is None:
            raise ValueError("Model omitted actual internal spike counts")
        neuron_counts = numpy(raw_counts)
        if (neuron_counts.ndim != 2 or neuron_counts.shape[0] != count
                or not np.isfinite(neuron_counts).all() or (neuron_counts < 0).any()
                or not np.equal(neuron_counts, np.floor(neuron_counts)).all()):
            raise ValueError("Internal event counts must be nonnegative integers")
        if (neuron_counts[~mask] != 0).any():
            raise ValueError("Padded observation created physical events")
        if per_neuron_counts is None:
            per_neuron_counts = np.zeros_like(neuron_counts, dtype=np.int64)
        per_neuron_counts += neuron_counts.astype(np.int64)
        internal_counts += neuron_counts.sum(axis=1).astype(np.int64)
        if keep_trace:
            for event in output.get("spike_times", []):
                row = int(event["batch"])
                event_time = float(event["time"])
                if (not 0 <= row < count or not mask[row] or not np.isfinite(event_time)
                        or event_time < last[row]-float(elapsed[row])-1e-7
                        or event_time > last[row]+1e-7):
                    raise ValueError("Internal spike timestamp outside its actual interval")
                internal_events[row].append(dict(event))
            if sum(map(len, internal_events)) > 1_000_000:
                raise RuntimeError("Declared actual event log cap exceeded")
        actions = np.argmax(np.where(legal, logits, -np.inf), axis=1)
        for row in np.flatnonzero(mask):
            scenario, now = scenarios[row], times[row][index]
            before = int(budgets[row])
            live, budget, reward, info = transition(scenario, now, int(lives[row]), before, int(actions[row]))
            lives[row], budgets[row] = live, budget
            queues[row].enqueue(info["outputs"])
            spent[row] += info["cost"]
            renewed[row] += info["renewals"]
            dropped[row] += info["dropped"]
            traces[row].append({"time": now, "action": int(actions[row]),
                                "digits": ACTION_DIGITS[actions[row]].tolist(),
                                "budget_before": before, "budget_after": budget,
                                "deliveries": arrivals[row], "outputs": info["outputs"],
                                "expected_output_reward": reward})
    if not np.array_equal(budgets, np.asarray([s.budget for s in scenarios])+added-removed-spent):
        raise AssertionError("Batched task resource conservation failed")
    if (budgets < 0).any() or any(queue.pending for queue in queues):
        raise AssertionError("Unpaid budget or pending delivery at terminal query")
    if keep_trace and any(len(events) != int(internal_counts[row])
                          for row, events in enumerate(internal_events)):
        raise AssertionError("Recorded actual internal events disagree with counts")
    # All actor calls have finished before any terminal query realization exists.
    rows = []
    for row, scenario in enumerate(scenarios):
        group = int(metadata[row]["group"])
        query_base = QUERY_BASE[dataset] if query_seed_base is None else int(query_seed_base)
        query_seeds = [query_base+group*101+draw for draw in range(query_draws)]
        settlements = [settle_output_pulses(scenario, queues[row].delivered,
                       np.random.default_rng(seed).random(4) < scenario.query_probability)
                       for seed in query_seeds]
        expected = settlements[0]["expected_utility"]
        optimum = float(oracle_values[row])
        if expected > optimum+1e-8:
            raise AssertionError("Expected actor utility exceeds independent expected DP")
        delivered_ids = {pulse["item"] for pulse in queues[row].delivered}
        high_items = sorted((i for i in range(4) if (scenario.initial_live >> i) & 1),
                            key=lambda i: (-scenario.values[i], i))[:2]
        high_total = sum(scenario.values[i] for i in high_items)
        high_delivered = sum(scenario.values[i] for i in high_items if i in delivered_ids)
        item = {"scenario_index": row, "scenario_digest": scenario_digest(scenario),
                "group": group, "condition": metadata[row]["condition"],
                "training_seed": int(training_seed), "latent_replay": latent_replay,
                "initial_state_sha256": canonical_digest(initial_snapshots[row]),
                "expected_utility": expected, "oracle_expected_utility": optimum,
                "normalized_utility": expected/optimum if optimum > 1e-12 else 1.,
                "regret": max(optimum-expected, 0.),
                "query_seeds": query_seeds,
                "query_bits": [result["query_bits"] for result in settlements],
                "realized_query_utility": [result["realized_utility"] for result in settlements],
                "budget_final": int(budgets[row]), "budget_spent": int(spent[row]),
                "shock_removed": int(removed[row]), "refill_added": int(added[row]),
                "renewals": int(renewed[row]), "dropped": int(dropped[row]),
                "task_output_pulses": len(queues[row].delivered),
                "delivered": queues[row].delivered, "live_final": int(lives[row]),
                "high_value_item_ids": high_items, "high_value_delivered_value": high_delivered,
                "high_value_total": high_total,
                "high_value_delivery_fraction": high_delivered/high_total if high_total > 0 else 1.,
                "internal_spikes": int(internal_counts[row]),
                "internal_spikes_per_neuron": per_neuron_counts[row].tolist(),
                "task_trace": traces[row]}
        if keep_trace:
            item["internal_spike_times"] = internal_events[row]
        rows.append(item)
    expected = np.asarray([row["expected_utility"] for row in rows])
    normalized = np.asarray([row["normalized_utility"] for row in rows])
    return {"schema": "rrsnn-v4-closed-loop-evaluation-1", "dataset": dataset,
            "episodes": count, "training_seed": int(training_seed), "latent_replay": latent_replay,
            "latent_seed": selected_seed, "query_draws_per_scenario": query_draws,
            "initial_rng_sha256": initial_rng_digest,
            "post_initialization_rng_sha256": after_initial_rng_digest,
            "initial_state_snapshots": initial_snapshots,
            "paired_initial_state_receipts": initial_witnesses,
            "paired_initial_state_equal": bool(initial_witnesses),
            "query_rule": "same scenario group and draw share observer seed across models, training seeds, and latent replays",
            "real_future_window": False, "all_resource_invariants_passed": True,
            "expected_utility_mean": float(expected.mean()),
            "normalized_utility_mean": float(normalized.mean()),
            "realized_query_utility_mean": float(np.mean([row["realized_query_utility"] for row in rows])),
            "oracle_expected_mean": float(oracle_values.mean()),
            "zero_oracle_episodes": int((oracle_values <= 1e-12).sum()),
            "high_value_delivery_mean": float(np.mean([row["high_value_delivery_fraction"] for row in rows])),
            "state_storage": numeric_state_storage(state, count),
            "model_step_cpu_seconds": cpu_nanoseconds/1e9,
            "model_batch_step_seconds": [duration/1e9 for duration in step_nanoseconds],
            "elapsed_seconds_including_task": time.perf_counter()-begun,
            "rows": rows,
            "inference_scope": "Latent replays and observer draws are nested within the same scenarios, not new independent test examples. Deterministic repeats must not increase the effective sample size."}


def load_policy(checkpoint, training_protocol_sha256=None):
    from .models import make_policy
    blob = torch.load(checkpoint, map_location="cpu", weights_only=False)
    if training_protocol_sha256 is not None:
        path = Path(checkpoint)
        if (blob.get("protocol_sha256") != training_protocol_sha256
                or blob.get("run_name", blob["variant"]) != path.parent.parent.name
                or int(blob["seed"]) != int(path.parent.name[5:])):
            raise ValueError("Checkpoint training protocol or run identity differs")
    model = make_policy(blob["variant"])
    model.load_state_dict(blob["state_dict"])
    model.eval()
    return model, blob


def validate_selection(checkpoint, selection_path, freeze_path):
    selection = json.loads(Path(selection_path).read_text())
    if (selection.get("holdout_metrics_used_for_selection") is not False
            or selection.get("protocol_sha256") != sha(freeze_path)):
        raise ValueError("Model selection is not bound to the frozen pre-holdout protocol")
    relative = str(Path(checkpoint).resolve().relative_to(ROOT))
    if selection.get("checkpoints", {}).get(relative) != sha(checkpoint):
        raise ValueError("Checkpoint was not included in the frozen selection")
    training_path = ROOT / "experiment_protocol.json"
    training_hash = sha(training_path)
    if selection.get("training_protocol_sha256") != training_hash:
        raise ValueError("Selection is not bound to the full training protocol")
    training_protocol = json.loads(training_path.read_text())
    for name, expected in training_protocol["frozen_files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Frozen training source or data changed: {name}")
    receipt_path = Path(checkpoint).with_name("training.json")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("status") != "completed" or receipt.get("protocol_sha256") != training_hash
            or receipt.get("checkpoint_sha256") != sha(checkpoint)
            or receipt.get("holdout_opened_by_training") is not False
            or receipt.get("variant") != Path(checkpoint).parent.parent.name
            or receipt.get("seed") != int(Path(checkpoint).parent.name[5:])
            or selection.get("training_receipts_sha256", {}).get(str(receipt_path.resolve().relative_to(ROOT))) != sha(receipt_path)):
        raise ValueError("Training receipt does not match the selected checkpoint")
    return selection


def evaluate_checkpoint(checkpoint, freeze_path, selection_path,
                        datasets=("test", "shift", "paired"), replays=range(REPLAYS)):
    validate_freeze(freeze_path)
    selection = validate_selection(checkpoint, selection_path, freeze_path)
    model, blob = load_policy(checkpoint, selection["training_protocol_sha256"])
    torch.set_num_threads(1)
    outputs = []
    for dataset in datasets:
        scenarios, arrays, metadata, manifest = load_data(dataset, freeze_path)
        for replay in replays:
            destination = Path(checkpoint).parent / f"evaluation_{dataset}_rep{replay}.json.gz"
            header = {"variant": blob.get("run_name", blob["variant"]),
                      "model_variant": blob["variant"], "training_seed": int(blob["seed"]),
                      "checkpoint_sha256": sha(checkpoint), "protocol_sha256": sha(freeze_path),
                      "training_protocol_sha256": selection["training_protocol_sha256"],
                      "selection_sha256": sha(selection_path), "evaluator_sha256": sha(__file__),
                      "task_sha256": sha(ROOT / "task.py"),
                      "data_manifest_sha256": sha(ROOT / "data" / "manifest.json"),
                      "source_files": next(row["files"] for row in manifest["splits"] if row["name"] == dataset),
                      "dataset": dataset, "latent_replay": replay,
                      "primary_comparator": "ctrnn_state_cpu", "real_future_window": False}
            if destination.exists():
                with gzip.open(destination, "rt") as handle:
                    existing = json.load(handle)
                if existing["identity"] != header:
                    raise ValueError("Existing evaluation identity differs; refusing overwrite")
                outputs.append(str(destination))
                continue
            result = evaluate(model, scenarios, oracle_values=arrays["oracle_utility"],
                              episode_metadata=metadata, dataset=dataset, training_seed=blob["seed"],
                              latent_replay=replay, keep_trace=(dataset == "paired"))
            temporary = destination.with_suffix(destination.suffix+".tmp")
            with gzip.open(temporary, "wt", encoding="utf-8") as handle:
                json.dump({"identity": header, "evaluation": result}, handle, allow_nan=False)
            temporary.replace(destination)
            outputs.append(str(destination))
            print(json.dumps({"evaluated": str(destination),
                              "normalized_utility": result["normalized_utility_mean"]}), flush=True)
    return outputs


def validate_development():
    """Compare real baseline batch execution with the independent scalar runner."""
    from .baselines import make_encoder
    from .prepare_data import make_arrays, paired_scenarios
    from .task import Scenario, rollout

    class Wrapper(torch.nn.Module):
        def __init__(self, variant):
            super().__init__()
            self.encoder = make_encoder(variant)
            self.head = torch.nn.Linear(8, 81)
        def initial_state(self, batch_size, rng):
            return self.encoder.initial_state(batch_size)
        def step(self, state, observation, elapsed, rng, event_mask=True, record_spikes=False):
            state, output = self.encoder.step(state, observation, elapsed, event_mask, record_spikes)
            output["logits"] = self.head(output["latent"])
            return state, output

    scenarios = [Scenario((1.2, .8, .4, .2), (1., 1., 3., 3.), 3, 2, 1),
                 Scenario((.3, 1.3, .6, 1.1), (2., 2., 2., 2.), 4, 0, 1),
                 Scenario((1.4, .2, 1.2, .4), (.75, 1.25, 2.75, 3.25), 2, 2, 1,
                          shock_time=1.25, refill_time=2.75)]
    torch.set_num_threads(1)
    comparisons = []
    for model_index, variant in enumerate(("lif", "alif", "resource_lif", "ctrnn", "ctrnn_matched")):
        torch.manual_seed(903000+model_index)
        model = Wrapper(variant).eval()
        batch = evaluate(model, scenarios, dataset="development", keep_trace=True)
        for row, scenario in enumerate(scenarios):
            state = model.initial_state(1, None)
            random = np.random.default_rng(903100)
            def callback(history, dt, valid):
                nonlocal state
                with torch.no_grad():
                    state, output = model.step(state, torch.from_numpy(history[-1:]),
                                               torch.tensor([dt[-1]], dtype=torch.float32),
                                               random, record_spikes=True)
                return int(np.argmax(np.where(valid, numpy(output["logits"])[0], -np.inf)))
            scalar = rollout(scenario, callback, query_seed=QUERY_BASE["development"]+row*101)
            actual = batch["rows"][row]
            assert abs(actual["expected_utility"]-scalar["expected_utility"]) < 1e-10
            assert actual["delivered"] == scalar["delivered"]
            assert actual["budget_final"] == scalar["budget_final"]
            assert [r["action"] for r in actual["task_trace"]] == [r["action"] for r in scalar["trace"]]
            assert actual["query_bits"][0] == scalar["query_bits"]
            assert actual["realized_query_utility"][0] == scalar["realized_utility"]
            comparisons.append({"variant": variant, "scenario": row,
                                "expected_utility": actual["expected_utility"],
                                "internal_spikes": actual["internal_spikes"], "passed": True})
    from .models import make_policy
    rr_comparisons = []
    torch.manual_seed(901301)
    rr_model = make_policy("rr_full").eval()
    for index, scenario in enumerate(scenarios):
        seed = 901400+index
        batched = evaluate(rr_model, [scenario], latent_seed=seed, keep_trace=True)
        random = np.random.default_rng(seed)
        state = rr_model.initial_state(1, random)
        events = []
        def rr_callback(history, dt, valid):
            nonlocal state
            with torch.no_grad():
                state, output = rr_model.step(state, torch.from_numpy(history[-1:]),
                                              torch.tensor([dt[-1]], dtype=torch.float32),
                                              random, record_spikes=True)
            events.extend(output["spike_times"])
            return int(np.argmax(np.where(valid, numpy(output["logits"])[0], -np.inf)))
        scalar = rollout(scenario, rr_callback, query_seed=QUERY_BASE["development"])
        # The scalar task runner does not invoke the actor for its terminal
        # no-op; advance the neural path to the same declared terminal event.
        terminal = state_features(scenario, 4., scalar["live_final"], scalar["budget_final"])
        with torch.no_grad():
            state, output = rr_model.step(state, torch.from_numpy(terminal[None, :]),
                torch.tensor([4.-float(state.time[0])], dtype=torch.float32),
                random, record_spikes=True)
        events.extend(output["spike_times"])
        actual = batched["rows"][0]
        assert actual["delivered"] == scalar["delivered"]
        assert abs(actual["expected_utility"]-scalar["expected_utility"]) < 1e-10
        assert [r["action"] for r in actual["task_trace"]] == [r["action"] for r in scalar["trace"]]
        assert events == actual["internal_spike_times"]
        rr_comparisons.append({"scenario": index, "latent_seed": seed,
                               "actual_internal_spikes": len(events),
                               "expected_utility": actual["expected_utility"], "passed": True})
    pairs, metadata = paired_scenarios(901010, groups=2)
    arrays = make_arrays(pairs)
    assert arrays["x"].shape == (8, 32, 22)
    assert np.all(arrays["dt"][:, 0] == 0) and not arrays["decision"][:, 0].any()
    for group in range(2):
        rows = pairs[4*group:4*group+4]
        assert len({row.values for row in rows}) == 1
        assert {sum(row.deadlines)/4 for row in rows} == {2.}
        assert {row.budget for row in rows} == {3}
    strict = evaluate(rr_model, pairs, oracle_values=arrays["oracle_utility"], episode_metadata=metadata,
                      dataset="paired", latent_seed=901601, keep_trace=True, query_seed_base=901700)
    assert strict["paired_initial_state_equal"] and len(strict["paired_initial_state_receipts"]) == 2
    for group in range(2):
        cases = [row for row in strict["rows"] if row["group"] == group]
        assert len({row["initial_state_sha256"] for row in cases}) == 1
        assert len({tuple(row["query_seeds"]) for row in cases}) == 1
    assert [row["scenario_index"] for row in strict["rows"]] == list(range(8))
    # Actual checkpoint/receipt fixtures isolate the two distinct freeze hashes.
    import tempfile
    saved_root = ROOT
    identity_rejections = []
    with tempfile.TemporaryDirectory(prefix="rrv4-evaluation-identity-") as temporary:
        try:
            globals()["ROOT"] = Path(temporary)
            pre = ROOT/"pre_data_freeze.json"
            pre.write_text(json.dumps({"scope": "DEVELOPMENT_ONLY_SOURCE_FREEZE"}))
            full = ROOT/"experiment_protocol.json"
            full.write_text(json.dumps({"scope": "DEVELOPMENT_ONLY_TRAINING_FREEZE", "frozen_files": {}}))
            checkpoint = ROOT/"results"/"ctrnn_state_cpu"/"seed_901803"/"model.pt"
            checkpoint.parent.mkdir(parents=True)
            model = make_policy("ctrnn_state")
            blob = {"variant": "ctrnn_state", "run_name": "ctrnn_state_cpu", "seed": 901803,
                    "state_dict": model.state_dict(), "protocol_sha256": sha(full)}
            torch.save(blob, checkpoint)
            receipt_path = checkpoint.with_name("training.json")
            receipt = {"status": "completed", "variant": "ctrnn_state_cpu", "seed": 901803,
                       "checkpoint_sha256": sha(checkpoint), "protocol_sha256": sha(full),
                       "holdout_opened_by_training": False}
            receipt_path.write_text(json.dumps(receipt))
            selection_path = ROOT/"selection.json"
            selection = {"protocol_sha256": sha(pre), "training_protocol_sha256": sha(full),
                "holdout_metrics_used_for_selection": False,
                "checkpoints": {str(checkpoint.relative_to(ROOT)): sha(checkpoint)},
                "training_receipts_sha256": {str(receipt_path.relative_to(ROOT)): sha(receipt_path)}}
            selection_path.write_text(json.dumps(selection))
            validate_selection(checkpoint, selection_path, pre)
            _, loaded = load_policy(checkpoint, sha(full))
            assert loaded["run_name"] == "ctrnn_state_cpu" and loaded["variant"] == "ctrnn_state"
            for target, field, wrong in ((selection, "training_protocol_sha256", sha(pre)),
                                         (receipt, "protocol_sha256", sha(pre)),
                                         (receipt, "seed", 901804)):
                previous = target[field]
                target[field] = wrong
                path = selection_path if target is selection else receipt_path
                path.write_text(json.dumps(target))
                try:
                    validate_selection(checkpoint, selection_path, pre)
                except ValueError:
                    identity_rejections.append(field)
                else:
                    raise AssertionError("Mismatched selection/receipt identity was accepted")
                target[field] = previous
                path.write_text(json.dumps(target))
            for field, wrong in (("protocol_sha256", sha(pre)), ("run_name", "ctrnn_state")):
                previous = blob[field]
                blob[field] = wrong
                torch.save(blob, checkpoint)
                try:
                    load_policy(checkpoint, sha(full))
                except ValueError:
                    identity_rejections.append("checkpoint_"+field)
                else:
                    raise AssertionError("Mismatched checkpoint identity was accepted")
                blob[field] = previous
        finally:
            globals()["ROOT"] = saved_root
    result = {"schema": "rrsnn-v4-batched-evaluation-validation-1", "all_passed": True,
              "scalar_vs_batch_cases": comparisons, "paired_development_groups": 2,
              "rr_single_row_identical_stream_cases": rr_comparisons,
              "strict_paired_pre_cue_state_and_rng_cases": strict["paired_initial_state_receipts"],
              "two_freeze_and_cpu_run_identity_rejections": identity_rejections,
              "rr_batching_limit": "Multirow random draw consumption differs; one-row same-stream replay checks do not claim path equality across arbitrary batch sizes.",
              "only_development_data_used": True, "production_splits_generated": False,
              "source_sha256": {"task.py": sha(ROOT/"task.py"),
                                "prepare_data.py": sha(ROOT/"prepare_data.py"),
                                "evaluate.py": sha(__file__)}}
    (ROOT/"evaluation_validation.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--validate-development", action="store_true")
    parser.add_argument("--datasets", nargs="+", default=["test", "shift", "paired"])
    parser.add_argument("--replays", nargs="+", type=int, default=list(range(REPLAYS)))
    arguments = parser.parse_args()
    if arguments.validate_development:
        result = validate_development()
        print(json.dumps({"all_passed": result["all_passed"],
                          "scalar_vs_batch_cases": len(result["scalar_vs_batch_cases"])}))
    elif arguments.checkpoint and arguments.freeze and arguments.selection:
        evaluate_checkpoint(arguments.checkpoint, arguments.freeze, arguments.selection,
                            tuple(arguments.datasets), arguments.replays)
    else:
        parser.error("Provide --checkpoint, --freeze, --selection, or --validate-development")
