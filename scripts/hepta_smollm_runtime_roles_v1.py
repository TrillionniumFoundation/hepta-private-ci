"""Explicit material and execution roles for the fixed public V2 bridge.

This validates inputs and records their distinct identities. It issues no model,
training, installation or final-use authority.
"""

import hashlib
import os
from pathlib import Path

import hepta_neural_forward_bootstrap_v2 as bridge
import hepta_smollm_execution_source_v1 as execution

OLD_SCHEMA = "hepta-smollm-neural-native-check-v2"
SCHEMA = "hepta-smollm-neural-native-check-material-bridge-v1"
FIELDS = frozenset(
    "schema python chain materials parent parent_sha256 output runtime_snapshot "
    "runtime_snapshot_sha256 material_runtime_bridge".split()
)
HISTORICAL_COMMITS = frozenset(
    (
        "cfa57cd04751427451302b5c10539b3984d7f8db",
        "c16507147b65285ea94dead22d3b93c5db7295af",
        "c96022b897c1235fdbdbfcfa32764403511c6aab",
    )
)
CONTRACT = "c9b06f9a029a3257801844f89acb59b5f59f6a39087335af323f274e9152992f"


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical_path(value):
    require(type(value) is str, "explicit source path")
    path = Path(value)
    require(path.is_absolute() and path.resolve() == path, "canonical source role path")
    return path


def selected_runtime():
    profile = os.environ.get("HEPTA_RUNTIME_EXECUTION_PROFILE")
    commit = os.environ.get("HEPTA_RUNTIME_CHAIN_SHA")
    if profile is None and commit is None:
        return False
    require(
        profile == bridge.PROFILE and commit == bridge.CHAIN_COMMIT,
        "explicit fixed current runtime role required",
    )
    return True


def validate_current(config):
    require(
        type(config) is dict and set(config) == FIELDS and config["schema"] == SCHEMA,
        "closed versioned native input",
    )
    binding = config["material_runtime_bridge"]
    require(
        type(binding) is dict
        and set(binding) == {"profile", "material_plan"}
        and binding["profile"] == bridge.BRIDGE_PROFILE
        and type(binding["material_plan"]) is str
        and hashlib.sha256(binding["material_plan"].encode()).hexdigest()
        == bridge.MATERIAL_PLAN_SHA256,
        "fixed historical material pair required",
    )
    for key in ("python", "chain", "materials", "parent", "output", "runtime_snapshot"):
        canonical_path(config[key])
    parent = bridge.object_at(
        {"path": config["parent"], "sha256": config["parent_sha256"]}, 8 * 1024 * 1024
    )
    require(
        parent["schema"] == "hepta-smollm-parent-material-v1"
        and type(parent["generation"]) is int
        and parent["generation"] == 1
        and parent["contract"] == CONTRACT,
        "actual generation-one material parent",
    )
    bridge.checked(
        {
            "path": config["runtime_snapshot"],
            "sha256": config["runtime_snapshot_sha256"],
        },
        16 * 1024 * 1024,
    )
    return execution.verify(canonical_path(config["chain"]), bridge.PROFILE)


def native_roles(config, historical_chain, historical_commit):
    if config.get("schema") == OLD_SCHEMA:
        require(
            "material_runtime_bridge" not in config and historical_chain is None,
            "legacy native input cannot select new source roles",
        )
        return Path(config["chain"]), None
    current = validate_current(config)
    require(
        historical_chain is not None and historical_commit in HISTORICAL_COMMITS,
        "explicit retained historical Chain role required",
    )
    historical = canonical_path(str(historical_chain))
    require(
        historical != Path(config["chain"]), "historical and current roles cannot alias"
    )
    head = execution.git("rev-parse", "HEAD", repository=historical)
    require(head == historical_commit, "exact historical Chain commit required")
    execution.git(
        "diff",
        "--exit-code",
        "HEAD",
        "--",
        "scripts",
        "formal",
        "config",
        repository=historical,
    )
    return historical, {
        "schema": "hepta-material-runtime-source-roles-v1",
        "current_runtime": dict(current, root=config["chain"]),
        "historical_chain": {"root": str(historical), "commit": head},
        "material_plan_sha256": bridge.MATERIAL_PLAN_SHA256,
        "historical_contract": CONTRACT,
        "installation_authorized": False,
    }
