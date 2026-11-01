"""Run the preregistered V14 experiment on an actual pretrained Transformer.

Dependency/download failures are recorded and fail the process.  Scientific
negative results are valid completed experiments, never silently retried/tuned.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import pickle
import platform
import resource
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from language_data import MODEL, REVISION, SEEDS, WEIGHTS_SHA256, canonical, digest, execute, generate
from language_costs import comparisons, sequential_reads
from language_models import Baseline, frozen_hash, make_network, predict_network, tensor_hash, train_network


HERE = Path(__file__).resolve().parent


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def file_sha(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def metrics(data, rows, predictions):
    labels = np.array([row["label"] for row in rows])
    result = {"accuracy": float(np.mean(labels == predictions)), "count": len(rows),
              "correct": int(np.sum(labels == predictions)), "predictions": predictions.tolist()}
    for phase in sorted({row["phase"] for row in rows}):
        selected = np.array([row["phase"] == phase for row in rows])
        result[f"phase_{phase}_accuracy"] = float(np.mean(labels[selected] == predictions[selected]))
    if rows is data["test"] and data["task"] == "procedure_selection":
        outcomes = []
        for item in data["composition"]:
            first, second = item["first"], item["second"]
            expected = execute(labels[second], execute(labels[first], item["x"], item["y"]), item["z"])
            intermediate = execute(predictions[first], item["x"], item["y"])
            actual = None if intermediate is None else execute(predictions[second], intermediate, item["z"])
            outcomes.append({"expected": expected, "actual": actual, "correct": actual == expected})
        result["known_interpreter_composition"] = {"accuracy": float(np.mean([x["correct"] for x in outcomes])), "outcomes": outcomes,
                                                   "algorithm_learning_demonstrated": False, "learned_topology_demonstrated": False}
    return result


def main(args):
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    output = args.output
    protocol = json.loads((HERE / "LANGUAGE_PROTOCOL.json").read_text())
    expected = json.loads((HERE / "language_manifest.json").read_text())
    started = time.perf_counter()
    snapshot = Path(snapshot_download(MODEL, revision=REVISION,
                    allow_patterns=["config.json", "vocab.txt", "model.safetensors"]))
    download_seconds = time.perf_counter() - started
    if snapshot.name != REVISION or file_sha(snapshot / "model.safetensors") != WEIGHTS_SHA256:
        raise ValueError("Pinned pretrained checkpoint identity mismatch")
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    backbone = AutoModel.from_pretrained(str(snapshot), local_files_only=True, use_safetensors=True, add_pooling_layer=False)
    backbone.requires_grad_(False).eval()
    model_load_seconds = time.perf_counter() - started
    base_hash = frozen_hash(backbone)
    base_bytes = sum(p.numel() * p.element_size() for p in backbone.parameters())

    def tokenize(texts):
        return tokenizer(texts, padding="max_length", truncation=True, max_length=48, return_tensors="pt")

    def encode(texts):
        encoded = tokenize(texts)
        results = []
        with torch.no_grad():
            for i in range(0, len(texts), 64):
                batch = {key: value[i:i + 64] for key, value in encoded.items()}
                results.append(backbone(**batch).last_hidden_state[:, 0])
        return torch.cat(results)

    results = {"status": "running", "seed": args.seed, "protocol_sha256": digest(protocol),
               "github_commit": os.getenv("GITHUB_SHA"), "github_run_id": os.getenv("GITHUB_RUN_ID"),
               "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
               "python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
               "packages": {x: importlib.metadata.version(x) for x in ("torch", "transformers", "numpy", "scipy", "scikit-learn")},
               "model": {"repo": MODEL, "revision": REVISION, "safetensors_sha256": WEIGHTS_SHA256,
                         "frozen_tensor_sha256": base_hash, "resident_parameter_bytes": base_bytes,
                         "download_or_cache_check_seconds": download_seconds, "load_seconds": model_load_seconds,
                         "required_file_bytes": sum((snapshot / n).stat().st_size for n in ("config.json", "vocab.txt", "model.safetensors")),
                         "physical_network_bytes": None, "physical_network_bytes_note": "Not instrumented; artifact bytes are not wire bytes."},
               "tasks": {}, "stable_three_seed_claim": None,
               "unmeasured_costs": ["energy", "physical network bytes", "distributed placement and migration", "production resident opportunity cost"],
               "source_files": {p.name: file_sha(p) for p in HERE.glob("language_*.py")}}
    write_json(output / "language_run.json", results)
    for task in args.tasks:
        # Knowledge is generated only after loading/fixing the immutable backbone.
        data = generate(args.seed, task)
        if digest(data) != expected[f"{args.seed}/{task}"]["data_sha256"]:
            raise ValueError("Frozen data manifest mismatch")
        write_json(output / f"language_data_{task}.json", data)
        task_results = {"data_sha256": digest(data), "test_sha256": digest(data["test"]),
                        "interpretation": data["interpretation"], "arms": {}, "source_bytes": len(canonical(data["sources"]))}
        results["tasks"][task] = task_results
        features = {}
        encoding_cost = {}
        for split in ("validation", "test", "unknown"):
            started = time.perf_counter()
            features[split] = encode([row["query"] for row in data[split]])
            encoding_cost[split] = time.perf_counter() - started
        task_results["shared_frozen_encoding_seconds"] = encoding_cost
        feature_kinds = ("feature_nearest", "feature_ridge", "fast_weights")
        kinds = ("exact_kv", "bm25", "lexical_ridge") + feature_kinds + ("feature_linear", "feature_mlp", "attention_lora")
        for kind in kinds:
            arm = {"phases": [], "requires_shared_backbone": kind in feature_kinds or kind.startswith("feature_") or kind == "attention_lora"}
            task_results["arms"][kind] = arm
            is_neural = kind in ("feature_linear", "feature_mlp", "attention_lora")
            if is_neural:
                started = time.perf_counter()
                network = make_network(backbone, kind, args.seed)
                params = [p for p in network.parameters() if p.requires_grad]
                optimizer = torch.optim.AdamW(params, lr=.002, weight_decay=.001)
                initial = {name: p.detach().clone() for name, p in network.named_parameters() if p.requires_grad}
                arm.update({"trainable_parameters": sum(p.numel() for p in params), "trainable_bytes": sum(p.numel() * p.element_size() for p in params),
                            "initial_parameter_sha256": tensor_hash(initial), "initialization_seconds": time.perf_counter() - started})
            else:
                method = Baseline(kind)
            cumulative_write = 0.
            for phase, steps in ((0, 220), (1, 120)):
                selected = [i for i, row in enumerate(data["train"]) if row["phase"] <= phase]
                rows = [data["train"][i] for i in selected]
                sources = [row for row in data["sources"] if row["phase"] <= phase]
                feature_cost = 0.
                feature_tensor = None
                if kind in feature_kinds or kind in ("feature_linear", "feature_mlp"):
                    started = time.perf_counter()
                    feature_tensor = encode([row["query"] for row in rows])
                    feature_cost = time.perf_counter() - started
                if is_neural:
                    started = time.perf_counter()
                    inputs = tokenize([row["query"] for row in rows]) if kind == "attention_lora" else feature_tensor
                    prep = time.perf_counter() - started
                    training = train_network(network, optimizer, inputs, torch.tensor([row["label"] for row in rows]), steps, args.seed + phase)
                    training["write_preparation_seconds"] = prep
                    checkpoint = {"parameters": {name: p.detach().clone() for name, p in network.named_parameters() if p.requires_grad},
                                  "optimizer": optimizer.state_dict(), "model_revision": REVISION, "phase": phase,
                                  "data_sha256": digest(data), "base_hash": base_hash}
                    started = time.perf_counter()
                    artifact = output / f"language_{task}_{kind}_phase{phase}.pt"
                    torch.save(checkpoint, artifact)
                    training["serialization_seconds"] = time.perf_counter() - started
                    training["optimizer_tensor_bytes"] = sum(v.numel() * v.element_size() for state in optimizer.state.values() for v in state.values() if torch.is_tensor(v))
                    training["parameter_sha256"] = tensor_hash(checkpoint["parameters"])
                    training["optimizer_tensor_sha256"] = tensor_hash({f"{i}/{k}": v for i, state in optimizer.state_dict()["state"].items() for k, v in state.items() if torch.is_tensor(v)})
                    training["frozen_backbone_unchanged"] = kind != "attention_lora" or frozen_hash(network.backbone) == base_hash
                    if not training["frozen_backbone_unchanged"]:
                        raise ValueError("Frozen pretrained backbone changed")
                    write_seconds = training["training_seconds"] + prep + training["serialization_seconds"]
                else:
                    method.fit(rows, sources, feature_tensor.numpy() if feature_tensor is not None else None, args.seed + phase)
                    started = time.perf_counter()
                    artifact = output / f"language_{task}_{kind}_phase{phase}.pkl"
                    artifact.write_bytes(pickle.dumps(method, protocol=5))
                    training = {"training_seconds": method.fit_seconds, "serialization_seconds": time.perf_counter() - started}
                    write_seconds = sum(training.values())
                # Feature construction was actually rerun/timed for this arm and phase.
                cumulative_write += write_seconds + feature_cost
                phase_result = {"phase": phase, "training": training, "checkpoint_sha256": file_sha(artifact),
                                "checkpoint_bytes": artifact.stat().st_size, "charged_feature_construction_seconds": feature_cost,
                                "cumulative_write_seconds": cumulative_write, "evaluations": {}}
                arm["phases"].append(phase_result)
                for split in ("validation", "test", "unknown"):
                    texts = [row["query"] for row in data[split]]
                    started = time.perf_counter()
                    if is_neural:
                        inputs = tokenize(texts) if kind == "attention_lora" else features[split]
                        predictions, probabilities = predict_network(network, inputs)
                    else:
                        predictions = method.predict(texts, features[split].numpy() if kind in feature_kinds else None)
                    elapsed = time.perf_counter() - started
                    evaluation = metrics(data, data[split], predictions)
                    evaluation["read_seconds"] = elapsed + (encoding_cost[split] if arm["requires_shared_backbone"] and kind != "attention_lora" else 0.)
                    evaluation["cached_feature_or_direct_seconds"] = elapsed
                    if is_neural:
                        evaluation["probabilities"] = probabilities.tolist()
                    phase_result["evaluations"][split] = evaluation
                write_json(output / "language_run.json", results)
            if is_neural:
                # Exact round-trip of trained parameters AND optimizer, on validation only.
                started = time.perf_counter()
                restored = make_network(backbone, kind, args.seed)
                loaded = torch.load(artifact, map_location="cpu", weights_only=True)
                with torch.no_grad():
                    for name, value in restored.named_parameters():
                        if value.requires_grad:
                            value.copy_(loaded["parameters"][name])
                restored_optimizer = torch.optim.AdamW([p for p in restored.parameters() if p.requires_grad], lr=.002, weight_decay=.001)
                restored_optimizer.load_state_dict(loaded["optimizer"])
                arm["restore_seconds"] = time.perf_counter() - started
                validation_input = tokenize([r["query"] for r in data["validation"]]) if kind == "attention_lora" else features["validation"]
                _, before = predict_network(network, validation_input)
                _, after = predict_network(restored, validation_input)
                arm["checkpoint_restore_bitwise_match"] = bool(np.array_equal(before, after))
                arm["optimizer_restore_tensor_hash"] = tensor_hash({f"{i}/{k}": v for i, state in restored_optimizer.state_dict()["state"].items() for k, v in state.items() if torch.is_tensor(v)})
                arm["optimizer_restore_state_match"] = arm["optimizer_restore_tensor_hash"] == arm["phases"][-1]["training"]["optimizer_tensor_sha256"]
                if not arm["checkpoint_restore_bitwise_match"]:
                    raise ValueError("Checkpoint output changed on restore")
                if not arm["optimizer_restore_state_match"]:
                    raise ValueError("Optimizer state changed on restore")
                def query_predictor(texts):
                    values = tokenize(texts) if kind == "attention_lora" else encode(texts)
                    return predict_network(network, values)[0]
                arm["sequential_reads"] = sequential_reads(data, query_predictor)
                if kind == "attention_lora":
                    for module in network.loras:
                        module.enabled = False
                    predictions, _ = predict_network(network, tokenize([r["query"] for r in data["test"]]))
                    arm["lora_disabled_trained_head"] = metrics(data, data["test"], predictions)
                with torch.no_grad():
                    for name, value in network.named_parameters():
                        if value.requires_grad:
                            value.copy_(initial[name])
                predictions, _ = predict_network(network, tokenize([r["query"] for r in data["test"]]) if kind == "attention_lora" else features["test"])
                arm["all_trainable_parameters_reset"] = metrics(data, data["test"], predictions)
                del network, restored, optimizer, restored_optimizer
            else:
                started = time.perf_counter()
                restored = pickle.loads(artifact.read_bytes())
                arm["restore_seconds"] = time.perf_counter() - started
                validation_texts = [row["query"] for row in data["validation"]]
                restored_predictions = restored.predict(validation_texts, features["validation"].numpy() if kind in feature_kinds else None)
                arm["checkpoint_restore_bitwise_match"] = restored_predictions.tolist() == arm["phases"][-1]["evaluations"]["validation"]["predictions"]
                if not arm["checkpoint_restore_bitwise_match"]:
                    raise ValueError("Baseline checkpoint output changed on restore")
                def query_predictor(texts):
                    values = encode(texts).numpy() if kind in feature_kinds else None
                    return method.predict(texts, values)
                arm["sequential_reads"] = sequential_reads(data, query_predictor)
        comparisons(task_results["arms"], task_results["source_bytes"], len(canonical(data["train"])),
                    results["model"]["required_file_bytes"], download_seconds + model_load_seconds)
    results["status"] = "executed"
    results["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform != "darwin" else 1)
    write_json(output / "language_run.json", results)
    print(json.dumps({"status": results["status"], "output": str(output / "language_run.json"), "stable_three_seed_claim": None}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, choices=SEEDS, required=True)
    parser.add_argument("--tasks", nargs="+", choices=("facts", "procedure_selection"), default=["facts", "procedure_selection"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        main(args)
    except Exception as error:
        write_json(args.output / "language_failure.json", {"status": "failed", "seed": args.seed,
                   "exception_type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
        raise
