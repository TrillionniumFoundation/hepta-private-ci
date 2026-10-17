"""Read-only exact-revision Hugging Face file plan for Hepta stem trials.

The source-plan is not a publisher signature or an actual loaded model receipt.
Only the selected candidate's required files enter the physical download budget.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath

from gate import AUTHORITY, MODELS, require, sha

SCHEMA = "hepta.stem.equal-size.source-preflight.v2"
WANTED = {
    "laya421": ("model.safetensors", "rl_agent_config.json", "tokenizer/tokenizer.json", "encoder/config.json"),
    "laya_typed421": ("model.safetensors", "rl_agent_config.json", "tokenizer/tokenizer.json", "encoder/config.json"),
    "ettin400": ("pytorch_model.bin", "config.json", "tokenizer.json"),
    "openjev434": ("model.safetensors", "head.safetensors", "config.json", "tokenizer.json"),
}
MAX_FILES = 512
# Public Hugging Face snapshots normally contain this Git bookkeeping file.
# It is *not* a model/Tokenizer input; no other hidden path is admitted.
IGNORED_GIT_METADATA = frozenset({".gitattributes"})
MAX_WEIGHT_BYTES = 3 * 1024**3
MAX_SMALL_BYTES = 32 * 1024**2
MAX_TOTAL_BYTES = 4 * 1024**3
FILE_TYPES = (".safetensors", ".bin", ".json", ".model", ".txt", ".vocab")


def member(name):
    if type(name) is not str or not 0 < len(name) <= 256 or "\\" in name:
        return False
    parts = name.split("/")
    return (all(p not in ("", ".", "..") and not p.startswith(".") for p in parts)
            and PurePosixPath(name).as_posix() == name)


def is_weight(path):
    return path.endswith((".safetensors", ".bin"))


def chosen(model, name):
    if name in WANTED[model]:
        return True
    if model.startswith("laya"):
        return ((name.startswith("tokenizer/") or name.startswith("encoder/"))
                and name.endswith(FILE_TYPES))
    if model == "ettin400":
        return ("/" not in name and name in {"tokenizer_config.json", "special_tokens_map.json", "added_tokens.json"})
    if model == "openjev434":
        return ("/" not in name and name in {"open_jev_config.json", "tokenizer_config.json",
                                                "special_tokens_map.json", "added_tokens.json", "spm.model"})
    return False


def _source_id(blob):
    lfs = getattr(blob, "lfs", None)
    lfs_sha = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
    if lfs is not None:
        require(sha(lfs_sha), "invalid recorded upstream LFS/Xet compatibility hash")
        return "lfs_sha256", lfs_sha
    blob_id = getattr(blob, "blob_id", None)
    require(type(blob_id) is str and len(blob_id) == 40 and
            all(c in "0123456789abcdef" for c in blob_id), "unidentified non-LFS source blob")
    return "git_blob_sha1", blob_id


def inspect_model(model_name, metadata):
    require(model_name in MODELS, "unexpected candidate model")
    repo, rev, approx, kind = MODELS[model_name]
    require(getattr(metadata, "sha", None) == rev, "Hub returned a different immutable revision")
    names = {}
    siblings = getattr(metadata, "siblings", None)
    require(type(siblings) in (list, tuple) and 0 < len(siblings) <= MAX_FILES,
            "missing/unbounded upstream file census")
    for f in siblings:
        n = getattr(f, "rfilename", None)
        if n in IGNORED_GIT_METADATA:
            # Exact, root-only Git transport metadata; never selected for use.
            # Still reject a duplicate member and retain it in the full census.
            require(n not in names, "duplicate Git bookkeeping file")
        else:
            require(member(n) and n not in names,
                    "unsafe, missing or duplicate source path")
        names[n] = f
    require(set(WANTED[model_name]).issubset(names), "required checkpoint/config/tokenizer absent")
    selected = sorted(name for name in names if chosen(model_name, name))
    require(set(WANTED[model_name]).issubset(selected), "load file omitted")
    require(any("tokenizer" in n and n.endswith((".json", ".model")) for n in selected),
            "tokenizer source missing")
    weights = [n for n in selected if is_weight(n)]
    require(weights and all(name in selected for name in WANTED[model_name] if is_weight(name)),
            "missing complete target weight set")
    receipts, total, weight_bytes = [], 0, 0
    for n in selected:
        f = names[n]
        size = getattr(f, "size", None)
        limit = MAX_WEIGHT_BYTES if is_weight(n) else MAX_SMALL_BYTES
        require(type(size) is int and 0 < size <= limit, "unknown/oversized selected file")
        typ, oid = _source_id(f)
        if is_weight(n):
            require(typ == "lfs_sha256", "tensor source lacks LFS/Xet-compatible byte SHA256")
            weight_bytes += size
        total += size
        require(total <= MAX_TOTAL_BYTES, "unbounded selected candidate bytes")
        receipts.append({"filename": n, "published_size": size, "source_identity_type": typ,
                         "source_identity": oid, "is_weight": is_weight(n)})
    return {"schema": SCHEMA, "model": model_name, "repo": repo, "revision": rev,
            "published_approx_params": approx, "basis": kind,
            "selected_source_inventory": receipts,
            "original_weight_inventory": [r for r in receipts if r["is_weight"]],
            "selected_total_bytes": total, "selected_weight_bytes": weight_bytes,
            "other_repo_files_excluded": len(names) - len(selected),
            "requires_safe_weights_only_conversion": any(n.endswith(".bin") for n in weights),
            "remote_code_execution_allowed": False, "snapshot_weight_bytes_checked": False,
            "loaded_model_tensors_verified": False, "issuer_signature_verified": False,
            "user_task_quality_verified": False, "authority": AUTHORITY,
            "production_promotion_permitted": False, "disposition": "HOLD_NO_GO"}


def run(model_info):
    records = []
    for model_name, (repo, rev, _, _) in MODELS.items():
        records.append(inspect_model(model_name, model_info(repo_id=repo, revision=rev, files_metadata=True)))
    require(len(records) == 4, "incomplete source metadata census")
    return {"schema": SCHEMA, "models": records, "authority": AUTHORITY,
            "disposition": "HOLD_NO_GO", "production_promotion_permitted": False,
            "all_original_weights_downloaded": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pinned source metadata only: no weights downloaded")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    from huggingface_hub import HfApi
    receipt = run(HfApi().model_info)
    out = Path(args.out)
    require(out.parent.is_dir() and not out.parent.is_symlink() and not out.exists(), "invalid metadata output path")
    data = (json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    print("4/4 pinned Hub metadata censused; NO WEIGHT DOWNLOAD; HOLD_NO_GO")


if __name__ == "__main__":
    main()
