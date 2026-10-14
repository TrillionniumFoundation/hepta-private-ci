"""Fail-closed identity fence for the first executed public Stem/Cell study.

The pinned values were read from the completed GitHub Actions run 38521871187
(artifact 11875264069, commit 1f231584124e62a11cf932d937ea4a7ad2437ab2)
before the new val2 holdout model evaluation. These SHA256/Q24 lineage digests
identify previously computed local tensors; they do NOT sign/model-authenticate
Hugging Face origin, confer FinalUse, or establish longitudinal learning.
"""
from __future__ import annotations

from collections.abc import Mapping

# Source: executed public Laya/Gemma paired report, not a fixture estimate.
HISTORICAL = {
    "source_run": 38521871187,
    "source_commit": "1f231584124e62a11cf932d937ea4a7ad2437ab2",
    "original_panel_digest": "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4",
    "gemma_revision": "914f7f89142e33e77833254d9c9b90c3cef7303b",
    "laya_revision": "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851",
    "gemma_stem_digest": "67c4b70b017cf5fce950b2b57594a8dc3e1440d21e49ed4781cd71ba444c7017",
    "frozen_head_digest": "c59acb59eb450623f69b3e50eb8d3615cea0901843c6e58661036c7a14851061",
    "trained_head_digest": "007420eef8999ea6096d74d390c910f0bcfb5e2ae44b3bd717a0e369d7fa2e0e",
    "head_parameters": 2018,
    "head_optimizer_steps": 40,
    "training_seed": 17,
    "laya_parameters": 421293827,
    "archived_zip_sha256": "cbedc87a883b34bc26447fab73f425469a3baa1f76afb35361abb0a446bda75d",
}


class HistoricalIdentityError(ValueError):
    """Mismatch between a fresh candidate and previously measured tensors."""


def check_values(*, original_panel_digest: str, gemma_revision: str,
                 stem_digest: str, frozen_head_digest: str,
                 trained_head_digest: str, head_parameters: int,
                 head_optimizer_steps: int, training_seed: int) -> dict:
    observed = {
        "original_panel_digest": original_panel_digest,
        "gemma_revision": gemma_revision,
        "gemma_stem_digest": stem_digest,
        "frozen_head_digest": frozen_head_digest,
        "trained_head_digest": trained_head_digest,
        "head_parameters": head_parameters,
        "head_optimizer_steps": head_optimizer_steps,
        "training_seed": training_seed,
    }
    for key, value in observed.items():
        if type(value) is not type(HISTORICAL[key]) or value != HISTORICAL[key]:
            raise HistoricalIdentityError(f"old pretrained Stem/Head not preserved: {key}")
    return {
        "schema": "hepta.stem.historical-weights-lock.v1",
        "executed_reference_run": HISTORICAL["source_run"],
        "executed_reference_commit": HISTORICAL["source_commit"],
        "reference_archive_sha256": HISTORICAL["archived_zip_sha256"],
        "reference_local_tensor_lineage_matched": True,
        "model_origin_independently_authenticated": False,
        "outcome_independently_authenticated": False,
        "production_promotion": "DENY_ALL",
    }


def check_reports(*, original_panel_digest: str,
                  original_gemma: list[dict], original_laya: dict) -> dict:
    if (not isinstance(original_gemma, list) or len(original_gemma) != 2
            or not isinstance(original_laya, Mapping)):
        raise HistoricalIdentityError("original public arm bundle missing")
    by_arm = {r.get("arm_id"): r for r in original_gemma if isinstance(r, dict)}
    if set(by_arm) != {"gemma2_frozen_head", "gemma2_trained_head"}:
        raise HistoricalIdentityError("missing or duplicated original Head arm")
    frozen = by_arm["gemma2_frozen_head"].get("metadata")
    trained = by_arm["gemma2_trained_head"].get("metadata")
    laya = original_laya.get("metadata")
    if not all(isinstance(x, dict) for x in (frozen, trained, laya)):
        raise HistoricalIdentityError("original Head metadata missing")
    if (frozen.get("optimizer_steps") != 0 or
            frozen.get("head_parameters") != trained.get("head_parameters") or
            frozen.get("stem_digest") != trained.get("stem_digest") or
            frozen.get("revision") != trained.get("revision") or
            laya.get("revision") != HISTORICAL["laya_revision"] or
            laya.get("model_parameter_count") != HISTORICAL["laya_parameters"] or
            laya.get("trainable_parameters") != 0):
        raise HistoricalIdentityError("reference model or frozen control mismatch")
    return check_values(
        original_panel_digest=original_panel_digest,
        gemma_revision=trained.get("revision"),
        stem_digest=trained.get("stem_digest"),
        frozen_head_digest=frozen.get("head_artifact_digest"),
        trained_head_digest=trained.get("head_artifact_digest"),
        head_parameters=trained.get("head_parameters"),
        head_optimizer_steps=trained.get("optimizer_steps"),
        training_seed=HISTORICAL["training_seed"],
    )
