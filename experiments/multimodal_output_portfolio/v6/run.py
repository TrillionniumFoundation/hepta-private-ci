"""Execute versioned real neural generation, control, and independent scoring.

An output directory is single-use. The complete data/protocol/source manifest is
written before training; failed/partial experiments are retained, never resumed
as if they were complete. All evaluator labels stay outside inference backends.
"""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import traceback

import torch

from .control import ControllerConfig, WorkBudget, choose
from .data import Observation, load_corpus, make_batch, render_tokens
from .forecast import ForecastArtifact, fit_forecast
from .joint_contract import PROFILE as JOINT_CONTRACT_PROFILE
from .joint_contract import bind_v6_output, latent_digest, require_v6_capabilities
from .neural import TrainConfig, train_profiles
from .observer import METRIC, METRIC_DIGEST, fit_observer, observe_tensors, read_bundle, write_bundle
from .plan_training import ALLOCATION_PLAN, ControlledSnapshot, PLANS, fit_plan_head
from .reporting import evaluate_native, owner_tsv, summarize


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def source_identity():
    root = Path(__file__).resolve().parents[3]
    paths = sorted(Path(__file__).parent.glob("*.py"))
    paths.extend(sorted(Path(__file__).parent.glob("protocol*.json")))
    paths.append(Path(__file__).parent / "neuron_calibration_spec.json")
    paths.extend(sorted(root.glob("codex-rs/hepta-ndu/src/**/*.rs")))
    for crate in ("hepta-infer-core", "hepta-infer-worker-host", "hepta-neuron",
                  "hepta-bellman-operator", "hepta-intelligence-eval"):
        paths.extend(sorted(root.glob(f"codex-rs/{crate}/src/**/*.rs")))
        paths.append(root / "codex-rs" / crate / "Cargo.toml")
    paths.extend(sorted(root.glob("codex-rs/hepta-infer-worker-host/tests/generation_owner_execution*.rs")))
    paths.extend(sorted(root.glob("codex-rs/hepta-agentd/tests/generation_*.rs")))
    paths.extend(sorted(root.glob("codex-rs/hepta-agentd/tests/support/*.rs")))
    paths.append(root / "codex-rs/hepta-agentd/tests/terminal_cell_subset.rs")
    paths.append(root / "codex-rs/hepta-agentd/Cargo.toml")
    paths.append(root / "codex-rs/hepta-agentd/src/test_support.rs")
    paths.extend(root / path for path in (
        "codex-rs/hepta-ndu/Cargo.toml", "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml"))
    files = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in paths}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    return {"git_commit": commit, "files": files, "bundle_sha256": digest(files),
            "dirty": bool(subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True).strip())}


def case_batch(corpus, split, index, corruption):
    source_split = "test" if split == "future" else "retention"
    actual = "missing" if corruption in ("wrong_hint", "missing_no_hint") else corruption
    batch = make_batch(corpus, source_split, 1, 424242 + index, actual,
                       offset=index, drop_hint=corruption == "missing_no_hint")
    if corruption == "wrong_hint":
        tokens = batch.observation.text_tokens.clone()
        for location in (3, 5):
            if int(tokens[0, location]) >= 14:
                tokens[0, location] = 14 + (int(tokens[0, location]) - 14 + 1) % 10
        batch = replace(batch, observation=Observation(
            batch.observation.pixels, batch.observation.mask, tokens))
    return batch


def registered_cases(corpus, config):
    """Freeze disjoint source identities before any fit or heldout scoring."""
    offsets = config.get("evaluation_case_offsets", {"future": 0, "retention": 0})
    if not isinstance(offsets, dict) or set(offsets) != {"future", "retention"} or any(
            type(value) is not int or value < 0 for value in offsets.values()):
        raise ValueError("Evaluation offsets must be nonnegative exact integers for both splits")
    exclusion = config.get("prior_heldout_exclusion")
    excluded = set()
    if exclusion is not None:
        supplied = exclusion.get("source_pixel_sha256", [])
        prior_digest = exclusion.get("protocol_sha256", "")
        hashes = [*supplied, prior_digest]
        if (not supplied or len(set(supplied)) != len(supplied) or any(
                not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in hashes)):
            raise ValueError("Prior heldout exclusion requires unique source and protocol hashes")
        excluded = set(supplied)
    cases, used = {}, set()
    for split, count in (("future", config["future_cases"]),
                         ("retention", config["retention_cases"])):
        if type(count) is not int or count < 1:
            raise ValueError("Each evaluation cohort needs a positive exact case count")
        cases[split] = []
        for ordinal in range(count):
            index = offsets[split] + ordinal
            corruption = (config["corruptions"][ordinal % len(config["corruptions"])]
                          if split == "future" else "clean")
            batch = case_batch(corpus, split, index, corruption)
            sources = list(batch.source_ids[0])
            pixel_ids = {source.rsplit(":", 1)[-1] for source in sources}
            if len(pixel_ids) != 2 or pixel_ids & (excluded | used):
                raise ValueError("Evaluation reuses a source within or across frozen experiments")
            used.update(pixel_ids)
            cases[split].append({"case_id": f"{split}-{index:04}", "source_ids": sources,
                                 "corruption": corruption, "index": index})
    return cases


def rollout(snapshot, forecast, observation, policy, budget_limit, config,
            context_id, noise_seed):
    """No labels or evaluator object cross this function's input boundary."""
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    state = snapshot.encode(observation, noise_seed=noise_seed,
                            content_control=policy != "allocation_only")
    encode_ns = time.perf_counter_ns() - start_wall
    initial_actions = list(ALLOCATION_PLAN if state.plan_index == -1 else PLANS[state.plan_index])
    started = time.perf_counter_ns()
    backend = forecast.backend(snapshot, context_id, observation=observation)
    backend_setup_ns = time.perf_counter_ns() - started
    work = WorkBudget(budget_limit, stop_reserve=4,
                      initial_work=3 + int(policy != "allocation_only") + forecast.public_summary_work)
    if forecast.public_summary_work:
        work.calls["public_summary"] = 1
    choices, controller_ns, execute_ns, actions = [], 0, 0, []
    controller_config = ControllerConfig(
        policy=policy, fixed_order=tuple(forecast.static_sequence or ("refine_image",))
        if policy == "fixed_dev_tuned" else ("refine_image", "refine_text", "couple"),
        **config["control"])
    with backend.inference_guard():
        for step_index in range(config["inference_horizon"]):
            if policy == "fixed_dev_tuned" and step_index >= len(forecast.static_sequence):
                break
            started = time.perf_counter_ns()
            remaining_config = replace(controller_config, horizon=min(
                controller_config.horizon, config["inference_horizon"] - step_index))
            decision = choose(backend, state, work, remaining_config,
                              step_index=step_index, router=backend.router)
            controller_ns += time.perf_counter_ns() - started
            choices.append(asdict(decision))
            if decision.action is None:
                break
            work.charge_execution(backend.action_cost(state, decision.action))
            started = time.perf_counter_ns()
            state = backend.transition(state, decision.action)
            execute_ns += time.perf_counter_ns() - started
            actions.append(decision.action)
        started = time.perf_counter_ns()
        output = snapshot.decode(state)
        pixels = output.image_logits.sigmoid()
        caption = render_tokens(output.token_ids[0])
        decode_ns = time.perf_counter_ns() - started
        # Reserve the known two-crop post-execution observer work as well as decode.
        work.finish_stop(4)
    snapshot.verify_integrity()
    return pixels, caption, {
        "actions": actions, "initial_content_plan": initial_actions,
        "decisions": choices, "calls": work.calls,
        "final_state_sha256": snapshot.state_key(state),
        "latent_sha256": {"shared": latent_digest(state.neural.h),
                          "image": latent_digest(state.neural.image),
                          "text": latent_digest(state.neural.text)},
        "cost": {"wall_ns": time.perf_counter_ns() - start_wall,
                 "cpu_ns": time.process_time_ns() - start_cpu,
                 "encode_ns": encode_ns, "backend_setup_ns": backend_setup_ns,
                 "controller_ns": controller_ns,
                 "execute_ns": execute_ns, "decode_ns": decode_ns,
                 "modeled_work": work.used, "search_units": work.search_work,
                 "execution_units": work.execution_work + snapshot.initial_plan_cost},
    }


def run(config, cache, output, native_binary=None):
    cache = Path(cache).resolve()
    native_binary = Path(native_binary).resolve() if native_binary else None
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows, training_reports, forecast_reports, native_receipts = [], {}, {}, []
    previous_directory = Path.cwd()
    write_json(output / "status.json", {"state": "initializing"})
    try:
        write_json(output / "requested-config.json", config)
        required_modalities = require_v6_capabilities(config.get("hard_output_modalities"))
        started = time.perf_counter_ns()
        torch.set_num_threads(config["training"]["threads"])
        torch.use_deterministic_algorithms(True)
        source = source_identity()
        if config.get("require_clean_source", False) and source["dirty"]:
            raise RuntimeError("This registered protocol requires a clean committed source")
        corpus = load_corpus(cache, evaluator_sources=config["observer_sources"])
        cases = registered_cases(corpus, config)
        protocol = {**config, "cases": cases, "metric": METRIC,
                    "joint_contract": JOINT_CONTRACT_PROFILE,
                    "metric_sha256": METRIC_DIGEST, "source": source,
                    "dataset_manifest": corpus.manifest,
                    "native_binary_sha256": hashlib.sha256(native_binary.read_bytes()).hexdigest()
                    if native_binary else None}
        objective_digest = digest({"metric": METRIC, "requirements": required_modalities})
        write_json(output / "protocol.json", protocol)
        write_json(output / "status.json", {"state": "running", "protocol_sha256": digest(protocol)})
        os.chdir(output)
        observer_pool = corpus.splits["evaluator"]
        half = len(observer_pool) // 2
        pools = [replace(observer_pool, images=observer_pool.images[a:b],
                         labels=observer_pool.labels[a:b], ids=observer_pool.ids[a:b],
                         pixel_hashes=observer_pool.pixel_hashes[a:b])
                 for a, b in ((0, half), (half, len(observer_pool)))]
        observer, reward_report = fit_observer(
            pools[0], steps=config["observer_steps"], seed=config["observer_seeds"]["reward"])
        audit_observer, audit_report = fit_observer(
            pools[1], steps=config["observer_steps"], seed=config["observer_seeds"]["audit"])
        observer_report = {"reward": reward_report, "audit": audit_report,
                           "source_disjoint": not bool(set(pools[0].pixel_hashes) & set(pools[1].pixel_hashes)),
                           "audit_model_exposed_to_training_or_control": False}
        torch.save(observer.state_dict(), output / "reward-observer.pt")
        torch.save(audit_observer.state_dict(), output / "audit-observer.pt")
        observer_report["weights_sha256"] = {name: hashlib.sha256(
            (output / f"{name}-observer.pt").read_bytes()).hexdigest() for name in ("reward", "audit")}
        write_json(output / "observer.json", observer_report)
        print(canonical({"observer": observer_report}), flush=True)
        for seed in config["seeds"]:
            print(canonical({"training_seed": seed}), flush=True)
            def progress(profile, record):
                print(canonical({"seed": seed, "profile": profile, **record}), flush=True)
            bases, pretraining = train_profiles(
                corpus, TrainConfig(seed=seed, **config["training"]), progress=progress)
            for training in config["trainings"]:
                label = f"seed-{seed}-{training}"
                snapshot, plan_report = fit_plan_head(
                    bases[training], corpus, observer, training, seed,
                    fit_pairs=config["plan_fit_pairs"], steps=config["plan_fit_steps"])
                model_path = output / f"{label}.pt"
                snapshot.save(model_path)
                model_file_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
                # Deserialize the complete selected model before any evaluation.
                restored = ControlledSnapshot.load(model_path,
                                                    expected_file_sha256=model_file_sha256)
                if restored.fingerprint != snapshot.fingerprint:
                    raise RuntimeError("Fresh model reload changed parameters")
                snapshot = restored
                training_reports[label] = {"pretraining": pretraining[training],
                                           "content_plan": plan_report,
                                           "checkpoint_file_sha256": model_file_sha256,
                                           "snapshot_sha256": snapshot.fingerprint}
                write_json(output / "training.json", training_reports)
                forecast, forecast_report = fit_forecast(
                    snapshot, corpus, observer, seed,
                    fit_pairs=config["forecast_fit_pairs"],
                    calibration_pairs=config["forecast_calibration_pairs"],
                    dev_pairs=config["forecast_dev_pairs"],
                    horizon=config["inference_horizon"],
                    action_cost_penalty=config["control"]["cost_penalty"],
                    distribution=config.get("forecast_distribution", "empirical_residual_v1"))
                forecast_path = output / f"{label}-forecast.pt"
                forecast.save(forecast_path)
                forecast_file_sha256 = hashlib.sha256(forecast_path.read_bytes()).hexdigest()
                restored_forecast = ForecastArtifact.load(
                    forecast_path, expected_file_sha256=forecast_file_sha256)
                if restored_forecast.fingerprint != forecast.fingerprint:
                    raise RuntimeError("Fresh forecast reload changed its frozen identity")
                forecast = restored_forecast
                forecast_report["checkpoint_file_sha256"] = forecast_file_sha256
                forecast_reports[label] = forecast_report
                write_json(output / "forecast.json", forecast_reports)
                print(canonical({"trained": label, "snapshot": snapshot.fingerprint}), flush=True)
                for split, split_cases in cases.items():
                    for case in split_cases:
                        batch = case_batch(corpus, split, case["index"], case["corruption"])
                        for budget in config["budgets"]:
                            group = []
                            policy_order = list(config["policies"])
                            random.Random(seed * 100003 + case["index"] * 17 + budget).shuffle(policy_order)
                            for order, policy in enumerate(policy_order):
                                key = f"{label}-{case['case_id']}-b{budget}-{policy}"
                                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                                pixels, caption, trace = rollout(
                                    snapshot, forecast, batch.observation, policy, budget,
                                    config, case["case_id"], noise_seed=seed * 10000 + case["index"])
                                paths = write_bundle(output / "outputs" / key, caption, pixels)
                                observed_start = time.perf_counter_ns()
                                raw_pixels, raw_caption, hashes = read_bundle(paths)
                                joint_output = bind_v6_output(
                                    required_modalities, snapshot.fingerprint,
                                    trace["final_state_sha256"], trace["latent_sha256"],
                                    hashes, case["case_id"])
                                metrics = observe_tensors(audit_observer, raw_pixels, [raw_caption],
                                                          batch.target.pixels,
                                                          batch.target.labels)[0]
                                trace["cost"]["observer_ns"] = time.perf_counter_ns() - observed_start
                                trace["cost"]["inference_ns"] = trace["cost"]["wall_ns"]
                                trace["cost"]["wall_ns"] = time.perf_counter_ns() - wall
                                trace["cost"]["cpu_ns"] = time.process_time_ns() - cpu
                                row = {"seed": seed, "training": training, "policy": policy,
                                       "split": split, "case_id": case["case_id"], "budget": budget,
                                       "source_ids": case["source_ids"], "corruption": case["corruption"],
                                       "snapshot_sha256": snapshot.fingerprint,
                                       "snapshot_file_sha256": model_file_sha256,
                                       "forecast_sha256": forecast.fingerprint,
                                       "forecast_file_sha256": forecast_file_sha256,
                                       "observer_sha256": observer_report["weights_sha256"]["audit"],
                                       "reward_observer_sha256": observer_report["weights_sha256"]["reward"],
                                       "metrics": metrics,
                                       "output_paths": {kind: str(Path(path).relative_to(output))
                                                        for kind, path in paths.items()},
                                       "execution_order": order,
                                       "joint_output_contract": joint_output,
                                       "output_hashes": hashes, **trace}
                                row["receipt_sha256"] = digest(row)
                                rows.append(row)
                                group.append(row)
                                with (output / "rows.jsonl").open("a") as handle:
                                    handle.write(canonical(row) + "\n")
                            if native_binary:
                                exported = owner_tsv(group, objective_digest,
                                                     source["bundle_sha256"], METRIC_DIGEST,
                                                     budget, 60_000_000_000)
                                native_start = time.perf_counter_ns()
                                receipt = evaluate_native(exported, native_binary)
                                receipt["adapter_wall_ns"] = time.perf_counter_ns() - native_start
                                receipt["binary_sha256"] = protocol["native_binary_sha256"]
                                native_receipts.append(receipt)
                                with (output / "native-receipts.jsonl").open("a") as handle:
                                    handle.write(canonical(receipt) + "\n")
                        if case["index"] % 10 == 0:
                            print(canonical({"evaluated": label, "split": split,
                                             "case": case["index"], "rows": len(rows)}), flush=True)
        final_source = source_identity()
        if (final_source["files"] != source["files"]
                or (config.get("require_clean_source", False) and final_source != source)):
            raise RuntimeError("Source changed during the experiment")
        report = summarize(rows, protocol)
        try:
            import resource
            peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_rss *= 1 if sys.platform == "darwin" else 1024
        except ImportError:
            peak_rss = None
        report.update({"source": source, "protocol_sha256": digest(protocol),
                       "observer": observer_report, "native_receipt_count": len(native_receipts),
                       "end_to_end_wall_ns": time.perf_counter_ns() - started,
                       "environment": {"python": sys.version, "torch": torch.__version__,
                                       "platform": platform.platform(), "cuda": torch.cuda.is_available()},
                       "run_process_peak_rss_bytes": peak_rss,
                       "energy_joules": None, "energy_measurement_available": False})
        write_json(output / "native-receipts.json", native_receipts)
        write_json(output / "summary.json", report)
        write_json(output / "status.json", {"state": "completed", "rows": len(rows),
                                            "summary_sha256": digest(report)})
        print(canonical({"completed": str(output), "rows": len(rows)}), flush=True)
        return report
    except BaseException as error:
        write_json(output / "status.json", {"state": "failed", "rows": len(rows),
                                            "error": str(error), "traceback": traceback.format_exc()})
        raise
    finally:
        os.chdir(previous_directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("protocol.json"))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.protocol.read_text())
    if args.smoke:
        config.update(mode="mechanism_smoke_only", seeds=[17], budgets=[64],
                      future_cases=2, retention_cases=2, observer_steps=10,
                      plan_fit_pairs=4, plan_fit_steps=4, forecast_fit_pairs=4,
                      forecast_calibration_pairs=4, forecast_dev_pairs=4)
        config["training"].update(steps=12, batch_size=8, hidden=32)
        if "mechanism_smoke_case_offsets" in config:
            config["evaluation_case_offsets"] = dict(config["mechanism_smoke_case_offsets"])
    run(config, args.cache, args.output, args.native_binary)


if __name__ == "__main__":
    main()
