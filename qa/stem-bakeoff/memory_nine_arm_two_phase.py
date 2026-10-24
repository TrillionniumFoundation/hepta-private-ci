"""Two-stage, source-first A--I preregistration reconciliation (SHADOW_ONLY).

A trained Head digest cannot honestly be sealed before it is trained. Stage 1
commits every experiment-design field with only E--I trained material left NULL;
stage 2 fills *only* those material fields and binds complete physical E--I
training receipts before future evaluations begin. Both stages require external
SHA-256 commitments, which are NOT independent signatures or trusted timestamps.

This module authenticates neither the committers nor GPU/CPU measurements, model
origins, future observation dates or gold isolation. No production authority.
"""

from __future__ import annotations

from copy import deepcopy

from memory_nine_arm_gate import (
    ARMS, Refused, audit, canonical, digest, keys, require, sha, validate_plan,
)
from memory_nine_arm_training_cost import verify_training_receipts

PHASE1_SCHEMA = "hepta.memory.a-i.protocol-freeze.v1"
PHASE2_SCHEMA = "hepta.memory.a-i.material-freeze.v1"
TRAINED_ARMS = "EFGHI"
AFTER_TRAINING_FIELDS = ("artifact_sha256", "training_receipt_sha256")
PRODUCER_ID_FIELDS = ("source_sha256", "configuration_sha256", "training_recipe_sha256")


def _validate_producers(producers):
    require(type(producers) is dict and set(producers) == set(ARMS),
            "all nine A-I producer identities required before training")
    for arm in ARMS:
        producer = producers[arm]
        keys(producer, PRODUCER_ID_FIELDS, "source-first producer identity")
        for field in PRODUCER_ID_FIELDS:
            digest(producer[field], f"{arm} {field}")


def _phase_one_projection(materialized):
    """Canonical deletion of ONLY hashes unknowable before training.

    This projection is not a legal final qualification plan. Its NULLs must
    never be replaced with fabricated 'already trained' SHA values in a report.
    """
    result = deepcopy(materialized)
    require(type(result) is dict and type(result.get("arms")) is dict,
            "invalid experiment arm inventory")
    require(set(result["arms"]) == set(ARMS), "nine arms required")
    for arm in TRAINED_ARMS:
        require(type(result["arms"][arm]) is dict, "invalid training arm")
        for field in AFTER_TRAINING_FIELDS:
            require(field in result["arms"][arm], "missing after-training identity")
            result["arms"][arm][field] = None
    return result


def _verify_design(design):
    require(type(design) is dict and type(design.get("arms")) is dict,
            "missing frozen source-first design")
    require(set(design["arms"]) == set(ARMS), "nine design arms required")
    # All values, including unrelated learner/reader/source budgets, get the
    # inherited full-plan validator. Hashes below are INTERNAL fake stand-ins;
    # they are never accepted as model bytes, returned or written to disk.
    probe = deepcopy(design)
    for arm in TRAINED_ARMS:
        require(type(probe["arms"][arm]) is dict,
                "training arm must be a mapping")
        for field in AFTER_TRAINING_FIELDS:
            require(field in probe["arms"][arm]
                    and probe["arms"][arm][field] is None,
                    "trained material was improperly predeclared")
            probe["arms"][arm][field] = sha(
                ("HEPTA:DESIGN-VALIDATION-ONLY:" + arm + ":" + field).encode()
            )
    validate_plan(probe)


def validate_phase1(phase1):
    keys(phase1, ("schema", "design", "producer_identities",
                  "withheld_gold_commitment_sha256", "label_separation_policy"),
         "phase-1 preregistration")
    require(phase1["schema"] == PHASE1_SCHEMA, "phase-1 version")
    require(phase1["label_separation_policy"] == "gold_unavailable_to_producers",
            "future gold not isolated by policy")
    digest(phase1["withheld_gold_commitment_sha256"],
           "externally withheld gold commitment")
    _validate_producers(phase1["producer_identities"])
    _verify_design(phase1["design"])


def validate_phase2(phase2):
    keys(phase2, ("schema", "phase1_sha256", "materialized_plan",
                  "materialized_plan_sha256", "training_package",
                  "training_package_sha256", "evaluation_start_cut_sha256",
                  "model_custody_receipt_sha256", "executed_producer_identities"),
         "phase-2 material seal")
    require(phase2["schema"] == PHASE2_SCHEMA, "phase-2 version")
    for field in ("phase1_sha256", "materialized_plan_sha256",
                  "training_package_sha256", "evaluation_start_cut_sha256",
                  "model_custody_receipt_sha256"):
        digest(phase2[field], field)
    _validate_producers(phase2["executed_producer_identities"])
    validate_plan(phase2["materialized_plan"])
    require(phase2["materialized_plan_sha256"]
            == sha(canonical(phase2["materialized_plan"])),
            "materialized full-plan hash mismatch")
    require(phase2["training_package_sha256"]
            == sha(canonical(phase2["training_package"])),
            "complete training inventory hash mismatch")


def verify_two_phase(phase1, phase2, *, trusted_phase1_sha256,
                     trusted_phase2_sha256):
    """Fail closed on any design/budget/source drift or borrowed training work.

    'trusted' means provided by the independent caller. This function does NOT
    verify who created that pin, the chronological order of the pins, or an
    independent evaluator's signature; those remain hard promotion blockers.
    """
    digest(trusted_phase1_sha256, "externally pinned phase-1 digest")
    digest(trusted_phase2_sha256, "externally pinned phase-2 digest")
    validate_phase1(phase1)
    validate_phase2(phase2)
    require(sha(canonical(phase1)) == trusted_phase1_sha256,
            "original preregistration changed after external freeze")
    require(sha(canonical(phase2)) == trusted_phase2_sha256,
            "trained material changed after external freeze")
    require(phase2["phase1_sha256"] == trusted_phase1_sha256,
            "phase-2 seal does not descend from frozen preregistration")
    material = phase2["materialized_plan"]
    # Python dict equality equates int 2 and float 2.0 (and bool with int),
    # but those serialize to DIFFERENT original protocol bytes. Compare the
    # frozen canonical encodings, not type-coercing native object equality.
    require(canonical(_phase_one_projection(material))
            == canonical(phase1["design"]),
            "training changed protocol/reader/cohort/source/budget/arm design")
    require(canonical(phase2["executed_producer_identities"])
            == canonical(phase1["producer_identities"]),
            "executed producer source/config differs from pre-registered source")
    # Distinct physical trained-artifact identities: no aliasing G/H/I to an
    # unchanged predecessor while self-reporting routing/graph/evolution work.
    for field in AFTER_TRAINING_FIELDS:
        hashes = [material["arms"][arm][field] for arm in TRAINED_ARMS]
        require(len(set(hashes)) == len(hashes),
                "trained A-I arms borrowed identical physical material")
    training = verify_training_receipts(material, phase2["training_package"])
    require(training["training_budget_reconciled"] is True,
            "actual E-I training budget not reconciled")
    return {
        "schema": PHASE2_SCHEMA + ".audit",
        "phase1_sha256": trusted_phase1_sha256,
        "phase2_sha256": trusted_phase2_sha256,
        "materialized_plan_sha256": phase2["materialized_plan_sha256"],
        "training_package_sha256": phase2["training_package_sha256"],
        "source_first_design_immutable": True,
        "physical_training_receipt_arithmetic_reconciled": True,
        "independent_source_owner_authenticated": False,
        "independent_freeze_chronology_authenticated": False,
        "independent_model_origin_authenticated": False,
        "independent_future_evaluation_authenticated": False,
        "scientific_superiority_established": False,
        "production_activation_allowed": False,
        "authority": "DENY_ALL",
        "status": "HOLD_NO_GO",
    }


def audit_with_two_phase(plan_phase1, material_phase2, observations, judgments, *,
                         trusted_phase1_sha256, trusted_phase2_sha256):
    """Connect the two-stage source/material seal to the *real* A-I audit.

    Neither success of the syntactic freeze nor a full synthetic A-I census
    can turn an unauthenticated physical/semantic result into qualification.
    """
    freeze = verify_two_phase(plan_phase1, material_phase2,
                              trusted_phase1_sha256=trusted_phase1_sha256,
                              trusted_phase2_sha256=trusted_phase2_sha256)
    report = audit(material_phase2["materialized_plan"], observations, judgments,
                   material_phase2["materialized_plan_sha256"],
                   training_receipts=material_phase2["training_package"])
    require(report["status"] == "HOLD_NO_GO"
            and report["production_accepted"] is False,
            "research plan unexpectedly granted runtime admission")
    report["two_phase_freeze_audit"] = freeze
    report["blockers"] = list(report["blockers"]) + [
        "independent phase-1/phase-2 chronological attestations not authenticated",
        "future observation source owner / evaluator signatures not authenticated",
    ]
    return report
