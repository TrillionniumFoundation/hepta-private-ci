"""Fetch only registered public checkpoint bytes at immutable Hub revisions.

Acquisition is deliberately separate from offline model execution. Every file
is checked against the revision's Git blob or LFS digest before it is admitted.
The result is integrity/provenance evidence, not a model-quality qualification.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote
from urllib.request import Request, urlopen

from real_encoder import CANDIDATES
from teacher_snapshot import inventory

COMMON = ("config.json", "tokenizer.json", "tokenizer_config.json",
          "special_tokens_map.json", "tokenizer.model", "README.md", "LICENSE")
FILES = {
    "granite97m": COMMON + ("model.safetensors",),
    "embeddinggemma2_740m": COMMON + ("model.safetensors", "processor_config.json",
                                      "preprocessor_config.json", "chat_template.jinja"),
    "mmbert_small": COMMON + ("pytorch_model.bin",),
    "laya_encoder_only": ("config.json", "model.safetensors", "encoder/config.json",
                          "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json",
                          "tokenizer/special_tokens_map.json", "README.md", "LICENSE"),
}
MAX_FILE_BYTES = 4 * 1024 ** 3


def _request(url):
    return urlopen(Request(url, headers={"User-Agent": "Hepta-reproducible-research/1"}),
                   timeout=120)


def _verify_file(path, metadata):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("checkpoint must contain unaliased regular files")
    size = before.st_size
    if size != metadata["size"] or size > MAX_FILE_BYTES:
        raise ValueError("downloaded size differs from pinned revision")
    sha = hashlib.sha256()
    git = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("checkpoint changed before hashing")
        while block := stream.read(1024 * 1024):
            sha.update(block)
            git.update(block)
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns, before.st_nlink) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns, after.st_nlink):
        raise ValueError("checkpoint changed while hashing")
    lfs = metadata.get("lfs")
    if lfs:
        if sha.hexdigest() != lfs["sha256"]:
            raise ValueError("downloaded bytes do not match pinned LFS digest")
    elif git.hexdigest() != metadata["blobId"]:
        raise ValueError("downloaded bytes do not match pinned Git blob")
    return {"path": metadata["rfilename"], "bytes": size, "sha256": sha.hexdigest(),
            "upstream_lfs_sha256": lfs["sha256"] if lfs else None,
            "upstream_git_blob": metadata["blobId"]}


def fetch_checkpoint(candidate, destination):
    spec = CANDIDATES[candidate]
    repo, revision = spec["repository"], spec["revision"]
    api = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
    with _request(api) as response:
        body = response.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024:
        raise ValueError("Hub metadata exceeds budget")
    metadata = json.loads(body)
    if metadata.get("sha") != revision:
        raise ValueError("Hub response is not the registered immutable revision")
    available = {}
    for item in metadata["siblings"]:
        name = item["rfilename"]
        if name in available:
            raise ValueError("duplicate filename in Hub revision metadata")
        available[name] = item
    weights = "pytorch_model.bin" if candidate == "mmbert_small" else "model.safetensors"
    required = {"config.json", weights}
    required.add("tokenizer/tokenizer.json" if candidate == "laya_encoder_only"
                 else "tokenizer.json")
    if not required <= available.keys():
        raise ValueError("registered checkpoint is missing required files")
    expected_weights = spec.get("weight_sha256", spec.get("upstream_bin_sha256"))
    if available[weights].get("lfs", {}).get("sha256") != expected_weights:
        raise ValueError("Hub weight digest disagrees with registered source pin")
    for name in FILES[candidate]:
        if name not in available:
            continue
        item = available[name]
        if (type(item.get("size")) is not int or not 0 <= item["size"] <= MAX_FILE_BYTES
                or not re.fullmatch(r"[0-9a-f]{40}", item.get("blobId", ""))):
            raise ValueError("missing or invalid upstream file size/blob digest")
        if item.get("lfs") and not re.fullmatch(r"[0-9a-f]{64}", item["lfs"].get("sha256", "")):
            raise ValueError("invalid upstream LFS digest")
    root = Path(destination).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("destination may not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for name in FILES[candidate]:
        if name not in available:
            continue
        item = available[name]
        target = root / name
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError("destination contains a symlink")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(target.name + ".partial")
            # An existing partial file is never silently overwritten or trusted.
            created = False
            try:
                with temporary.open("xb") as output:
                    created = True
                    url = f"https://huggingface.co/{repo}/resolve/{revision}/{quote(name)}"
                    with _request(url) as response:
                        total = 0
                        while block := response.read(1024 * 1024):
                            total += len(block)
                            if total > item["size"]:
                                raise ValueError("remote body exceeds declared file size")
                            output.write(block)
                _verify_file(temporary, item)
                # Atomic no-clobber installation; a concurrent final file wins.
                os.link(temporary, target, follow_symlinks=False)
            finally:
                if created:
                    temporary.unlink(missing_ok=True)
        results.append(_verify_file(target, item))
        print(json.dumps({"verified_file": name, "bytes": item["size"]}), flush=True)
    contents = inventory(root)
    expected = sorted(({k: row[k] for k in ("path", "bytes", "sha256")}
                       for row in results), key=lambda row: row["path"])
    if contents["entries"] != expected:
        raise ValueError("snapshot contains unverified or concurrently modified files")
    receipt = {
        "schema": "hepta.public-checkpoint-acquisition.v1", "candidate": candidate,
        "repository": repo, "revision": revision, "metadata_url": api,
        "metadata_sha256": hashlib.sha256(body).hexdigest(), "files": results,
        "inventory_sha256": contents["inventory_sha256"],
        "publisher_signature_verified": False, "quality_qualified": False,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY",
    }
    # Outside the snapshot: no self-referential inventory and no mutable Hub cache.
    receipt_path = root.with_name(root.name + ".acquisition.json")
    if receipt_path.exists() or receipt_path.is_symlink():
        info = receipt_path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > 4 * 1024 * 1024):
            raise ValueError("invalid existing acquisition receipt")
        previous = json.loads(receipt_path.read_bytes())
        # Hub counters may change the API response bytes at an immutable revision.
        stable = {key: value for key, value in receipt.items() if key != "metadata_sha256"}
        if {key: value for key, value in previous.items() if key != "metadata_sha256"} != stable:
            raise ValueError("existing acquisition receipt conflicts with verified snapshot")
        return previous
    with receipt_path.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, choices=sorted(FILES))
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    print(json.dumps(fetch_checkpoint(args.candidate, args.destination), indent=2))


if __name__ == "__main__":
    main()
