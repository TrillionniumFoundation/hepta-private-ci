"""Physically acquire exact source bytes; no model import, torch.load, or model inference.

Pinned Hub revisions and Git blob/LFS content IDs are verified against downloaded
files. This is a read-only research artifact, NOT a signed model-load receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import time
from pathlib import Path

import preflight
from gate import AUTHORITY, MODELS, require

SCHEMA = "hepta.stem.equal-size.physical-source-bytes.v1"
READ_CHUNK = 4 * 1024**2


def _physical_bytes(root, filename, declared_size, source_type, original_source_id):
    """Read with NOFOLLOW, reject path aliasing, verify SHA256 + Git identity."""
    require(preflight.member(filename), "invalid source filename")
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "source root not ordinary directory")
    p = root.joinpath(*filename.split("/"))
    parents = list(p.parents)
    for candidate in parents:
        if candidate == root:
            break
        require(candidate.is_dir() and not candidate.is_symlink(), "aliased/missing source directory")
    require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root.resolve()),
            "source file missing, escaped or symlinked")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(p, flags)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size == declared_size,
                "source not regular file or published length mismatch")
        s256 = hashlib.sha256()
        git = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
        length = 0
        with os.fdopen(fd, "rb", closefd=False) as f:
            while data := f.read(READ_CHUNK):
                length += len(data)
                require(length <= declared_size, "source grew while reading")
                s256.update(data)
                git.update(data)
        after = os.fstat(fd)
        require(length == declared_size and (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) ==
                (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size), "source changed mid-review")
        actual = s256.hexdigest()
        expected = actual if source_type == "lfs_sha256" else git.hexdigest()
        require(source_type in ("lfs_sha256", "git_blob_sha1") and expected == original_source_id,
                "upstream source byte/hash mismatch")
        return actual
    finally:
        os.close(fd)


def verify_snapshot(plan, stage_root):
    require(type(plan) is dict and plan.get("schema") == preflight.SCHEMA and
            plan.get("model") in MODELS and plan.get("authority") == AUTHORITY and
            plan.get("disposition") == "HOLD_NO_GO", "source plan not admitted")
    items = plan.get("selected_source_inventory")
    require(type(items) is list and 0 < len(items) <= preflight.MAX_FILES, "invalid selection inventory")
    require([v.get("filename") for v in items if type(v) is dict] == sorted(set(
        v.get("filename") for v in items if type(v) is dict)), "duplicate/unsorted source files")
    require(all(type(x) is dict and set(x) == {"filename", "published_size", "source_identity_type",
                                                     "source_identity", "is_weight"} for x in items),
            "malformed source item")
    total = 0
    measured = []
    for item in items:
        filename = item["filename"]
        require(preflight.member(filename) and preflight.chosen(plan["model"], filename)
                and type(item["published_size"]) is int and item["published_size"] > 0 and
                item["is_weight"] is preflight.is_weight(filename), "incompatible source item")
        total += item["published_size"]
        require(total <= preflight.MAX_TOTAL_BYTES, "unbounded source bytes")
        hash_value = _physical_bytes(stage_root, filename, item["published_size"],
                                     item["source_identity_type"], item["source_identity"])
        measured.append({"filename":filename, "sha256":hash_value,"size":item["published_size"]})
    require(total == plan["selected_total_bytes"], "selected source total mismatch")
    # Reject a downloader that staged any unadmitted file, apart from private Hub
    # transfer bookkeeping. In particular never reuse a sibling family weight.
    names = {x["filename"] for x in measured}
    for path in Path(stage_root).rglob("*"):
        relative = path.relative_to(stage_root).as_posix()
        if relative == ".cache" or relative.startswith(".cache/huggingface"):
            continue
        if path.is_file() or path.is_symlink():
            require(relative in names and not path.is_symlink(),
                    "unselected or symlinked file staged by downloader")
    return measured


def acquire(model, model_info, snapshot_download, stage):
    require(model in MODELS, "unregistered model")
    repo, revision, _, _ = MODELS[model]
    plan = preflight.inspect_model(model, model_info(repo_id=repo, revision=revision, files_metadata=True))
    root = Path(stage)
    require(root.parent.is_dir() and not root.parent.is_symlink() and not root.exists(),
            "stage must be new and parent an ordinary directory")
    root.mkdir(mode=0o700)
    try:
        names = [x["filename"] for x in plan["selected_source_inventory"]]
        started = time.monotonic_ns()
        location = snapshot_download(repo_id=repo, revision=revision, local_dir=str(root),
                                     allow_patterns=names, max_workers=2)
        require(Path(location).resolve() == root.resolve(), "downloader returned another directory")
        measured = verify_snapshot(plan, root)
        elapsed = time.monotonic_ns() - started
    except BaseException:
        # Leave a failed stage for runner cleanup/forensics; never publish success.
        raise
    return {"schema":SCHEMA, "model":model, "repo":repo,"revision":revision,
            "source_schema":preflight.SCHEMA,"selected_source_inventory":plan["selected_source_inventory"],
            "files":measured,"file_count":len(measured),
            "download_verify_wall_ns_self_reported":elapsed,
            "selected_source_bytes_verified":True,"weight_bytes_verified":plan["selected_weight_bytes"],
            "requires_safe_weights_only_conversion":plan["requires_safe_weights_only_conversion"],
            "model_imported":False,"torch_pickle_loaded":False,"tensor_model_loaded":False,
            "real_model_forward_completed":False,"publisher_signature_verified":False,
            "production_promotion_permitted":False,"authority":AUTHORITY,"disposition":"HOLD_NO_GO"}


def write_new(path, doc):
    out = Path(path)
    require(out.parent.is_dir() and not out.parent.is_symlink() and not out.exists(),
            "output must be create-only in ordinary directory")
    data = (json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    require(len(data) <= 256 * 1024, "overlarge source receipt")
    fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def main(argv=None):
    ap = argparse.ArgumentParser(description="SHA-checked genuine checkpoint BYTE intake, NO model load")
    ap.add_argument("--model", required=True, choices=tuple(MODELS))
    ap.add_argument("--stage", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    from huggingface_hub import HfApi, snapshot_download
    receipt = acquire(args.model, HfApi().model_info, snapshot_download, args.stage)
    write_new(args.out, receipt)
    print(f"{args.model}: verified {receipt['file_count']} real source files, "
          "no torch.load or model forward, HOLD_NO_GO")


if __name__ == "__main__":
    main()
