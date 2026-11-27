"""Preserve every terminal continuation output without importing numerical code."""

import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import resource
import tarfile
import time


HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    require(path.is_file() and not path.is_symlink(), "regular exact input: " + str(path))
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "input changed while hashing: " + str(path))
    return {"bytes": after.st_size, "sha256": digest.hexdigest()}


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write(path, value):
    with path.open("xb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def main(native_status):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (300, 310))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    bindings = json.loads((HERE / "BINDINGS.json").read_text())
    native = json.loads(native_status.read_text())
    require(native.get("terminal_publication_confirmed") is True and native.get("output_complete") is True
            and native.get("state") in ("succeeded", "failed", "cancelled", "timed_out"),
            "authoritative finished native process and complete logs are required")
    launch = json.loads((HERE / "RUN_LAUNCH.json").read_text())
    require(native["job_id"] == launch["job"]["id"] and launch["job"]["idempotency_key"] == request["identity"],
            "unique actual separately identified continuation job")
    output = HERE / "RUN_OUTPUT"
    terminal = json.loads((output / "TERMINAL.json").read_text())
    require(terminal["identity"] == request["identity"] == freeze["identity"] == bindings["identity"],
            "unchanged new continuation identity")
    require(terminal["status"] not in ("RUNNING", "FINISHING")
            and set(terminal["fits"]) == {fit["name"] for fit in request["fits"]},
            "both actual controller dispositions are required")
    require(all(not Path("/proc", str(row["pid"])).exists() for row in terminal["fits"].values()
                if "pid" in row), "no live recorded child may be archived")

    members = {}

    def add(name, path, role, expected=None):
        path = Path(path)
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts and name not in members,
                "unique safe archive member")
        observed = identity(path)
        if expected is not None:
            require(observed["sha256"] == expected["sha256"]
                    and ("bytes" not in expected or observed["bytes"] == expected["bytes"]),
                    "unchanged bound original input: " + str(path))
        members[name] = {"source_path": str(path), "role": role, **observed}

    for name, expected in freeze["files"].items():
        add("source/" + name, HERE / name, "frozen_execution_source", {"sha256": expected})
    add("source/FREEZE.json", HERE / "FREEZE.json", "execution_freeze")
    if "source/archive_results.py" not in members:
        add("source/archive_results.py", Path(__file__), "postprocessing_only")
    add("native/NATIVE_TERMINAL.json", native_status, "authoritative_native_terminal")
    for name in ("RUN_LAUNCH.json", "NATIVE.stdout", "NATIVE.stderr"):
        add("native/" + name, HERE / name, "native_process_record")
    original_run_files = sorted(path.relative_to(output).as_posix() for path in output.rglob("*")
                                if path.is_file())
    for relative in original_run_files:
        add("run/" + relative, output / relative, "all_actual_output_without_selection")
    for path, expected in bindings["input_files"].items():
        add("inputs/" + Path(path).as_posix().lstrip("/"), path, "original_bound_evidence_input", expected)
    expectations_path = Path(request["cold_probe_root"]) / "SOURCE_EXPECTATIONS.json"
    expectations = json.loads(expectations_path.read_text())
    actual_source = Path(request["original_root"]) / request["source_relative"]
    for relative, expected in expectations["source_files"].items():
        path = actual_source / relative
        name = "inputs/" + path.as_posix().lstrip("/")
        if name not in members:
            add(name, path, "actual_original_numerical_source", {"sha256": expected})
    # Episode payloads remain externally bound by the complete INPUT_IDENTITIES
    # and dataset manifest. Archival does not open sealed confirmation data.
    plans = [json.loads((Path(request["original_root"]) / "campaign-v2" / fit["name"] / "plan.json").read_text())
             for fit in request["fits"]]
    for path in sorted({str(Path(plan["prepared"]) / "data-manifest.json") for plan in plans}):
        name = "inputs/" + path.lstrip("/")
        if name not in members:
            add(name, path, "dataset_manifest_only", {"sha256": request["manifest_sha256"]})
    total_bytes = sum(row["bytes"] for row in members.values())
    require(total_bytes < 1024**3, "unexpected total artifact bytes; preserve inputs and review archival budget")
    manifest = {"schema": "hcsn-c2-continuation-exact-tar-v1", "identity": request["identity"],
        "members": dict(sorted(members.items())), "all_run_output_files": original_run_files,
        "run_output_files": len(original_run_files), "uncompressed_member_bytes": total_bytes,
        "dataset_payload_scope": "No episode payload copied. Exact episode hashes remain in INPUT_IDENTITIES.json and the original data manifest.",
        "scope": "All actual update and epoch checkpoints, all generated output, frozen source, original bound inputs, actual v8 numerical source, and native process records.",
        "model_forward_calls": 0, "optimizer_calls": 0}
    manifest_bytes = json_bytes(manifest)
    archive = HERE / "c2-continuation-exact-artifact.tar.xz"
    with archive.open("xb") as raw:
        with lzma.LZMAFile(raw, "w", preset=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as stream:
                for name, record in sorted(members.items()):
                    info = tarfile.TarInfo(name)
                    info.size = record["bytes"]
                    info.mode = 0o644
                    with Path(record["source_path"]).open("rb") as source:
                        stream.addfile(info, source)
                info = tarfile.TarInfo("MANIFEST.json")
                info.size, info.mode = len(manifest_bytes), 0o644
                stream.addfile(info, io.BytesIO(manifest_bytes))
        raw.flush()
        os.fsync(raw.fileno())
    observed_names = []
    with tarfile.open(archive, "r|xz") as source:
        for item in source:
            require(item.isfile() and item.name not in observed_names, "regular unique tar member")
            observed_names.append(item.name)
            contents = source.extractfile(item)
            digest, size = hashlib.sha256(), 0
            for block in iter(lambda: contents.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
            expected = ({"bytes": len(manifest_bytes), "sha256": hashlib.sha256(manifest_bytes).hexdigest()}
                        if item.name == "MANIFEST.json" else members[item.name])
            require(size == expected["bytes"] and digest.hexdigest() == expected["sha256"],
                    "complete lossless archive roundtrip: " + item.name)
    require(set(observed_names) == set(members) | {"MANIFEST.json"}, "complete archive membership")
    require(sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
            == original_run_files, "output membership changed during archival")
    for record in members.values():
        require(identity(Path(record["source_path"])) == {key: record[key] for key in ("bytes", "sha256")},
                "exact original file changed during archival")
    receipt = {"schema": "hcsn-c2-continuation-archive-receipt-v1", "archive": str(archive),
        **identity(archive), "members": len(members) + 1, "uncompressed_member_bytes": total_bytes,
        "manifest_bytes": len(manifest_bytes), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "run_output_files": len(original_run_files), "all_members_roundtrip_verified": True,
        "wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time(),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "resource_scope": "Separate one-thread, 2 GiB address-space, 300 CPU-second postprocessing; no numerical calls or added training budget.",
        "model_forward_calls": 0, "optimizer_calls": 0, "scientific_admission": "HOLD",
        "original_controller_terminal": "UNKNOWN", "full_six_fit_replay": False}
    write(HERE / "ARTIFACT.json", receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-status", type=Path, default=HERE / "NATIVE_TERMINAL.json")
    main(parser.parse_args().native_status)
