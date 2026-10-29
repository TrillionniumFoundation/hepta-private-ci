"""Run registered jobs in an isolated tmpfs; preserve a verified local archive."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def last_line(path):
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 4096))
        lines = stream.read().decode(errors="replace").splitlines()
    return lines[-1] if lines else ""


def export_summaries(root, destination):
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue  # An exclusive writer may still be producing its final JSON.
        if path.name in {"COMPLETE.json", "FAILED.json", "ENDPOINTS.json", "INPUT_BINDING.json", "RESULT.json",
                         "SUMMARY.json", "REPORT.json", "B_REPORT.json", "C_REPORT.json", "W_REPORT.json"}:
            target = destination / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        elif path.name == "BANK.json":
            summary = {k: v for k, v in data.items() if k != "records"}
            summary["rows"] = [{k: r[k] for k in ("seed", "schedule_id", "prefix", "step", "action_values", "advantages",
                                                  "first_legal_successor_differences")}
                               for r in data["records"]]
            target = destination / path.relative_to(root).with_name("BANK_SUMMARY.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(target, summary)
        elif path.name == "PATHS.json":
            data["paths"] = [{k: v for k, v in row.items() if k != "trace"} for row in data["paths"]]
            target = destination / path.relative_to(root).with_name("PATHS_SUMMARY.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(target, data)


def archive_and_restore(root, mount, backup, export):
    files = sorted(p for p in root.rglob("*") if p.is_file())
    manifest = {str(p.relative_to(root)): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in files}
    atomic_json(root / "RAW_MANIFEST.json", manifest)
    files.append(root / "RAW_MANIFEST.json")
    expected = {str(p.relative_to(root)): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in files}
    if not backup.is_file() or backup.stat().st_size < 1040 * 1024 ** 2:
        raise ValueError("Required preallocated backup reservation missing")
    started = time.monotonic()
    with backup.open("r+b") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz", compresslevel=3) as archive:
            for path in files:
                archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
        written = stream.tell()
        if written > 1040 * 1024 ** 2:
            raise RuntimeError("Archive exceeded reserved bytes")
        stream.truncate(written)
        stream.flush()
        os.fsync(stream.fileno())
    restored = mount / "literal_restore"
    restored.mkdir(exist_ok=False)
    seen = set()
    with tarfile.open(backup, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise ValueError("Unexpected archive member")
            target = (restored / member.name).resolve()
            if not target.is_relative_to(restored.resolve()):
                raise ValueError("Unsafe archive path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                shutil.copyfileobj(archive.extractfile(member), stream)
            if target.stat().st_size != expected[member.name]["bytes"] or sha(target) != expected[member.name]["sha256"]:
                raise ValueError("Literal artifact restore mismatch")
            seen.add(member.name)
    if seen != set(expected):
        raise ValueError("Archive omitted artifacts")
    record = {"complete": True, "archive": str(backup), "archive_sha256": sha(backup),
              "archive_bytes": backup.stat().st_size, "literal_files_restored": len(seen),
              "literal_bytes_restored": sum(x["bytes"] for x in expected.values()),
              "wall_seconds": time.monotonic() - started, "external_uploads": 0}
    atomic_json(export / "ARCHIVE_VERIFICATION.json", record)
    return record


def command(stage, freeze, args, root):
    prefix = [sys.executable, "-B", "-m", "experiments.parameter_field_fullstudy_20261029."]
    common = ["--assets", args.assets, "--root", str(root), "--freeze", freeze]
    if stage in ("A", "B"):
        return [(stage + "-" + str(seed), [*prefix[:-1], prefix[-1] + "run", *common, "--phase", stage, "--seed", str(seed)])
                for seed in (17, 29, 43)]
    if stage in ("A_endpoint", "B_endpoint"):
        argv = [*prefix[:-1], prefix[-1] + "endpoints", *common, "--phase", stage[0]]
        if stage[0] == "B":
            argv += ["--source-manifest", args.source_manifest]
        return [(stage, argv)]
    if stage in ("C", "C_endpoint"):
        module = "architecture_run" if stage == "C" else "architecture_endpoints"
        argv = [*prefix[:-1], prefix[-1] + module, *common, "--reference-root", args.repository,
                "--protocol", args.protocol, "--execute"]
        if stage == "C_endpoint":
            argv += ["--source-manifest", args.source_manifest]
        return [(stage, argv)]
    if stage == "W":
        return [(stage, [*prefix[:-1], prefix[-1] + "witness", *common, "--protocol", args.protocol])]
    if stage == "preflight":
        return [(stage, [*prefix[:-1], prefix[-1] + "preflight", "--assets", args.assets, "--out", str(root / "preflight")])]
    raise ValueError("Unregistered stage " + stage)


def analyze(root, protocol, export):
    from .analysis import summarize
    from .endpoints import load_records as load_b
    from .architecture_endpoints import load_records as load_c
    for stage, path, loader in (("B", root / "stage_B/endpoints/ENDPOINTS.json", load_b),
                                ("C", root / "stage_C/endpoint_evaluation/ENDPOINTS.json", load_c)):
        if path.exists() and not path.with_name("FAILED.json").exists():
            report = summarize(loader(path, sha(path)), stage, protocol)
            atomic_json(root / (stage + "_REPORT.json"), report)
            atomic_json(export / (stage + "_REPORT.json"), report)


def main():
    parser = argparse.ArgumentParser()
    for name in ("mount", "export", "queue", "backup", "assets", "repository", "protocol", "source-manifest"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    mapping = Path("/proc/self/uid_map").read_text().split()
    if len(mapping) != 3 or mapping[2] != "1":
        raise RuntimeError("Launch only inside a private unshare --user --map-root-user --mount namespace")
    mount, export = Path(args.mount).resolve(), Path(args.export).resolve()
    if not mount.is_relative_to(Path(args.repository).resolve().parent):
        raise ValueError("Private mount must be in the task-owned workspace")
    mount.mkdir(parents=True, exist_ok=True)
    if any(mount.iterdir()):
        raise ValueError("Refusing to mount over existing artifacts")
    subprocess.run(["mount", "-t", "tmpfs", "-o", "size=4G,mode=700", "tmpfs", str(mount)], check=True)
    root = mount / "runs"
    root.mkdir()
    export.mkdir(parents=True, exist_ok=True)
    logs = root / "logs"
    logs.mkdir()
    protocol = json.loads(Path(args.protocol).read_text())
    pending, running, results, submitted = [], {}, {}, set()
    last_export = 0.
    started = time.monotonic()
    while True:
        queue = json.loads(Path(args.queue).read_text())
        for entry in queue["jobs"]:
            if entry["stage"] not in submitted:
                pending.extend(command(entry["stage"], entry.get("freeze", ""), args, root))
                submitted.add(entry["stage"])
        while pending and len(running) < 4:
            name, argv = pending.pop(0)
            log_path = logs / (name + ".log")
            stream = log_path.open("xb")
            process = subprocess.Popen(argv, cwd=args.repository, stdout=stream, stderr=subprocess.STDOUT)
            running[name] = (process, stream, log_path, time.monotonic())
        for name, (process, stream, log_path, launched) in list(running.items()):
            code = process.poll()
            if code is not None:
                stream.close()
                results[name] = {"exit_code": code, "wall_seconds": time.monotonic() - launched,
                                 "last_line": last_line(log_path)}
                del running[name]
                print(json.dumps({"job_finished": name, **results[name]}), flush=True)
        if time.monotonic() - last_export > 10:
            export_summaries(root, export)
            status = {"running": {name: {"pid": item[0].pid, "last_line": last_line(item[2])} for name, item in running.items()},
                      "pending": [x[0] for x in pending], "results": results,
                      "raw_bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file()),
                      "elapsed_seconds": time.monotonic() - started}
            atomic_json(export / "PROGRESS.json", status)
            print(json.dumps(status), flush=True)
            last_export = time.monotonic()
        if queue.get("finalize") and not running and not pending:
            analyze(root, protocol, export)
            export_summaries(root, export)
            record = archive_and_restore(root, mount, Path(args.backup), export)
            atomic_json(export / "EXECUTION.json", {"jobs": results, "archive": record,
                        "elapsed_seconds": time.monotonic() - started})
            print(json.dumps({"finalized": True, "archive": record}), flush=True)
            break
        if time.monotonic() - started > 12 * 3600:
            raise RuntimeError("Outer registered execution window exhausted")
        time.sleep(1)


if __name__ == "__main__":
    main()
