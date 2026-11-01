"""Execute semantic memory qualification after protocol/holdout commit."""

import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
import pickle
import resource
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from language_data import MODEL, REVISION, WEIGHTS_SHA256
from language_models import frozen_hash, predict_network, tensor_hash, train_network
from semantic_costs import assess, query_timings
from semantic_data import HERE, SEEDS, SKILLS, TASKS, V13, canonical, evaluate, manifest, new_holdout, sha, training_data
from semantic_models import SemanticBaseline, make_semantic_network


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(args):
    run_started = time.perf_counter()
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoTokenizer
    sys.path.insert(0, str(V13))
    from download_model import download as download_minilm
    from backend import FrozenEncoder
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if manifest() != json.loads((HERE / "semantic_manifest.json").read_text()):
        raise ValueError("Frozen semantic data/executor identity mismatch")
    protocol = json.loads((HERE / "semantic_protocol.json").read_text())
    old = training_data()
    train, calibration = old["train"], old["calibration"]
    held = new_holdout()
    prior = json.loads(args.prior_cost_ledger.read_text())["entries"]
    results = {"schema": "hepta.semantic.run.v1", "status": "running", "seed": args.seed,
               "github_commit": os.getenv("GITHUB_SHA"), "github_run_id": os.getenv("GITHUB_RUN_ID"),
               "protocol_sha256": sha(protocol), "data_manifest": manifest(), "arms": {},
               "packages": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "numpy", "scikit-learn", "onnxruntime")},
               "scope": "Authored known-skill selection and explicit-step composition; not open-domain algorithm learning.",
               "source_files": {p.name: hash_file(p) for p in sorted(HERE.glob("semantic_*.py"))},
               "inherited_source_files": {name: hash_file(HERE / name) for name in ("language_data.py", "language_models.py")}}
    dump(args.output / "semantic_run.json", results)
    started = time.perf_counter()
    snapshot = Path(snapshot_download(MODEL, revision=REVISION,
                    allow_patterns=["config.json", "vocab.txt", "model.safetensors"]))
    if snapshot.name != REVISION or hash_file(snapshot / "model.safetensors") != WEIGHTS_SHA256:
        raise ValueError("Pinned BERT identity mismatch")
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    backbone = AutoModel.from_pretrained(str(snapshot), local_files_only=True, use_safetensors=True, add_pooling_layer=False)
    backbone.requires_grad_(False).eval()
    bert_start = time.perf_counter() - started
    base_hash = frozen_hash(backbone)
    bert_bytes = sum((snapshot / n).stat().st_size for n in ("config.json", "vocab.txt", "model.safetensors"))
    started = time.perf_counter()
    minilm_manifest = download_minilm(args.cache_dir / "minilm")
    minilm = FrozenEncoder(args.cache_dir / "minilm", batch_size=32, max_length=256, threads=2)
    minilm_start = time.perf_counter() - started
    minilm_bytes = sum(value["bytes"] for value in minilm_manifest["files"].values())
    results["models"] = {"bert": {"repo": MODEL, "revision": REVISION, "sha256": WEIGHTS_SHA256, "file_bytes": bert_bytes,
                                    "acquisition_load_seconds": bert_start, "base_tensor_sha256": base_hash},
                          "minilm": {**minilm_manifest, "file_bytes": minilm_bytes, "acquisition_load_seconds": minilm_start}}

    def tokenize(texts):
        values = tokenizer(texts, padding=True, truncation=False, return_tensors="pt")
        if values["input_ids"].shape[1] > 96:
            raise ValueError("BERT sequence exceeds preregistered 96-token limit; no silent truncation")
        return values

    def bert_encode(texts):
        values = tokenize(texts)
        batches = []
        with torch.no_grad():
            for i in range(0, len(texts), 64):
                batches.append(backbone(**{k: v[i:i + 64] for k, v in values.items()}).last_hidden_state[:, 0])
        return torch.cat(batches)

    arms = [("exact_kv", "text", "exact_kv"), ("bm25", "text", "bm25"), ("kv_bm25", "text", "kv_bm25"),
            ("lexical_ridge", "text", "lexical_ridge")]
    arms += [(f"bert_{kind}", "bert", kind) for kind in ("nearest", "centroid", "ridge", "fast_weights")]
    arms += [(f"minilm_{kind}", "minilm", kind) for kind in ("nearest", "centroid", "ridge")]
    arms += [("bert_linear", "bert", "feature_linear"), ("bert_mlp", "bert", "feature_mlp"), ("bert_lora", "bert", "attention_lora")]
    for name, encoder, kind in arms:
        arm_started = time.perf_counter()
        arm = {"encoder": encoder, "kind": kind, "all_calibration_candidates": []}
        results["arms"][name] = arm
        cost = {"model_acquisition_load_seconds": bert_start if encoder == "bert" else minilm_start if encoder == "minilm" else 0.,
                "base_files_bytes": bert_bytes if encoder == "bert" else minilm_bytes if encoder == "minilm" else 0,
                "source_bytes": len(canonical(train)) + len(canonical(calibration)), "serialization_seconds": 0., "all_candidate_checkpoint_bytes": 0}
        arm["cost"] = cost
        neural = kind in ("feature_linear", "feature_mlp", "attention_lora")
        started = time.perf_counter()
        if encoder == "bert" and kind != "attention_lora":
            x, xc = bert_encode([r["text"] for r in train]), bert_encode([r["text"] for r in calibration])
        elif encoder == "minilm":
            x, xc = minilm.encode([r["text"] for r in train]), minilm.encode([r["text"] for r in calibration])
        elif kind == "attention_lora":
            x, xc = tokenize([r["text"] for r in train]), tokenize([r["text"] for r in calibration])
        else:
            x, xc = None, None
        cost["prepare_seconds"] = time.perf_counter() - started
        if neural:
            started = time.perf_counter()
            network = make_semantic_network(backbone, kind, args.seed)
            trainable = [p for p in network.parameters() if p.requires_grad]
            optimizer = torch.optim.AdamW(trainable, lr=.002, weight_decay=.001)
            initial = {n: p.detach().clone() for n, p in network.named_parameters() if p.requires_grad}
            arm["trainable_parameters"] = sum(p.numel() for p in trainable)
            arm["initial_parameters_sha256"] = tensor_hash(initial)
            y = torch.tensor([r["label"] for r in train])
            best, total_steps = (-1., -1.), 0
            for increment in (80, 80, 160):
                training = train_network(network, optimizer, x, y, increment, args.seed + total_steps)
                total_steps += increment
                cal_predictions, probabilities = predict_network(network, xc)
                scored = evaluate(calibration, cal_predictions)
                candidate = {"steps": total_steps, "training": training, "calibration": scored}
                arm["all_calibration_candidates"].append(candidate)
                params = {n: p.detach().clone() for n, p in network.named_parameters() if p.requires_grad}
                checkpoint = {"parameters": params, "optimizer": copy.deepcopy(optimizer.state_dict()), "calibration_probabilities": torch.tensor(probabilities),
                              "model_revision": REVISION, "base_hash": base_hash, "steps": total_steps, "protocol_sha256": sha(protocol)}
                artifact = args.output / f"semantic_{name}_{total_steps}.pt"
                serialization = time.perf_counter()
                torch.save(checkpoint, artifact)
                cost["serialization_seconds"] += time.perf_counter() - serialization
                cost["all_candidate_checkpoint_bytes"] += artifact.stat().st_size
                candidate["checkpoint_sha256"] = hash_file(artifact)
                key = (scored["task_success"], scored["label_accuracy"])
                if key > best:
                    best, selected = key, artifact
            cost["all_training_and_selection_seconds"] = time.perf_counter() - started - cost["serialization_seconds"]
            started = time.perf_counter()
            selected_state = torch.load(selected, map_location="cpu", weights_only=True)
            with torch.no_grad():
                for n, p in network.named_parameters():
                    if p.requires_grad:
                        p.copy_(selected_state["parameters"][n])
            optimizer.load_state_dict(selected_state["optimizer"])
            _, restored_probabilities = predict_network(network, xc)
            if not np.array_equal(restored_probabilities, selected_state["calibration_probabilities"].numpy()):
                raise ValueError("Selected neural checkpoint does not restore exactly")
            if kind == "attention_lora" and frozen_hash(network.backbone) != base_hash:
                raise ValueError("Pretrained backbone parameters changed")
            cost["restore_seconds"] = time.perf_counter() - started
            arm["selected_steps"] = selected_state["steps"]
            arm["checkpoint_restore_bitwise_match"] = True
            arm["selected_parameter_sha256"] = tensor_hash(selected_state["parameters"])
            arm["optimizer_tensor_sha256"] = tensor_hash({f"{i}/{k}": v for i, s in optimizer.state_dict()["state"].items() for k, v in s.items() if torch.is_tensor(v)})
            def predict(texts):
                return predict_network(network, tokenize(texts) if kind == "attention_lora" else bert_encode(texts))[0]
        else:
            method = SemanticBaseline(kind)
            method.fit(train, calibration, x.numpy() if torch.is_tensor(x) else x, xc.numpy() if torch.is_tensor(xc) else xc, args.seed)
            arm["all_calibration_candidates"] = method.history
            arm["selected"] = getattr(method, "selected", None)
            cost["all_training_and_selection_seconds"] = method.fit_seconds
            started = time.perf_counter()
            artifact = args.output / f"semantic_{name}.pkl"
            artifact.write_bytes(pickle.dumps(method, protocol=5))
            cost["serialization_seconds"] = time.perf_counter() - started
            cost["all_candidate_checkpoint_bytes"] = artifact.stat().st_size
            started = time.perf_counter()
            restored = pickle.loads(artifact.read_bytes())
            features = xc.numpy() if torch.is_tensor(xc) else xc
            cal_text = [r["text"] for r in calibration]
            arm["checkpoint_restore_bitwise_match"] = bool(np.array_equal(method.predict(cal_text, features), restored.predict(cal_text, features)))
            if not arm["checkpoint_restore_bitwise_match"]:
                raise ValueError("Baseline checkpoint restoration changed predictions")
            cost["restore_seconds"] = time.perf_counter() - started
            arm["checkpoint_sha256"] = hash_file(artifact)
            def predict(texts):
                values = bert_encode(texts).numpy() if encoder == "bert" else minilm.encode(texts) if encoder == "minilm" else None
                return method.predict(texts, values)
        # No path from the new holdout to training, calibration, or checkpoint selection.
        started = time.perf_counter()
        predictions = predict([r["text"] for r in held["rows"]])
        arm["holdout"] = evaluate(held["rows"], predictions)
        arm["final_holdout_seconds"] = time.perf_counter() - started
        arm["compositions"] = [dict(id=case["id"], **TASKS.execute_composition(case, lambda text: int(predict([text])[0]))) for case in held["compositions"]]
        arm["composition_success"] = sum(item["correct"] for item in arm["compositions"]) / len(held["compositions"])
        arm["query_timings"] = query_timings(held["rows"], predict)
        if neural:
            if kind == "attention_lora":
                for module in network.loras:
                    module.enabled = False
                arm["lora_disabled_trained_head"] = evaluate(held["rows"], predict([r["text"] for r in held["rows"]]))
            with torch.no_grad():
                for n, p in network.named_parameters():
                    if p.requires_grad:
                        p.copy_(initial[n])
            arm["all_trainable_parameters_reset"] = evaluate(held["rows"], predict([r["text"] for r in held["rows"]]))
            del network, optimizer
        arm["physical_arm_wall_seconds"] = time.perf_counter() - arm_started
        dump(args.output / "semantic_run.json", results)
    results["physical_run_wall_seconds"] = time.perf_counter() - run_started
    assess(results, prior)
    results["status"] = "executed"
    results["minilm_encoder_stats"] = minilm.stats
    results["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform != "darwin" else 1)
    dump(args.output / "semantic_run.json", results)
    print(json.dumps({"status": "executed", "output": str(args.output / "semantic_run.json"), "stable_three_seed_claim": None}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, choices=SEEDS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/hepta-semantic-models"))
    parser.add_argument("--prior-cost-ledger", type=Path, default=HERE / "semantic_prior_costs.json")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    began = time.perf_counter()
    try:
        run(args)
    except Exception as error:
        dump(args.output / "semantic_failure.json", {"status": "failed", "seed": args.seed, "wall_seconds": time.perf_counter() - began,
             "exception": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
        raise
