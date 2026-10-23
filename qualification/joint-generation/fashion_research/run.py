"""Frozen, local-data-only D probe. Importing this entry does not load data."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

from .cost import AdmissionRefused, Budget, BudgetExceeded, cpu_ns
from .lifecycle import Progress, atomic_json, worker_signals

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FROZEN = HERE / "FROZEN-recovery-v2.json"
PROTOCOL = HERE / "protocol-recovery-v2.json"
MARKER = HERE / "D-PROBE-OPENED.json"
NS = 10**9


def write_json(path, value):
    atomic_json(path, value)


def sources():
    files = list(HERE.glob("*.py")) + [HERE / "protocol.json", PROTOCOL, HERE / "MIT-DATA-LICENSE.txt",
        ROOT / "contracts.py", ROOT / "multimodal_contract.py",
        ROOT / "research/fashion-mnist-candidate-20261023/plan.json"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def freeze():
    if FROZEN.exists() or MARKER.exists():
        raise ValueError("freeze/measurement identity already exists")
    import subprocess
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    write_json(FROZEN, {"schema": "hepta.fashion-D-freeze.v1", "sources": sources(),
        "source_commit": head, "numpy": importlib.metadata.version("numpy"),
        "threadpoolctl": importlib.metadata.version("threadpoolctl"),
        "previous_freeze_sha256": hashlib.sha256((HERE / "FROZEN.json").read_bytes()).hexdigest(),
        "candidate_commit": "dedbb0a0d3470dd58bfafbe770c8d916f7ff17cc",
        "created_unix_ns": time.time_ns(), "scope": "D preprobe only; no formal evaluation"})


def preflight(data, out):
    frozen = json.loads(FROZEN.read_text())
    if frozen["sources"] != sources() or frozen["numpy"] != "2.3.5":
        raise ValueError("frozen complete source/runtime identity mismatch")
    if importlib.metadata.version("numpy") != frozen["numpy"]:
        raise ValueError("installed NumPy differs from freeze")
    if frozen.get("threadpoolctl") != importlib.metadata.version("threadpoolctl"):
        raise ValueError("installed threadpoolctl differs from freeze")
    if MARKER.exists():
        raise ValueError("D measurement identity already consumed; no repeat")
    for name in ("train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz"):
        if not (Path(data) / name).is_file():
            raise FileNotFoundError("required local official TRAIN file missing: " + name)
    output = Path(out)
    if output.exists():
        raise ValueError("output already exists; retain its uncertain/terminal state")


def smoke():
    # The real module/import path, without constructors, fitting, dataset IO or
    # marker/output creation. Hand-made tensors are tested in separate tests.
    from . import data, model, transport
    from threadpoolctl import threadpool_info
    required = (data.load_train, data.noisy_images, model.ContentModel,
                model.Actor, transport.encode, transport.decode, transport.score)
    if not all(callable(v) for v in required):
        raise RuntimeError("entry dependency API missing")
    return {"schema": "hepta.fashion-D-no-data-smoke.v1", "status": "passed",
            "constructors_called": False, "data_loaded": False,
            "marker_created": False, "measurement_started": False,
            "dependency_source_files": len(sources()),
            "BLAS_thread_pools": threadpool_info()}


def train_content(model, z, clean, labels, seed, budget, output, protocol):
    import numpy as np
    start = cpu_ns()
    rng = np.random.Generator(np.random.PCG64DXSM(seed + 20000))
    noise_rng = np.random.Generator(np.random.PCG64DXSM(seed + 30000))
    order, cursor, epochs, steps = rng.permutation(len(z)), 0, 0, 0
    quotes, initial_saved = [], False
    cap = protocol["content_CPU_ns"]
    before_params = {k: v.copy() for k, v in model.params.items()}
    cycle = protocol["sequence_cycle"]
    journal = output / "training-progress.jsonl"
    journal.touch(exist_ok=False)
    while True:
        quote = max(5_000_000, 2 * max(quotes)) if len(quotes) >= 9 else protocol["bootstrap_step_quote_CPU_ns"]
        try:
            budget.check(quote, start_ns=start, phase_ns=cap,
                         phase_tail_ns=protocol["content_bookkeeping_tail_CPU_ns"],
                         tail_ns=protocol["global_required_tail_CPU_ns"] + protocol["policy_tail_quote_CPU_ns"])
        except AdmissionRefused as error:
            if "phase" not in str(error) or steps < 9:
                raise
            break
        if not initial_saved and (epochs >= 2 or cpu_ns() - start + quote > 150 * NS):
            model.export(output / "initial.npz", include_optimizer=True)
            initial_saved = True
        if cursor == len(order):
            order, cursor = rng.permutation(len(z)), 0
        index = order[cursor:cursor + 64]
        t = cpu_ns()
        try:
            loss, grads, metrics = model.loss_grad(z[index], clean[index], labels[index],
                                                  cycle[steps % 9], noise_rng)
            model.adam_step(grads, lr=0.001)
        except Exception as error:
            with journal.open("a") as stream:
                stream.write(json.dumps({"step": steps, "sequence": cycle[steps % 9],
                    "CPU_ns": cpu_ns()-t, "status": "operation_failed", "error": repr(error)}) + "\n")
            raise
        elapsed = cpu_ns() - t
        quotes.append(elapsed)
        with journal.open("a") as stream:
            stream.write(json.dumps({"step": steps, "sequence": cycle[steps % 9],
                "CPU_ns": elapsed, "loss": loss, "status": "updated",
                "timing_boundary": "loss/VJP/Adam; journal and control also charged by phase clock"}) + "\n")
        budget.check(start_ns=start, phase_ns=cap)
        cursor += len(index)
        if cursor == len(order):
            epochs += 1
        steps += 1
    if not initial_saved:
        raise RuntimeError("content quota did not produce initial checkpoint")
    result = {"steps": steps, "epochs_completed": epochs, "last_loss": loss,
            "last_metrics": metrics, "calibration_first9_CPU_ns": quotes[:9],
            "all_observed_step_CPU_ns": quotes,
            "maximum_observed_step_CPU_ns": max(quotes), "final_digest": model.digest(),
            "parameter_delta_L2": {k: float(np.linalg.norm(v - before_params[k]))
                                   for k, v in model.params.items()},
            "cpu_ns": cpu_ns() - start}
    budget.check(start_ns=start, phase_ns=cap)
    return result


def labels_and_features(model, z, clean, y, budget, output, policy_start, protocol):
    import numpy as np
    from .transport import encode, score
    schedule = ["", "T", "I", "J"] + protocol["sequence_cycle"]
    values = {s: [] for s in schedule}
    features, rows, wire_bytes = [], [], 0
    (output / "wire").mkdir()
    for start in range(0, len(z), 64):
        budget.check(2 * NS, start_ns=policy_start,
                     phase_ns=protocol["policy_selection_export_CPU_ns"],
                     phase_tail_ns=protocol["seed_export_tail_CPU_ns"],
                     tail_ns=protocol["global_required_tail_CPU_ns"], extra_bytes=50_000_000)
        predictions, f = model.all_sequences(z[start:start + 64], return_features=True)
        features.append(f)
        for sequence in schedule:
            pred = predictions[sequence]
            payload = encode(pred.p, pred.image)
            path = output / "wire" / f"{sequence or 'empty'}-{start:06d}.json"
            path.write_bytes(payload)
            wire_bytes += len(payload)
            result = score(payload, clean[start:start + 64].reshape(-1, 28, 28), y[start:start + 64])
            values[sequence].append(result["utility"])
            for j in range(len(result["utility"])):
                rows.append({"policy_row": start + j, "sequence": sequence,
                             "accuracy": float(result["accuracy"][j]),
                             "mse": float(result["mse"][j]),
                             "utility": float(result["utility"][j])})
        budget.check(start_ns=policy_start, phase_ns=protocol["policy_selection_export_CPU_ns"])
    values = {s: np.concatenate(v) for s, v in values.items()}
    write_json(output / "paired-rows.json", rows)
    np.savez(output / "policy-labels.npz", features=np.concatenate(features), **{s or "empty": v for s, v in values.items()})
    return np.concatenate(features), values, wire_bytes


def fit_actor(features, targets, folds, seed, budget, policy_start, output, protocol):
    import numpy as np
    from .model import Actor
    oof = np.empty_like(targets)
    fits = []
    for fold in range(4):
        train = np.flatnonzero(folds != fold) if fold < 3 else np.arange(len(folds))
        hold = np.flatnonzero(folds == fold) if fold < 3 else np.arange(len(folds))
        if not len(train) or not len(hold):
            raise ValueError("empty grouped policy train/hold fold")
        actor = Actor(seed + 40000 + fold)
        rng = np.random.Generator(np.random.PCG64DXSM(seed + 100000 + fold))
        order, cursor = rng.permutation(train), 0
        for step in range(protocol["policy_updates"]):
            budget.check(protocol["policy_step_quote_CPU_ns"], start_ns=policy_start,
                         phase_ns=protocol["policy_selection_export_CPU_ns"],
                         phase_tail_ns=protocol["seed_export_tail_CPU_ns"],
                         tail_ns=protocol["global_required_tail_CPU_ns"])
            if cursor == len(order):
                order, cursor = rng.permutation(train), 0
            batch = order[cursor:cursor + 64]
            loss, grads, _ = actor.loss_grad(features[batch], targets[batch])
            actor.adam_step(grads, lr=0.001)
            budget.check(start_ns=policy_start, phase_ns=protocol["policy_selection_export_CPU_ns"])
            cursor += len(batch)
        if fold < 3:
            oof[hold] = actor.predict(features[hold])
        else:
            actor.export(output / "actor.npz")
        fits.append({"fold": fold, "updates": protocol["policy_updates"], "train_rows": len(train),
                     "hold_rows": len(hold), "final_loss": float(loss), "digest": actor.digest()})
    chosen = oof.argmax(axis=1)
    return chosen, fits, oof, actor.predict(features[:64]), actor.digest()


def prepare_policy_indices(fit, policy, metadata):
    import numpy as np
    position = {int(row): i for i, row in enumerate(fit)}
    return (np.asarray([position[int(row)] for row in policy]),
            np.asarray([metadata["rows"][int(row)]["fold"] for row in policy]))


def close_shared_preparation(fit, policy, metadata, budget, protocol):
    pindex, folds = prepare_policy_indices(fit, policy, metadata)
    row = budget.row("shared_intake_noise_and_policy_indices", 0)
    budget.check(phase_ns=protocol["shared_CPU_ns"])
    return pindex, folds, row["end_cpu_ns"]


def worker(data_path, out):
    preflight(data_path, out)
    if any(os.environ.get(key) != "1" for key in
           ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")):
        raise ValueError("worker requires declared single-thread environment")
    output = Path(out)
    output.mkdir(parents=True)
    budget = Budget(output)
    protocol = json.loads(PROTOCOL.read_text())
    progress = Progress(output, protocol["seeds"])
    terminal = {"schema": "hepta.fashion-D-preprobe-result.v1", "status": "failed",
                "qualification": False, "measurement_started": False, "seeds": [],
                "started_seeds": []}
    code = 1
    try:
        # The latch precedes all measured intake. Missing local files/source
        # mismatch fail in cheap preflight and never consume this identity.
        with MARKER.open("x") as f:
            json.dump({"freeze_sha256": hashlib.sha256(FROZEN.read_bytes()).hexdigest(),
                       "output": str(output.resolve()), "started_unix_ns": time.time_ns()}, f)
        terminal["measurement_started"] = True
        progress.start_stage("shared")
        import numpy as np
        from threadpoolctl import threadpool_info
        from .data import load_train, noisy_images
        from .model import ContentModel, Actor
        pools = threadpool_info()
        if not pools or any(pool["num_threads"] != 1 for pool in pools):
            raise ValueError("actual numerical backend is not single threaded")
        write_json(output / "runtime.json", {"numpy": np.__version__, "thread_pools": pools,
                                             "python": sys.version})
        budget.check(5 * NS, phase_ns=protocol["shared_CPU_ns"], tail_ns=15 * NS)
        data = load_train(data_path, cache_noisy=False)
        fit, policy = data["indices"]["FIT"], data["indices"]["POLICY"]
        raw, y = data["images"], data["labels"]
        z = noisy_images(raw[fit])
        clean = raw[fit].astype(np.float64) / 255
        write_json(output / "all-TRAIN-identities.json", data["metadata"])
        np.save(output / "FIT-noisy.npy", z)
        (output / "MIT-DATA-LICENSE.txt").write_bytes((HERE / "MIT-DATA-LICENSE.txt").read_bytes())
        pindex, folds, build_boundary = close_shared_preparation(
            fit, policy, data["metadata"], budget, protocol)
        progress.complete_stage("shared")
        for seed in protocol["seeds"]:
            # Transition bookkeeping belongs to the following build, which
            # starts at the preceding exact closing timestamp.
            build_start = build_boundary
            terminal["started_seeds"].append(seed)
            terminal["active_seed"] = seed
            progress.start_stage("content", seed)
            folder = output / str(seed)
            folder.mkdir()
            model = ContentModel(seed)
            training = train_content(model, z, clean, y[fit], seed, budget, folder, protocol)
            progress.complete_stage("content", seed)
            policy_start = cpu_ns()
            progress.start_stage("export", seed)
            model.export(folder / "final.npz", include_optimizer=True)
            reloaded = ContentModel.load(folder / "final.npz")
            if (reloaded.digest() != model.digest()
                    or reloaded.optimizer_digest() != model.optimizer_digest()):
                raise RuntimeError("content/optimizer export-reload mismatch")
            progress.complete_stage("export", seed)
            progress.start_stage("policy", seed)
            features, values, wire_bytes = labels_and_features(model, z[pindex], clean[pindex], y[policy], budget, folder, policy_start, protocol)
            targets = np.column_stack([values[s] for s in ("JT", "JI", "JJ")])
            best_static = max(float(v.mean()) for v in values.values())
            oracle = float(targets.max(axis=1).mean())
            row = {"seed": seed, "training": training, "wire_bytes": wire_bytes,
                   "static_means": {s or "empty": float(v.mean()) for s, v in values.items()},
                   "oracle_U": oracle, "best_static_U": best_static,
                   "oracle_headroom": oracle - best_static}
            terminal["seeds"].append(row)
            budget.check(start_ns=policy_start, phase_ns=protocol["policy_selection_export_CPU_ns"])
            budget.check(start_ns=build_start, phase_ns=protocol["seed_build_CPU_ns"])
            if not oracle > best_static:
                progress.complete_stage("policy", seed)
                budget.check(start_ns=policy_start, phase_ns=protocol["policy_selection_export_CPU_ns"])
                build_boundary = budget.row(f"seed-{seed}-complete-build", build_start)["end_cpu_ns"]
                terminal["status"] = "negative_development_probe"
                terminal["reason"] = "predeclared negative: no positive oracle raw headroom"
                break
            choices, fits, oof, original_prediction, original_digest = fit_actor(features, targets, folds, seed, budget, policy_start, folder, protocol)
            value = float(targets[np.arange(len(targets)), choices].mean())
            best_constant = float(targets.mean(axis=0).max())
            row.update(oof_U=value, best_constant_final_U=best_constant,
                       oof_gain=value-best_constant, actor_fits=fits,
                       choice_counts=np.bincount(choices, minlength=3).tolist(),
                       mean_oracle_regret=float((targets.max(axis=1)-targets[np.arange(len(targets)), choices]).mean()))
            np.savez(folder / "OOF.npz", predictions=oof, choices=choices, folds=folds, targets=targets)
            # Necessary method reload verification, not publication review.
            loaded_actor = Actor.load(folder / "actor.npz")
            if (loaded_actor.digest() != original_digest
                    or not np.array_equal(loaded_actor.predict(features[:64]), original_prediction)):
                raise RuntimeError("actor export/reload mismatch")
            budget.check(start_ns=policy_start, phase_ns=protocol["policy_selection_export_CPU_ns"])
            budget.check(start_ns=build_start, phase_ns=protocol["seed_build_CPU_ns"])
            progress.complete_stage("policy", seed)
            budget.check(start_ns=policy_start, phase_ns=protocol["policy_selection_export_CPU_ns"])
            build_boundary = budget.row(f"seed-{seed}-complete-build", build_start)["end_cpu_ns"]
            if not value > best_constant:
                terminal["status"] = "negative_development_probe"
                terminal["reason"] = "predeclared negative: OOF does not improve best constant final action"
                break
        else:
            code = 0
            terminal["status"] = "positive_development_probe_only"
            terminal["reason"] = "Return to parent; no automatic strong-static expansion or scientific pass"
    except Exception as error:
        terminal["reason"] = type(error).__name__ + ": " + str(error)
    finally:
        progress.interrupt_for_receipt()
        terminal.update(progress.snapshot())
        terminal["exit_code"] = code
        terminal["unrun_seeds"] = [seed for seed in protocol["seeds"]
                                   if seed not in terminal["started_seeds"]]
        terminal["cost_before_required_receipt"] = budget.snapshot()
        terminal["not_run"] = ["SELECT", "SCREEN", "official TEST", "other five arms", "formal confirmation"]
        write_json(output / "result.json", terminal)
        try:
            budget.check()
        except BudgetExceeded as error:
            code = 1
            terminal.update(status="failed", exit_code=1, reason="required receipt tail: " + str(error))
            write_json(output / "result.json", terminal)
        progress.complete_stage("final_receipt")
        try:
            budget.check()
        except BudgetExceeded as error:
            code = 1
            terminal.update(status="failed", exit_code=1, reason="required progress tail: " + str(error))
            write_json(output / "result.json", terminal)
    return code


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--smoke", action="store_true")
    action.add_argument("--freeze", action="store_true")
    action.add_argument("--worker", action="store_true")
    parser.add_argument("--data")
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.smoke:
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    if args.freeze:
        freeze()
        return 0
    if not args.data or not args.out:
        parser.error("worker requires local --data and --out")
    with worker_signals():
        return worker(args.data, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
