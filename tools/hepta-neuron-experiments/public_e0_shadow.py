#!/usr/bin/env python3
"""Public pretrained Encoder -> existing low-rank Q24 projection -> diagnostic Q24 readout.

SHADOW/MECHANISM ONLY. Not a trained Head, native Worker, Neuron Tick,
independent outcome observation, signed artifact, or E0 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import sys
import time

HF_SOURCE_COMMIT = "be511bd63aaae8813c415a116d50f01fe54baba5"
HF_SOURCE_TREE = "e2ae2b013e16f7aa3a0babe2869104b28a913132"
PROJECTION_SOURCE_COMMIT = "d6f35c362289c90427bfbdffd4505d2e535c1b1b"
PROJECTION_SOURCE_TREE = "eff00c335408b3931e4316c2b0d4334d7620aee4"
MODEL_ID = "answerdotai/ModernBERT-base"
MODEL_REVISION = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
MODEL_WEIGHT_SHA256 = "340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9"
SNAPSHOT_SHA256 = "43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d"
FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
         "special_tokens_map.json")
WIDTH = 768
NATIVE_WIDTH = 256
Q = 1 << 24
SCHEMA = "hepta.e0.public-pretrained-q24-shadow.v1"


def require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)


def file_sha256(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), "source file missing/linked")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def source_checkout(path: Path, commit: str, tree: str) -> Path:
    require(path.is_dir() and not path.is_symlink(), "source checkout absent")
    observed = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD", "HEAD^{tree}"],
                              capture_output=True, text=True, check=True).stdout.splitlines()
    require(observed == [commit, tree], "source checkout SHA/tree mismatch")
    require(not subprocess.run(["git", "-C", str(path), "status", "--porcelain",
                                "--untracked-files=no"], capture_output=True,
                               text=True, check=True).stdout.strip(), "dirty source checkout")
    return path / "qualification" / "stem-cell-v1"


def make_diagnostic_projection(Projection, *, encoder: str, preprocessor: str,
                               runtime: str, normalizer: str):
    """Explicit full-input synthetic control. It is NEVER an approved learned projection."""
    a0 = (Q // WIDTH,) * WIDTH  # all 768 coordinates, including the final coordinate
    a1 = tuple(Q // 2 if k in (0, WIDTH - 1) else 0 for k in range(WIDTH))
    b = []
    for i in range(NATIVE_WIDTH):
        if i == 0:
            b.extend((Q, 0))
        elif i == 1:
            b.extend((0, Q))
        elif i % 2 == 0:
            b.extend((Q // (i + 1), 0))
        else:
            b.extend((0, Q // (i + 1)))
    result = Projection(encoder, preprocessor, runtime, normalizer, "mean",
                        WIDTH, NATIVE_WIDTH, 2, a0 + a1, tuple(b), (0,) * NATIVE_WIDTH)
    result.validate()
    return result


def feature_hash(vector) -> str:
    require(len(vector) == WIDTH, "wrong real HF feature width")
    h = hashlib.sha256(b"hepta.e0.public-pretrained-mean-feature.f32.v1")
    h.update(WIDTH.to_bytes(4, "big"))
    for value in vector:
        h.update(struct.pack(">f", float(value)))
    return h.hexdigest()


def control_readout(native_bridge, projected):
    # Deliberately fixed control (not trained, not a selected Cell Head).
    drive = [0] * (NATIVE_WIDTH * 2)
    drive[0] = Q
    drive[NATIVE_WIDTH + 1] = Q
    artifact = {"input_width": NATIVE_WIDTH, "output_width": 2,
                "drive_weights_q24": drive, "drive_bias_q24": [0, 0]}
    return native_bridge.native_logits(artifact, [v / Q for v in projected])


def ensure_snapshot(root: Path, *, hf_source: Path) -> Path:
    from huggingface_hub import snapshot_download
    cache = root / "download-cache"
    raw_dir = snapshot_download(
        repo_id=MODEL_ID, revision=MODEL_REVISION, token=False,
        local_dir=str(cache), allow_patterns=FILES,
    )
    snapshot = root / "snapshot"
    snapshot.mkdir()
    for name in FILES:
        raw = Path(raw_dir) / name
        if name == "special_tokens_map.json" and not raw.exists():
            continue
        require(raw.is_file() and not raw.is_symlink(), "pinned HF file missing")
        shutil.copyfile(raw, snapshot / name)
    require(file_sha256(snapshot / "model.safetensors") == MODEL_WEIGHT_SHA256,
            "pretrained weight SHA256 changed")
    from hf_encoder_kernel import snapshot_digest
    require(snapshot_digest(snapshot) == SNAPSHOT_SHA256, "pinned snapshot digest changed")
    return snapshot


def run(*, hf_checkout: Path, projection_checkout: Path, output: Path) -> dict:
    require(not output.exists(), "nonempty/existing output is never overwritten")
    hf_source = source_checkout(hf_checkout, HF_SOURCE_COMMIT, HF_SOURCE_TREE)
    proj_source = source_checkout(projection_checkout, PROJECTION_SOURCE_COMMIT,
                                  PROJECTION_SOURCE_TREE)
    require(hf_source.is_dir() and proj_source.is_dir(), "missing exact model/projection sources")
    # Both imported modules are pinned by verified repository commits/trees.
    sys.path.insert(0, str(proj_source))
    sys.path.insert(0, str(hf_source))
    import torch
    import transformers
    from transformers import AutoTokenizer
    from hf_encoder_kernel import snapshot_digest, vectorize_case, verify_loaded_safetensors
    from hf_complete_checkpoint import TIED_ALIASES, load_complete_mlm
    from stem_projection import LowRankProjectionQ24
    import native_bridge
    torch.set_num_threads(1)
    require(str(transformers.__version__) == "4.57.1", "HF version drift")
    require(str(torch.__version__).startswith("2.10.0"), "Torch version drift")
    output.mkdir(parents=True)
    started = time.perf_counter_ns()
    try:
        snapshot = ensure_snapshot(output, hf_source=hf_source)
        checkpoint, encoder, loading = load_complete_mlm(snapshot)
        require(encoder.config.hidden_size == WIDTH, "source hidden size changed")
        tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True,
                                                   trust_remote_code=False)
        preprocessor_digest = file_sha256(snapshot / "tokenizer.json")
        runtime_digest = hashlib.sha256(
            ("torch:" + str(torch.__version__) + "/transformers:" +
             str(transformers.__version__) + "/cpu/fp32/eager").encode()).hexdigest()
        normalizer_digest = hashlib.sha256(b"mean-pool.valid-mask.fp32.v1").hexdigest()
        projection = make_diagnostic_projection(
            LowRankProjectionQ24, encoder=SNAPSHOT_SHA256,
            preprocessor=preprocessor_digest, runtime=runtime_digest,
            normalizer=normalizer_digest)
        # These three public texts are not evaluation/training observations.
        texts = ("The engineer repaired the electric motor.",
                 "A garden contains green plants and red flowers.",
                 "The engineer repaired the electric motor.")
        values, result, tokens, physical_forward_ns = [], [], [], []
        def forbidden(*_args):
            raise AssertionError("MLM vocabulary prediction head executed")
        guard = checkpoint.head.register_forward_pre_hook(forbidden)
        try:
            for text in texts:
                tick = time.perf_counter_ns()
                feature, n_tokens = vectorize_case(
                    torch, encoder, tokenizer,
                    {"state": text, "question": "Identify the subject.",
                     "options": ["person", "place"]}, "cpu", max_tokens=128)
                elapsed = time.perf_counter_ns() - tick
                require(feature.ndim == 1 and len(feature) == WIDTH,
                        "non-768 actual encoder result")
                vector = feature.tolist()
                projected = projection.project_float32(vector)
                require(len(projected) == NATIVE_WIDTH, "native width bound violated")
                logits = control_readout(native_bridge, projected)
                values.append((feature_hash(vector), tuple(projected)))
                tokens.append(n_tokens)
                physical_forward_ns.append(elapsed)
                result.append({"feature_sha256": feature_hash(vector),
                               "q24_sha256": hashlib.sha256(
                                   b"".join(int(v).to_bytes(8, "big", signed=True)
                                            for v in projected)).hexdigest(),
                               "diagnostic_readout": logits,
                               "source_width": WIDTH, "projected_width": NATIVE_WIDTH})
        finally:
            guard.remove()
        require(values[0] == values[2], "repeat input lost deterministic parity")
        require(values[0] != values[1], "different inputs collapsed to identical Q24 result")
        # Prove the projection responds to the last coordinate; no 512-wide silent slicing.
        perturb = [0.0] * WIDTH
        perturb[-1] = 0.25
        zero = projection.project_float32([0.0] * WIDTH)
        changed = projection.project_float32(perturb)
        require(zero != changed and zero[1] != changed[1],
                "last source coordinate silently dropped")
        verify_loaded_safetensors(torch, checkpoint, snapshot, tied_aliases=TIED_ALIASES)
        require(snapshot_digest(snapshot) == SNAPSHOT_SHA256 and
                file_sha256(snapshot / "model.safetensors") == MODEL_WEIGHT_SHA256,
                "snapshot drift after physical forward")
        record = {
            "schema": SCHEMA,
            "exact_hf_source": {"commit": HF_SOURCE_COMMIT, "tree": HF_SOURCE_TREE},
            "exact_projection_source": {"commit": PROJECTION_SOURCE_COMMIT,
                                        "tree": PROJECTION_SOURCE_TREE},
            "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
            "weight_sha256": MODEL_WEIGHT_SHA256, "snapshot_sha256": SNAPSHOT_SHA256,
            "checkpoint_parameters": loading["checkpoint_parameters"],
            "feature_parameters": loading["feature_parameters"],
            "feature_dimension": WIDTH,
            "q24_projection": {"kind": "deterministic_diagnostic_control_NOT_TRAINED",
                               "source_width": WIDTH, "native_width": NATIVE_WIDTH,
                               "rank": projection.rank, "digest": projection.digest,
                               "all_source_dimensions_represented": True,
                               "last_coordinate_perturbation_survived": True},
            "actual_hf_forward_calls": len(values), "token_counts": tokens,
            "model_forward_plus_projection_wall_ns": physical_forward_ns,
            "observations": result,
            "repeat_input_exact": True, "distinct_input_survived": True,
            "checkpoint_reverified_after_execution": True,
            "process_lifetime_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "elapsed_including_download_load_ns": time.perf_counter_ns() - started,
            "real_pretrained_model_loaded": True,
            "trained_cell_head": False, "native_worker_invoked": False,
            "neuron_checkpoint_committed": False, "independent_outcomes": False,
            "ndu_benefit_established": False, "e0_accepted": False,
            "production_authorized": False,
        }
        (output / "shadow.json").open("x", encoding="utf-8").write(
            json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
        return record
    except BaseException as exc:
        (output / "FAILED.json").open("x", encoding="utf-8").write(
            json.dumps({"schema": SCHEMA, "completed": False,
                        "error_type": type(exc).__name__, "e0_accepted": False,
                        "production_authorized": False}, indent=2) + "\n")
        raise


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hf-checkout", type=Path, required=True)
    p.add_argument("--projection-checkout", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = run(hf_checkout=args.hf_checkout, projection_checkout=args.projection_checkout,
                 output=args.output)
    print(json.dumps({"schema": report["schema"],
                      "model_forward_calls": report["actual_hf_forward_calls"],
                      "e0_accepted": report["e0_accepted"]}, sort_keys=True))


if __name__ == "__main__":
    main()
