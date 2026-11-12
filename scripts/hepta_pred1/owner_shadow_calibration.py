"""Join only the original owner action's independent effect to a shadow panel.

Retain UNKNOWN/censoring and the observer's incomplete ledger. This artifact
cannot enter ordinary observed-policy readers, and no counterfactual action is
labeled. All identities and evidence remain unauthenticated declarations.
"""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from .native_ledger import Artifact, _collection, _digest, _identity, _integer, _require
from .observed_evaluation import score_forecast
from .owner_bridge import join_owner_effect, observed_from_artifact
from .owner_history_shadow import (
    SOURCE_FILES as SHADOW_SOURCE_FILES,
    validate_owner_history_shadow,
)

SOURCE_FILES = (*SHADOW_SOURCE_FILES, "owner_shadow_calibration.py")
SCHEMA = "pred1-owner-shadow-calibration-v1"


def _sources():
    return {
        name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in SOURCE_FILES
    }


def _calibration(
    shadow_path,
    snapshot_path,
    checkpoint_path,
    owner_collection,
    effect,
    *,
    expected_shadow_sha256,
    **expected,
):
    _digest(expected_shadow_sha256)
    sources = _sources()
    shadow = Artifact.read(shadow_path)
    _require(shadow.digest == expected_shadow_sha256, "shadow bytes differ")
    validate_owner_history_shadow(shadow, snapshot_path, checkpoint_path, **expected)
    collection = _collection(owner_collection)
    for rows in collection["rows"].values():
        for row in rows:
            _integer(row["attempt"], 1, 1_000_000)
    _require(isinstance(effect, Artifact), "immutable effect artifact required")
    _identity(effect.payload["identity"])
    decision = Artifact.make(shadow.payload["owner_decision"])
    # Keep the existing effect.digest binding intact; never rewrite the witness
    # to fit a different action, decision or model policy.
    with TemporaryDirectory(prefix="pred-shadow-effect-") as directory:
        root = Path(directory)
        decision_path = root / "decision.json"
        decision.save(decision_path)
        joined = join_owner_effect(
            root / "joined.json", decision_path, owner_collection, effect
        )
    observed = observed_from_artifact(joined)
    executed = observed.executed_action == observed.chosen_action
    _require(_sources() == sources, "calibration source changed")
    p = decision.payload
    return Artifact.make(
        {
            "schema": SCHEMA,
            "shadow_sha256": shadow.digest,
            "owner_decision_sha256": decision.digest,
            "snapshot_sha256": p["snapshot_digest"],
            "owner_collection_sha256": owner_collection.digest,
            "effect_sha256": effect.digest,
            "owner_action": observed.chosen_action,
            "owner_policy_id": observed.policy_id,
            "model_sha256": p["model_sha256"],
            "task_group": observed.task_group,
            "split": observed.split,
            "identity": p["identity"],
            "clock_id": observed.clock_id,
            "snapshot_cursor": p["snapshot_cursor"],
            "input_cutoff": p["input_cutoff"],
            "prediction_at": observed.prediction_at,
            "shadow_frozen_at": observed.decision_at,
            "target_schema_sha256": p["target_schema_sha256"],
            "success_definition": p["success_definition"],
            "cost_unit": p["utility_contract"]["cost_unit"],
            "budget_contract_digest": observed.budget_contract_digest,
            "executed_action": observed.executed_action,
            "execution_ref": observed.execution_ref,
            "observer_ref": effect.payload["observer_ref"],
            "evidence": asdict(observed.evidence),
            "costs": dict(observed.costs),
            "full_wall_seconds": observed.full_wall_seconds,
            "forecast_scores": score_forecast(observed.prediction, observed.evidence)
            if executed
            else None,
            "source": observed.source,
            "source_sha256": sources,
            "source_provenance_authenticated": False,
            "owner_authorization_authenticated": False,
            "forecast_role": "calibration_only",
            "policy_value_allowed": False,
            "observed_policy_gain": None,
            "physical_cost_complete": False,
            "scope": "only executed owner-action calibration; original owner choice time unknown; observer ledger excludes unmeasured join/replay costs",
        }
    )


def join_owner_shadow_effect(
    path,
    shadow_path,
    snapshot_path,
    checkpoint_path,
    owner_collection,
    effect,
    *,
    expected_shadow_sha256,
    **expected,
):
    """Create-only calibration artifact after strict panel and existing effect joins.

    The independent witness must bind owner_decision_sha256 published inside
    the original shadow artifact. A wrapper digest cannot substitute for it.
    expected arguments are the external bindings required by the panel validator.
    """
    artifact = _calibration(
        shadow_path,
        snapshot_path,
        checkpoint_path,
        owner_collection,
        effect,
        expected_shadow_sha256=expected_shadow_sha256,
        **expected,
    )
    artifact.save(path)
    return artifact


def validate_owner_shadow_calibration(
    artifact,
    shadow_path,
    snapshot_path,
    checkpoint_path,
    owner_collection,
    effect,
    *,
    expected_shadow_sha256,
    **expected,
):
    """Recompute both joins and scores; rehashed schema/label/identity changes fail."""
    _require(
        isinstance(artifact, Artifact) and artifact.payload.get("schema") == SCHEMA,
        "wrong shadow calibration schema",
    )
    rebuilt = _calibration(
        shadow_path,
        snapshot_path,
        checkpoint_path,
        owner_collection,
        effect,
        expected_shadow_sha256=expected_shadow_sha256,
        **expected,
    )
    _require(rebuilt.encoded == artifact.encoded, "shadow calibration replay differs")
    return artifact
