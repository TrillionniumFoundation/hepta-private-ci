"""Recover pinned original scientific packages from local wheels into a new venv."""

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())


def main(root):
    started = time.monotonic()
    request = json.loads((root / "REQUEST.json").read_text())
    resource.setrlimit(resource.RLIMIT_AS, (request["address_space_bytes"],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (request["whole_seconds"],) * 2)
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    require(sha(Path(sys.executable).resolve()) == request["python_sha256"], "original interpreter digest")
    records_root = Path(request["original_records"])
    frozen_records = {}
    for package, expected in request["records"].items():
        path = records_root / (package + "-installed-RECORD.txt")
        require(sha(path) == expected, "original archived RECORD: " + package)
        frozen_records[package] = list(csv.reader(io.StringIO(path.read_text())))
    venv = root / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=30)
    site = venv / "lib/python3.12/site-packages"
    wheel_roots = [Path(path) for path in request["wheel_roots"]]
    wheels = []
    for pattern in request["wheel_patterns"]:
        matches = [path for directory in wheel_roots for path in directory.glob(pattern)]
        require(len(matches) == 1, "unique original cached wheel: " + pattern)
        wheels.append(matches[0])
    wheel_records = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)} for path in wheels]
    save(root / "WHEELS_BEFORE.json", wheel_records)
    argv = [request["pip_interpreter"], "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile",
            "--no-cache-dir", "--target", str(site), *map(str, wheels)]
    with (root / "install.stdout").open("x") as stdout, (root / "install.stderr").open("x") as stderr:
        completed = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=420)
    save(root / "INSTALL.json", {"argv": argv, "returncode": completed.returncode})
    require(completed.returncode == 0, "offline original-wheel installation")
    copies = []
    for source_site, packages in request["copy_distribution_sources"].items():
        source_site = Path(source_site)
        distributions = {dist.metadata["Name"].lower().replace("_", "-"): dist
                         for dist in importlib.metadata.distributions(path=[str(source_site)])}
        for name in packages:
            require(name in distributions, "existing dependency metadata: " + name)
            dist = distributions[name]
            files = []
            for item in dist.files:
                relative = Path(str(item))
                if relative.is_absolute() or ".." in relative.parts or "__pycache__" in relative.parts:
                    continue
                source, target = source_site / relative, site / relative
                require(source.is_file() and not source.is_symlink(), "regular dependency source: " + str(source))
                require(not target.exists(), "no overwrite during dependency copy: " + str(target))
                target.parent.mkdir(parents=True, exist_ok=True)
                before = sha(source)
                shutil.copyfile(source, target)
                require(sha(target) == before == sha(source), "stable copied dependency")
                files.append({"path": str(relative), "bytes": target.stat().st_size, "sha256": before})
            copies.append({"name": name, "version": dist.version, "original_site": str(source_site), "files": files})
    save(root / "COPIED_DEPENDENCIES.json", copies)
    verification = {}
    for package, rows in frozen_records.items():
        checked, absent, generated, differences = 0, [], [], []
        for name, digest, size in rows:
            path = Path(name)
            if not digest or "__pycache__" in path.parts or path.is_absolute() or ".." in path.parts or any(p.endswith(".dist-info") for p in path.parts):
                generated.append(name); continue
            target = site / path
            if not target.is_file():
                absent.append(name); continue
            require(digest.startswith("sha256="), "original RECORD SHA256")
            expected = base64.urlsafe_b64decode(digest.split("=", 1)[1] + "==").hex()
            actual = sha(target)
            if actual != expected or target.stat().st_size != int(size):
                differences.append({"path": name, "expected": expected, "actual": actual})
            checked += 1
        verification[package] = {"payload_files_checked": checked, "absent": absent, "differences": differences,
                                 "generated_installation_metadata_or_unhashed_entries": generated}
    save(root / "ORIGINAL_PAYLOAD_VERIFICATION.json", verification)
    require(all(v["payload_files_checked"] > 0 and not v["absent"] and not v["differences"] for v in verification.values()), "all archived original scientific payload bytes")
    probe = """import hashlib,importlib.metadata,json,pathlib,platform,sys,torch,numpy,einops,mpmath,ncps,spikingjelly
from ncps.torch import CfC
from spikingjelly.activation_based import neuron,functional,surrogate
expected=json.loads(sys.argv[1])
actual={name:importlib.metadata.version(name) for name in expected}
assert actual==expected,(actual,expected)
assert torch.__version__=='2.8.0+cu128'
print(json.dumps({'packages':actual,'torch_version':torch.__version__,'torch_git':torch.version.git_version,'python':platform.python_version(),'executable':sys.executable,'resolved_python_sha256':hashlib.sha256(pathlib.Path(sys.executable).resolve().read_bytes()).hexdigest(),'torch_origin':torch.__file__,'numpy_origin':numpy.__file__,'sys_path':sys.path,'E_access':False,'model_construction_forward_backward_optimizer_calls':0},sort_keys=True))
"""
    with (root / "imports.stdout").open("x") as stdout, (root / "imports.stderr").open("x") as stderr:
        imported = subprocess.run([str(venv / "bin/python"), "-B", "-c", probe, json.dumps(request["versions"])],
                                  stdout=stdout, stderr=stderr, timeout=60)
    require(imported.returncode == 0, "restored original package imports")
    runtime = json.loads((root / "imports.stdout").read_text())
    require(runtime["resolved_python_sha256"] == request["python_sha256"], "restored exact Python executable")
    require(Path(runtime["torch_origin"]).is_relative_to(site), "original cu128 from isolated venv")
    require(not any("cold-resume" in path for path in runtime["sys_path"]), "no CPU runtime fallback on sys.path")
    require(wheel_records == [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)} for path in wheels], "cached wheels unchanged")
    save(root / "RESULT.json", {"schema": "original-C2-runtime-restoration-v1", "status": "ORIGINAL_SCIENTIFIC_PAYLOAD_RESTORED",
                               "runtime": runtime, "wall_seconds": time.monotonic() - started,
                               "cpu_self_seconds": time.process_time(), "peak_self_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                               "children_cpu_seconds": resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
                               "whole_seconds": request["whole_seconds"], "E_access": False, "model_work": 0,
                               "exact_archived_payload_checks": {p: v["payload_files_checked"] for p, v in verification.items()},
                               "old_environment_modified": False,
                               "scope": "Six archived scientific packages' hashed non-generated payload bytes plus exact Python binary. New installation metadata/path and separately pinned copied dependencies are explicit; this is not a claim to reproduce unrecorded historical system libraries."})
    print((root / "RESULT.json").read_text(), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
