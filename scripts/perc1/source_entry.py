"""Ordinary source capture and active observation through the existing owner.

Operator configuration supplies a finite source catalog and frozen model. Reads of
images, OCR and browser pages happen only inside the durable acquisition attempt.
Neither a hash nor an operator source-group label proves source independence.
"""

import re
import time
from pathlib import Path

from .browser_capture import configured_browser_capture, validate_browser_config
from .capture_entry import OwnedProducer, decode_native_wire, model_sha256
from .entry import _json, load_request, read_pinned
from .owner import Owner
from .schema import digest, exact, identifier, integer, require, sha
from .source_capture import configured_capture, validate_source_config

BACKEND_FILES = (
    "source_entry.py",
    "source_capture.py",
    "browser_capture.py",
    "capture_entry.py",
)
BACKEND_PINS = {
    name: sha(Path(__file__).with_name(name).read_bytes()) for name in BACKEND_FILES
}


def backend_sha256():
    require(
        all(
            sha(Path(__file__).with_name(name).read_bytes()) == value
            for name, value in BACKEND_PINS.items()
        ),
        "source backend changed; restart with a new explicit config",
    )
    return sha(BACKEND_PINS)


def make_config(
    state_dir, owner_id, generation, budget_units, sources, model, scope_digest
):
    """Prepare explicit local operator configuration; this grants no native authority."""
    backend = backend_sha256()
    grant = {
        "schema": "perc1.capture-grant.v1",
        "owner_id": owner_id,
        "generation": generation,
        "scope_digest": scope_digest,
        "source_ids": sorted(sources),
        "source_frontier": sha({"sources": sources, "capture_backend_sha256": backend}),
    }
    return {
        "schema": "perc1.source-operator-config.v1",
        "state_dir": str(state_dir),
        "owner_id": owner_id,
        "generation": generation,
        "budget_units": budget_units,
        "capture_backend_sha256": backend,
        "grant": grant,
        "model": model,
        "sources": sources,
    }


def operator_source_config(path):
    config = load_request(path)
    exact(
        config,
        "schema state_dir owner_id generation budget_units capture_backend_sha256 grant model sources",
    )
    require(
        config["schema"] == "perc1.source-operator-config.v1",
        "unknown source operator config",
    )
    require(
        digest(config["capture_backend_sha256"]) == backend_sha256(),
        "source backend pin mismatch",
    )
    identifier(config["owner_id"])
    integer(config["generation"], 1)
    integer(config["budget_units"], 1)
    require(
        type(config["state_dir"]) is str and Path(config["state_dir"]).is_absolute(),
        "absolute owner store required",
    )
    sources = config["sources"]
    require(type(sources) is dict and 0 < len(sources) <= 128, "source catalog bound")
    for source_id, source in sources.items():
        require(
            type(source_id) is str
            and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", source_id),
            "invalid source identity",
        )
        require(type(source) is dict, "source config must be an object")
        if source.get("schema") == "perc1.browser-capture.v1":
            validate_browser_config(source)
        else:
            validate_source_config(source)
    grant = exact(
        config["grant"],
        "schema owner_id generation source_frontier source_ids scope_digest",
    )
    require(digest(grant["scope_digest"]) != "0" * 64, "empty scope")
    require(
        grant["schema"] == "perc1.capture-grant.v1"
        and grant["owner_id"] == config["owner_id"]
        and grant["generation"] == config["generation"]
        and type(grant["source_ids"]) is list
        and all(type(item) is str for item in grant["source_ids"])
        and sorted(grant["source_ids"]) == sorted(sources)
        and grant["source_frontier"]
        == sha({"sources": sources, "capture_backend_sha256": backend_sha256()}),
        "source grant does not match operator catalog",
    )
    model = exact(
        config["model"], "weights weights_sha256 projection projection_sha256 device"
    )
    require(model["device"] in ("cpu", "cuda"), "invalid model device")
    for key in ("weights", "projection"):
        require(
            type(model[key]) is str and Path(model[key]).is_absolute(),
            "absolute model paths required",
        )
    digest(model["weights_sha256"])
    projection = _json(
        read_pinned(model["projection"], model["projection_sha256"], 8 * 1024 * 1024)
    )
    binding = {
        "owner_id": config["owner_id"],
        "generation": config["generation"],
        "source_frontier": grant["source_frontier"],
        "encoder_sha256": model_sha256(model["weights_sha256"], projection),
        "grant_sha256": sha(grant),
    }
    return config, projection, binding


def run_source_capture(config_path, operation_id, request=None, *, active=None):
    """Acquire/replay, read retained evidence, or make an owned ACQUIRE/STOP choice."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    require(not (request is not None and active is not None), "ambiguous source entry")
    config, projection, binding = operator_source_config(config_path)
    this_entry = {
        "source_callback_invocations": 0,
        "encoder_loaded": False,
        "encoder_completed_calls": 0,
    }
    decision, artifact_count = None, 0
    with Owner(config["state_dir"], binding, config["budget_units"]) as owner:
        if request is None and active is None:
            receipt = owner.receipt(operation_id)
            mode, status = "retained_readback", receipt["status"]
        else:
            model = config["model"]
            adapter = OwnedProducer(
                owner,
                config["grant"],
                model["weights"],
                model["weights_sha256"],
                projection,
                device=model["device"],
            )

            def capture(admitted):
                require(
                    backend_sha256() == config["capture_backend_sha256"],
                    "source backend changed after admission",
                )
                this_entry["source_callback_invocations"] += 1
                source = config["sources"][admitted["source_id"]]
                callback = (
                    configured_browser_capture
                    if source["schema"] == "perc1.browser-capture.v1"
                    else configured_capture
                )
                return callback(source, admitted)

            if active is None:
                receipt = adapter.observe(operation_id, request, capture)
                mode, status = "acquire_or_replay", receipt["status"]
            else:
                from .active_capture import observe

                fields = "head head_sha256 task_sha256 observed_operations candidates"
                feature_profile = None
                if type(active) is dict and "schema" in active:
                    exact(
                        active,
                        "schema feature_profile head_artifact head_sha256 "
                        "task_sha256 observed_operations candidates",
                    )
                    require(
                        active["schema"] == "perc1.profiled-source-active.v1",
                        "unknown profiled source request",
                    )
                    feature_profile = active["feature_profile"]
                    require(type(feature_profile) is dict, "feature profile required")
                    artifact = exact(active["head_artifact"], "path sha256")
                    require(
                        type(artifact["path"]) is str
                        and Path(artifact["path"]).is_absolute(),
                        "absolute trained head path required",
                    )
                    head = _json(
                        read_pinned(
                            artifact["path"], artifact["sha256"], 2 * 1024 * 1024
                        )
                    )
                else:
                    exact(active, fields)
                    head = active["head"]
                decision = observe(
                    adapter,
                    operation_id,
                    head,
                    active["candidates"],
                    capture,
                    expected_head_sha256=active["head_sha256"],
                    task_sha256=active["task_sha256"],
                    observed_operations=active["observed_operations"],
                    feature_profile=feature_profile,
                )
                receipt = decision["owner_receipt"]
                mode, status = "active_observation", decision["outcome"]
            this_entry["encoder_loaded"] = adapter.worker is not None
            this_entry["encoder_completed_calls"] = (
                0 if adapter.worker is None else adapter.worker.calls
            )
        if receipt is not None and receipt["status"] == "executed":
            result = receipt["result"]
            require(
                result.get("schema") == "perc1.owned-encoding.v2",
                "source receipt lacks retained exact artifacts",
            )
            decode_native_wire(result, source_root=owner.root)
            artifact_count = len(result["source_evidence"]["artifacts"])
        state = owner.status()
    return {
        "schema": "perc1.source-entry-result.v1",
        "mode": mode,
        "status": status,
        "receipt": receipt,
        "active": decision,
        "owner_status": state,
        "this_entry": this_entry,
        "verified_source_artifacts": artifact_count,
        "entry_measurements": {
            "wall_ns": time.perf_counter_ns() - started,
            "process_cpu_ns": time.process_time_ns() - cpu,
            "scope": "config, owner, actual source/browser/OCR/encoder, persistence and retained evidence readback; nested stage times are not additive",
            "energy_joules": None,
            "provider_billing": None,
        },
        "scientific_status": "HOLD",
        "adoption": "NoUpdate",
        "production_daemon_integrated": False,
    }


def read_source_decision(config_path, operation_id):
    """Read a retained STOP/ACQUIRE choice without starting a source or a model."""
    from .active_capture import read_decision

    started = time.perf_counter_ns()
    config, _, binding = operator_source_config(config_path)
    with Owner(config["state_dir"], binding, config["budget_units"]) as owner:
        decision = read_decision(owner, operation_id)
        state = owner.status()
    return {
        "schema": "perc1.source-decision-read.v1",
        "status": "retained_readback",
        "decision": decision,
        "owner_status": state,
        "this_entry": {
            "source_callback_invocations": 0,
            "encoder_loaded": False,
            "encoder_completed_calls": 0,
        },
        "wall_ns": time.perf_counter_ns() - started,
        "effect_completion_implied": False,
        "scientific_status": "HOLD",
    }
