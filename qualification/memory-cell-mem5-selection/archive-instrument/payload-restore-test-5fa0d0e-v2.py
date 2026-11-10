"""MEM5 archive payload cold-restore exercise; no owner or sealed authority."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from collections import defaultdict

ROOT = Path("/home/qian-qi/mem5-cold-custody-20261110")
ARCHIVE = ROOT / "raw-archive-5fa0d0e-v1"
VERIFIER = ROOT / "archive-run-strict-v2-6f57a286.py"
STAGE = ROOT / ".payload-recovery-stage-5fa0d0e-v1"
TARGET = ROOT / "payload-recovery-5fa0d0e-v1"
VERIFIER_SHA = "3e8466d63a03306f8e52de6e5f68bd378ce235731f98f9022ec47a4696677897"
INDEX_SHA = "470cb2217d2d4727c551b6f935f8f1ffaa66f7702af87ea1fdaa15b86e0b69f4"
MANIFEST_SHA = "c98d559d76dee6d80b509397813e5f57128e53174d2e05b527f1df13a2339304"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def need(condition, why):
    if not condition:
        raise ValueError(why)

def main():
    os.umask(0o077)
    need(ROOT.is_dir() and ROOT.stat().st_mode & 0o077 == 0, "private parent required")
    need(not STAGE.exists() and not STAGE.is_symlink(), "staging must be absent")
    need(not TARGET.exists() and not TARGET.is_symlink(), "target must be absent")
    need(sha(VERIFIER.read_bytes()) == VERIFIER_SHA, "verifier not pinned")
    need(sha((ARCHIVE / "INDEX.json").read_bytes()) == INDEX_SHA, "INDEX not pinned")
    spec = importlib.util.spec_from_file_location("mem5_archive_strict", VERIFIER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.verify(ARCHIVE)
    need(result["status"] == "verified" and result["all_logical_files_reconstructible"], "verification failure")
    need(result["manifest_sha256"] == MANIFEST_SHA, "manifest identity changed")
    need((result["logical_files"], result["logical_bytes"]) == (4000, 77913835), "cohort changed")
    index = mod.strict_json(mod.read_regular(ARCHIVE / "INDEX.json"))
    descriptor = index["manifest"]
    manifest_parts = mod.reader(ARCHIVE, descriptor["assets"], descriptor["parts"])
    raw = b"".join(manifest_parts(p["asset"])[p["member"]] for p in descriptor["parts"])
    need(sha(raw) == MANIFEST_SHA, "recovered manifest mismatch")
    manifest = mod.strict_json(raw)
    data_reader = mod.reader(ARCHIVE, manifest["assets"], manifest["chunks"].values())
    grouped = defaultdict(list)
    for chunk_id, value in manifest["chunks"].items():
        grouped[value["asset"]].append((chunk_id, value))
    chunks = {}
    for asset_name, group in grouped.items():
        pack = data_reader(asset_name)
        for chunk_id, ref in group:
            data = pack[ref["member"]]
            need(sha(data) == chunk_id, "chunk not bound")
            chunks[chunk_id] = data
    need(len(chunks) == 2859, "missing chunk")
    usage = os.statvfs(ROOT)
    need(usage.f_bavail * usage.f_frsize > 2 * result["logical_bytes"], "insufficient free disk budget")
    os.mkdir(STAGE, mode=0o700)
    count = 0
    amount = 0
    for name, ref in sorted(manifest["files"].items()):
        parts = mod.relative(name)
        need(parts and all(x not in (".", "..") for x in parts), "noncanonical path")
        out = STAGE.joinpath(*parts)
        out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        obj = manifest["objects"][ref["sha256"]]
        digest = hashlib.sha256()
        written = 0
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            for chunk_id in obj["chunks"]:
                data = chunks[chunk_id]
                stream.write(data)
                digest.update(data)
                written += len(data)
            stream.flush()
            os.fsync(stream.fileno())
        need(digest.hexdigest() == ref["sha256"] and written == ref["bytes"], "restored file mismatch")
        count += 1
        amount += written
    need((count, amount) == (4000, 77913835), "restored totals mismatch")
    reread_count = 0
    reread_bytes = 0
    for name, ref in sorted(manifest["files"].items()):
        candidate = STAGE.joinpath(*mod.relative(name))
        need(candidate.is_file() and not candidate.is_symlink(), "restored path changed")
        contents = candidate.read_bytes()
        need(len(contents) == ref["bytes"] and sha(contents) == ref["sha256"], "disk readback mismatch")
        reread_count += 1
        reread_bytes += len(contents)
    need((reread_count, reread_bytes) == (count, amount), "disk readback totals mismatch")
    os.rename(STAGE, TARGET)
    print(json.dumps({
        "result": "FULL_PAYLOAD_READBACK_PASS",
        "archive_index_sha256": INDEX_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "verifier_sha256": VERIFIER_SHA,
        "logical_files": count,
        "logical_bytes": amount,
        "readback_files": reread_count,
        "readback_bytes": reread_bytes,
        "target": str(TARGET),
        "owner_authenticated": False,
        "external_custodian": False,
        "full_owner_cold_recovery": False,
        "sealed_confirmation": False,
        "actor_reexecution": False,
        "original_archive_regenerated": False
    }, sort_keys=True))

if __name__ == "__main__":
    main()
