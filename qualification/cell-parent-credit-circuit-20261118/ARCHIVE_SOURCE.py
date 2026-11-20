"""Retain every completed E4 call, setup, failure and exact adapter byte."""

import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
import time

BASE = Path("/home/qian-qi/work/hepta-e4-parent-credit-20261118-2e9b")
ROOT = BASE / "candidate-18de3463"
DEST = BASE / "export-complete-3"
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
ENTRIES = {}
INDEX = []


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def add(name, path):
    assert (
        name not in ENTRIES
        and not Path(name).is_absolute()
        and ".." not in Path(name).parts
    ), name
    before = path.stat()
    assert path.is_file() and not path.is_symlink(), path
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    ENTRIES[name] = raw
    INDEX.append(
        {
            "path": name,
            "bytes": len(raw),
            "sha256": sha(raw),
            "original_path": str(path),
            "original_mode": stat.S_IMODE(before.st_mode),
            "original_uid": before.st_uid,
            "original_gid": before.st_gid,
        }
    )


def directory(prefix, path, python_only=False):
    for child in sorted(path.rglob("*")):
        if not child.is_file() or "__pycache__" in child.parts:
            continue
        if python_only and child.suffix != ".py":
            continue
        add(prefix + "/" + child.relative_to(path).as_posix(), child)


def main():
    start = time.monotonic()
    readout = json.loads((DEST / "READOUT.json").read_bytes())
    assert (
        readout["status"] == "AUDIT_PASS"
        and readout["total_model_calls"] == 112
        and readout["total_verifier_calls"] == 118
    )
    assert (
        sha((DEST / "READOUT.json").read_bytes())
        == "d60e05f9522e13763868a2fbeb8a21a6c8063e3dcc2cfde8e5b807805df787b0"
    )
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_bytes())
    add("run/SOURCE_FREEZE.json", ROOT / "SOURCE_FREEZE.json")
    for label in ("run-1", "owned-run-1", "deployment"):
        directory("run/" + label, ROOT / label)
    for name, expected in freeze["files"].items():
        path = ROOT / "source" / name
        assert sha(path.read_bytes()) == expected, name
        add("execution-source/" + name, path)
    for path in sorted(BASE.iterdir()):
        if path.is_dir() and path.name.startswith(
            ("preparation", "preflight", "final-format", "deployment")
        ):
            directory("preflight/" + path.name, path)
        elif path.is_file():
            add("preflight/" + path.name, path)
    for number in (1, 2):
        directory(
            "audit-failed-" + str(number), BASE / ("export-complete-" + str(number))
        )
    for name in (
        "READOUT.json",
        "CALLS.json",
        "TASKS.json",
        "INPUT_INDEX.json",
        "AUDIT_SOURCE.py",
        "AUDIT_EXIT.json",
        "AUDIT_STDOUT.json",
        "AUDIT_STDERR.log",
        "FORMAT_STDOUT.txt",
        "FORMAT_STDERR.txt",
        "RESULTS.md",
        "ARCHIVE_SOURCE.py",
    ):
        add("readout/" + name, DEST / name)
    old_source = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
    directory(
        "original-matched-source/scripts", old_source / "scripts", python_only=True
    )
    directory(
        "retained-provider-core/scripts",
        ARTIFACT / "candidate-qwen-03/scripts",
        python_only=True,
    )
    directory(
        "retained-research-source",
        ARTIFACT / "research-sft-v1-source",
        python_only=True,
    )
    directory(
        "retained-operation-helpers",
        ARTIFACT / "e1e2-operation-helpers-04",
        python_only=True,
    )
    credit = Path(
        "/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b/source/qualification/cell-current-policy-credit-20261118"
    )
    directory("original-credit-source", credit)
    add("calibration-original/INPUTS.json", ARTIFACT / "research-sft-02/INPUTS.json")
    provider = json.loads((ROOT / "run-1/FREEZE.json").read_bytes())["provider"]
    adapters = {}
    for cell, identity in provider["manifest_files"].items():
        manifest_path = Path(identity["path"])
        manifest_raw = manifest_path.read_bytes()
        assert sha(manifest_raw) == identity["sha256"]
        manifest = json.loads(manifest_raw)
        add("models/" + cell + "/manifest.json", manifest_path)
        adapter_dir = (ARTIFACT / manifest["adapter_directory"]).resolve(strict=True)
        assert adapter_dir.is_relative_to(ARTIFACT)
        directory("models/" + cell + "/adapter", adapter_dir)
        add("models/" + cell + "/TRAINING.json", adapter_dir.parent / "TRAINING.json")
        adapters[cell] = {
            "model_digest": readout["models"][cell],
            "normalized_FP32_parameter_sha256": readout[
                "actual_loaded_parameter_sha256"
            ][cell],
            "files": {
                p.name: {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
                for p in sorted(adapter_dir.iterdir())
                if p.is_file()
            },
        }
    (DEST / "ADAPTERS.json").write_text(
        json.dumps(adapters, sort_keys=True, indent=2) + "\n"
    )
    add("models/ADAPTERS.json", DEST / "ADAPTERS.json")
    jobs = [
        "1a1ef64829b-ffbe-4b3",
        "1a1ef682e90-ffbe-4c5",
        "1a1ef6a71aa-ffbe-4d0",
        "1a1ef6b861b-ffbe-4d7",
        "1a1ef705ec8-ffbe-4e8",
        "1a1ef73d613-ffbe-4f1",
        "1a1ef75566e-ffbe-4f6",
        "1a1ef774693-ffbe-4f9",
        "1a1ef8b5535-ffbe-537",
        "1a1ef8f1429-ffbe-541",
        "1a1ef9426ee-ffbe-54f",
    ]
    runtime = Path("/home/qian-qi/.local/state/hepta-runtime-mac-worker/jobs")
    job_layout = {}
    for job in jobs:
        folder = runtime / job
        assert (folder / "exit.json").is_file() and (
            folder / "exit.witness.json"
        ).is_file(), job
        job_layout[job] = [p.name for p in sorted(folder.iterdir()) if p.is_file()]
        for p in sorted(folder.iterdir()):
            if p.is_file() and (
                p.name in ("exit.json", "exit.witness.json")
                or "stdout" in p.name
                or "stderr" in p.name
            ):
                add("runtime-jobs/" + job + "/" + p.name, p)
    (DEST / "RUNTIME_JOB_LAYOUT.json").write_text(
        json.dumps(job_layout, sort_keys=True, indent=2) + "\n"
    )
    add("runtime-jobs/LAYOUT.json", DEST / "RUNTIME_JOB_LAYOUT.json")
    markers = []
    preparation_source = BASE / "source"
    for p in sorted(preparation_source.rglob(".hepta-lock-*")):
        if p.is_file():
            markers.append(
                {
                    "path": str(p),
                    "bytes": p.stat().st_size,
                    "sha256": sha(p.read_bytes()),
                    "left_unchanged": True,
                }
            )
            add("preflight/retained-tool-sidecars/" + p.name, p)
    assert markers, "first zero-call rejection marker must remain preserved"
    (DEST / "ZERO_CALL_DEPLOYMENT.json").write_text(
        json.dumps(
            {
                "job": "1a1ef73d613-ffbe-4f1",
                "model_calls": 0,
                "verifier_calls": 0,
                "reason": "tool-created sidecar caused clean-tree rejection before source freeze/owner launch",
                "markers": markers,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    add("preflight/ZERO_CALL_DEPLOYMENT.json", DEST / "ZERO_CALL_DEPLOYMENT.json")
    index = {
        "schema": "hepta.complete-parent-credit-e4-originals.v1",
        "files": sorted(INDEX, key=lambda row: row["path"]),
        "execution_source": freeze["source_commit"],
        "model_calls": 112,
        "verifier_calls": 118,
        "audit_model_calls": 0,
        "audit_verifier_calls": 0,
        "full_runtime_distribution_included": False,
        "base_model_weight_files_included": False,
    }
    index_raw = json.dumps(index, sort_keys=True, indent=2).encode() + b"\n"
    (DEST / "EVIDENCE_INDEX.json").write_bytes(index_raw)
    ENTRIES["EVIDENCE_INDEX.json"] = index_raw
    archive = DEST / "RAW_EVIDENCE.tar.xz"
    with tarfile.open(archive, "x:xz", preset=6) as stream:
        for name, raw in sorted(ENTRIES.items()):
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            entry.mode = 0o644
            entry.mtime = 0
            stream.addfile(entry, io.BytesIO(raw))
    with tarfile.open(archive, "r:xz") as stream:
        members = stream.getmembers()
        assert len(members) == len(ENTRIES) and len({p.name for p in members}) == len(
            members
        )
        for item in members:
            assert (
                item.isfile() and stream.extractfile(item).read() == ENTRIES[item.name]
            ), item.name
    raw = archive.read_bytes()
    manifest = {
        "schema": "hepta.complete-parent-credit-e4-archive.v1",
        "archive": str(archive),
        "bytes": len(raw),
        "sha256": sha(raw),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
        "members": len(ENTRIES),
        "indexed_originals": len(INDEX),
        "index_sha256": sha(index_raw),
        "readout_sha256": sha((DEST / "READOUT.json").read_bytes()),
        "archive_source_sha256": sha((DEST / "ARCHIVE_SOURCE.py").read_bytes()),
        "model_calls": 112,
        "verifier_calls": 118,
        "collector_new_model_calls": 0,
        "collector_new_verifier_calls": 0,
        "wall_seconds": time.monotonic() - start,
        "original_execution_source": freeze["source_commit"],
        "both_actual_adapter_tensors_included": True,
        "base_model_weights_remain_manifest_referenced": True,
    }
    (DEST / "ARCHIVE_MANIFEST.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    print(json.dumps(manifest, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
