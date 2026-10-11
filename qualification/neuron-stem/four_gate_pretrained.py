#!/usr/bin/env python3
"""Pinned real mmBERT CPU capture through the existing four_gate_capture port.

A physical-weight smoke is NOT a three-arm scientific gate. The Heads here are
untrained; inputs are unchanged repository excerpts, not independently labelled
Hepta episodes. No no-change outcome, future timestamp or grant is invented.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import platform
from pathlib import Path
import sys
import subprocess
import time

from four_gate_capture import capture_cpu, tensor_digest
from four_gate_common import canonical, digest, integer, require, sha, write_once
from hf_trial import make_head
from four_gate_inputs import QuestionPreservingInputs, joint_text

MODEL = "jhu-clsp/mmBERT-small"
REVISION = "abc32620dd4f6ab06f5fbe905dc25f310618e09f"
FILES = ("config.json", "pytorch_model.bin", "tokenizer.json",
         "tokenizer_config.json", "special_tokens_map.json")
SOURCES = ("docs/learning/NEURAL_BIOMIMICRY_SPEC.md",
           "docs/learning/NDU_FBSDE_SPEC.md",
           "docs/learning/CAUSAL_LONGITUDINAL_SPEC.md")
QUESTIONS = ("Which component owns this operation?", "Is execution authority provided?",
             "Is this a runtime rule or an evaluation rule?", "What evidence is required?")
OPTIONS = ("Neuron", "NDU", "Learning", "Insufficient evidence")


def file_hash(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        if algorithm == "sha1":
            h.update(f"blob {Path(path).stat().st_size}\0".encode())
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def verify_download(path, metadata):
    """Check real local bytes against metadata for the exact immutable revision."""
    require(path.is_file() and not path.is_symlink(), "nonregular/symlink model file")
    require(path.stat().st_size == metadata.size <= 1_000_000_000, "model file size drift")
    actual = file_hash(path)
    lfs = metadata.lfs
    if lfs is not None:
        expected = lfs.sha256 if hasattr(lfs, "sha256") else lfs["sha256"]
        require(actual == sha(expected), "physical LFS SHA256 mismatch")
    else:
        require(file_hash(path, "sha1") == sha(metadata.blob_id, 40), "Git blob mismatch")
    return {"size": path.stat().st_size, "sha256": actual,
            "upstream_git_blob": metadata.blob_id}


def load_pinned(directory):
    import torch
    from huggingface_hub import HfApi, hf_hub_download
    from transformers import AutoModel, AutoTokenizer

    info = HfApi().model_info(MODEL, revision=REVISION, files_metadata=True, token=False)
    require(info.sha == REVISION, "upstream immutable revision drift")
    siblings = {item.rfilename: item for item in info.siblings}
    require(set(FILES) <= set(siblings), "incomplete published model inventory")
    directory.mkdir(parents=True, exist_ok=True)
    inventory = {}
    for name in FILES:
        require(0 < siblings[name].size <= 1_000_000_000, "unbounded upstream file")
        path = Path(hf_hub_download(MODEL, name, revision=REVISION,
                                   local_dir=directory, token=False))
        inventory[name] = verify_download(path, siblings[name])
    tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True,
                                              trust_remote_code=False)
    # No remote Python; native ModernBERT and PyTorch's restricted weight loader.
    model, loading = AutoModel.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False,
        use_safetensors=False, weights_only=True, output_loading_info=True,
        attn_implementation="eager", reference_compile=False, torch_dtype=torch.float32)
    require(not loading.get("missing_keys") and not loading.get("mismatched_keys")
            and not loading.get("error_msgs"), "incomplete physical Encoder load")
    require(all(key.startswith(("head.", "decoder.", "lm_head."))
                for key in loading.get("unexpected_keys", [])), "unexpected non-MLM weight")
    require(model.config.model_type == "modernbert" and model.config.hidden_size == 384,
            "mmBERT-small architecture mismatch")
    model.eval().requires_grad_(False)
    return model, tokenizer, inventory, loading


def build_schedule(root, cells, active_bps, repeat_bps, *, public_corpus=None):
    import math

    require(cells in (64, 256, 1024, 4096), "unsupported Cell scale")
    require(active_bps in (500, 2500, 10000) and repeat_bps in (0, 5000, 9000),
            "unsupported workload setting")
    count = math.ceil(cells * active_bps / 10000)
    unique = max(1, round(count * (1 - repeat_bps / 10000)))
    excerpts, sources = [], {}
    for relative in SOURCES if public_corpus is None else ():
        path = root / relative
        require(path.is_file() and not path.is_symlink(), "missing source document")
        raw = path.read_bytes()
        require(0 < len(raw) < 1_000_000, "unbounded source document")
        sources[relative] = hashlib.sha256(raw).hexdigest()
        paragraphs = [p for p in raw.decode("utf-8").split("\n\n") if len(p.strip()) > 80]
        excerpts.extend(p[:1600] for p in paragraphs)
    if public_corpus is not None:
        require(type(public_corpus) is list and 0 < len(public_corpus) <= 20000, "bounded public corpus")
        require(all(type(v) is str and 0 < len(v) <= 4096 for v in public_corpus), "invalid public text")
        excerpts = public_corpus
        sources["publisher_train_text_inventory"] = digest(public_corpus)
    # Different source windows, not an appended random ID pretending to be new text.
    candidates = list(dict.fromkeys(excerpts))
    require(unique <= len(candidates), "insufficient distinct real excerpts for this workload")
    states = candidates[:unique]
    rows, payloads = [], {}
    for i in range(count):
        state = states[i % unique]
        question = QUESTIONS[i % len(QUESTIONS)]
        joint = joint_text(state, question, list(OPTIONS))
        row = {"request_id": f"request-{i}", "cell_id": i,
               "principal": "public-repository-research", "scope": "hepta-docs",
               "purpose": "non-authorizing-physical-stem-capture", "generation": 1,
               "authority_epoch": 1, "state_sha256": digest(state), "joint_sha256": digest(joint)}
        rows.append(row)
        payloads[row["request_id"]] = {"state": state, "joint": joint,
                                       "question": question, "options": list(OPTIONS)}
    return rows, payloads, sources


def run(args):
    import torch

    require(sys.platform.startswith("linux"), "physical RSS profile requires Linux")
    import resource

    integer(args.threads, "CPU threads", 1, 16)
    torch.set_num_threads(args.threads)
    torch.manual_seed(20261011)
    args.output.mkdir(parents=True, exist_ok=False)
    source = subprocess.check_output(["git", "-C", str(args.source_root), "rev-parse", "HEAD"],
                                     text=True).strip()
    sha(source, 40)
    corpus = None
    if args.source_corpus == "clinc-train":
        from four_gate_public_replay import read_public_data
        published, _ = read_public_data(args.output / "publisher")
        corpus = [entry[0] for entry in published["train"]]
    schedule, payloads, sources = build_schedule(args.source_root, args.cells,
        args.active_bps, args.repeat_bps, public_corpus=corpus)
    write_once(args.output / "input-plan.json", {
        "schema": "hepta.four-gate.physical-inputs.v1", "source_sha": source,
        "model": MODEL, "revision": REVISION, "schedule": schedule, "payloads": payloads,
        "source_documents": sources, "arm": args.arm, "max_tokens": args.max_tokens,
        "cells": args.cells, "active_bps": args.active_bps, "repeat_bps": args.repeat_bps,
        "head_seed": 20261011, "input_profile": "question_preserving_shared_state_budget.v2",
        "source_corpus": args.source_corpus, "not_a_prospective_efficacy_plan": True})
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    model, tokenizer, inventory, loading = load_pinned(args.model_dir)
    heads = {i: make_head(torch, torch.nn, "swiglu", 384, len(OPTIONS), 16384)[0].eval()
             for i in range(args.cells)}
    input_adapter = QuestionPreservingInputs(tokenizer, payloads, args.max_tokens)
    load_cost = {"cpu_ns": time.process_time_ns() - start_cpu,
                 "wall_ns": time.perf_counter_ns() - start_wall}
    head_inventory = {str(i): digest({key: tensor_digest(value) for key, value in head.state_dict().items()})
                      for i, head in heads.items()}
    pipeline = digest({"revision": REVISION, "files": inventory, "max_tokens": args.max_tokens,
                       "dtype": "float32", "attention": "eager", "pooling": "masked_mean",
                       "input_profile": "question_preserving_shared_state_budget.v2",
                       "source_corpus": args.source_corpus, "source_sha": source,
                       "input_adapter": input_adapter.pipeline})
    state = {}

    def prepare(rows, arm):
        tokens = input_adapter(rows, arm)
        state["mask"] = tokens["attention_mask"].float()
        return tokens

    def pool(output):
        mask = state["mask"].unsqueeze(-1)
        return (output.last_hidden_state.float() * mask).sum(1) / mask.sum(1).clamp_min(1)

    warm_cpu, warm_wall = time.process_time_ns(), time.perf_counter_ns()
    with torch.inference_mode():
        pool(model(**prepare(schedule[:1], args.arm)))
    warmup = {"cpu_ns": time.process_time_ns() - warm_cpu,
              "wall_ns": time.perf_counter_ns() - warm_wall}
    write_once(args.output / "load.json", {"source_sha": source, "model": MODEL,
        "revision": REVISION, "physical_files": inventory, "loading_info": loading,
        "pipeline_sha256": pipeline, "load_including_download_and_heads": load_cost,
        "warmup": warmup, "head_inventory": head_inventory,
        "input_adapter": input_adapter.pipeline,
        "head_parameters_each": sum(p.numel() for p in heads[0].parameters()),
        "encoder_parameters": sum(p.numel() for p in model.parameters()),
        "native_owner_load_authenticated": False})
    capture = capture_cpu(model, prepare, pool, heads, schedule, arm=args.arm,
                          pipeline_sha256=pipeline, cache_entries=4096)
    write_once(args.output / "token-audit.json", {
        "schema": "hepta.four-gate.token-audit.v2", "pipeline": input_adapter.pipeline,
        "requests": input_adapter.audit, "production_promotion_permitted": False})
    capture.update({"schema": "hepta.four-gate.physical-smoke.v2", "source_sha": source,
        "arm": args.arm, "model": MODEL, "revision": REVISION,
        "schedule_sha256": digest(schedule), "load_cost": load_cost, "warmup_cost": warmup,
        "process_high_watermark_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "rss_scope": "Linux whole fresh process, includes download/load/warmup",
        "environment": {name: importlib.metadata.version(name)
                        for name in ("torch", "transformers", "huggingface-hub", "psutil")},
        "platform": platform.platform(), "logical_cells": args.cells,
        "activated_cells": len({row["cell_id"] for row in schedule}),
        "heads_trained": False, "three_arm_scientific_gate_passed": False,
        "no_change_available": False, "genuine_future_outcomes_available": False,
        "production_promotion_permitted": False,
        "not_executed_lifecycle_phases": ["training", "search", "evaluation", "migration"]})
    write_once(args.output / "capture.json", capture)
    print(canonical({"source_sha": source, "arm": args.arm, "revision": REVISION,
                     "encoder_calls": len(capture["encoder_forwards"]),
                     "encoder_rows": sum(len(e["keys"]) for e in capture["encoder_forwards"]),
                     "requests": len(capture["requests"]), "real_weights_executed": True,
                     "three_arm_scientific_gate_passed": False}).decode(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-corpus", choices=("repository", "clinc-train"), default="repository")
    parser.add_argument("--arm", choices=("joint_batch", "feature_reuse"), required=True)
    parser.add_argument("--cells", type=int, choices=(64, 256, 1024, 4096), default=64)
    parser.add_argument("--active-bps", type=int, choices=(500, 2500, 10000), default=10000)
    parser.add_argument("--repeat-bps", type=int, choices=(0, 5000, 9000), default=9000)
    parser.add_argument("--max-tokens", type=int, choices=(64, 128, 256, 512), default=64)
    parser.add_argument("--threads", type=int, default=2)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
