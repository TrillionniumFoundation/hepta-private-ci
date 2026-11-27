"""Rebind frozen task inputs and qualification before loading any model."""

import json
from pathlib import Path

from edit_protocol import sha, unique
from solver_common import file_identity, read_pinned
from solver_prepare import source_inventory
from solver_tasks import EVALUATION, REPO, describe, task_contract
from runtime_profile import load_runtime


def document(identity):
    if set(identity) != {"path", "bytes", "sha256"}:
        raise ValueError("closed pinned document identity required")
    path = Path(identity["path"])
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < identity["bytes"] <= 8 * 1024 * 1024
    ):
        raise ValueError("bounded regular document required")
    with path.open("rb") as stream:
        raw = stream.read(identity["bytes"] + 1)
    if len(raw) != identity["bytes"] or sha(raw) != identity["sha256"]:
        raise ValueError("pinned document bytes changed")
    return json.loads(raw, object_pairs_hook=unique)


def exact_fixture(root, files):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("regular fixture directory required")
    observed = {}
    for path in root.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("fixture symlink or path escape")
        if path.is_file():
            observed[str(path.relative_to(root))] = file_identity(path)
        elif not path.is_dir():
            raise ValueError("nonregular fixture entry")
    if observed != files:
        raise ValueError("fixture file set or bytes changed before model admission")


def verify_request(request, protocol):
    required = {
        "output",
        "protocol",
        "protocol_sha256",
        "model_manifest",
        "model_manifest_sha256",
        "model",
        "arm",
        "task",
        "fixture",
        "runtime_profile",
        "retrieval",
        "retrieval_sha256",
    }
    if (
        set(request) != required
        or request["task"] not in protocol["task_order"]
        or request["arm"] not in protocol["arms"]
    ):
        raise ValueError("unregistered controller request, task or arm")
    task = protocol["tasks"][request["task"]]
    retrieval = protocol["retrieval_files"][request["task"] + ":" + request["arm"]]
    if (
        request["fixture"] != task["fixture"]
        or request["runtime_profile"] != task["runtime_profile"]
        or request["retrieval"] != retrieval["path"]
        or request["retrieval_sha256"] != retrieval["sha256"]
        or request["model_manifest_sha256"]
        != protocol["staged_model_manifest"]["sha256"]
    ):
        raise ValueError("request differs from frozen task/runtime/model/retrieval")
    if source_inventory(REPO) != protocol["source_files"]:
        raise ValueError("solver/executor source changed after freeze")
    spec, contract_sha = task_contract(request["task"])
    exact_fixture(request["fixture"], spec["files"])
    frozen_input = document(task["input"])
    expected_task, expected_files = describe(request["task"], request["fixture"])
    if frozen_input != {"task": expected_task, "files": expected_files}:
        raise ValueError("frozen model input differs from original allowed source")
    profile = task["runtime_profile"]
    if set(profile) != {"path", "sha256", "tools"}:
        raise ValueError("runtime controller profile shape")
    runtime = load_runtime(spec, contract_sha, profile["path"], profile["sha256"])
    if set(profile["tools"]) != set(runtime["tools"]) or any(
        file_identity(path) != runtime["tools"][name]
        for name, path in profile["tools"].items()
    ):
        raise ValueError("runtime executable changed before model admission")
    qualified = document(task["qualification"])
    command = document(task["qualification_command"])
    if (
        qualified.get("accepted") is not True
        or qualified.get("tests_run") != {"ruff": 9, "codec": 6}[request["task"]]
        or any(qualified.get(key) != 0 for key in ("failures", "errors", "skips"))
        or command.get("returncode") != 0
        or command.get("runtime_profile_sha256") != profile["sha256"]
    ):
        raise ValueError("matching runtime qualification did not succeed")
    if request["task"] == "ruff":
        same_profile = qualified.get("runtime_profile_sha256") == profile["sha256"]
    else:
        same_profile = (
            qualified.get("contract_sha256") == contract_sha
            and qualified.get("runtime") == runtime
        )
    if not same_profile:
        raise ValueError("qualification receipt belongs to another runtime/task")
    argv = command.get("argv", [])
    script = EVALUATION / (
        "test_ruff_executor.py"
        if request["task"] == "ruff"
        else "test_codec_executor_v2.py"
    )
    if (
        len(argv) < 3
        or Path(argv[0]).resolve() != Path(profile["tools"]["python"]).resolve()
        or argv[1] != "-B"
        or Path(argv[2]).resolve() != script.resolve()
        or len(argv[3:]) % 2
    ):
        raise ValueError("qualification command is not the registered harness")
    flags = dict(zip(argv[3::2], argv[4::2]))
    wanted = {
        "--fixture": task["fixture"],
        "--output": str(Path(task["qualification"]["path"]).parent),
        "--runtime-profile": profile["path"],
        "--runtime-profile-sha256": profile["sha256"],
        **{"--" + name: path for name, path in profile["tools"].items()},
    }
    if (
        len(flags) * 2 != len(argv[3:])
        or set(flags) != set(wanted) | {"--known-fix"}
        or any(flags.get(key) != value for key, value in wanted.items())
    ):
        raise ValueError("qualification argv differs from frozen runtime/source")
    retrieved = read_pinned(request["retrieval"], request["retrieval_sha256"])
    if file_identity(request["retrieval"]) != {
        key: retrieval[key] for key in ("bytes", "sha256")
    }:
        raise ValueError("retrieval identity changed")
    docs = retrieved.get("documents")
    if (
        not isinstance(docs, list)
        or (request["arm"] == "no_history" and docs)
        or len(docs) > protocol["retrieval"]["maximum_documents"]
        or sum(len(doc["text"].encode()) for doc in docs)
        > protocol["retrieval"]["maximum_utf8_bytes"]
    ):
        raise ValueError("retrieval arm or complete-document budget mismatch")
    model = read_pinned(request["model_manifest"], request["model_manifest_sha256"])
    if file_identity(request["model_manifest"]) != protocol[
        "staged_model_manifest"
    ] or not model.get("file"):
        raise ValueError("staged model manifest changed")
    # Consume the hash-bound copy, never reconstruct a prompt from mutable source.
    return frozen_input["task"], frozen_input["files"]
