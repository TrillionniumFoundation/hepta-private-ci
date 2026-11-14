"""Immutable Hugging Face source *metadata* census; no checkpoint download or load.

An LFS hash in an API response is NOT independent publisher signature, nor proof
that bytes were downloaded or loaded into a model. Report HOLD_NO_GO always.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath

from gate import AUTHORITY, MODELS, Denied, require, sha

SCHEMA = "hepta.stem.equal-size.source-preflight.v1"
WANTED = {
    "laya421": ("model.safetensors", "rl_agent_config.json"),
    "laya_typed421": ("model.safetensors", "rl_agent_config.json"),
    "ettin400": ("pytorch_model.bin", "config.json"),
    "openjev434": ("model.safetensors", "head.safetensors", "config.json"),
}
MAX_FILES = 256
MAX_WEIGHT_BYTES = 3 * 1024**3
MAX_TOTAL_BYTES = 6 * 1024**3


def member(name):
    if type(name) is not str or not 0 < len(name) <= 256 or "\\" in name:
        return False
    parts = name.split("/")
    return (all(p not in ("", ".", "..") and not p.startswith(".") for p in parts)
            and PurePosixPath(name).as_posix() == name)


def get_sha(sibling):
    lfs = getattr(sibling, "lfs", None)
    value = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
    return value.lower() if sha(value) else None


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
        require(member(n) and n not in names, "unsafe, missing or duplicate source path")
        names[n] = f
    require(set(WANTED[model_name]).issubset(names), "required checkpoint/config absent")
    require(any("tokenizer" in n and (n.endswith(".json") or n.endswith(".model"))
                for n in names), "tokenizer source missing")
    tensor_files = sorted(n for n in names if n.endswith((".safetensors", ".bin")))
    require(tensor_files and set(n for n in WANTED[model_name] if n.endswith((".safetensors", ".bin"))).issubset(tensor_files),
            "missing native tensor inventory")
    total = 0
    receipts = []
    for n in tensor_files:
        f = names[n]
        size = getattr(f, "size", None)
        lfs = get_sha(f)
        require(type(size) is int and 0 < size <= MAX_WEIGHT_BYTES, "missing/oversized tensor size")
        require(lfs is not None, "no original upstream weight LFS hash")
        total += size
        require(total <= MAX_TOTAL_BYTES, "unbounded total original model tensors")
        receipts.append({"filename":n, "published_size":size, "published_lfs_sha256":lfs})
    return {"schema":SCHEMA, "model":model_name,"repo":repo,"revision":rev,
            "published_approx_params":approx,"basis":kind,
            "original_weight_inventory":receipts,
            "requires_safe_weights_only_conversion":any(n.endswith(".bin") for n in tensor_files),
            "remote_code_execution_allowed":False, "snapshot_weight_bytes_checked":False,
            "loaded_model_tensors_verified":False, "issuer_signature_verified":False,
            "user_task_quality_verified":False, "authority":AUTHORITY,
            "production_promotion_permitted":False, "disposition":"HOLD_NO_GO"}


def run(model_info):
    records=[]
    for model_name,(repo,rev,_,_) in MODELS.items():
        # Exact full 40-hex revision, no fallback to main and no arbitrary repo id.
        records.append(inspect_model(model_name,model_info(repo_id=repo,revision=rev,files_metadata=True)))
    require(len(records) == 4, "incomplete model census")
    return {"schema":SCHEMA,"models":records,"authority":AUTHORITY,"disposition":"HOLD_NO_GO",
            "production_promotion_permitted":False,"all_original_weights_downloaded":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description="Physical-source preflight only, NO weight downloads")
    parser.add_argument("--out",required=True)
    args=parser.parse_args(argv)
    from huggingface_hub import HfApi
    receipt=run(HfApi().model_info)
    out=Path(args.out)
    require(out.parent.is_dir() and not out.parent.is_symlink(), "refuse symlinked output parent")
    data=(json.dumps(receipt,sort_keys=True,separators=(",", ":"),allow_nan=False)+"\n").encode()
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0)
    fd=os.open(out,flags,0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    print("4/4 pinned Hub metadata censused; ORIGINAL WEIGHTS NOT DOWNLOADED; HOLD_NO_GO")


if __name__ == "__main__":
    main()
