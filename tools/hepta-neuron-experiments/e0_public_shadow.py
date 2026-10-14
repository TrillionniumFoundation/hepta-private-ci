"""Opt-in REAL public ModernBERT CPU -> audited Stem Q24 projection shadow probe.

Runs pinned pretrained tensors and the existing stem_projection.py operator,
cross-checks a separate scalar oracle and executes an UNTRAINED diagnostic Q24
Head. No Neuron Worker, learned effectiveness or production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

from e0_projection_numeric import calculate, field, i64, u64

STEM_RESEARCH_SHA = "be511bd63aaae8813c415a116d50f01fe54baba5"
STEM_AUDIT_SHA = "d6f35c362289c90427bfbdffd4505d2e535c1b1b"
HF_REV = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
WEIGHT_SHA256 = "340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9"
SNAPSHOT_SHA256 = "43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d"
HF_MODEL = "answerdotai/ModernBERT-base"
MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json",
               "tokenizer_config.json", "special_tokens_map.json")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha(folder: Path) -> str:
    return subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def require_research_roots(research: Path, audited: Path) -> None:
    if git_sha(research) != STEM_RESEARCH_SHA or git_sha(audited) != STEM_AUDIT_SHA:
        raise ValueError("research/audited source not at frozen exact commits")


def freeze_public_snapshot(root: Path, *, acquire: bool) -> Path:
    """Network only on explicitly requested acquisition. Inference is local-only."""
    from hf_encoder_kernel import snapshot_digest
    if acquire:
        from huggingface_hub import snapshot_download
        if (os.environ.get("HF_HUB_OFFLINE") or os.environ.get("TRANSFORMERS_OFFLINE")):
            raise ValueError("offline policy blocks public acquisition")
        download = root / "huggingface-public"
        snapshot_download(repo_id=HF_MODEL, revision=HF_REV, token=False,
                          allow_patterns=MODEL_FILES, local_dir=str(download))
        snapshot = root / "snapshot"
        snapshot.mkdir()
        for filename in MODEL_FILES:
            original = download / filename
            if original.is_file():
                shutil.copyfile(original, snapshot / filename)
    else:
        snapshot = root
    if not snapshot.is_dir() or not (snapshot / "model.safetensors").is_file():
        raise ValueError("missing pinned public model snapshot")
    if file_sha(snapshot / "model.safetensors") != WEIGHT_SHA256:
        raise ValueError("pretrained weight SHA256 drift")
    if snapshot_digest(snapshot) != SNAPSHOT_SHA256:
        raise ValueError("pretrained snapshot inventory drift")
    return snapshot


class ShadowRequest:
    def __init__(self, projection, input_digest: str):
        self.request_id = "e0.public.shadow.1"
        self.scope_digest = sha(b"hepta.e0.public.diagnostic.scope.v1")
        self.generation = 1
        self.revocation_frontier_digest = sha(b"hepta.e0.public.no-authorization.v1")
        self.encoder_digest = projection.encoder_digest
        self.preprocessor_digest = projection.preprocessor_digest
        self.runtime_digest = projection.runtime_digest
        self.input_digest = input_digest
        self.representation = "mean"

    def validate(self):
        if self.generation != 1 or any(len(x) != 64 for x in
            (self.scope_digest, self.revocation_frontier_digest, self.encoder_digest,
             self.preprocessor_digest, self.runtime_digest, self.input_digest)):
            raise ValueError("invalid diagnostic request binding")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-root", type=Path, required=True)
    parser.add_argument("--audited-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--acquire-public", action="store_true")
    source.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    try:
        require_research_roots(args.research_root, args.audited_root)
        sys.path.insert(0, str(args.research_root / "qualification/stem-cell-v1"))
        sys.path.insert(0, str(args.audited_root / "qualification/stem-cell-v1"))
        from hf_complete_checkpoint import load_complete_mlm
        from hf_encoder_kernel import vectorize_case, snapshot_digest
        from stem_projection import LowRankProjectionQ24, project_ref, save_shadow_projection, Q
        from native_bridge import native_logits
        import torch
        from transformers import AutoTokenizer
        torch.set_num_threads(1)
        snapshot = freeze_public_snapshot(root if args.acquire_public else args.snapshot,
                                          acquire=args.acquire_public)
        t0 = time.perf_counter_ns()
        c0 = time.process_time_ns()
        rss_before_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        complete, encoder, loading = load_complete_mlm(snapshot)
        tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True,
                                                   trust_remote_code=False)
        # This exact joint input intentionally duplicates the established public canary.
        case = dict(state="The engineer repaired the electric motor.",
                    question="Identify the subject.", options=["person", "place"])
        t_forward = time.perf_counter_ns()
        feature, tokens = vectorize_case(torch, encoder, tokenizer, case, "cpu", max_tokens=128)
        forward_wall_ns = time.perf_counter_ns() - t_forward
        elapsed_ns = time.perf_counter_ns() - t0
        process_cpu_ns = time.process_time_ns() - c0
        rss_after_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if feature.shape != (768,) or feature.dtype != torch.float32:
            raise ValueError("public Encoder did not produce frozen 768-D float32")
        feature_f32 = tuple(feature.tolist())
        raw = struct.pack(">768f", *feature_f32)
        source_feature_file = root / "feature.f32be"
        source_feature_file.write_bytes(raw)
        feature_digest = hashlib.sha256(b"hepta.stem.feature.f32.v1" +
                                        u64(768) + raw + u64(tokens) + b"mean").hexdigest()
        source_feature = SimpleNamespace(values=feature_f32, token_count=tokens,
                                         representation="mean", feature_digest=feature_digest)
        encoder_digest = snapshot_digest(snapshot)
        # Non-authorizing stable diagnostic tuple, not a selected production bundle.
        preprocessor_digest = sha(b"hepta.e0.public.render_joint.max128.v1")
        runtime_digest = sha(b"hepta.e0.public.cpu-fp32.eager.transformers4.57.1.v1")
        normalizer_digest = sha(b"hepta.e0.public.attention-masked-mean.v1")
        a = [0] * 768
        a[767] = Q
        b = [0] * 256
        b[255] = Q
        projection = LowRankProjectionQ24(
            encoder_digest, preprocessor_digest, runtime_digest, normalizer_digest,
            "mean", 768, 256, 1, tuple(a), tuple(b), (0,) * 256)
        # The rank-one pass-through of the last coordinate is a *nontrained
        # diagnostic fixture*, explicitly NOT an optimized model/Cell Head.
        projection_path = root / "shadow-projection.json"
        projection_sha = save_shadow_projection(
            projection_path, projection,
            training_lineage_digest=sha(b"hepta.e0.untrained-diagnostic-projection.v1"))
        input_digest = sha(json.dumps(case, sort_keys=True, separators=(",", ":")).encode())
        request = ShadowRequest(projection, input_digest)
        ref = project_ref(request, source_feature, projection)
        trial = dict(schema="hepta.neuron.e0-projection-numeric-trial.v1",
                     source_kind="local_f32_capture_untrusted",
                     feature_file=str(source_feature_file),
                     feature_file_sha256=file_sha(source_feature_file),
                     feature_digest=feature_digest, token_count=tokens,
                     projection_manifest=str(projection_path),
                     projection_file_sha256=projection_sha,
                     projection_digest=projection.digest,
                     source_input_digest=input_digest, scope_digest=request.scope_digest,
                     revocation_frontier_digest=request.revocation_frontier_digest,
                     generation=request.generation, head_input_width=256,
                     expected_output_q24=list(ref.vector_q24),
                     projected_input_digest=ref.projected_input_digest)
        trial_path = root / "numeric-trial.json"
        trial_path.write_text(json.dumps(trial, sort_keys=True, separators=(",", ":")) + "\n")
        independent_oracle = calculate(trial_path)
        if not independent_oracle["numeric_oracle_agrees"]:
            raise AssertionError("independent numerical oracle did not agree")
        # Exercise the existing Q24 Head arithmetic using an untrained fixture.
        # This is NOT the native Rust Neuron Worker or a trained policy.
        weights = [0] * (2 * 256)
        weights[-1] = Q
        logits = native_logits(dict(input_width=256, output_width=2,
                                    drive_weights_q24=weights,
                                    drive_bias_q24=[0, 0]),
                               [int(x) / Q for x in ref.vector_q24])
        if len(logits) != 2 or logits[0] != 0 or round(logits[-1] * Q) != ref.vector_q24[-1]:
            raise AssertionError("native shadow Q24 Head did not match projection")
        if snapshot_digest(snapshot) != SNAPSHOT_SHA256:
            raise ValueError("public Encoder bytes drift after inference")
        report = dict(schema="hepta.neuron.e0-public-pretrained-projection-shadow.v1",
                      base_research_sha=STEM_RESEARCH_SHA, audited_projection_sha=STEM_AUDIT_SHA,
                      public_model_id=HF_MODEL, upstream_revision=HF_REV,
                      weights_sha256=WEIGHT_SHA256, snapshot_sha256=SNAPSHOT_SHA256,
                      parameters_full=loading["checkpoint_parameters"],
                      parameters_feature=loading["feature_parameters"],
                      encoder_width=768, projector_output_width=256,
                      token_count=tokens, original_feature_sha256=sha(raw),
                      projection_sha256=projection_sha, projection_digest=projection.digest,
                      projected_input_digest=ref.projected_input_digest,
                      oracle_result=independent_oracle,
                      diagnostic_head_logits_q24=[round(x * Q) for x in logits],
                      loading_and_forward_wall_ns=elapsed_ns,
                      forward_wall_ns=forward_wall_ns,
                      process_cpu_ns=process_cpu_ns,
                      process_lifetime_rss_peak_kib_before=rss_before_kib,
                      process_lifetime_rss_peak_kib_after=rss_after_kib,
                      peak_rss_scope="lifetime_high_water_not_single_request",
                      actual_public_pretrained_encoder_forward=True,
                      actual_original_stem_projection_forward=True,
                      actual_shadow_untrained_head_forward=True,
                      authorized_production_model=False, trained_cell_head=False,
                      neuron_worker_executed=False, durable_q24_neuron_tick=False,
                      independent_task_outcome=False, model_superiority=False)
        with (root / "report.json").open("x", encoding="utf-8") as f:
            json.dump(report, f, sort_keys=True, indent=2)
            f.write("\n")
        print(json.dumps({k: report[k] for k in (
            "schema", "public_model_id", "encoder_width", "projector_output_width",
            "token_count", "actual_public_pretrained_encoder_forward",
            "actual_original_stem_projection_forward", "neuron_worker_executed",
            "independent_task_outcome")}, sort_keys=True))
        return 0
    except Exception as exc:
        # Failure record contains no raw confidential weights/feature vectors.
        with (root / "FAILED.json").open("x", encoding="utf-8") as f:
            json.dump({"schema": "hepta.e0.public-shadow-failure.v1",
                       "error_type": type(exc).__name__, "complete": False,
                       "production_authorized": False}, f, sort_keys=True)
            f.write("\n")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
