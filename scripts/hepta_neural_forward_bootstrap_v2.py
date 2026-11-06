#!/usr/bin/env python3
"""Closed bootstrap for the runtime-bound study caller; no production authority."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from types import ModuleType, SimpleNamespace

PROFILE = "hepta-integrated-chain-execution-v12"
CHAIN_COMMIT = "cad4c18fe146b7d742ac7fa8872044cd4136c22b"
CHAIN_TREE = "1e753c4641f6108f50b356182f8b4e81fa941e31"
MANIFEST_NAME = "smollm2-public-initial-v2.execution-sources-v12.json"
MANIFEST_SHA256 = "02b51be8bd41850879993def86533da0b4870dece4c3d7be2afd646497768902"
BRIDGE_PROFILE = "smollm2-public-v2-material-runtime-bridge-v1"
MATERIAL_PLAN_SHA256 = (
    "01ec1a644f37b9fc7a4c6616f589768df97f8eed7a289b5de86afadaa7ce6165"
)
EXPECTED_BRIDGE = {
    "schema": "hepta-smollm-material-runtime-bridge-v1",
    "profile": BRIDGE_PROFILE,
    "historical_plan_sha256": MATERIAL_PLAN_SHA256,
    "historical_contract_sha256": "ebc8ac84999a91acb823d1bf8959a7dbc61fe20d7ba137f11affe426605d9852",
    "historical_contract": "c9b06f9a029a3257801844f89acb59b5f59f6a39087335af323f274e9152992f",
    "historical_runtime_source": "65ccc6454befd96fa5ce1f5bdde2c56cb6cbb741cf495b8d24a758039f99f755",
    "execution_runtime_source": "d2854289ae810115bccd3b7714c3d40b03cc6ec216747d6fca653aeac9299bd7",
    "execution_plan_sha256": "e9506293ba9e70ef16889efcbeb23007c177806677b4fdf68104726c885054e4",
    "execution_contract_sha256": "ab62a0df784f43274d01cb5ebff11c8ef798ec21ff389ce6b46662377e6f555d",
}
SCHEMA = "hepta-neural-positive-forward-v2"
CALLER_SCHEMA = "hepta-neural-forward-caller-v2"
CALLER_NAMES = (
    "hepta_neural_forward_bootstrap_v2.py",
    "hepta_neural_forward_v2.py",
)
RUNTIME_PATHS = (
    "formal/pon-nakamoto-v1/contract_wire.py",
    "formal/pon-nakamoto-v1/llm_adapter_contract.py",
    "config/pon/devnet-v1.json",
    "config/pon/ledger-v1.json",
    "config/pon/model-family-v1.json",
    "config/pon/work-profile-v1.json",
    "config/pon/model-family-smollm2-135m-v1.json",
    "scripts/llm_base_material.py",
    "scripts/llm_inherited_runtime.py",
    "scripts/llm_neural_read_worker.py",
    "scripts/llm_parent_material.py",
    "scripts/llm_python_runtime_contract.py",
    "scripts/llm_runtime_pilot.py",
)
CONFIG_FIELDS = frozenset(
    "schema source_sha256 chain chain_commit chain_tree execution_source_profile "
    "sources caller runtime_snapshot source_pins unused_bytecode_prefix "
    "materials parent worker_plan material_plan bridge_profile tasks output owner_pid deadline_monotonic_ns "
    "budget phase_id model window_id".split()
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def valid_digest(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate caller field")
        value[key] = item
    return value


def checked(pin, maximum):
    require(
        type(pin) is dict
        and set(pin) == {"path", "sha256"}
        and valid_digest(pin["sha256"]),
        "closed caller pin",
    )
    path = Path(pin["path"])
    require(path.is_absolute() and path.resolve() == path, "canonical caller path")
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    )
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "bounded regular caller file",
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
        and len(raw) == before.st_size
        and digest(raw) == pin["sha256"],
        "caller bytes changed",
    )
    return raw


def object_at(pin, maximum):
    return json.loads(
        checked(pin, maximum),
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def isolated_entry():
    require(
        sys.flags.isolated == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.no_user_site == 1
        and sys.flags.no_site == 1
        and sys.flags.dont_write_bytecode == 1,
        "runtime-bound study requires -I -S -B",
    )
    os.umask(0o077)


def project_sources(config, source):
    """Bind the declared Chain closure and precisely two caller source files."""
    require(
        type(config) is dict and set(config) == CONFIG_FIELDS, "closed v2 caller input"
    )
    require(
        re.fullmatch("[0-9a-f]{40}", CHAIN_COMMIT) is not None
        and re.fullmatch("[0-9a-f]{40}", CHAIN_TREE) is not None
        and valid_digest(MANIFEST_SHA256),
        "unpublished research composition cannot execute",
    )
    require(
        config["schema"] == SCHEMA
        and config["execution_source_profile"] == PROFILE
        and config["chain_commit"] == CHAIN_COMMIT
        and config["chain_tree"] == CHAIN_TREE
        and config["budget"] == {"wall_seconds": 600, "rss_bytes": 8 * 1024**3},
        "exact versioned study source and original budget",
    )
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "codex-rs/hepta-learning-artifacts/profiles"
        / MANIFEST_NAME
    )
    manifest = object_at(
        {"path": str(manifest_path), "sha256": MANIFEST_SHA256}, 64 * 1024
    )
    require(
        manifest["profile"] == PROFILE
        and manifest["chain_commit"] == CHAIN_COMMIT
        and manifest["chain_tree"] == CHAIN_TREE
        and set(RUNTIME_PATHS) <= set(manifest["files"]),
        "frozen study source manifest",
    )
    require(
        config["bridge_profile"] == BRIDGE_PROFILE, "explicit material/runtime bridge"
    )
    require(
        type(config["material_plan"]) is dict
        and config["material_plan"].get("sha256") == MATERIAL_PLAN_SHA256,
        "historical material plan commitment",
    )
    checked(config["material_plan"], 64 * 1024)
    chain = Path(config["chain"])
    require(
        chain.is_absolute() and chain.resolve() == chain, "canonical runtime checkout"
    )
    expected = {
        relative: manifest["files"][relative]["sha256"] for relative in RUNTIME_PATHS
    }
    require(
        config["sources"] == expected, "complete independently pinned Chain closure"
    )
    sources = {str(chain / relative): value for relative, value in expected.items()}
    caller = config["caller"]
    require(
        type(caller) is dict
        and set(caller) == {"schema", "sources"}
        and caller["schema"] == CALLER_SCHEMA
        and type(caller["sources"]) is dict
        and set(caller["sources"]) == set(CALLER_NAMES)
        and all(valid_digest(value) for value in caller["sources"].values()),
        "exact two-source caller contract",
    )
    require(
        source.name == "hepta_neural_forward_v2.py"
        and source.resolve() == source
        and source.parent == Path(__file__).resolve().parent
        and caller["sources"][source.name] == config["source_sha256"],
        "actual caller entry binding",
    )
    for name in CALLER_NAMES:
        path = source.parent / name
        require(str(path) not in sources, "caller cannot shadow Chain source")
        sources[str(path)] = caller["sources"][name]
    require(len(sources) == 15, "exact full study source set")
    supplied = object_at(config["source_pins"], 128 * 1024)
    require(
        supplied == sources, "source pin file must equal complete caller commitment"
    )
    for path, expected_digest in sources.items():
        checked({"path": path, "sha256": expected_digest}, 2 * 1024 * 1024)
    return sources


def read_ready(path):
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    )
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 128 * 1024,
            "bounded regular Ready",
        )
        raw = source.read(128 * 1024 + 1)
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
        "Ready changed during capture",
    )
    return raw


def validate_ready(ready, parent, plan, worker_args, config):
    identities = {
        Path(path).name: pin for path, pin in worker_args.runtime_source_pins.items()
    }
    require(
        len(identities) == len(worker_args.runtime_source_pins) == 15,
        "complete unaliased runtime and caller commitment",
    )
    require(
        type(ready) is dict
        and set(ready)
        == {
            "schema",
            "actual_loaded_parent",
            "file_sha256",
            "contract",
            "generation",
            "backbone",
            "tokenizer",
            "source_pins",
            "worker_source",
            "runtime_snapshot_sha256",
            "actions",
            "observed_rss_bytes",
            "authority",
            "material_runtime_bridge",
            "runtime_source_set_sha256",
        },
        "closed bridge Ready",
    )
    require(
        ready["schema"] == "hepta-smollm-neural-read-ready-material-bridge-v1"
        and ready["material_runtime_bridge"] == EXPECTED_BRIDGE
        and ready["runtime_source_set_sha256"]
        == digest(
            json.dumps(identities, sort_keys=True, separators=(",", ":")).encode()
        )
        and ready["actual_loaded_parent"] == parent["adapter"]
        and ready["file_sha256"] == parent["file_sha256"]
        and ready["contract"] == parent["contract"]
        and ready["generation"] == parent["generation"]
        and ready["source_pins"] == plan["inherited_sources"]
        and ready["worker_source"] == plan["worker_source"]
        and ready["runtime_snapshot_sha256"]
        == plan["runtime_snapshot_sha256"]
        == config["runtime_snapshot"]["sha256"]
        and ready["actions"] == plan["actions"]
        and ready["authority"]
        == {
            "installation_authorized": False,
            "selection_authorized": False,
            "independent_accepted": False,
            "prospective_accepted": False,
            "public_reward_eligible": False,
            "hepta_final_use": False,
        },
        "actual loaded model binding",
    )


def prepare(config, source):
    """Run the canonical Chain bootstrap before all original parent/plan checks."""
    isolated_entry()
    sources = project_sources(config, source)
    deadline = config["deadline_monotonic_ns"]
    require(
        type(deadline) is int and time.monotonic_ns() < deadline,
        "original phase expired before bootstrap",
    )
    require(
        type(sys.pycache_prefix) is str
        and sys.pycache_prefix == config["unused_bytecode_prefix"]
        and Path(sys.pycache_prefix).is_absolute()
        and not Path(sys.pycache_prefix).exists(),
        "exact unused private bytecode prefix",
    )
    snapshot = config["runtime_snapshot"]
    require(
        type(snapshot) is dict
        and set(snapshot) == {"path", "sha256"}
        and valid_digest(snapshot["sha256"]),
        "explicit runtime snapshot",
    )
    object_at(snapshot, 16 * 1024 * 1024)
    worker_path = Path(config["chain"]) / "scripts/llm_neural_read_worker.py"
    raw = checked(
        {"path": str(worker_path), "sha256": sources[str(worker_path)]}, 2 * 1024 * 1024
    )
    require("llm_neural_read_worker" not in sys.modules, "worker already imported")
    worker = ModuleType("llm_neural_read_worker")
    worker.__file__ = str(worker_path)
    sys.modules[worker.__name__] = worker
    try:
        exec(compile(raw, str(worker_path), "exec"), worker.__dict__)
        arguments = SimpleNamespace(
            runtime_snapshot=snapshot["path"],
            runtime_snapshot_sha256=snapshot["sha256"],
            source_pins=config["source_pins"]["path"],
            source_pins_sha256=config["source_pins"]["sha256"],
            plan=config["worker_plan"]["path"],
            plan_sha256=config["worker_plan"]["sha256"],
            materials=config["materials"],
        )
        worker.bootstrap_runtime_v2(arguments)
    except BaseException:
        sys.modules.pop(worker.__name__, None)
        raise
    require(time.monotonic_ns() < deadline, "original phase expired during bootstrap")
    require(worker.MAX_REQUESTS == 64, "original worker request cap")
    parent = worker.inherited.validate_parent(
        object_at(config["parent"], 8 * 1024 * 1024)
    )
    plan = object_at(config["worker_plan"], 512 * 1024)
    require(
        plan["schema"] == "hepta-smollm-neural-read-plan-material-bridge-v1"
        and plan["material_bridge"]
        == {
            "profile": BRIDGE_PROFILE,
            "material_plan": checked(config["material_plan"], 64 * 1024).decode(
                "utf-8"
            ),
        }
        and plan["parent"] == parent
        and plan["worker_source"] == sources[str(worker_path)]
        and plan["inherited_sources"] == worker.worker_sources()
        and plan["runtime_snapshot_sha256"] == snapshot["sha256"],
        "original parent and complete runtime-bound worker plan",
    )
    # The same public preflight used by explicit direct callers precedes the
    # client thread and model construction. The worker repeats it at actual use.
    worker.preflight_material_runtime_bridge_v1(arguments)
    return worker, parent, plan, arguments
