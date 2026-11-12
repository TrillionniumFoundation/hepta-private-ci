"""Freeze typed one-step forecasts from a pinned, still-prospective history.

This adapter prepares a choice only. Source hashes, clock IDs and cursors bind
caller declarations; they do not authenticate an owner or authorize dispatch.
Observational marginals do not identify unexecuted-action causal outcomes.
"""

from hashlib import sha256
from pathlib import Path
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
from .observed_policy import choose_fixed1
from .owner_bridge import freeze_owner_decision, owner_information_digest

SOURCE_FILES = (
    "__init__.py",
    "action_history.py",
    "contracts.py",
    "models.py",
    "native_ledger.py",
    "observed_evaluation.py",
    "observed_gru.py",
    "observed_history.py",
    "observed_models.py",
    "observed_policy.py",
    "owner_bridge.py",
    "owner_history_predict.py",
)


def predict_owner_history_choice(
    path,
    snapshot_path,
    checkpoint_path,
    *,
    model_kind,
    expected_sha256,
    expected_snapshot_sha256,
    expected_clock_id,
    expected_cursor,
    task_group,
    split,
    contract,
    inference_cost,
    source="fixture",
):
    """Load a typed checkpoint, forecast one panel and freeze the actual choice.

    The caller supplies its host/boot monotonic clock and reserved arrival
    cursor; these must exactly match the pinned snapshot. The same process
    clock must measure inference. A summary MLP sees last/mean/length once;
    the current GRU implementation re-encodes history per candidate. Loader
    validation probes and candidate inference calls are counted separately.
    All preparation through the final source check is metered. Freeze IO and
    later owner/observer work remain outside this incomplete physical ledger.
    """
    started_at, wall, cpu = monotonic(), perf_counter(), process_time()
    _require(
        type(model_kind) is str and model_kind in ("empirical", "mlp", "gru"),
        "explicit model kind required",
    )
    _digest(expected_sha256)
    _digest(expected_snapshot_sha256)
    _text(expected_clock_id)
    _integer(expected_cursor)
    _time(inference_cost)
    _require(
        isinstance(contract, UtilityContract), "explicit utility contract required"
    )
    source_hashes = {
        name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in SOURCE_FILES
    }
    snapshot = Artifact.read(snapshot_path)
    _require(snapshot.digest == expected_snapshot_sha256, "snapshot bytes differ")
    p = _snapshot(snapshot)
    _require(p["clock_id"] == expected_clock_id, "snapshot clock differs")
    _require(p["cursor"] == expected_cursor, "snapshot arrival cursor differs")
    _require(p["decision_at"] <= started_at, "snapshot is from a future clock")
    _require(
        not p["collection"]["rows"]["attempts"],
        "attempt already visible; not prospective",
    )
    loader = ObservedGRU if model_kind == "gru" else ObservedModel
    try:
        model = loader.load(checkpoint_path, expected_sha256=expected_sha256)
        meta = model.metadata
        _require(meta["kind"] == model_kind, "checkpoint kind differs")
        _require(
            meta["duration_unit"] == "seconds"
            and meta["cost_unit"] == contract.cost_unit,
            "checkpoint target units differ",
        )
        _text(meta["success_definition"], 512)
        features, names = p["features"][-1], p["feature_names"]
        if model_kind == "mlp":
            features, names = summarize_history(p["features"], names)
            encoding = "history_last_mean_length_v1"
        elif model_kind == "gru":
            features = p["features"]
            encoding = "observed_history_v1"
        else:
            encoding = "last_observed_row"
        _require(
            meta["feature_encoding"] == encoding and meta["feature_names"] == names,
            "checkpoint history feature schema differs",
        )
        actions = meta["action_ids"]
        _require(
            type(actions) is list and 1 <= len(actions) <= 64,
            "bounded checkpoint action panel required",
        )
        _require(
            set(actions) == set(meta["training"]["action_counts"]),
            "checkpoint panel contains unsupported actions",
        )
        # This also checks every action is legal in the actual snapshot schema.
        information = owner_information_digest(
            snapshot, actions, contract, meta["success_definition"]
        )
        predictions = {action: model.predict(features, action) for action in actions}
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("malformed typed checkpoint") from error
    prediction_at = monotonic()
    choice = choose_fixed1(
        predictions,
        contract,
        preparation_seconds=perf_counter() - wall,
        preparation_cost=inference_cost,
    )
    _require(
        all(
            sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == digest
            for name, digest in source_hashes.items()
        ),
        "inference source changed",
    )
    elapsed = perf_counter() - wall
    calls = len(actions)
    meter = {
        "started_at": started_at,
        "wall_seconds": elapsed,
        "process_cpu_seconds": process_time() - cpu,
        "declared_resource_cost": inference_cost,
        "model_kind": model_kind,
        "feature_encoding": encoding,
        "history_rows": len(p["features"]),
        "snapshot_sha256": snapshot.digest,
        "clock_id": expected_clock_id,
        "arrival_cursor": expected_cursor,
        "source_sha256": source_hashes,
        "candidate_prediction_calls": calls,
        "checkpoint_validation_prediction_calls": calls,
        "neural_forward_calls": 0 if model_kind == "empirical" else 2 * calls,
        "recurrent_forward_calls": 2 * calls if model_kind == "gru" else 0,
        "recurrent_steps": calls * (len(p["features"]) + 1)
        if model_kind == "gru"
        else 0,
        "summary_passes": 1 if model_kind == "mlp" else 0,
        "horizon": 1,
        "physical_cost_complete": False,
        "source_provenance_authenticated": False,
        "observed_policy_gain": None,
        "scope": "source/snapshot/checkpoint validation and panel through source check; excludes freeze IO and downstream work",
    }
    return freeze_owner_decision(
        path,
        snapshot_path,
        predictions=predictions,
        chosen_action=choice["chosen_action"],
        policy_id=model_kind + ":history:Fixed1",
        model_sha256=expected_sha256,
        task_group=task_group,
        split=split,
        information_set_digest=information,
        contract=contract,
        prediction_at=prediction_at,
        decision_at=monotonic(),
        success_definition=meta["success_definition"],
        source=source,
        inference_meter=meter,
        expected_snapshot_sha256=snapshot.digest,
    )
