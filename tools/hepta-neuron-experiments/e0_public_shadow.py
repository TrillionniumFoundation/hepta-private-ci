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
from e0_feature_normalization import (
    normalize_feature_bytes, choose_diagnostic_tail_index,
)

STEM_RESEARCH_SHA = "be511bd63aaae8813c415a116d50f01fe54baba5"
STEM_AUDIT_SHA = "d6f35c362289c90427bfbdffd4505d2e535c1b1b"
HF_REV = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
WEIGHT_SHA256 = "340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9"
SNAPSHOT_SHA256 = "43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d"
HF_MODEL = "answerdotai/ModernBERT-base"
TORCH_CPU_VERSION = "2.10.0+cpu"
TRANSFORMERS_VERSION = "4.57.1"
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


def require_import_origins(items: tuple) -> None:
    """Deny imported source implementations from shadowed / unexpected trees."""
    for module, expected in items:
        actual = getattr(module, "__file__", None)
        if not actual or Path(actual).resolve() != expected.resolve():
            raise ValueError("unqualified model/projection module import")


def require_runtime_versions(torch_version: str, transformers_version: str) -> None:
    """Fail closed rather than silently changing the measured CPU numerical stack."""
    if torch_version != TORCH_CPU_VERSION or transformers_version != TRANSFORMERS_VERSION:
        raise ValueError("unreviewed pretrained CPU execution dependency revision")


def require_research_roots(research: Path, audited: Path) -> None:
    for root, expected in ((research, STEM_RESEARCH_SHA), (audited, STEM_AUDIT_SHA)):
        if git_sha(root) != expected:
            raise ValueError("research/audited source not at frozen exact commits")
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all", "--ignored"],
            check=True, capture_output=True, text=True).stdout.strip()
        if dirty:
            raise ValueError("research/audited source has tracked file drift or untracked/ignored shadow")


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
    # Source checkouts must remain byte-for-byte clean through final admission.
    # Disable Python bytecode writes BEFORE importing either research tree.
    sys.dont_write_bytecode = True
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    try:
        require_research_roots(args.research_root, args.audited_root)
        sys.path.insert(0, str(args.research_root / "qualification/stem-cell-v1"))
        sys.path.insert(0, str(args.audited_root / "qualification/stem-cell-v1"))
        import hf_complete_checkpoint
        import hf_encoder_kernel
        import stem_projection
        import native_bridge
        import matrix_materials
        # The project intentionally uses TWO separately pinned source trees.
        # Resolve every imported implementation to its reviewed owner; sys.path
        # order or a same-named module may not silently substitute another tree.
        expected_modules = (
            (hf_complete_checkpoint, args.research_root / "qualification/stem-cell-v1/hf_complete_checkpoint.py"),
            (hf_encoder_kernel, args.research_root / "qualification/stem-cell-v1/hf_encoder_kernel.py"),
            (stem_projection, args.audited_root / "qualification/stem-cell-v1/stem_projection.py"),
            (matrix_materials, args.research_root / "qualification/stem-cell-v1/matrix_materials.py"),
            (native_bridge, args.audited_root / "qualification/stem-cell-v1/native_bridge.py"),
        )
        require_import_origins(expected_modules)
        from hf_complete_checkpoint import load_complete_mlm
        from hf_encoder_kernel import vectorize_case, snapshot_digest
        from stem_projection import LowRankProjectionQ24, project_ref, save_shadow_projection, Q
        from native_bridge import native_logits
        import torch
        import transformers
        from transformers import AutoTokenizer
        require_runtime_versions(torch.__version__, transformers.__version__)
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
        # Preserve the actual 768-D pretrained output independently from the
        # normalized feature that the existing Q24 Stem projector consumes.
        # The policy is frozen; the integer shift is per input and diagnostic,
        # never a learned or production-approved normalizer.
        raw = struct.pack(">768f", *feature.tolist())
        raw_feature_file = root / "encoder-raw.f32be"
        raw_feature_file.write_bytes(raw)
        normalized_raw, normalization = normalize_feature_bytes(raw)
        feature_f32 = struct.unpack(">768f", normalized_raw)
        source_feature_file = root / "projection-input-normalized.f32be"
        source_feature_file.write_bytes(normalized_raw)
        feature_digest = hashlib.sha256(b"hepta.stem.feature.f32.v1" +
                                        u64(768) + normalized_raw + u64(tokens) + b"mean").hexdigest()
        source_feature = SimpleNamespace(values=feature_f32, token_count=tokens,
                                         representation="mean", feature_digest=feature_digest)
        encoder_digest = snapshot_digest(snapshot)
        # Non-authorizing stable diagnostic tuple, not a selected production bundle.
        preprocessor_digest = sha(b"hepta.e0.public.render_joint.max128.dyadic.v2")
        runtime_digest = sha(b"hepta.e0.public.cpu-fp32.eager.transformers4.57.1.v1")
        normalizer_digest = normalization["policy_digest"]
        # Select the strongest *actual* tail coordinate solely to exercise a
        # nondegenerate diagnostic path. This input-dependent choice is not
        # a learned Head, a scientific selection or a valid deployed projector.
        tail_index = choose_diagnostic_tail_index(normalized_raw, 256)
        a = [0] * 768
        a[tail_index] = Q
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
        input_digest = sha(b"hepta.e0.public.diagnostic-input.normalized.v2" +
                           json.dumps(case, sort_keys=True, separators=(",", ":")).encode() +
                           bytes.fromhex(normalization["binding_digest"]))
        request = ShadowRequest(projection, input_digest)
        ref = project_ref(request, source_feature, projection)
        trial = dict(schema="hepta.neuron.e0-projection-numeric-trial.v2",
                     source_kind="normalized_local_f32_capture_untrusted",
                     raw_encoder_feature_file=str(raw_feature_file),
                     raw_encoder_feature_sha256=normalization["raw_sha256"],
                     normalization_shift=normalization["shift"],
                     normalization_binding_digest=normalization["binding_digest"],
                     normalization_policy_digest=normalization["policy_digest"],
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
        # Match native Neuron V1 state_width=256 without impersonating the
        # actual NeuronModelPort / Worker or introducing a selected policy.
        weights = [0] * (256 * 256)
        weights[-1] = Q
        logits = native_logits(dict(input_width=256, output_width=256,
                                    drive_weights_q24=weights,
                                    drive_bias_q24=[0] * 256),
                               [int(x) / Q for x in ref.vector_q24])
        if (len(logits) != 256 or any(logits[:-1]) or
                round(logits[-1] * Q) != ref.vector_q24[-1]):
            raise AssertionError("native shadow 256-wide Q24 Head mismatched projection")
        if snapshot_digest(snapshot) != SNAPSHOT_SHA256:
            raise ValueError("public Encoder bytes drift after inference")
        require_research_roots(args.research_root, args.audited_root)
        report = dict(schema="hepta.neuron.e0-public-pretrained-projection-shadow.v1",
                      base_research_sha=STEM_RESEARCH_SHA, audited_projection_sha=STEM_AUDIT_SHA,
                      public_model_id=HF_MODEL, upstream_revision=HF_REV,
                      weights_sha256=WEIGHT_SHA256, snapshot_sha256=SNAPSHOT_SHA256,
                      parameters_full=loading["checkpoint_parameters"],
                      parameters_feature=loading["feature_parameters"],
                      encoder_width=768, projector_output_width=256,
                      token_count=tokens,
                      original_feature_sha256=normalization["raw_sha256"],
                      normalized_feature_sha256=normalization["normalized_sha256"],
                      normalization=normalization,
                      diagnostic_tail_coordinate=tail_index,
                      projection_sha256=projection_sha, projection_digest=projection.digest,
                      projected_input_digest=ref.projected_input_digest,
                      oracle_result=independent_oracle,
                      diagnostic_head_width=256,
                      diagnostic_head_drive_q24_sha256=sha(
                          b"".join(i64(round(x * Q)) for x in logits)),
                      diagnostic_head_prediction_policy="all_zero_untrained",
                      execution_stack=dict(python=sys.version.split()[0], torch=torch.__version__,
                                           transformers=transformers.__version__,
                                           cpu_threads=1),
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
