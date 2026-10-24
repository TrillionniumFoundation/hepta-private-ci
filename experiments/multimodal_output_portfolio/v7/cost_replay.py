"""One bounded batch-one development cost replay, with real media serialization.

This is a cost supplement, not a new scientific holdout or an equal-cost claim.
It never loads an observer or passes Target into a policy. The actual native
Rust MPC and four-modal ONNX/codec service have separate timing contracts.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import torch

from ..v6.data import Observation, render_tokens
from ..v6.neural import PROFILES
from ..v6.observer import read_bundle, write_bundle
from .control import POLICIES, control
from .data import VIEWS, make_batch
from .forecast import CONTINUATIONS, CategoricalForecast
from .plans import ControlledSnapshot
from .snapshot import observation_digest
from .sources import canonical, load_roles


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixed_plans(pilot, profile, penalty):
    """Use only the already completed development table, before timed runs.

    The portfolio baseline gets a genuine nonempty candidate even if the best
    static continuation is stop. Repeating the same forecast is not useful work.
    """
    root = Path(pilot) / profile
    mechanism_path = root / "mechanism.json"
    mechanism = json.loads(mechanism_path.read_text())
    if mechanism["formal_holdout_opened"]:
        raise ValueError("Cost plans cannot be selected from formal outcomes")
    sums, counts, seen, pins = defaultdict(float), Counter(), set(), {}
    for slot in range(4):
        directory = root / "development" / f"scenario-{slot}"
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        path = directory / manifest["actual_endpoints_file"]
        pins[str(manifest_path)] = file_sha(manifest_path)
        pins[str(path)] = file_sha(path)
        if (manifest["role"] != "development" or manifest["pairs"] != 64
                or manifest["views"] != list(VIEWS)
                or pins[str(path)] != manifest["actual_endpoints_file_sha256"]):
            raise ValueError("Development endpoint source identity changed")
        logical = hashlib.sha256()
        with gzip.open(path, "rb") as stream:
            for raw in stream:
                logical.update(raw)
                row = json.loads(raw)
                if row["initialization"] != "full":
                    continue
                plan = tuple(row["continuation"])
                key = (slot, row["pair"], row["view"], plan)
                if key in seen or plan not in CONTINUATIONS:
                    raise ValueError("Duplicate or unregistered development endpoint")
                seen.add(key)
                sums[plan] += row["utility"]
                counts[plan] += 1
        if logical.hexdigest() != manifest["actual_endpoints_sha256"]:
            raise ValueError("Logical endpoint digest mismatch")
    expected = {(slot, pair, view, plan) for slot in range(4) for pair in range(64)
                for view in VIEWS for plan in CONTINUATIONS}
    if seen != expected:
        raise ValueError("Fixed-plan selection requires the complete development census")
    ranking = lambda plan: (sums[plan] / counts[plan] - penalty * len(plan),
                            -len(plan), -CONTINUATIONS.index(plan))
    static = max(CONTINUATIONS, key=ranking)
    pool = max((plan for plan in CONTINUATIONS if plan), key=ranking)
    if list(static) != mechanism["static_plans"]["full"]:
        raise ValueError("Static plan does not reproduce the completed pilot")
    pins[str(mechanism_path)] = file_sha(mechanism_path)
    return {"static": static, "static_pool": pool,
            "selection_source": "completed development table, in-sample",
            "pool_nonempty_supplement": True}, pins


class CountCalls:
    """Count actual public calls without replacing their numerical execution."""

    def __init__(self, delegate, names):
        self.delegate, self.names, self.calls = delegate, frozenset(names), Counter()

    def __getattr__(self, name):
        value = getattr(self.delegate, name)
        if name not in self.names:
            return value

        def counted(*args, **kwargs):
            self.calls[name] += 1
            return value(*args, **kwargs)

        return counted


def infer_once(snapshot, forecast, observation, policy, static_plan, directory, noise_seed):
    model = CountCalls(snapshot, ("encode", "step", "decode"))
    critic = CountCalls(forecast, ("bind_observation", "all_plan_distributions_bound"))
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    initial = model.encode(observation, noise_seed, content_control=policy != "allocation_only")
    result = control(model, critic, observation, initial, policy, static_plan=static_plan)
    output = model.decode(result.state)
    paths = write_bundle(directory, render_tokens(output.token_ids[0]), output.image_logits[0].sigmoid())
    pixels, caption, hashes = read_bundle(paths)
    final_state_key = model.state_key(result.state)
    cpu, wall = time.process_time_ns() - cpu, time.perf_counter_ns() - wall
    if (model.calls["encode"] != 1 or model.calls["decode"] != 1
            or critic.calls["all_plan_distributions_bound"] != result.forecasts
            or model.calls["step"] != result.simulated_actions + result.executed_actions
            or len(initial.initial_state_keys) != 3 or len(initial.initial_actions) != 2
            or pixels.shape != (1, 1, 28, 56) or not isinstance(caption, str)):
        raise RuntimeError("Measured execution/call census does not match the controller receipt")
    return {"wall_ns": wall, "cpu_ns": cpu, "actions": result.actions,
            "initial_actions": initial.initial_actions, "initial_plan_index": initial.plan_index,
            "final_step_count": result.state.step_count, "state_sha256": final_state_key,
            "raw_sha256": hashes, "model_public_calls": dict(model.calls),
            "forecast_public_calls": dict(critic.calls),
            "encoder_examples": 1, "initial_action_examples": 2,
            "continuation_action_examples": model.calls["step"],
            "forecast_nn_examples": result.forecasts,
            "gate_examples": int(policy != "allocation_only"),
            "decoder_examples": 1, "png_roundtrips": 1, "utf8_roundtrips": 1,
            "selected_candidate_steps": result.simulated_actions,
            "committed_continuation_steps": result.executed_actions}


def summary(rows):
    return {"count": len(rows), **{
        measure: {"mean": statistics.mean(row[measure] for row in rows),
                  "median": statistics.median(row[measure] for row in rows),
                  "min": min(row[measure] for row in rows),
                  "max": max(row[measure] for row in rows)}
        for measure in ("wall_ns", "cpu_ns", "continuation_action_examples", "forecast_nn_examples")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "manifest", "plan-run", "pilot", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    module = Path(__file__).resolve().parent
    spec = json.loads((module / "forecast_spec.json").read_text())
    pilot, plan_run = Path(args.pilot), Path(args.plan_run)
    status = json.loads((pilot / "status.json").read_text())
    plan_status = json.loads((plan_run / "status.json").read_text())
    if (status["status"] != "completed" or status["formal_holdout_opened"]
            or plan_status["status"] != "completed" or plan_status["formal_holdout_opened"]
            or spec != status["specification"]):
        raise ValueError("Cost replay requires the exact completed development registration")
    sources = [*module.glob("*.py"), module / "forecast_spec.json",
               *(module.parent / "v6" / f"{name}.py" for name in ("data", "neural", "observer", "plan_training"))]
    pins = {str(path): file_sha(path) for path in sources}
    for path in (Path(args.manifest), pilot / "status.json", plan_run / "status.json"):
        pins[str(path)] = file_sha(path)
    corpus = load_roles(args.cache, args.manifest, ("development",))
    if corpus.manifest["manifest_sha256"] != status["source_manifest_sha256"]:
        raise ValueError("Cost source role differs from the completed pilot")
    plans = {}
    for profile in PROFILES:
        plans[profile], source_pins = fixed_plans(pilot, profile, spec["continuation_action_penalty"])
        pins.update(source_pins)
    registration = {"schema": "hepta.ndu-v7.batch-one-cost.v1", "status": "prepared",
                    "formal_holdout_opened": False, "observer_or_target_in_policy": False,
                    "source_manifest_sha256": corpus.manifest["manifest_sha256"],
                    "pairs": spec["timing_pairs"], "views": spec["timing_views"],
                    "policies": POLICIES, "training_profiles": PROFILES, "threads": spec["threads"],
                    "public_seed": 424242, "latent_seed_rule": "73421 + pair_index",
                    "fixed_plans": plans, "source_and_input_file_sha256": pins,
                    "timing_scope": "batch-one encode including gate and actual initial trace; all policy NN/steps; AR decode; PNG/UTF8 write/read; final state identity",
                    "outside_timing": "Python import; model load (reported separately); input acquisition; corpus preparation; aggregate report serialization",
                    "same_budget_is_equal_work_claim": False, "equal_wall_or_cpu_budget_claim": False,
                    "native_mpc_timing_claim": False, "four_modal_timing_claim": False,
                    "scientific_superiority_claim": False,
                    "host": {"platform": platform.platform(), "python": platform.python_version(), "torch": torch.__version__}}
    (output / "registration.json").write_bytes(canonical(registration) + b"\n")
    torch.set_num_threads(spec["threads"])
    snapshots, forecasts, loading = {}, {}, {}
    for profile in PROFILES:
        model_path, forecast_path = plan_run / f"{profile}.pt", pilot / profile / "forecast.pt"
        model_sha = plan_status["result"][profile]["file_sha256"]
        forecast_sha = status["result"][profile]["forecast_file_sha256"]
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        snapshots[profile] = ControlledSnapshot.load(model_path, expected_file_sha256=model_sha)
        forecasts[profile] = CategoricalForecast.load(forecast_path, expected_file_sha256=forecast_sha)
        loading[profile] = {"wall_ns": time.perf_counter_ns() - wall,
                            "cpu_ns": time.process_time_ns() - cpu,
                            "model_file_sha256": model_sha, "forecast_file_sha256": forecast_sha}
        if forecasts[profile].snapshot_digest != snapshots[profile].fingerprint:
            raise ValueError("Cost checkpoint/forecast binding mismatch")
        pins[str(model_path)], pins[str(forecast_path)] = model_sha, forecast_sha
    # Create the same observations as the pilot's 64-pair batch, then slice each
    # into one example. No repeated-batch speedup enters the inference timers.
    batches = {view: make_batch(corpus, "development", spec["development_pairs"], 424242,
                               view=view, offset=0) for view in spec["timing_views"]}
    warmup, rows = [], []
    for profile in PROFILES:
        batch = batches[spec["timing_views"][0]]
        observation = Observation(*(getattr(batch.observation, name)[:1] for name in
                                    ("pixels", "mask", "text_tokens")))
        for policy in POLICIES:
            static = plans[profile]["static_pool" if policy == "static_pool" else "static"]
            warmup.append({"profile": profile, "policy": policy,
                           **infer_once(snapshots[profile], forecasts[profile], observation, policy,
                                        static, output / "warmup" / profile / policy, 73421)})
    for pair in range(spec["timing_pairs"]):
        for view_index, view in enumerate(spec["timing_views"]):
            batch = batches[view]
            observation = Observation(*(getattr(batch.observation, name)[pair:pair + 1] for name in
                                        ("pixels", "mask", "text_tokens")))
            public_sha = observation_digest(observation)
            order = tuple((profile, policy) for policy in POLICIES for profile in PROFILES)
            shift = (pair * len(spec["timing_views"]) + view_index) % len(order)
            for profile, policy in order[shift:] + order[:shift]:
                static = plans[profile]["static_pool" if policy == "static_pool" else "static"]
                receipt = infer_once(snapshots[profile], forecasts[profile], observation, policy, static,
                                     output / "raw" / f"{pair:02d}" / view / profile / policy, 73421 + pair)
                rows.append({"profile": profile, "policy": policy, "pair": pair, "view": view,
                             "source_ids": batch.source_ids[pair], "public_observation_sha256": public_sha,
                             "noise_seed": 73421 + pair, **receipt})
    for snapshot in snapshots.values():
        snapshot.verify_integrity()
    for forecast in forecasts.values():
        forecast.verify_integrity()
    if pins != {path: file_sha(path) for path in pins}:
        raise RuntimeError("Cost execution source/input/checkpoint changed")
    expected = len(PROFILES) * len(POLICIES) * spec["timing_pairs"] * len(spec["timing_views"])
    if len(rows) != expected:
        raise RuntimeError("Incomplete cost census")
    rows_path = output / "rows.jsonl"
    rows_path.write_bytes(b"".join(canonical(row) + b"\n" for row in rows))
    report = {**registration, "status": "completed", "loading": loading, "warmup": warmup,
              "source_and_input_file_sha256": pins, "rows": len(rows),
              "rows_file_sha256": file_sha(rows_path),
              "summary": {f"{profile}/{policy}": summary([row for row in rows if
                          row["profile"] == profile and row["policy"] == policy])
                          for profile in PROFILES for policy in POLICIES}}
    (output / "summary.json").write_bytes(canonical(report) + b"\n")
    print(json.dumps({"status": "completed", "rows": len(rows), "summary": report["summary"]}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
