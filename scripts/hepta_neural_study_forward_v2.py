#!/usr/bin/env python3
"""Explicit current-runtime forwards with the original historical observer."""

import argparse
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import time
from types import ModuleType

PROFILE = "hepta-integrated-chain-execution-v12"
CALLER_MANIFEST_NAME = "smollm2-neural-forward-v2.sources.json"
CALLER_MANIFEST_SHA256 = (
    "2af311dd66043dcaa43701606075511a2a838e84a19ff826ed74fd17d1479fe7"
)
CALLER_NAMES = ("hepta_neural_forward_bootstrap_v2.py", "hepta_neural_forward_v2.py")
OBSERVERS = {
    "neural-v1": (
        "c16507147b65285ea94dead22d3b93c5db7295af",
        "hepta-integrated-chain-execution-v4",
    ),
    "binary-v2": ("ad490ed4b1132a333159fd76702809fd248a4462", None),
    "diverse-v3": ("ad490ed4b1132a333159fd76702809fd248a4462", None),
}
FORWARD_FIELDS = frozenset(
    "schema operation runtime_chain training_chain materials parent worker_plan "
    "tasks model window_id phase_id output forward_profile study_profile".split()
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def read_file(path, maximum):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, "canonical source path")
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    )
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "bounded regular parent input",
        )
        raw = source.read(maximum + 1)
        after = os.fstat(source.fileno())
    require(
        (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        and len(raw) == before.st_size,
        "parent input changed during capture",
    )
    return raw


def checked(pin, maximum):
    require(type(pin) is dict and set(pin) == {"path", "sha256"}, "closed pin")
    raw = read_file(pin["path"], maximum)
    require(hashlib.sha256(raw).hexdigest() == pin["sha256"], "pinned source changed")
    return raw


def unique(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "duplicate member")
        result[name] = value
    return result


def object_at(pin, maximum):
    return json.loads(
        checked(pin, maximum),
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def source_pin(path, maximum):
    raw = read_file(path, maximum)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def load_caller():
    root = Path(__file__).resolve().parents[1]
    manifest = object_at(
        {
            "path": str(
                root
                / "codex-rs/hepta-learning-artifacts/profiles"
                / CALLER_MANIFEST_NAME
            ),
            "sha256": CALLER_MANIFEST_SHA256,
        },
        64 * 1024,
    )
    require(
        set(manifest)
        == {
            "schema",
            "profile",
            "chain_commit",
            "chain_tree",
            "runtime_manifest_sha256",
            "files",
        }
        and manifest["schema"] == "hepta-neural-forward-source-contract-v2"
        and manifest["profile"] == PROFILE
        and set(manifest["files"]) == set(CALLER_NAMES),
        "closed fixed caller contract",
    )
    sources = {}
    for name, value in manifest["files"].items():
        require(set(value) == {"size", "sha256"}, "closed caller source")
        raw = checked(
            {"path": str(root / "scripts" / name), "sha256": value["sha256"]},
            2 * 1024 * 1024,
        )
        require(len(raw) == value["size"], "caller source size")
        sources[name] = raw
    name = "hepta_neural_forward_bootstrap_v2"
    require(name not in sys.modules, "caller bootstrap already loaded")
    module = ModuleType(name)
    path = root / "scripts" / (name + ".py")
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(sources[name + ".py"], str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    require(
        module.PROFILE == PROFILE
        and module.CHAIN_COMMIT == manifest["chain_commit"]
        and module.CHAIN_TREE == manifest["chain_tree"]
        and module.MANIFEST_SHA256 == manifest["runtime_manifest_sha256"],
        "caller and current runtime contract disagree",
    )
    return module, {name: value["sha256"] for name, value in manifest["files"].items()}


def forward(value, input_pin):
    os.umask(0o077)
    require(
        type(value) is dict
        and set(value) == FORWARD_FIELDS
        and value["schema"] == "hepta-neural-study-v1"
        and value["operation"] == "forward"
        and value["forward_profile"] == PROFILE
        and value["study_profile"] in OBSERVERS,
        "explicit closed current-runtime forward request",
    )
    bootstrap, caller = load_caller()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    original = importlib.import_module("hepta_neural_study_v1")
    observer_commit, training_profile = OBSERVERS[value["study_profile"]]
    require(
        original.EXECUTION_SOURCE_PROFILE == training_profile
        and original.TRAINING == observer_commit,
        "historical study roles changed",
    )
    runtime_chain, observation_chain = (
        Path(value["runtime_chain"]),
        Path(value["training_chain"]),
    )
    manifest = original.execution_source.checked_manifest(PROFILE)
    original.execution_source.verify(runtime_chain, PROFILE)
    original.checkout(observation_chain, observer_commit)
    original.execution_source.verify_selected(observation_chain, training_profile)
    original.runtime_snapshot()
    snapshot = source_pin(
        Path(os.environ["HEPTA_PUBLIC_INITIAL_RUNTIME_SNAPSHOT"]), 16 * 1024 * 1024
    )
    sys.path.insert(0, str(observation_chain / "scripts"))
    runtime = importlib.import_module("llm_runtime_pilot")
    script = Path(__file__).with_name("hepta_neural_forward_v2.py").resolve()
    material = (
        script.parents[1]
        / "codex-rs/hepta-learning-artifacts/profiles/smollm2-public-initial-v2.plan.json"
    )
    material_pin = {"path": str(material), "sha256": bootstrap.MATERIAL_PLAN_SHA256}
    checked(material_pin, 64 * 1024)
    output = Path(value["output"])
    require(output.is_absolute(), "absolute private forward output")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    sources = {
        relative: manifest["files"][relative]["sha256"]
        for relative in bootstrap.RUNTIME_PATHS
    }
    complete = {
        str(runtime_chain / relative): digest for relative, digest in sources.items()
    }
    complete.update(
        {str(script.with_name(name)): digest for name, digest in caller.items()}
    )
    require(len(complete) == 15, "closed Chain and caller source set")
    source_pins = original.save(output / "source-pins.json", complete)
    unused_prefix = output / "unused-bytecode"
    require(not unused_prefix.exists(), "unused private bytecode prefix")
    config = {
        "schema": bootstrap.SCHEMA,
        "source_sha256": caller[script.name],
        "chain": str(runtime_chain),
        "chain_commit": bootstrap.CHAIN_COMMIT,
        "chain_tree": bootstrap.CHAIN_TREE,
        "execution_source_profile": PROFILE,
        "sources": sources,
        "caller": {"schema": bootstrap.CALLER_SCHEMA, "sources": caller},
        "runtime_snapshot": snapshot,
        "source_pins": source_pins,
        "unused_bytecode_prefix": str(unused_prefix),
        "materials": value["materials"],
        "parent": value["parent"],
        "worker_plan": value["worker_plan"],
        "material_plan": material_pin,
        "bridge_profile": bootstrap.BRIDGE_PROFILE,
        "tasks": value["tasks"],
        "output": str(output / "worker"),
        "owner_pid": os.getpid(),
        "deadline_monotonic_ns": time.monotonic_ns() + 600000000000,
        "budget": {"wall_seconds": 600, "rss_bytes": 8 * 1024**3},
        "phase_id": value["phase_id"],
        "model": value["model"],
        "window_id": value["window_id"],
    }
    bootstrap.project_sources(config, script)
    config_pin = original.save(output / "observed-input.json", config)
    result = runtime.supervise(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=" + str(unused_prefix),
            str(script),
            "--input",
            config_pin["path"],
            "--input-sha256",
            config_pin["sha256"],
            "--bootstrap-sha256",
            caller["hepta_neural_forward_bootstrap_v2.py"],
        ],
        output / "supervisor",
        config["budget"],
        exit_observation=runtime.exit_observation_profile(
            "linux-owned-exit-worker-pidfd-v4"
        ),
    )
    original.save(output / "supervisor-result.json", result)
    require(
        result["outcome"] == "success"
        and result["exit_code"] == 0
        and result["stop_reason"] is None
        and result["waited_child_reaped"] is True
        and result["owned_child_reap_resolved"] is True
        and result["exit_observation_profile"]["maximum_drain_ns"] == 100000000,
        "original 600s/8GiB/100ms complete forward supervision",
    )
    actual_pin = original.pin(output / "worker/forward-result.json")
    actual = original.read_pin(actual_pin)
    require(
        actual["schema"] == bootstrap.SCHEMA + "-result"
        and actual["input"] == config_pin
        and actual["forwards"] == 512
        and actual["loads"] == 9,
        "complete real forwards from the versioned caller",
    )
    original.runtime_snapshot()
    original.save(
        output / "phase-result.json",
        {
            "schema": original.SCHEMA + "-forward-result",
            "input": input_pin,
            "actual": actual_pin,
            "supervisor": original.pin(output / "supervisor-result.json"),
            "window_id": value["window_id"],
            "model": value["model"],
            "installation_authority": False,
        },
    )


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-sha256", required=True)
    args = parser.parse_args()
    request = {"path": str(Path(args.input).resolve()), "sha256": args.input_sha256}
    value = object_at(request, 32 * 1024 * 1024)
    owner = value.pop("host_parent_pid")
    require(
        type(owner) is int and owner > 1 and os.getppid() == owner,
        "original Rust parent lost",
    )
    libc = ctypes.CDLL(None, use_errno=True)
    require(
        libc.prctl(1, signal.SIGKILL, 0, 0, 0) == 0 and os.getppid() == owner,
        "original Rust parent death binding",
    )
    forward(value, request)
