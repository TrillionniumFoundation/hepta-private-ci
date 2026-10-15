#!/usr/bin/env python3
"""Run the exact 97M/140M/149M pretrained core trio on one public E1 cohort.

Real local safetensors execution, 40-step frozen-feature Head learning. No
production Stem selection, genuine future observations or external attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e1_public_triplet_real_cpu import load_panel, fit_heads, canonical, sha
from e1e2_q24_identity import feature_digest, feature_inventory

PANEL_SHA256 = "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4"
MODELS = {
    "granite_97m_r2": ("ibm-granite/granite-embedding-97m-multilingual-r2",
                       "835ad14087e140460703cf0fae09f97d469d65c2", 384,
                       "encoder", "cls-first-token"),
    "mmbert_small": ("jhu-clsp/mmBERT-small",
                     "0eb3d056ec1d6333cf4e19b0966dfde342a41a3a", 384,
                     "masked_lm", "attention-mask-mean"),
    "modernbert_base": ("answerdotai/ModernBERT-base",
                        "fa3113d09d6dacfe5528708803dd92a62240237a", 768,
                        "masked_lm", "attention-mask-mean"),
}
MAX_STAGE_BYTES = 2 * 1024**3
MAX_TOKENS = 512


class Invalid(ValueError):
    pass


def spec(model):
    if model not in MODELS:
        raise Invalid("unregistered core Encoder: never silently substitute Gemma")
    return MODELS[model]


def _publisher_digest(path: Path, sibling):
    """Compare actual bytes against publisher LFS SHA256 or Git blob SHA1."""
    if type(sibling.size) is not int or path.stat().st_size != sibling.size:
        raise Invalid("published model file size differs")
    lfs = getattr(sibling, "lfs", None)
    expected = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if lfs is not None:
        if not isinstance(expected, str) or digest != expected:
            raise Invalid("publisher LFS digest drift")
    else:
        expected = getattr(sibling, "blob_id", None)
        git = hashlib.sha1(b"blob " + str(path.stat().st_size).encode() + b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024**2), b""):
                git.update(chunk)
        if not isinstance(expected, str) or git.hexdigest() != expected:
            raise Invalid("publisher Git-blob digest drift")
    return digest


def stage_pinned(model: str, stage_root: Path):
    """Acquisition only; the actual Encoder has no network access or pickle."""
    from huggingface_hub import HfApi, snapshot_download

    repository, revision, width, kind, pooling = spec(model)
    stage_root.mkdir(parents=True, exist_ok=False)
    info = HfApi().model_info(repo_id=repository, revision=revision, files_metadata=True)
    if info.sha != revision:
        raise Invalid("moving remote revision is forbidden")
    siblings = {s.rfilename: s for s in info.siblings}
    if len(siblings) != len(info.siblings):
        raise Invalid("duplicated model filename in publisher response")
    allowed = tuple(n for n in siblings if n.endswith((".json", ".txt", ".model", ".safetensors")))
    if ("model.safetensors" not in allowed or "tokenizer.json" not in allowed
            or "config.json" not in allowed):
        raise Invalid("full pinned safetensors/tokenizer/config required; no binary conversion")
    total = 0
    for name in allowed:
        part = Path(name)
        if (part.is_absolute() or ".." in part.parts or
                any(p in ("", ".") for p in part.parts)):
            raise Invalid("unsafe model file name")
        size = siblings[name].size
        if type(size) is not int or not 0 <= size <= MAX_STAGE_BYTES:
            raise Invalid("unknown publisher file size")
        total += size
    if total > MAX_STAGE_BYTES:
        raise Invalid("unbounded candidate snapshot")
    cached = Path(snapshot_download(repo_id=repository, revision=revision,
                                    allow_patterns=list(allowed),
                                    cache_dir=stage_root / "download-cache"))
    dest = stage_root / "model"
    dest.mkdir()
    files = {}
    for name in sorted(allowed):
        src = cached / name
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not src.is_file():
            raise Invalid("missing publisher file: " + name)
        shutil.copyfile(src, target)
        files[name] = _publisher_digest(target, siblings[name])
    profile = {"path": "model", "kind": kind, "revision": revision,
               "model_id": repository, "conversion": None, "files": files}
    if sum((dest / path).stat().st_size for path in files) > MAX_STAGE_BYTES:
        raise Invalid("snapshot grew after publisher verification")
    return profile, sha(canonical(sorted(files.items())))


def _render_joint(joint: dict) -> str:
    if (type(joint) is not dict or set(joint) != {"state", "question", "options"}
            or type(joint["state"]) is not str
            or type(joint["question"]) is not str
            or type(joint["options"]) is not list):
        raise Invalid("wrong complete joint decision input")
    options = " | ".join(f"{i}: {option}" for i, option in enumerate(joint["options"]))
    return f"State: {joint['state']}\nQuestion: {joint['question']}\nOptions: {options}"


def execute(panel: dict, panel_sha256: str, model: str, stage_root: Path) -> dict:
    import torch
    from experiments.shared_stem_cell.execution import LocalEncoder

    repository, revision, width, kind, pooling = spec(model)
    if panel_sha256 != PANEL_SHA256:
        raise Invalid("different public source panel; do not splice cross-study tasks")
    started = time.perf_counter_ns()
    process_cpu = time.process_time_ns()
    staged, publisher_files_digest = stage_pinned(model, stage_root)
    if (staged["model_id"], staged["revision"], staged["kind"]) != (repository, revision, kind):
        raise Invalid("model source drift")
    begin = time.perf_counter_ns()
    torch.set_num_threads(2)
    backend = LocalEncoder(stage_root / "model", staged, maximum_tokens=MAX_TOKENS)
    load_ms = (time.perf_counter_ns() - begin) / 1e6
    if backend.loaded.config.hidden_size != width:
        raise Invalid("full pretrained model width drift")
    if backend.forward_calls != 0:
        raise Invalid("dirty physical forward counter")
    features, tokens, digests, latency = {}, {}, {}, {}
    cases = panel["cases"]
    for c in cases:
        ident = c["case_id"]
        text = _render_joint(c["joint_input"])
        tokenizer_options = {"truncation": False, "return_tensors": "pt"}
        if backend.loaded.config.model_type == "modernbert":
            tokenizer_options["return_token_type_ids"] = False
        raw = backend.tokenizer(text, **tokenizer_options)
        count = int(raw["input_ids"].shape[1])
        if not 1 <= count <= MAX_TOKENS:
            raise Invalid("no silent truncation or changed tokenizer")
        t0 = time.perf_counter_ns()
        vector = backend.encode([text], pooling=pooling)
        elapsed = (time.perf_counter_ns() - t0) / 1e6
        if (tuple(vector.shape) != (1, width)
                or not bool(torch.isfinite(vector).all())
                or not float(torch.linalg.vector_norm(vector[0])) > 1e-12):
            raise Invalid("invalid actual token-pooled pretrained feature")
        vec = torch.nn.functional.normalize(vector[0].float(), p=2, dim=0)
        values = [round(float(v) * (1 << 24)) / (1 << 24) for v in vec.tolist()]
        if not all(math.isfinite(v) and -8 <= v <= 8 for v in values):
            raise Invalid("out-of-domain rounded Q24 feature")
        features[ident] = values
        tokens[ident] = count
        digests[ident] = feature_digest(ident, values)
        latency[ident] = elapsed
    if backend.forward_calls != len(cases) or len(features) != 224:
        raise Invalid("actual model forward count or case coverage drift")
    backend.close()
    bank = feature_inventory([c["case_id"] for c in cases], features)
    fit = fit_heads(panel, model, features, feature_width=width if model == "modernbert_base" else None)
    if feature_inventory([c["case_id"] for c in cases], features) != bank:
        raise Invalid("frozen features mutated during Head learning")
    total_wall_ms = (time.perf_counter_ns() - started) / 1e6
    return {
        "schema": "hepta.e1-english-public-pretrained-head.v1",
        "model": model, "model_name": repository,
        "model_revision": revision, "feature_width": width,
        "public_panel_sha256": panel_sha256,
        "public_dataset_is_chronological_future": False,
        "english_only": True, "actual_pretrained_local_weight_execution_claimed": True,
        "model_origin_independently_authenticated": False,
        "physical_transformer_forward_count_attested": False,
        "tokens_per_case": tokens, "features_q24_identity": digests,
        "frozen_feature_bank_identity": bank,
        "physical_observations": {
            "load_ms": load_ms, "encode_ms_by_case": latency,
            "local_model_api_requests": len(cases),
            "local_encoder_forward_calls_observed": backend.forward_calls,
            "physical_transformer_forward_count_attested": False,
            "local_all_saved_model_tensors_checked_by_loader": True,
            "publisher_files_checked_by_local_acquisition": True,
            "publisher_file_inventory_sha256": publisher_files_digest,
            "reference_transformers_runtime_version": __import__("transformers").__version__,
        },
        "fitting": fit, "wall_ms": total_wall_ms,
        "cpu_process_ms": (time.process_time_ns() - process_cpu) / 1e6,
        "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "independent_no_change_production_arm_present": False,
        "future_ndu_verified": False, "production_promotion_permitted": False,
        "authority": "DENY_ALL",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--model", choices=sorted(MODELS), required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.stage.exists():
        raise FileExistsError("no overwrite of staged inputs or result")
    panel, panel_hash = load_panel(args.panel)
    result = execute(panel, panel_hash, args.model, args.stage)
    with args.output.open("x", encoding="utf8") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
