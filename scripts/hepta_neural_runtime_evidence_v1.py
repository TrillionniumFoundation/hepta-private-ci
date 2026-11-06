"""Separate current runtime evidence from the retained training role records."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import hepta_neural_forward_bootstrap_v2 as bootstrap
import hepta_neural_study_forward_v2 as forward
import hepta_smollm_runtime_roles_v1 as roles

SUFFIX = "-material-bridge-v1"


def bridged(record):
    return str(record.get("schema", "")).endswith(SUFFIX)


def names(historical, record):
    return set(historical) | ({"chain-runtime"} if bridged(record) else set())


def schema(historical, record):
    return historical + SUFFIX if bridged(record) else historical


def current_contracts():
    current, parent = roles.runtime_contract()
    if parent is None:
        return (
            bootstrap,
            forward,
            Path(__file__).resolve().with_name("hepta_neural_forward_v2.py"),
        )
    return current, parent, parent.caller_path()


def append_runtime(record, root, collector, current_runtime):
    if current_runtime is None:
        return
    record["schema"] += SUFFIX
    try:
        roles.require(roles.selected_runtime(), "explicit current runtime environment")
        current_bootstrap, _, _ = current_contracts()
        path = roles.canonical_path(str(current_runtime))
        roles.require(
            path == root.parent / "chain-runtime", "separate named runtime checkout"
        )
        verified = roles.execution.verify(path, current_bootstrap.PROFILE)
        record["repositories"]["chain-runtime"] = collector(
            path, current_bootstrap.CHAIN_COMMIT
        )
        record["current_runtime"] = verified
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        record["errors"].append({"repository": "chain-runtime", "error": str(error)})


def validate_sources(record, historical_schema, historical_names, config):
    roles.require(
        record["schema"] == schema(historical_schema, record)
        and set(record["repositories"]) == names(historical_names, record),
        "exact versioned repository roles required",
    )
    if not bridged(record):
        roles.require(
            "current_runtime" not in record
            and config.get("schema") in (None, roles.OLD_SCHEMA),
            "legacy evidence cannot relabel a current runtime",
        )
        return
    roles.require(roles.selected_runtime(), "explicit current runtime environment")
    current_bootstrap, _, _ = current_contracts()
    current = record["repositories"]["chain-runtime"]
    historical = record["repositories"]["chain"]
    roles.require(
        current["identity"]["commit"] == current_bootstrap.CHAIN_COMMIT
        and current["identity"]["tree"] == current_bootstrap.CHAIN_TREE
        and current["identity"]["dirty"] is False
        and config["chain"] == current["root"]
        and all(
            current["root"] != record["repositories"][name]["root"]
            for name in historical_names
        ),
        "distinct actual current runtime source required",
    )
    _, observed = roles.native_roles(
        config, Path(historical["root"]), historical["identity"]["commit"]
    )
    expected = dict(observed["current_runtime"])
    del expected["root"]
    roles.require(
        record["current_runtime"] == expected,
        "current source observation cannot inherit an old role",
    )


def verify_forward(config, phase_input, worker_input, actual, pin):
    if config.get("schema") != roles.SCHEMA:
        roles.require(
            config.get("schema") in (None, roles.OLD_SCHEMA)
            and "material_runtime_bridge" not in config,
            "legacy forward cannot inherit current runtime evidence",
        )
        return
    roles.require(roles.selected_runtime(), "explicit current runtime environment")
    current_bootstrap, current_forward, current_script = current_contracts()
    roles.validate_current(config)
    roles.require(
        phase_input["forward_profile"] == current_bootstrap.PROFILE
        and phase_input["study_profile"] in current_forward.OBSERVERS
        and phase_input["runtime_chain"] == worker_input["chain"] == config["chain"]
        and worker_input["runtime_snapshot"]["path"] == config["runtime_snapshot"]
        and worker_input["runtime_snapshot"]["sha256"]
        == config["runtime_snapshot_sha256"],
        "actual forward uses the explicit current runtime",
    )
    observer, old_profile = current_forward.OBSERVERS[phase_input["study_profile"]]
    historical = Path(phase_input["training_chain"])
    roles.require(
        historical != Path(config["chain"])
        and roles.execution.git("rev-parse", "HEAD", repository=historical) == observer,
        "actual forward retains its original observer",
    )
    roles.execution.verify_selected(historical, old_profile)
    root = Path(__file__).resolve().parents[1]
    manifest = current_forward.object_at(
        {
            "path": str(
                root
                / "codex-rs/hepta-learning-artifacts/profiles"
                / current_forward.CALLER_MANIFEST_NAME
            ),
            "sha256": current_forward.CALLER_MANIFEST_SHA256,
        },
        64 * 1024,
    )
    caller = {name: value["sha256"] for name, value in manifest["files"].items()}
    roles.require(
        worker_input["caller"]["sources"] == caller,
        "independent fixed caller commitment required",
    )
    sources = current_bootstrap.project_sources(worker_input, current_script)
    roles.require(
        actual["schema"] == current_bootstrap.SCHEMA + "-result"
        and actual["source_sha256"] == worker_input["source_sha256"]
        and len(actual["prefix_chain"]) == 8,
        "actual versioned complete forward",
    )
    plan = pin(worker_input["worker_plan"])
    roles.require(
        plan["material_bridge"] == config["material_runtime_bridge"],
        "actual worker retains the complete historical material bridge",
    )
    observations = [pin(item)["actual_ready"] for item in actual["prefix_chain"]]
    observations.append(actual["last_ready"])
    roles.require(
        len(observations) == 9, "all nine original loads retain Ready evidence"
    )
    for item in observations:
        roles.require(
            set(item) == {"path", "sha256", "observation"},
            "closed actual Ready evidence",
        )
        loaded = pin({key: item[key] for key in ("path", "sha256")})
        roles.require(loaded == item["observation"], "retained actual Ready changed")
        current_bootstrap.validate_ready(
            loaded,
            actual["parent"],
            plan,
            SimpleNamespace(runtime_source_pins=sources),
            worker_input,
        )
