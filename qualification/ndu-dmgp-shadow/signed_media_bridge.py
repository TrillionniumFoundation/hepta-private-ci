"""Compose independent signed pair with original-byte decoded-media evidence.

Research-only, offline, fail-closed bridge. Both observer and host-meter must
SIGN the same frozen media-plan digest and newly observed original media/content
digest. The plan identity comes from a caller-supplied out-of-band trust pin.
True semantic perception, physical calibration and key custody remain unproven.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from decoded_media_audit import (
    DecodedMediaRejected, _sha, audit_decoded_media,
)
from signed_evidence import (
    EvidenceRejected, _read_key_der, canonical_json, verify_pair,
)


def plan_fingerprint(plan: dict) -> str:
    """Freeze an unambiguous plan *before* observed outputs exist."""
    try:
        return hashlib.sha256(
            b"hepta.ndu-dmgp.media-plan.freeze.v1\x00" + canonical_json(plan)
        ).hexdigest()
    except (EvidenceRejected, TypeError, ValueError) as exc:
        raise DecodedMediaRejected("invalid frozen external media plan") from exc


def verify_signed_decoded_media(
    entry: dict, plan: dict, output_manifest: dict,
    *, asset_root: Path, observer_public_key: Path, meter_public_key: Path,
    trusted_plan_digest: str, expected_objective: str,
    expected_evaluator_digest: str, expected_device_digest: str,
    training_cutoff: int,
) -> dict:
    """Verify original bytes AND authentic cross-role reference binding.

    The two signers' roles must be independently authorized elsewhere. No
    influence on production authorization or selection is returned.
    """
    if type(plan) is not dict or "max_skew_ms" not in plan:
        raise DecodedMediaRejected("missing registered media-plan time profile")
    if not (_sha(trusted_plan_digest) and trusted_plan_digest != "0" * 64):
        raise DecodedMediaRejected("missing out-of-band plan pin")
    # Order matters: external plan is frozen before reading any run content;
    # no observed media can amend the registered objective or source roster.
    if plan_fingerprint(plan) != trusted_plan_digest:
        raise DecodedMediaRejected("untrusted or altered frozen media plan")
    if hashlib.sha256(_read_key_der(observer_public_key)).digest() == hashlib.sha256(
            _read_key_der(meter_public_key)).digest():
        raise EvidenceRejected("observer and meter key role collision")
    row = verify_pair(
        entry, observer_public_key, meter_public_key,
        expected_objective=expected_objective,
        expected_evaluator_digest=expected_evaluator_digest,
        expected_device_digest=expected_device_digest,
        training_cutoff=training_cutoff,
        max_av_skew_ms=plan["max_skew_ms"],
    )
    if entry["observer"]["payload"]["objective_digest"] != expected_objective:
        raise DecodedMediaRejected("objective and media plan mismatch")
    if (row["input_digest"] != plan.get("input_digest")
            or entry["observer"]["payload"]["generation"] != plan.get("generation")
            or plan.get("objective_digest") != expected_objective):
        raise DecodedMediaRejected("signed execution and frozen media plan mismatch")
    report = audit_decoded_media(plan, output_manifest, asset_root=asset_root)
    obs = entry["observer"]["payload"]
    meter = entry["meter"]["payload"]
    for signer in (obs, meter):
        if (set(("media_plan_digest", "decoded_media_content_digest"))
                - set(signer)
                or signer["media_plan_digest"] != trusted_plan_digest
                or signer["decoded_media_content_digest"] != report["content_digest"]):
            raise EvidenceRejected("signer does not bind verified physical media bytes")
    if set(obs["modalities"]) != set(output_manifest["outputs"][i]["modality"]
                                   for i in range(len(output_manifest["outputs"]))):
        raise EvidenceRejected("observer claims different decoded output modalities")
    return {
        "schema": "hepta.ndu-dmgp.signed-decoded-media-bridge.v1",
        "run_id": row["run_id"],
        "trace_digest": row["trace_digest"],
        "frozen_plan_digest": trusted_plan_digest,
        "decoded_content_digest": report["content_digest"],
        "signed_observer_and_meter_binding_verified": True,
        "original_media_bytes_decoded": True,
        "observer_independent_perceptual_truth_verified": False,
        "original_model_generated_outputs_verified": False,
        "device_energy_calibration_verified": False,
        "external_signer_key_custody_verified": False,
        "production_blockers_closed": False,
        "no_promotion_authority": True,
    }