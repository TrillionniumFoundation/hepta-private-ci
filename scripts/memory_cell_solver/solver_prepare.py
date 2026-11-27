"""Qualify task runtimes, freeze source-only inputs, and stage pinned weights."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

from fixture_inputs import restore_inputs
from solver_common import file_identity, read_pinned, runtime, save
from solver_tasks import EVALUATION, describe, retrieval_corpus, runtime_profile
from retrieval_index import build, Retriever


HERE = Path(__file__).resolve().parent


def source_inventory(repo):
    paths = []
    for name in ("memory_cell_solver", "memory_cell_evaluation"):
        paths.extend(
            p
            for p in (repo / "scripts" / name).iterdir()
            if p.is_file() and p.suffix in (".py", ".json", ".md")
        )
    paths.extend(
        repo / "scripts/memory_cell_budget" / name
        for name in ("retrieval_index.py", "budget_ledger.py")
    )
    paths.extend(
        repo / "scripts/memory_cell_network" / name
        for name in ("model_child.py", "model_process.py")
    )
    return {str(p.relative_to(repo)): file_identity(p) for p in sorted(paths)}


def qualify(task, fixture, gold, profile, output):
    command = [
        sys.executable,
        "-B",
        str(
            EVALUATION
            / (
                "test_ruff_executor.py"
                if task == "ruff"
                else "test_codec_executor_v2.py"
            )
        ),
        "--fixture",
        str(fixture),
        "--known-fix",
        str(gold),
        "--output",
        str(output),
        "--runtime-profile",
        profile["path"],
        "--runtime-profile-sha256",
        profile["sha256"],
    ]
    for name, path in profile["tools"].items():
        command.extend(["--" + name, path])
    parent = output.parent
    started = time.monotonic()
    with (
        (parent / "qualification.stdout").open("xb") as stdout,
        (parent / "qualification.stderr").open("xb") as stderr,
    ):
        result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=600)
    save(
        parent / "qualification-command.json",
        {
            "argv": command,
            "returncode": result.returncode,
            "wall_seconds": time.monotonic() - started,
            "runtime_profile_sha256": profile["sha256"],
        },
    )
    receipt = json.loads((output / "qualification.json").read_text())
    if (
        result.returncode
        or not receipt["accepted"]
        or receipt["failures"]
        or receipt["errors"]
        or receipt["skips"]
    ):
        raise ValueError("task runtime qualification failed: " + task)
    return {
        "path": str(output / "qualification.json"),
        **file_identity(output / "qualification.json"),
    }


def prepare(repo, output, expected_head):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    if output.is_relative_to(repo):
        raise ValueError("all run outputs must remain outside the source tree")
    output.mkdir(exist_ok=False)
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain=v1"], cwd=repo, text=True
    )
    if actual != expected_head or dirty:
        raise ValueError("exact clean committed source required")
    before = source_inventory(repo)
    recipe = json.loads((HERE / "recipe.json").read_text())
    model = read_pinned(HERE / "model_manifest.json", recipe["model_manifest_sha256"])
    save(output / "runtime-before.json", runtime())
    save(output / "source-before.json", before)
    save(output / "model-manifest.json", model)
    tools = {
        "python": sys.executable,
        **{
            name: shutil.which(name)
            for name in ("ruff", "ffmpeg", "ffprobe", "openssl")
        },
    }
    if not all(tools.values()):
        raise ValueError("required original-gate tool unavailable")
    tasks = {}
    retrieval_files = {}
    for task in recipe["task_order"]:
        directory = output / "tasks" / task
        fixture, gold = restore_inputs(repo, task, directory, tools["ruff"])
        profile = runtime_profile(task, tools, directory / "runtime-profile.json")
        qualification = qualify(
            task, fixture, gold, profile, directory / "qualification"
        )
        task_input, original = describe(task, fixture)
        save(directory / "task-input.json", {"task": task_input, "files": original})
        tasks[task] = {
            "fixture": str(fixture),
            "runtime_profile": profile,
            "qualification": qualification,
            "qualification_command": {
                "path": str(directory / "qualification-command.json"),
                **file_identity(directory / "qualification-command.json"),
            },
            "input": {
                "path": str(directory / "task-input.json"),
                **file_identity(directory / "task-input.json"),
            },
        }
    docs = retrieval_corpus(output / "corpus.json")
    index = output / "retrieval.sqlite"
    index_receipt = build(index, docs, train_until="2026-10-25T12:00:00Z")
    save(output / "retrieval-build.json", index_receipt)
    retriever = Retriever(index)
    for task in recipe["task_order"]:
        description = describe(task, tasks[task]["fixture"])[0]
        result = retriever.query(
            {
                "task_id": task,
                "text": description["instruction"],
                "paths": description["allowed_paths"],
            }
        )
        chosen, used = [], 0
        for row in result["results"]:
            if len(chosen) >= recipe["retrieval"]["maximum_documents"]:
                break
            document = row["document"]
            count = len(document["text"].encode())
            if used + count > recipe["retrieval"]["maximum_utf8_bytes"]:
                continue
            chosen.append(document)
            used += count
        for arm in recipe["arms"]:
            path = output / "tasks" / task / (arm + "-retrieval.json")
            save(
                path,
                {
                    "documents": chosen if arm == "retrieval" else [],
                    "retrieval_receipt": result if arm == "retrieval" else None,
                },
            )
            retrieval_files[task + ":" + arm] = {
                "path": str(path),
                **file_identity(path),
            }
    retriever.close()
    if source_inventory(repo) != before:
        raise ValueError("source changed during preparation")
    frozen = {
        **recipe,
        "source_head": actual,
        "source_files": before,
        "tasks": tasks,
        "corpus": file_identity(output / "corpus.json"),
        "retrieval_files": retrieval_files,
        "staged_model_manifest": file_identity(output / "model-manifest.json"),
        "retrieval_index": file_identity(index),
        "registered_unix_ns": time.time_ns(),
        "registration_boundary": "after actual runtime qualification, before the first model load/query",
    }
    save(output / "protocol.json", frozen)
    save(
        output / "freeze.json",
        {
            "protocol": file_identity(output / "protocol.json"),
            "source_head": actual,
            "model_calls_so_far": 0,
            "training_updates": 0,
        },
    )
    return file_identity(output / "protocol.json")["sha256"]


def acquire(manifest_path, expected, model_directory, receipt):
    manifest = read_pinned(manifest_path, expected)
    directory = Path(model_directory)
    directory.mkdir(exist_ok=False)
    destination = directory / manifest["filename"]
    url = (
        "https://huggingface.co/"
        + manifest["repository"]
        + "/resolve/"
        + manifest["revision"]
        + "/"
        + manifest["filename"]
    )
    digest, count, started = hashlib.sha256(), 0, time.monotonic()
    with (
        urllib.request.urlopen(url, timeout=90) as stream,
        destination.open("xb") as target,
    ):
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > manifest["file"]["bytes"] or time.monotonic() - started > 900:
                raise ValueError("model acquisition exceeded fixed bytes/time")
            digest.update(chunk)
            target.write(chunk)
    identity = {"bytes": count, "sha256": digest.hexdigest()}
    if identity != manifest["file"]:
        raise ValueError("downloaded GGUF differs from pinned source")
    destination.chmod(0o444)
    save(
        receipt,
        {
            "url": url,
            "identity": identity,
            "wall_seconds": time.monotonic() - started,
            "model_calls": 0,
            "training_updates": 0,
        },
    )
    return str(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("prepare")
    for name in ("repo", "output", "expected-head"):
        stage.add_argument("--" + name, required=True)
    stage = commands.add_parser("acquire")
    for name in ("manifest-path", "expected", "model-directory", "receipt"):
        stage.add_argument("--" + name, required=True)
    arguments = vars(parser.parse_args())
    command = arguments.pop("command")
    print(prepare(**arguments) if command == "prepare" else acquire(**arguments))
