#!/usr/bin/env python3
"""Public pretrained Encoder -> existing low-rank Q24 projection -> diagnostic Q24 readout.

SHADOW/MECHANISM ONLY. Not a trained Head, native Worker, Neuron Tick,
independent outcome observation, signed artifact, or E0 acceptance.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import sys
import tempfile
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
SCHEMA = "hepta.e0.public-pretrained-q24-shadow.v2"
SOURCE_PREFIX = "qualification/stem-cell-v1/"
MAX_SOURCE_FILES = 128
MAX_SOURCE_FILE_BYTES = 1 << 20
MAX_SOURCE_TOTAL_BYTES = 8 << 20


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


def git_bytes(path: Path, *args: str) -> bytes:
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(["git", "--no-replace-objects", "-C", str(path), *args],
                          capture_output=True, check=True, env=env).stdout


def source_checkout(path: Path, commit: str, tree: str) -> Path:
    require(path.is_dir() and not path.is_symlink(), "source checkout absent")
    observed = git_bytes(path, "rev-parse", "HEAD", "HEAD^{tree}").decode().splitlines()
    require(observed == [commit, tree], "source checkout SHA/tree mismatch")
    require(not git_bytes(path, "status", "--porcelain", "--untracked-files=no").strip(),
            "dirty source checkout")
    return path / "qualification" / "stem-cell-v1"


def project_source_bytes(path: Path, commit: str, tree: str, names=None) -> dict:
    """Read regular flat Python blobs from the fixed tree, never the worktree."""
    source_checkout(path, commit, tree)
    entries = git_bytes(path, "ls-tree", "-rlz", "--full-tree", tree, "--", SOURCE_PREFIX)
    found, total = {}, 0
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        relative = raw_path.decode("utf-8")
        if not relative.endswith(".py"):
            continue
        require(relative.startswith(SOURCE_PREFIX), "project source escaped its prefix")
        leaf = relative[len(SOURCE_PREFIX):]
        module = leaf[:-3]
        require("/" not in leaf and module.isascii() and module.isidentifier()
                and module != "__init__", "project Python sources must be flat modules")
        if names is not None and module not in names:
            continue
        mode, kind, oid, size = header.split()
        require(mode in (b"100644", b"100755") and kind == b"blob",
                "project Python source must be a regular blob")
        oid = oid.decode("ascii")
        require(len(oid) == 40 and all(c in "0123456789abcdef" for c in oid),
                "invalid project blob identity")
        size = int(size)
        total += size
        require(0 < size <= MAX_SOURCE_FILE_BYTES and total <= MAX_SOURCE_TOTAL_BYTES
                and len(found) < MAX_SOURCE_FILES, "project Python source exceeds bounds")
        raw = git_bytes(path, "cat-file", "blob", oid)
        require(len(raw) == size, "project Python blob size mismatch")
        actual_oid = hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest()
        require(actual_oid == oid, "project Python blob identity mismatch")
        require(module not in found, "duplicate project module")
        found[module] = {
            "bytes": raw,
            "identity": {"module": module, "commit": commit, "tree": tree, "path": relative,
                         "git_blob": oid, "bytes": size, "sha256": hashlib.sha256(raw).hexdigest()},
        }
    require(bool(found) and (names is None or set(found) == set(names)),
            "required project Python source missing")
    return found


class ProjectSourceLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Compile the verified buffers; filesystem source/bytecode loaders are bypassed."""

    def __init__(self, modules):
        self.modules = modules
        self.created = {}
        self.loaded = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.modules:
            return None
        return importlib.util.spec_from_loader(
            fullname, self, origin=str(self.modules[fullname]["snapshot"]))

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source = self.modules[module.__name__]
        self.created[module.__name__] = module
        module.__file__ = str(source["snapshot"])
        module.__cached__ = None
        exec(compile(source["bytes"], module.__file__, "exec", dont_inherit=True),
             module.__dict__)
        self.loaded[module.__name__] = dict(source["identity"])

    def loaded_sources(self):
        return [self.loaded[name] for name in sorted(self.loaded)]


@contextmanager
def bound_project_sources(specifications):
    """One-process scope for project Python only; external runtimes stay external."""
    modules = {}
    for path, commit, tree, names in specifications:
        found = project_source_bytes(path, commit, tree, names)
        require(not (modules.keys() & found.keys()), "ambiguous project module ownership")
        modules.update(found)
    require(sum(len(source["bytes"]) for source in modules.values()) <= MAX_SOURCE_TOTAL_BYTES,
            "combined project Python source exceeds bounds")
    require(not (modules.keys() & sys.modules.keys()), "project module already loaded")
    with tempfile.TemporaryDirectory(prefix="hepta-e0-source-") as directory:
        for source in modules.values():
            identity = source["identity"]
            snapshot = Path(directory) / identity["commit"] / identity["path"]
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(source["bytes"])
            snapshot.chmod(0o400)
            source["snapshot"] = snapshot
        loader = ProjectSourceLoader(modules)
        sys.meta_path.insert(0, loader)
        try:
            yield loader
        finally:
            if loader in sys.meta_path:
                sys.meta_path.remove(loader)
            for name, module in loader.created.items():
                if sys.modules.get(name) is module:
                    del sys.modules[name]


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
    specifications = (
        (hf_checkout, HF_SOURCE_COMMIT, HF_SOURCE_TREE, None),
        (projection_checkout, PROJECTION_SOURCE_COMMIT, PROJECTION_SOURCE_TREE,
         ("stem_projection", "native_bridge")),
    )
    with bound_project_sources(specifications) as sources:
        return _run_bound(output=output, sources=sources)


def _run_bound(*, output: Path, sources: ProjectSourceLoader) -> dict:
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
        hf_source = sources.modules["hf_encoder_kernel"]["snapshot"].parent
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
                require(feature.ndim == 1 and len(feature) == WIDTH,
                        "non-768 actual encoder result")
                vector = feature.tolist()
                projected = projection.project_float32(vector)
                elapsed = time.perf_counter_ns() - tick
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
        peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            peak_rss_kib //= 1024
        record = {
            "schema": SCHEMA,
            "project_python_sources": sources.loaded_sources(),
            "project_python_binding": "verified_git_blobs_compiled_from_same_bytes",
            "external_runtime_binding": "existing_version_checks_only",
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
            "process_lifetime_peak_rss_kib": peak_rss_kib,
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
