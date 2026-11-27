"""Curate exact recovered files while keeping missing originals explicit."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import time
import zipfile


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or "\\" in name or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError("unsafe destination: " + name)
    return path.as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.monotonic(), time.process_time()
    config_bytes = args.config.read_bytes()
    config = json.loads(config_bytes)
    pending = []
    names = set()

    def add(source, name, expected):
        source = Path(source)
        name = relative(name)
        if name in names or source.is_symlink() or not source.is_file():
            raise ValueError("duplicate name or nonregular input: " + name)
        data = source.read_bytes()
        actual = identity(data)
        if actual != expected or actual["bytes"] > 500000:
            raise ValueError("input identity or blob-size failure: " + name)
        names.add(name)
        pending.append((source, name, data, actual))

    for row in config["files"]:
        add(row["source"], row["destination"], {k: row[k] for k in ("bytes", "sha256")})
    for bundle in config["copy_lists"]:
        source = Path(bundle["source"])
        raw = source.read_bytes()
        add(source, bundle["destination"] + "/COPY_LIST.json", {k: bundle[k] for k in ("bytes", "sha256")})
        document = json.loads(raw)
        rows = document.get("files", document.get("entries"))
        if not isinstance(rows, list):
            raise ValueError("copy list must contain explicit entries")
        for row in rows:
            path = row.get("source", row.get("path"))
            name = next((row[k] for k in ("destination", "target", "relative_destination", "relative_path", "suggested_name") if k in row), None)
            if name is None:
                raise ValueError("copy-list entry lacks an explicit destination")
            strip = bundle.get("strip_prefix", "")
            if strip:
                if not name.startswith(strip + "/"):
                    raise ValueError("copy-list prefix mismatch")
                name = name[len(strip) + 1:]
            add(path, bundle["destination"] + "/" + relative(name), {k: row[k] for k in ("bytes", "sha256")})

    for source, name, data, expected in pending:
        if identity(source.read_bytes()) != expected:
            raise ValueError("input changed before writing: " + name)
    args.destination.mkdir(exist_ok=False)

    def write(name, data):
        target = args.destination / relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)

    def record(name, value):
        write(name, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())

    for source, name, data, expected in pending:
        write(name, data)
        if identity(source.read_bytes()) != expected:
            raise ValueError("source changed during copy: " + name)
    write("curation/CONFIG.json", config_bytes)
    write("curation/build_recovery_appendix_v1.py", Path(__file__).read_bytes())

    archives = []
    for path in sorted(args.destination.rglob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            labels = [relative(m.filename.rstrip("/")) for m in members]
            if len(labels) != len(set(labels)):
                raise ValueError("duplicate ZIP member")
            if sum(m.file_size for m in members) > 1024**3:
                raise ValueError("ZIP exceeds expanded-byte budget")
            if any(stat.S_ISLNK(m.external_attr >> 16) for m in members):
                raise ValueError("ZIP symlink member")
            if archive.testzip() is not None:
                raise ValueError("ZIP CRC failure")
            rows = {m.filename: identity(archive.read(m)) for m in members if not m.is_dir()}
        archives.append({"path": path.relative_to(args.destination).as_posix(),
                         **identity(path.read_bytes()), "members": rows, "CRC_passed": True})
    record("ARCHIVES.json", {"schema": "hcsn-recovery-archive-identities-v1", "archives": archives,
                            "scope": "Directly stored ZIPs; nested members are identified by their own complete bytes."})
    record("COPY-RECEIPT.json", {
        "schema": "hcsn-exact-recovery-curation-v1",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "copied": [{"source": str(s), "destination": n, **i} for s, n, _, i in pending],
        "sources_unchanged": True,
        "main_entry_wall_prefix_seconds": time.monotonic() - started,
        "main_entry_CPU_prefix_seconds": time.process_time() - cpu,
        "cost_scope": "Prefix excludes imports, this receipt, manifest, stdout and process exit. No additive total is inferred.",
        "model_or_oracle_execution": False,
        "original_missing_receipts_reconstructed": False,
        "original_native_jobs_restarted": False,
    })
    rows = {p.relative_to(args.destination).as_posix(): identity(p.read_bytes())
            for p in sorted(args.destination.rglob("*")) if p.is_file()}
    if any(v["bytes"] > 500000 for v in rows.values()):
        raise ValueError("curated file exceeds blob-size policy")
    record("MANIFEST.json", {"schema": "hcsn-recovery-evidence-manifest-v1", "files": rows,
                             "actual_C2_terminal_audit": "not executed",
                             "whole_training_numerical_admission": "HOLD", "scientific_admission": "HOLD"})
    print(json.dumps({"files": len(rows), "manifest": identity((args.destination / "MANIFEST.json").read_bytes())}))


if __name__ == "__main__":
    main()
