"""Acquire exact B3 upstream blobs and a separate, byte-pinned replay environment."""

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import signal
import subprocess
import time
import urllib.request


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path = Path(path)
    raw = value if isinstance(value, bytes) else (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)


def safe_path(value):
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or str(parsed) != value:
        raise ValueError("noncanonical material path")
    return value


def run_command(command, output, seconds=240):
    output.mkdir(exist_ok=False)
    begin = time.perf_counter()
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    with (output / "stdout.txt").open("xb") as out:
        with (output / "stderr.txt").open("xb") as err:
            child = subprocess.Popen(
                command, stdout=out, stderr=err, env=env, start_new_session=True
            )
            write(output / "STARTED.json", {
                "argv": command, "pid": child.pid, "started_at_ns": time.time_ns(),
                "timeout_seconds": seconds, "automatic_retry": False,
            })
            try:
                result = child.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    result = child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    result = child.wait(timeout=10)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {
        "argv": command, "exit_code": result, "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - begin,
        "child_user_cpu_seconds": after.ru_utime - cpu.ru_utime,
        "child_system_cpu_seconds": after.ru_stime - cpu.ru_stime,
        "stdout_sha256": sha((output / "stdout.txt").read_bytes()),
        "stderr_sha256": sha((output / "stderr.txt").read_bytes()),
    }
    write(output / "RESULT.json", receipt)
    return receipt


def main(args):
    payload_raw = args.payload.read_bytes()
    payload = json.loads(payload_raw)
    inputs = args.payload.parent
    selection_raw = (inputs / "SOURCE_SELECTION.json").read_bytes()
    manifest_raw = (inputs / "ACQUISITION_MANIFEST.json").read_bytes()
    source_raw = Path(__file__).read_bytes()
    if sha(selection_raw) != payload["selection_sha256"]:
        raise ValueError("prospective selection changed")
    if sha(manifest_raw) != payload["manifest_sha256"]:
        raise ValueError("prospective Git inventory changed")
    if sha(source_raw) != payload["acquire_sha256"]:
        raise ValueError("published acquisition source changed")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise ValueError("exact published source commit required")
    root = args.root
    root.mkdir(exist_ok=False)
    started = time.perf_counter()
    initial_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    records, stages = [], []
    status = {
        "schema": "hepta.b3.original_acquisition.v1",
        "source_commit": args.source_commit,
        "acquire_sha256": sha(source_raw),
        "selection_sha256": sha(selection_raw),
        "prospective_git_inventory_sha256": sha(manifest_raw),
        "new_model_calls": 0, "new_training_updates": 0, "new_test_calls": 0,
        "authenticated_user_count": 0,
        "full_system_cost_known": False,
        "started_at_ns": time.time_ns(),
    }
    write(root / "SOURCE_DEPLOYMENT.json", status)
    write(root / "SOURCE_SELECTION.json", selection_raw)
    write(root / "ACQUISITION_MANIFEST.json", manifest_raw)
    try:
        sources = json.loads(manifest_raw)
        wanted = {}
        for entry in sources["sources"]:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", entry["project_id"]):
                raise ValueError("invalid pinned upstream repository")
            for item in entry["source_files"]:
                path = safe_path(item["path"])
                for variant in ("before", "after"):
                    revision = entry[variant + "_commit"]
                    if not re.fullmatch(r"[0-9a-f]{40}", revision):
                        raise ValueError("unpinned upstream commit")
                    expected = item[variant]
                    location = {
                        "project_id": entry["project_id"], "variant": variant,
                        "commit": revision, "path": path,
                        "url": "https://raw.githubusercontent.com/" +
                               entry["project_id"] + "/" + revision + "/" + path,
                    }
                    blob = expected["git_blob_sha1"]
                    record = wanted.setdefault(blob, {
                        "git_blob_sha1": blob, "bytes": expected["bytes"],
                        "locations": [],
                    })
                    if record["bytes"] != expected["bytes"]:
                        raise ValueError("inconsistent original Git object length")
                    record["locations"].append(location)
        blobs = root / "git-blobs"
        blobs.mkdir()
        calls = root / "acquisition-calls"
        calls.mkdir()

        def fetch(entry):
            begun = time.perf_counter()
            row = {**entry, "started_at_ns": time.time_ns(), "attempt": 1}
            url = entry["locations"][0]["url"]
            row["requested_url"] = url
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "hepta-b3-original-intake/1"}
                )
                with urllib.request.urlopen(request, timeout=40) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                    row["http_status"] = response.status
                row["received_bytes"] = len(raw)
                if len(raw) != entry["bytes"]:
                    raise ValueError("original byte length differs")
                git_blob = hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw
                ).hexdigest()
                if git_blob != entry["git_blob_sha1"]:
                    raise ValueError("original Git blob identity differs")
                raw.decode("utf-8")
                row["sha256"] = sha(raw)
                write(blobs / git_blob, raw)
                row["passed"] = True
            except BaseException as error:
                row.update(passed=False, error_type=type(error).__name__, error=str(error))
            row["wall_seconds"] = time.perf_counter() - begun
            write(calls / (entry["git_blob_sha1"] + ".json"), row)
            return row

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(fetch, wanted.values()))
        write(root / "BLOBS.json", records)
        if not all(row["passed"] for row in records):
            raise ValueError("one or more original Git blobs could not be verified")
        for entry in sources["sources"]:
            short = entry["project_id"].split("/")[-1]
            for variant in ("before", "after"):
                for item in entry["source_files"]:
                    raw = (blobs / item[variant]["git_blob_sha1"]).read_bytes()
                    target = root / "repositories" / short / variant / item["path"]
                    write(target, raw)
                    os.chmod(target, int(item["mode"][-3:], 8))
                    item[variant]["sha256"] = sha(raw)
            entry["license"]["verified_notices"] = [
                {"path": path, "sha256": sha(
                    (root / "repositories" / short / "after" / path).read_bytes()
                )}
                for path in entry["license"]["paths"]
            ]
        write(root / "SOURCES.json", sources)

        previous = Path(payload["existing_wheel_root"])
        previous_index = previous / "environment/WHEELS.json"
        index_raw = previous_index.read_bytes()
        if sha(index_raw) != payload["existing_wheel_index_sha256"]:
            raise ValueError("original isolated wheel inventory changed")
        wheel_index = json.loads(index_raw)
        environment = root / "environment"
        environment.mkdir()
        wheels = root / "wheels"
        wheels.mkdir()
        for name, expected in sorted(wheel_index.items()):
            safe_path(name)
            original = previous / "wheels" / name
            if original.is_symlink():
                raise ValueError("wheel source is a symlink")
            raw = original.read_bytes()
            if len(raw) != expected["bytes"] or sha(raw) != expected["sha256"]:
                raise ValueError("original wheel bytes changed")
            write(wheels / name, raw)
        write(environment / "WHEELS.json", index_raw)
        requirements = payload["direct_requirements"]
        write(environment / "DIRECT_REQUIREMENTS.json", requirements)
        owned = root / "owned-setup-1"
        owned.mkdir()
        commands = [
            ["/usr/bin/python3", "-m", "venv", str(root / "venv")],
            [str(root / "venv/bin/python"), "-m", "pip", "--isolated",
             "--disable-pip-version-check", "install", "--no-index",
             "--find-links", str(wheels), *requirements],
            [str(root / "venv/bin/python"), "-m", "pip", "freeze", "--all"],
        ]
        for index, command in enumerate(commands):
            stage = run_command(command, owned / str(index))
            stages.append(stage)
            if stage["exit_code"] != 0 or stage["timed_out"]:
                raise ValueError("isolated environment setup failed")
        write(environment / "pip-freeze.txt", (owned / "2/stdout.txt").read_bytes())
        if sha(Path(__file__).read_bytes()) != payload["acquire_sha256"]:
            raise ValueError("acquisition source changed during execution")
        status.update(
            status="ACQUIRED", passed=True, sources=len(sources["sources"]),
            distinct_git_blobs=len(records),
            downloaded_blob_bytes=sum(row["bytes"] for row in records),
            sources_sha256=sha((root / "SOURCES.json").read_bytes()),
            isolated_environment=True, existing_environment_modified=False,
            new_dependency_downloads=0,
        )
    except BaseException as error:
        status.update(
            status="ACQUISITION_FAILED", passed=False,
            error_type=type(error).__name__, error=str(error),
        )
    final_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    status.update(
        stages=stages, original_requests=len(records),
        successful_original_requests=sum(row.get("passed", False) for row in records),
        wall_seconds=time.perf_counter() - started,
        completed_child_cpu_seconds=(
            final_cpu.ru_utime + final_cpu.ru_stime -
            initial_cpu.ru_utime - initial_cpu.ru_stime
        ),
        cost_scope="Owner includes concurrent raw reads and nested setup; do not add nested wall windows.",
        gpu_energy_joules=None, network_energy_joules=None, monetary_cost=None,
        finished_at_ns=time.time_ns(),
    )
    write(root / "ACQUISITION.json", status)
    print(json.dumps({
        key: status.get(key) for key in (
            "status", "passed", "sources", "distinct_git_blobs",
            "downloaded_blob_bytes", "sources_sha256", "wall_seconds"
        )
    }, sort_keys=True), flush=True)
    return 0 if status["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    raise SystemExit(main(parser.parse_args()))
