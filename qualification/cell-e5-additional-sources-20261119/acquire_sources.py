"""Retain exact upstream snapshots and isolated replay dependencies for original E5."""

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import subprocess
import sys
import tarfile
import time
import urllib.request


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def fetch_snapshot(root, entry, variant):
    began = time.perf_counter()
    revision = entry[variant + "_commit"]
    tree = json.loads((root / "upstream-api" / f"{entry['index']}-{variant}-tree.json").read_bytes())
    assert not tree["truncated"]
    expected = {row["path"]: row for row in tree["tree"] if row["type"] == "blob"}
    assert all(row["mode"] in ("100644", "100755") for row in expected.values())
    assert not any(row["type"] == "commit" for row in tree["tree"]), "submodule requires separate provenance"
    url = f"https://codeload.github.com/{entry['project_id']}/tar.gz/{revision}"
    request = urllib.request.Request(url, headers={"User-Agent": "hepta-e5-source-intake/1"})
    archive = root / "archives" / f"{entry['index']}-{variant}.tar.gz"
    archive.parent.mkdir(exist_ok=True)
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read(32 * 1024 * 1024 + 1)
    assert len(raw) <= 32 * 1024 * 1024, "source archive acquisition bound"
    with archive.open("xb") as stream:
        stream.write(raw)
    folder = root / "repositories" / str(entry["index"]) / variant
    folder.mkdir(parents=True, exist_ok=False)
    retained = []
    with tarfile.open(archive) as source:
        for member in source:
            if member.isdir():
                continue
            assert member.isfile(), "non-regular source archive member"
            parts = PurePosixPath(member.name).parts
            assert len(parts) >= 2 and ".." not in parts and not member.name.startswith("/")
            relative = "/".join(parts[1:])
            item = expected.pop(relative)
            data = source.extractfile(member).read()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            assert len(data) == item["size"] and blob == item["sha"], relative
            destination = folder / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
            destination.chmod(int(item["mode"][-3:], 8))
            retained.append({"path": relative, "bytes": len(data), "git_blob_sha1": blob, "sha256": digest(data), "mode": item["mode"]})
    assert not expected, "archive omitted tracked source files"
    record = {"project_id": entry["project_id"], "variant": variant, "revision": revision, "url": url, "archive_sha256": digest(raw), "archive_bytes": len(raw), "files": retained, "wall_seconds": time.perf_counter() - began}
    write(root / "snapshots" / f"{entry['index']}-{variant}.json", record)
    print(json.dumps({key: record[key] for key in ("project_id", "variant", "revision", "archive_bytes", "wall_seconds")}), flush=True)
    return record


def setup(root):
    names = ["pytest", "pytest-timeout", "pytest-asyncio", "freezegun", "mock", "regex", "more-itertools", "requests", "responses", "attrs", "jsonschema-specifications", "referencing", "rpds-py"]
    environment = root / "environment"
    environment.mkdir(exist_ok=False)
    requirements = []
    for name in names:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
        (environment / f"{name}.pypi.json").write_bytes(raw)
        assert len(raw) <= 32 * 1024 * 1024, "dependency metadata exceeds acquisition limit"
        requirements.append(name + "==" + json.loads(raw)["info"]["version"])
    write(environment / "DIRECT_REQUIREMENTS.json", requirements)
    python = str(root / "venv/bin/python")
    commands = [[sys.executable, "-m", "venv", str(root / "venv")], [python, "-m", "pip", "--isolated", "--disable-pip-version-check", "--cache-dir", str(root / "pip-cache"), "download", "--only-binary=:all:", "--dest", str(root / "wheels"), *requirements], [python, "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--no-index", "--find-links", str(root / "wheels"), *requirements]]
    stages = []
    for index, argv in enumerate(commands):
        then = time.perf_counter()
        with (environment / f"{index}.stdout").open("xb") as out, (environment / f"{index}.stderr").open("xb") as err:
            result = subprocess.run(argv, stdout=out, stderr=err, timeout=240, check=False)
        row = {"argv": argv, "exit_code": result.returncode, "wall_seconds": time.perf_counter() - then}
        write(environment / f"{index}.EXIT.json", row)
        stages.append(row)
        assert result.returncode == 0, row
    freeze = subprocess.run([python, "-m", "pip", "freeze", "--all"], capture_output=True, check=True, timeout=30).stdout
    (environment / "pip-freeze.txt").write_bytes(freeze)
    write(environment / "WHEELS.json", [{"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path.read_bytes())} for path in sorted((root / "wheels").iterdir())])
    return stages


def main(root):
    started = time.perf_counter()
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    plan = json.loads((root / "ACQUISITION_PLAN.json").read_bytes())
    write(root / "ACQUISITION_STARTED.json", {"pid": os.getpid(), "started_at_ns": time.time_ns(), "plan_sha256": digest((root / "ACQUISITION_PLAN.json").read_bytes()), "runner_sha256": digest(Path(__file__).read_bytes()), "new_model_calls": 0, "new_training_updates": 0})
    outcomes = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {(entry["index"], variant): pool.submit(fetch_snapshot, root, entry, variant) for entry in plan["projects"] for variant in ("before", "after")}
            for identity, future in futures.items():
                try:
                    result = future.result()
                    outcomes.append({"identity": identity, "status": "ACQUIRED", "files": len(result["files"]), "archive_sha256": result["archive_sha256"]})
                except Exception as error:
                    outcomes.append({"identity": identity, "status": "FAILED", "error": repr(error)})
        write(root / "SNAPSHOT_ACQUISITION.json", outcomes)
        assert all(row["status"] == "ACQUIRED" for row in outcomes)
        stages = setup(root)
        status, error = "ACQUIRED", None
    except Exception as failure:
        status, error, stages = "FAILED", repr(failure), []
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"status": status, "error": error, "snapshots": outcomes, "setup_stages": stages, "new_model_calls": 0, "new_training_updates": 0, "new_native_children": 0, "new_authenticated_users": 0, "source_growth_qualified": False, "wall_seconds": time.perf_counter() - started, "completed_child_cpu_seconds": after.ru_utime + after.ru_stime - cpu.ru_utime - cpu.ru_stime, "full_system_cost_known": False}
    write(root / "ACQUISITION.json", result)
    print(json.dumps(result), flush=True)
    return 0 if status == "ACQUIRED" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    raise SystemExit(main(parser.parse_args().root.resolve(strict=True)))
