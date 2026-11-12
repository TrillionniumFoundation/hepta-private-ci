"""Forecast a panel without selecting or dispatching an owner action.

The caller declares action, policy, clock and cursor without native authority.
The distinct calibration-only schema rejects ordinary policy-value readers;
internal decision_at is shadow freeze time, not the original owner choice.
"""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, perf_counter, process_time

from .native_ledger import (
    Artifact,
    _digest,
    _integer,
    _require,
    _snapshot,
    _text,
    _time,
)
from .observed_evaluation import UtilityContract
from .observed_gru import ObservedGRU
from .observed_history import summarize_history
from .observed_models import ObservedModel
from .owner_bridge import freeze_owner_decision, owner_information_digest
from .owner_history_predict import SOURCE_FILES as BASE_SOURCE_FILES

SOURCE_FILES = (*BASE_SOURCE_FILES, "owner_history_shadow.py")
SCHEMA = "pred1-owner-history-shadow-v1"
MEASURED_FIELDS = (
    "started_at",
    "wall_seconds",
    "process_cpu_seconds",
    "declared_resource_cost",
)


def _sources():
    return {
        name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in SOURCE_FILES
    }


def _panel(snapshot, checkpoint_path, kind, digest, contract):
    _require(kind in ("empirical", "mlp", "gru"), "explicit model kind required")
    _digest(digest)
    p = _snapshot(snapshot)
    loader = ObservedGRU if kind == "gru" else ObservedModel
    try:
        model = loader.load(checkpoint_path, expected_sha256=digest)
        meta = model.metadata
        _require(meta["kind"] == kind, "checkpoint kind differs")
        _require(
            meta["duration_unit"] == "seconds"
            and meta["cost_unit"] == contract.cost_unit,
            "checkpoint target units differ",
        )
        features, names = p["features"][-1], p["feature_names"]
        encoding = "last_observed_row"
        if kind == "mlp":
            features, names = summarize_history(p["features"], names)
            encoding = "history_last_mean_length_v1"
        elif kind == "gru":
            features, encoding = p["features"], "observed_history_v1"
        _require(
            meta["feature_encoding"] == encoding and meta["feature_names"] == names,
            "checkpoint history feature schema differs",
        )
        actions = meta["action_ids"]
        _require(
            type(actions) is list and 1 <= len(actions) <= 64,
            "bounded action panel required",
        )
        _require(
            set(actions) == set(meta["training"]["action_counts"]),
            "unsupported checkpoint actions",
        )
        information = owner_information_digest(
            snapshot, actions, contract, meta["success_definition"]
        )
        predictions = {action: model.predict(features, action) for action in actions}
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("malformed typed checkpoint") from error
    return predictions, meta["success_definition"], information, encoding


def _snapshot_bound(path, digest, clock, cursor):
    _digest(digest)
    _text(clock)
    _integer(cursor)
    snapshot = Artifact.read(path)
    _require(snapshot.digest == digest, "snapshot bytes differ")
    p = _snapshot(snapshot)
    _require(
        p["clock_id"] == clock and p["cursor"] == cursor,
        "snapshot clock/cursor differs",
    )
    _require(
        not p["collection"]["rows"]["attempts"],
        "attempt already visible; not prospective",
    )
    return snapshot


def _meter(snapshot, kind, encoding, calls, sources, measured, contract):
    _require(
        type(measured) is dict and set(measured) == set(MEASURED_FIELDS),
        "shadow measurement fields differ",
    )
    for value in measured.values():
        _time(value)
    p = snapshot.payload
    _require(
        p["decision_at"] <= measured["started_at"], "snapshot is from a future clock"
    )
    for field, limit in (
        ("wall_seconds", contract.max_wall_seconds),
        ("declared_resource_cost", contract.max_total_cost),
    ):
        _require(
            limit is None or measured[field] <= limit,
            "shadow preparation exceeds budget",
        )
    return {
        **measured,
        "model_kind": kind,
        "feature_encoding": encoding,
        "history_rows": len(p["features"]),
        "snapshot_sha256": snapshot.digest,
        "clock_id": p["clock_id"],
        "arrival_cursor": p["cursor"],
        "source_sha256": sources,
        "candidate_prediction_calls": calls,
        "checkpoint_validation_prediction_calls": calls,
        "neural_forward_calls": 0 if kind == "empirical" else 2 * calls,
        "recurrent_steps": calls * (len(p["features"]) + 1) if kind == "gru" else 0,
        "summary_passes": int(kind == "mlp"),
        "horizon": 1,
        "physical_cost_complete": False,
        "source_provenance_authenticated": False,
        "scope": "validation and panel; excludes artifact IO, later observer work and unmeasured resource costs",
    }


def _wrap(decision):
    p = decision.payload
    return Artifact.make(
        {
            "schema": SCHEMA,
            "owner_decision": p,
            "owner_decision_sha256": decision.digest,
            "owner_action": p["chosen_action"],
            "owner_policy_id": p["policy_id"],
            "model_sha256": p["model_sha256"],
            "forecast_role": "calibration_only",
            "policy_value_allowed": False,
            "observed_policy_gain": None,
            "owner_action_authority": "caller_declared_not_native_authorization",
            "source_provenance_authenticated": False,
            "timing_scope": "internal decision_at is shadow freeze time; owner selection time is unobserved",
        }
    )


def _freeze(snapshot_path, **options):
    # The legacy schema is used only inside a private temporary directory for
    # existing validation/effect bindings; it is never the public shadow file.
    with TemporaryDirectory(prefix="pred-shadow-") as directory:
        decision_path = Path(directory) / "decision.json"
        decision = freeze_owner_decision(decision_path, snapshot_path, **options)
    return _wrap(decision)


def predict_owner_history_shadow(
    path,
    snapshot_path,
    checkpoint_path,
    *,
    owner_action,
    owner_policy_id,
    model_kind,
    expected_sha256,
    expected_snapshot_sha256,
    expected_clock_id,
    expected_cursor,
    expected_budget_contract_digest,
    task_group,
    split,
    contract,
    inference_cost,
    source="fixture",
):
    """Create-only freeze of caller action and panel, without dispatch.

    Known charges must fit declared caps; other costs/caps remain unknown.
    Clock/cursor must already be reserved in the host snapshot.
    """
    started_at, wall, cpu = monotonic(), perf_counter(), process_time()
    _text(owner_action)
    _text(owner_policy_id)
    _require(
        isinstance(contract, UtilityContract), "explicit utility contract required"
    )
    _digest(expected_budget_contract_digest)
    _require(
        contract.digest == expected_budget_contract_digest, "budget contract differs"
    )
    _time(inference_cost)
    sources = _sources()
    snapshot = _snapshot_bound(
        snapshot_path, expected_snapshot_sha256, expected_clock_id, expected_cursor
    )
    panel, success, information, encoding = _panel(
        snapshot, checkpoint_path, model_kind, expected_sha256, contract
    )
    prediction_at = monotonic()
    _require(_sources() == sources, "inference source changed")
    meter = _meter(
        snapshot,
        model_kind,
        encoding,
        len(panel),
        sources,
        {
            "started_at": started_at,
            "wall_seconds": perf_counter() - wall,
            "process_cpu_seconds": process_time() - cpu,
            "declared_resource_cost": inference_cost,
        },
        contract,
    )
    _require(started_at <= prediction_at, "inference clock moved backwards")
    artifact = _freeze(
        snapshot_path,
        predictions=panel,
        chosen_action=owner_action,
        policy_id=owner_policy_id,
        model_sha256=expected_sha256,
        task_group=task_group,
        split=split,
        information_set_digest=information,
        contract=contract,
        prediction_at=prediction_at,
        decision_at=monotonic(),
        success_definition=success,
        source=source,
        inference_meter=meter,
        expected_snapshot_sha256=snapshot.digest,
    )
    artifact.save(path)
    return artifact


def validate_owner_history_shadow(
    artifact,
    snapshot_path,
    checkpoint_path,
    *,
    expected_owner_action,
    expected_owner_policy_id,
    expected_task_group,
    expected_split,
    expected_sha256,
    expected_snapshot_sha256,
    expected_clock_id,
    expected_cursor,
    contract,
    expected_source,
):
    """Replay pinned owner, model, input, group/split bindings and entire wrapper.

    Measurements remain unauthenticated; revalidation costs are additional.
    """
    _require(
        isinstance(artifact, Artifact) and isinstance(contract, UtilityContract),
        "typed shadow artifact/contract required",
    )
    p = artifact.payload
    _require(p.get("schema") == SCHEMA, "wrong shadow schema")
    try:
        d, receipt = p["owner_decision"], p["owner_decision"]["inference_meter"]
        for key, expected in (
            ("chosen_action", expected_owner_action),
            ("policy_id", expected_owner_policy_id),
            ("task_group", expected_task_group),
            ("split", expected_split),
            ("source", expected_source),
            ("model_sha256", expected_sha256),
            ("budget_contract_digest", contract.digest),
        ):
            _require(d[key] == expected, "shadow binding differs: " + key)
        snapshot = _snapshot_bound(
            snapshot_path, expected_snapshot_sha256, expected_clock_id, expected_cursor
        )
        sources = _sources()
        panel, success, information, encoding = _panel(
            snapshot, checkpoint_path, receipt["model_kind"], expected_sha256, contract
        )
        _require(_sources() == sources, "inference source changed")
        measured = {key: receipt[key] for key in MEASURED_FIELDS}
        meter = _meter(
            snapshot,
            receipt["model_kind"],
            encoding,
            len(panel),
            sources,
            measured,
            contract,
        )
        _require(meter["started_at"] <= d["prediction_at"], "inference clock differs")
        rebuilt = _freeze(
            snapshot_path,
            predictions=panel,
            chosen_action=expected_owner_action,
            policy_id=expected_owner_policy_id,
            model_sha256=expected_sha256,
            task_group=expected_task_group,
            split=expected_split,
            information_set_digest=information,
            contract=contract,
            prediction_at=d["prediction_at"],
            decision_at=d["decision_at"],
            success_definition=success,
            source=expected_source,
            inference_meter=meter,
            expected_snapshot_sha256=snapshot.digest,
        )
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("malformed shadow artifact") from error
    _require(rebuilt.encoded == artifact.encoded, "shadow replay differs")
    return artifact
