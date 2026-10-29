"""Prepare fixed CPU dependencies and only the registered native training inputs."""

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from common import BASELINE, HERE, ROOT, identity, load, raw_identity, require, save


def restore_legacy(output, pins):
    source = ROOT / pins["repository_directory"]
    raw = (source / "ARCHIVE.json").read_bytes()
    require(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == pins["index_git_blob"],
            "legacy archive index differs from the fixed baseline Git blob")
    index = load(source / "ARCHIVE.json", 256_000)
    require(pins["commit"] == BASELINE and index["archive"] == pins["archive"], "legacy archive pin differs")
    require(len(index["parts"]) == 10 and len({p["path"] for p in index["parts"]}) == 10, "invalid legacy part inventory")
    chunks = []
    for part in index["parts"]:
        require(re.fullmatch(r"raw-evidence\.tar\.xz\.part-00[0-9]", part["path"]), "unsafe legacy part path")
        path = source / part["path"]
        require(not path.is_symlink() and 0 < path.stat().st_size <= 400_000, "unsafe legacy part")
        require(identity(path) == {key: part[key] for key in ("bytes", "sha256")}, "legacy part digest differs")
        chunks.append(path.read_bytes())
    compressed = b"".join(chunks)
    require(raw_identity(compressed) == pins["archive"], "legacy archive digest differs")
    expected, found, seen = pins["selected_files"], {}, set()
    require(len(expected) == 14 and all(index["files"].get(name) == value for name, value in expected.items()),
            "legacy selected input pins differ from the archive")
    destination = output / "legacy"
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(compressed), mode="r|xz") as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            require(member.isfile() and member.name not in seen and not relative.is_absolute()
                    and ".." not in relative.parts and str(relative) == member.name and len(seen) < 2048,
                    "unexpected legacy archive member metadata")
            seen.add(member.name)
            if member.name not in expected:
                continue
            require(member.size == expected[member.name]["bytes"], "legacy selected member size differs")
            data = archive.extractfile(member).read(member.size + 1)
            require(raw_identity(data) == expected[member.name], "legacy selected member digest differs")
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(data)
            found[member.name] = expected[member.name]
    require(found == expected, "incomplete legacy selected input restoration")
    save(output / "LEGACY_RESTORATION.json", {"schema": "hepta.memory.v10.ci-legacy-inputs.v1",
         "baseline_commit": BASELINE, "index_git_blob": pins["index_git_blob"], "archive": pins["archive"],
         "selected_files": found, "archive_stream_decompressed": True,
         "old_holdout_members_extracted": False, "old_holdout_json_loaded": False, "fitting_performed": False})
    return destination


def download_encoder(runtime, output, pins):
    destination = runtime / "encoder"
    destination.mkdir(exist_ok=True)
    rows = []
    for name, expected in pins["files"].items():
        path = destination / name
        require(not any(p.is_symlink() for p in (path, *path.parents)), "symlinked encoder cache")
        started = time.monotonic_ns()
        row = {"path": name, "expected": expected, "cache_hit": path.exists()}
        rows.append(row)
        save(output / "ENCODER_DOWNLOAD.json", {"pins": pins, "files": rows, "completed": False})
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".download")
            url = "https://huggingface.co/" + pins["repo"] + "/resolve/" + pins["revision"] + "/" + quote(name)
            count, digest = 0, hashlib.sha256()
            try:
                with urlopen(Request(url, headers={"User-Agent": "hepta-memory-v10-ci"}), timeout=60) as response:
                    require(response.status == 200, "encoder download did not return HTTP 200")
                    with temporary.open("xb") as handle:
                        while data := response.read(262_144):
                            count += len(data)
                            require(count <= expected["bytes"], "encoder download exceeds pinned byte bound")
                            require(time.monotonic_ns() - started < 600_000_000_000, "encoder download exceeded ten minutes")
                            digest.update(data)
                            handle.write(data)
            except (HTTPError, URLError, OSError):
                raise ValueError("encoder asset download failed: " + name) from None
            require({"bytes": count, "sha256": digest.hexdigest()} == expected, "downloaded encoder digest differs")
            temporary.rename(path)
        require(identity(path) == expected, "cached encoder bytes differ from fixed pin")
        row.update(wall_ns=time.monotonic_ns() - started, observed=identity(path), verified=True)
        print("Verified encoder asset: " + name, flush=True)
    save(output / "ENCODER_DOWNLOAD.json", {"pins": pins, "files": rows, "completed": True,
         "encoder_executed_by_preparation": False, "authorization_headers_used": False})
    return destination


def prepare(runner, runtime):
    require(sys.version_info[:2] == (3, 12), "Python 3.12 is required")
    require(runtime.is_absolute() and not any(p.is_symlink() for p in (runtime, *runtime.parents)),
            "absolute nonsymlink runtime directory required")
    runtime.mkdir(exist_ok=True)
    output = runner.output / "inputs"
    output.mkdir()
    pins = load(HERE / "INPUT_PINS.json", 65_536)
    save(output / "INPUT_PINS.json", pins)
    venv = runtime / "venv"
    require(not venv.exists(), "fresh isolated Python environment required")
    runner.execute("create-venv", [sys.executable, "-I", "-m", "venv", str(venv)])
    python = str(venv / "bin/python")
    pip = [python, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check"]
    runner.execute("pin-pip", [*pip, "install", "--no-deps", "--no-cache-dir", "--index-url",
                              "https://pypi.org/simple", "pip==25.0.1"])
    runner.execute("install-runtime", [*pip, "install", "--no-deps", "--no-cache-dir", "--index-url",
                   "https://pypi.org/simple", "-r", str(HERE / "runtime-requirements.txt")])
    runner.execute("install-cpu-torch", [*pip, "install", "--no-deps", "--no-cache-dir", "--index-url",
                                        "https://download.pytorch.org/whl/cpu", "torch==2.8.0+cpu"])
    runner.execute("dependency-consistency", [*pip, "check"])
    runner.execute("pip-freeze", [*pip, "freeze", "--all"])
    diagnostic = """import importlib.metadata as m,json,pathlib,sys
import numpy,onnxruntime,tokenizers,torch
source,output=map(pathlib.Path,sys.argv[1:])
pins=[row.split('==') for row in source.read_text().splitlines() if row and not row.startswith('#')]
pins += [('torch','2.8.0+cpu'),('pip','25.0.1')]
assert all(m.version(name)==version for name,version in pins), 'installed dependency pin differs'
assert torch.version.cuda is None and str(torch.__version__)=='2.8.0+cpu', 'CPU Torch required'
output.write_text(json.dumps({'versions':dict(pins),'python':sys.version,'executable':sys.executable,
 'torch_cuda':torch.version.cuda,'numpy_config':str(numpy.show_config(mode='dicts')),
 'full_environment_dependency_freeze_used':False},indent=2)+'\\n')
"""
    runner.execute("validate-dependencies", [python, "-I", "-B", "-c", diagnostic,
                   str(HERE / "runtime-requirements.txt"), str(output / "DEPENDENCIES.json")])
    legacy = restore_legacy(output, pins["legacy"])
    encoder = download_encoder(runtime, output, pins["encoder"])
    shutil.copyfile(HERE / "runtime-requirements.txt", output / "runtime-requirements.txt")
    result = {"python": python, "legacy": str(legacy), "encoder": str(encoder),
              "research": str(ROOT / "qualification/memory-cell-v10")}
    save(output / "PREPARATION.json", {"schema": "hepta.memory.v10.ci-preparation.v1", "paths": result,
         "passed": True, "fitting_performed": False, "old_holdout_run": False})
    return result
