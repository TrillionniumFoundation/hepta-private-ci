"""Create a verified RAM copy while preserving every original model/runtime byte."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import time
import traceback

ROOT = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
WORKSPACE = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
OWNERSHIP_SHA = "b526ddc15709e080a99b0c05102c1179c0e2c15313d3c971a4214946d2fcd37a"
MATERIALS_SHA = "2e06a748dfc4d378598d94d1c81beb3a33f19df91c79b2822fa14b173849ccd6"
ENVIRONMENT_SHA = "7f9368b38843ab1fbf158108e75008a04bf8d3b57c1e73a3e523d4bac832fac9"
SOURCE_SHA = "38a6f8bbc8a602befcd45ebd919bbcb2eca12d9f105798b29d72b2eb051c42d7"
SOURCE_MANIFEST_SHA = "f4baf14dfb07513ade469adf6877ce6cd15ac98fbcc0e390854fcf24c85ae2be"
BOOT = "8c55b477-233a-4771-995a-6f666f6299b3"


def file_hash(path):
    if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("regular nonsymlink file required")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for raw in iter(lambda: stream.read(4 * 1024**2), b""):
            result.update(raw)
    return result.hexdigest()


def snapshot():
    memory = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
    return {"observed_at_ns": time.time_ns(), "MemAvailable_bytes": memory,
            "tmpfs_available_bytes": shutil.disk_usage(WORKSPACE).free,
            "original_root_available_bytes": shutil.disk_usage(ROOT).free,
            "data_f_bavail": os.statvfs("/data").f_bavail,
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def write_new(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def identity(path):
    observed = path.lstat()
    return {"device": observed.st_dev, "inode": observed.st_ino, "bytes": observed.st_size,
            "mtime_ns": observed.st_mtime_ns, "mode": observed.st_mode, "nlink": observed.st_nlink}


def copy_one(source, destination, expected_sha, expected_bytes):
    before = identity(source)
    if source.resolve() != source or not stat.S_ISREG(before["mode"]) or before["bytes"] != expected_bytes:
        raise ValueError("source identity or size changed")
    if destination.parent.resolve() != destination.parent:
        raise ValueError("nonsymlink destination required")
    result = hashlib.sha256()
    with source.open("rb") as reader, destination.open("xb") as writer:
        for raw in iter(lambda: reader.read(4 * 1024**2), b""):
            result.update(raw)
            writer.write(raw)
        writer.flush()
        os.fsync(writer.fileno())
    if (identity(source) != before or result.hexdigest() != expected_sha
            or destination.stat().st_size != expected_bytes or file_hash(destination) != expected_sha
            or file_hash(source) != expected_sha or identity(source) != before):
        raise ValueError("full source/destination byte identity verification failed")
    return {"source": str(source), "destination": str(destination), "bytes": expected_bytes,
            "sha256": expected_sha, "source_identity_before": before,
            "source_identity_after": identity(source), "destination_identity": identity(destination),
            "independent_destination_sha256_checked": True, "source_rehashed_after_copy": True}


def main():
    assert Path(sys.executable) == ROOT / "venv/bin/python" and Path(sys.prefix) == ROOT / "venv"
    assert sys.flags.isolated and sys.dont_write_bytecode
    assert WORKSPACE.resolve() == WORKSPACE and WORKSPACE.stat().st_uid == os.getuid()
    assert file_hash(WORKSPACE / "WORKSPACE_OWNERSHIP.json") == OWNERSHIP_SHA
    assert file_hash(ROOT / "operations/recovery-04/MODEL_MATERIALS.json") == MATERIALS_SHA
    assert file_hash(ROOT / "operations/recovery-03/ENVIRONMENT_READY.json") == ENVIRONMENT_SHA
    assert file_hash(ROOT / "qwen-source-02.zip") == SOURCE_SHA
    assert file_hash(ROOT / "operations/QWEN_SOURCE_02.json") == SOURCE_MANIFEST_SHA
    before = snapshot()
    assert before["boot"] == BOOT
    assert before["tmpfs_available_bytes"] >= 8 * 1024**3 and before["MemAvailable_bytes"] >= 10 * 1024**3
    materials = json.loads((ROOT / "operations/recovery-04/MODEL_MATERIALS.json").read_bytes())
    assert len(materials["files"]) == 9
    assert materials["model_id"] == "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    assert materials["revision"] == "2e1fd397ee46e1388853d2af2c993145b0f1098a"
    total = sum(row["bytes"] for row in materials["files"])
    assert before["tmpfs_available_bytes"] >= total + 8 * 1024**3
    output = WORKSPACE / "operations"
    write_new(output / "MATERIALS_COPY_03_STARTED.json", {"before": before, "runtime_root": str(ROOT),
              "workspace_root": str(WORKSPACE), "expected_material_bytes": total,
              "ownership_sha256": OWNERSHIP_SHA, "materials_receipt_sha256": MATERIALS_SHA,
              "environment_receipt_sha256": ENVIRONMENT_SHA, "original_files_will_be_preserved": True})
    rows = []
    try:
        target = WORKSPACE / "materials-recovered"
        target.mkdir(mode=0o700, exist_ok=False)
        for item in materials["files"]:
            name = item["path"]
            assert Path(name).name == name
            assert shutil.disk_usage(WORKSPACE).free >= item["bytes"] + 8 * 1024**3
            rows.append(copy_one(ROOT / "materials-recovered" / name, target / name, item["sha256"], item["bytes"]))
            print(json.dumps({"copied": name, "bytes": item["bytes"], "sha256": item["sha256"]}), flush=True)
        other = []
        for relative, expected in (("qwen-source-02.zip", SOURCE_SHA), ("operations/QWEN_SOURCE_02.json", SOURCE_MANIFEST_SHA)):
            source, destination = ROOT / relative, WORKSPACE / relative
            other.append(copy_one(source, destination, expected, source.stat().st_size))
        after = snapshot()
        assert after["tmpfs_available_bytes"] >= 8 * 1024**3 and after["MemAvailable_bytes"] >= 10 * 1024**3
        report = {"schema": "hepta.qwen-materials-ram-copy.v3", "status": "VERIFIED",
                  "runtime_root": str(ROOT), "workspace_root": str(WORKSPACE),
                  "materials_relative_directory": "materials-recovered", "model_id": materials["model_id"],
                  "revision": materials["revision"], "before": before, "after": after,
                  "materials_receipt_sha256": MATERIALS_SHA, "environment_receipt_sha256": ENVIRONMENT_SHA,
                  "ownership_sha256": OWNERSHIP_SHA, "files": rows, "source_files": other,
                  "original_files_modified": False, "venv_copied": False, "symlinks_created": False,
                  "model_loaded": False, "training_started": False, "independent_sample_increment": 0}
        sha = write_new(output / "MATERIALS_COPY_03.json", report)
        print(json.dumps({"status": "VERIFIED", "receipt_sha256": sha, "material_files": len(rows),
                          "material_bytes": total, "after": after}), flush=True)
    except BaseException as error:
        write_new(output / "MATERIALS_COPY_03_FAILED.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "completed_files": rows, "after": snapshot(), "original_files_modified": False,
                  "partial_files_preserved": True, "model_loaded": False})
        raise


if __name__ == "__main__":
    signal.alarm(300)
    main()
