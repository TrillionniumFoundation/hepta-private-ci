"""Execute the preregistered study; training and test deployment are separate phases."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import torch

from ..v6.data import load_corpus, make_batch
from ..v6.neural import parameter_hash
from ..v6.observer import Recognizer, observe_tensors
from ..v6.plan_training import ControlledSnapshot
from .adapters import make_model, load_adapter, save_adapter, local_hash, local_parameters
from .adaptation import adapt, explore, fixed_output
from .controls import native_features, history_features, fit_readout, choose
from .native_bridge import NativeBridge
from .protocol import P
from .task import ACTIONS, build_bank, prepare_episode, finish_episode


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def setup(args, audit=False):
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    assets = Path(args.assets).resolve()
    receipt = json.loads((assets / "RESTORATION.json").read_text())
    if receipt["archive_sha256"] != P["asset_sha256"]:
        raise ValueError("Original archive identity differs from registration")
    manifest = {row["path"]: row["sha256"] for row in receipt["selected_files"]}
    def checked(relative):
        path = assets / relative
        if digest(path) != manifest[relative]:
            raise ValueError(f"Original asset changed: {relative}")
        return path
    for path in manifest:
        if path.startswith("ndu-data/"):
            checked(path)
    corpus = load_corpus(assets / "ndu-data", evaluator_sources=10000)
    if corpus.manifest["manifest_sha256"] != P["corpus_manifest"]:
        raise ValueError("Underlying source population changed")
    observers = {}
    for name in ("reward", "audit") if audit else ("reward",):
        path = checked(f"ndu-runs/full-002/{name}-observer.pt")
        record = torch.load(path, map_location="cpu", weights_only=True)
        observer = Recognizer().eval().requires_grad_(False)
        observer.load_state_dict(record["state_dict"] if "state_dict" in record else record)
        observers[name] = observer
    originals, identities = {}, {}
    for seed in P["seeds"]:
        path = checked(f"ndu-runs/full-002/seed-{seed}-{P['initial_profile']}.pt")
        snapshot = ControlledSnapshot.load(path, expected_file_sha256=digest(path))
        originals[seed] = snapshot._base._model
        identities[seed] = {"file_sha256": digest(path), "parameter_sha256": parameter_hash(originals[seed]),
                            "config": originals[seed].config}
    return corpus, observers, originals, identities


def bank_set(model, corpus, observer, *, split, offset, count, seed, role):
    features0, features1, returns, identities, resources, outputs = [], [], [], [], [], []
    for condition_index, condition in enumerate(P["training_conditions"]):
        batch = make_batch(corpus, split, count, seed * 1009 + condition_index,
                           offset=offset, corruption=condition)
        bank = build_bank(model, batch, observer, noise_seed=seed * 2017 + condition_index, role=role)
        features0.append(bank["features0"].numpy())
        features1.append(bank["features1"].numpy())
        costs = P["refinement_charge"] * (1 + (np.arange(len(ACTIONS)) != 0))
        returns.append(bank["reward"].numpy() - costs)
        identities.extend(batch.source_ids)
        resources.append(bank["resources"])
        outputs.append({"condition": condition, "pixels_u8": bank["pixels_u8"], "token_ids": bank["token_ids"]})
    return {"x0": np.concatenate(features0), "x1": np.concatenate(features1),
            "returns": np.concatenate(returns), "source_ids": identities, "resources": resources, "outputs": outputs}


def fit_runtime(model, corpus, observer, bridge, seed, profile, out):
    started = time.perf_counter_ns()
    train = bank_set(model, corpus, observer, split="train", offset=P["runtime_train_offset"],
                     count=P["runtime_train_pairs"], seed=seed, role="train")
    dev = bank_set(model, corpus, observer, split="validation", offset=P["readout_development_offset"],
                   count=P["readout_development_pairs"], seed=seed + 701, role="development")
    root = out / "runtime" / f"{seed}-{profile}"
    root.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(root / "banks.npz", train_x0=train["x0"], train_x1=train["x1"],
                        train_returns=train["returns"], dev_x0=dev["x0"], dev_x1=dev["x1"], dev_returns=dev["returns"])
    torch.save({"train": train["outputs"], "development": dev["outputs"]}, root / "hard-bank-outputs.pt")
    write_json(root / "BANK_IDENTITIES.json", {"train": train["source_ids"], "development": dev["source_ids"],
                                               "train_resources": train["resources"], "development_resources": dev["resources"]})
    t_native = native_features(bridge, train["x0"], train["x1"], f"fit-{seed}-{profile}",
                               receipt_path=root / "train-native.jsonl")
    d_native = native_features(bridge, dev["x0"], dev["x1"], f"dev-{seed}-{profile}",
                               receipt_path=root / "dev-native.jsonl")
    models = {
        "native": fit_readout(t_native, train["returns"], d_native, dev["returns"]),
        "history": fit_readout(history_features(train["x0"], train["x1"]), train["returns"],
                               history_features(dev["x0"], dev["x1"]), dev["returns"]),
    }
    write_json(root / "READOUTS.json", {"models": models, "total_fit_wall_ns": time.perf_counter_ns() - started,
                                       "shared_training_and_development_label_queries": int(train["returns"].size + dev["returns"].size)})
    return models


def source_manifest():
    root = Path(__file__).parent
    files = sorted([*root.rglob("*.py"), *root.rglob("*.rs"), root / "PROTOCOL.json",
                    *(root / "native_reproduction").rglob("*.json")])
    result = {str(path.relative_to(root)): digest(path) for path in files}
    for name in ("data", "neural", "conditioned", "observer", "plan_training"):
        result[f"../v6/{name}.py"] = digest(root.parent / "v6" / f"{name}.py")
    return result


def train(args):
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "TRAINING_COMPLETE.json").exists():
        raise ValueError("Training already frozen; choose a fresh output directory")
    corpus, observers, originals, identities = setup(args)
    sources = source_manifest()
    freeze_path = out / "SOURCE_FREEZE.json"
    if freeze_path.exists() and json.loads(freeze_path.read_text())["files"] != sources:
        raise ValueError("Source changed during a resumable training run")
    write_json(freeze_path, {"files": sources, "protocol_sha256": object_hash(P),
                            "registered_commit": "9c61f74cbf0a581baccd370e70e4f11181f8e244"})
    write_json(out / "ENVIRONMENT.json", {"python": sys.version, "torch": torch.__version__,
        "numpy": np.__version__, "platform": platform.platform(), "torch_threads": torch.get_num_threads(),
        "native_binary_sha256": digest(args.native), "source_models": identities, "corpus": corpus.manifest})
    all_seeds = {}
    progress = lambda message: print(message, flush=True)
    with NativeBridge(args.native, args.native_sha256) as bridge:
        for seed in P["seeds"]:
            seed_root = out / "training" / str(seed)
            seed_root.mkdir(parents=True, exist_ok=True)
            completed = seed_root / "COMPLETE.json"
            if completed.exists():
                all_seeds[seed] = json.loads(completed.read_text())
                continue
            original = originals[seed]
            frozen = make_model(original, seed)
            check_batch = make_batch(corpus, "validation", 8, 271027, offset=700, corruption="clean")
            with torch.inference_mode():
                left = fixed_output(original, check_batch, 0, 107)
                right = fixed_output(frozen, check_batch, 0, 107)
            if not (torch.equal(left.image_logits, right.image_logits) and torch.equal(left.token_ids, right.token_ids)):
                raise RuntimeError("Zero adapter did not preserve original model output")
            selected = bank_set(frozen, corpus, observers["reward"], split="validation", offset=P["fixed_development_offset"],
                                count=P["fixed_development_pairs"], seed=seed + 1701, role="development")
            action = int(np.argmax(selected["returns"].mean(0)))
            write_json(seed_root / "FIXED_POLICY.json", {"action": action, "action_name": ACTIONS[action],
                "development_action_mean_returns": selected["returns"].mean(0).tolist(),
                "source_ids": selected["source_ids"], "resources": selected["resources"], "zero_adapter_exact_parity": True})
            bank = explore(original, corpus, observers["reward"], seed, action, progress)
            write_json(seed_root / "EXPLORATION.json", bank)
            models, result = {"frozen": frozen}, {"fixed_action": action, "profiles": {}, "readouts": {}}
            for profile in ("ordinary", "field", "generic", "richer"):
                model, optimizer, evidence = adapt(original, corpus, observers["reward"], seed, action, profile, bank, progress)
                model_path = seed_root / f"{profile}.pt"
                saved = save_adapter(model_path, model, optimizer, base_file_sha256=identities[seed]["file_sha256"],
                                      metadata={"seed": seed, "profile": profile, "protocol_sha256": object_hash(P)})
                loaded, _ = load_adapter(model_path, original, seed, identities[seed]["file_sha256"])
                with torch.inference_mode():
                    before = fixed_output(model, check_batch, action, 107)
                    after = fixed_output(loaded, check_batch, action, 107)
                if not torch.equal(before.image_logits, after.image_logits) or not torch.equal(before.token_ids, after.token_ids):
                    raise RuntimeError("Saved adapter does not reproduce actual inference")
                evidence["saved"] = saved
                evidence["reload_exact_output_parity"] = True
                write_json(seed_root / f"{profile}.json", evidence)
                models[profile] = loaded
                result["profiles"][profile] = saved
            for profile in ("frozen", "ordinary", "field"):
                result["readouts"][profile] = fit_runtime(models[profile], corpus, observers["reward"], bridge, seed, profile, out)
                progress(f"seed={seed} {profile} matched native/history readouts frozen")
            write_json(completed, result)
            all_seeds[seed] = result
    if source_manifest() != sources:
        raise RuntimeError("Source changed during training")
    write_json(out / "TRAINING_COMPLETE.json", {"seeds": all_seeds, "source_files": sources,
        "audit_observer_loaded": False, "test_or_retention_scored": False,
        "native_binary_sha256": digest(args.native), "trainable_parameters": sum(p.numel() for p in local_parameters(frozen))})
    progress("ALL TRAINING FROZEN; no test/retention outcomes have been scored")


def evaluate(args):
    out = Path(args.out).resolve()
    frozen = json.loads((out / "TRAINING_COMPLETE.json").read_text())
    if source_manifest() != frozen["source_files"]:
        raise ValueError("Decision/evaluation source differs from the frozen training source")
    if digest(args.native) != frozen["native_binary_sha256"]:
        raise ValueError("Native executable differs from the frozen training executable")
    if (out / "rows.jsonl").exists():
        raise ValueError("Evaluation already started; preserve it instead of overwriting")
    corpus, observers, originals, identities = setup(args, audit=True)
    arms = {**P["canonical_arms"], **P["supplementary_arms"]}
    count = 0
    with NativeBridge(args.native, args.native_sha256) as bridge, (out / "rows.jsonl").open("x") as stream:
        for seed in P["seeds"]:
            seed_info = frozen["seeds"][str(seed)]
            models = {"frozen": make_model(originals[seed], seed)}
            for profile in ("ordinary", "field", "generic", "richer"):
                adapter_path = out / "training" / str(seed) / f"{profile}.pt"
                if digest(adapter_path) != seed_info["profiles"][profile]["file_sha256"]:
                    raise ValueError(f"Frozen adapter changed: {seed}/{profile}")
                models[profile], _ = load_adapter(adapter_path, originals[seed], seed, identities[seed]["file_sha256"])
            arm_order = list(arms)
            np.random.default_rng(seed + 271027).shuffle(arm_order)
            for arm in arm_order:
                profile, control = arms[arm]
                model = models[profile]
                readout = None if control == "fixed" else seed_info["readouts"][profile]["native" if control == "reset" else control]
                controller_sha = object_hash(readout if readout is not None else {"action": seed_info["fixed_action"]})
                for split, pairs, offset, conditions in (
                    ("test", P["test_pairs"], P["test_offset"], P["test_conditions"]),
                    ("retention", P["retention_pairs"], P["retention_offset"], P["retention_conditions"]),
                ):
                    for condition_index, condition in enumerate(conditions):
                        for start in range(0, pairs, P["evaluation_batch_size"]):
                            size = min(P["evaluation_batch_size"], pairs - start)
                            batch_seed = 271027 + start + condition_index * 10000
                            batch = make_batch(corpus, split, size, batch_seed, offset=offset + start, corruption=condition)
                            noise_seed = seed * 100003 + start + condition_index * 1009
                            media_root = out / "outputs" / str(seed) / arm / split / condition
                            names = [f"pair-{start + i:04d}" for i in range(size)]
                            prepared = prepare_episode(model, batch.observation, observers["reward"], noise_seed=noise_seed,
                                                        output_root=media_root, case_ids=names)
                            before, before_cpu = time.perf_counter_ns(), time.process_time_ns()
                            native_summary = {}
                            if control == "fixed":
                                actions = np.full(size, seed_info["fixed_action"], dtype=int)
                            elif control == "history":
                                actions = choose(readout, history_features(prepared.features0, prepared.features1))
                            else:
                                feature_path = out / "native" / f"{seed}-{arm}-{split}-{condition}-{start}.jsonl"
                                features = native_features(bridge, prepared.features0, prepared.features1,
                                    f"{seed}-{arm}-{split}-{condition}-{start}", reset=control == "reset", receipt_path=feature_path)
                                native_summary = bridge.last_feature_batch.copy()
                                actions = choose(readout, features)
                            decision_wall, decision_cpu = time.perf_counter_ns() - before, time.process_time_ns() - before_cpu
                            final = finish_episode(model, prepared, actions)
                            scores = {name: observe_tensors(observer, final.pixels_u8.float() / 255, final.captions,
                                                           batch.target.pixels, batch.target.labels)
                                      for name, observer in observers.items()}
                            resource = {"decision_wall_ns": decision_wall / size, "decision_python_cpu_ns": decision_cpu / size,
                                        "native_tick_calls": 2 if control in {"native", "reset"} else 0,
                                        "native_kernel_ns": native_summary.get("native_ns", 0) / size}
                            for prefix, source in (("prepare", prepared.resources), ("finish", final.resources)):
                                resource.update({f"{prefix}_{key}": value / size for key, value in source.items() if isinstance(value, (int, float))})
                            for index in range(size):
                                receipts = [prepared.preview0.receipts[index], prepared.preview1.receipts[index], final.receipts[index]]
                                for receipt in receipts:
                                    receipt["paths"] = {key: str(Path(path).relative_to(out)) for key, path in receipt["paths"].items()}
                                row = {"seed": seed, "arm": arm, "split": split, "corruption": condition, "pair": start + index,
                                    "source_ids": batch.source_ids[index], "action": int(actions[index]),
                                    "refinement_count": 1 + int(actions[index] != 0), "reward": scores["reward"][index],
                                    "audit": scores["audit"][index], "resources": resource, "artifacts": receipts,
                                    "model_sha": prepared.model_sha256, "controller_sha": controller_sha,
                                    "batch_seed": batch_seed, "noise_seed": noise_seed, "batch_start": start, "batch_size": size,
                                    "public_features0": prepared.features0[index].tolist(), "public_features1": prepared.features1[index].tolist(),
                                    "private_labels_after_decision": batch.target.labels[index].tolist()}
                                stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                                count += 1
                            stream.flush()
                print(f"evaluation seed={seed} arm={arm} complete; rows={count}", flush=True)
    if source_manifest() != frozen["source_files"]:
        raise RuntimeError("Source changed during test deployment")
    from .analyze import analyze
    rows = [json.loads(line) for line in (out / "rows.jsonl").open()]
    write_json(out / "RESULT.json", analyze(rows))
    write_json(out / "EVALUATION_COMPLETE.json", {"rows": count, "row_sha256": digest(out / "rows.jsonl"),
        "source_files": frozen["source_files"], "training_complete_sha256": digest(out / "TRAINING_COMPLETE.json"),
        "source_models_unchanged": all(parameter_hash(originals[s]) == identities[s]["parameter_sha256"] for s in P["seeds"])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["train", "evaluate"])
    parser.add_argument("--assets", required=True)
    parser.add_argument("--native", required=True)
    parser.add_argument("--native-sha256", default="a86032964bbab3a28150ffe58474d0d6c7fc7988caf3f0be4ecd46e37985cbd7")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    (train if args.phase == "train" else evaluate)(args)


if __name__ == "__main__":
    main()
