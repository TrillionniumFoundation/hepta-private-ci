//! Complete, bounded row commitments. Signing a hash of this versioned
//! preimage avoids the evidence verifier's 1 MiB transport limit without
//! silently truncating rows. The materialization bound is checked first.

use super::MAX_SIGNED_OPERATOR_ROWS;
use super::OperatorDatasetBindingError;
use super::verify_evidence_membership;
use super::verify_tabular_plan_binding;
use crate::TabularOperatorPlanV1;
use crate::WorldModelSampleV1;
use crate::preflight_signed_tabular_v3;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::collections::BTreeSet;

type BindingError = OperatorDatasetBindingError;

/// Public signer-side canonicalization. The observer must obtain this context
/// from the authoritative owner, not construct a verifier from submitted keys.
/// V1 detached signatures are intentionally not accepted by the V3 owner API.
pub fn tabular_training_signing_payload_v2(
    plan: &TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
    owner: &LedgerWriter,
) -> Result<Vec<u8>, BindingError> {
    // This must precede evidence-set allocation and row canonicalization.
    preflight_signed_tabular_v3(plan)?;
    if receipt.snapshot.source_record_digests.len() > MAX_SIGNED_OPERATOR_ROWS {
        return Err(BindingError::Bounds);
    }
    verify_tabular_plan_binding(plan, receipt)?;
    let mut bytes = canonical_tabular_row_semantics_v1(plan, receipt)?;
    bytes.extend_from_slice(&(plan.minimum_samples_per_cell as u64).to_be_bytes());
    let sensors = canonical_ids(&plan.sensor_ids, &mut bytes)?;
    let actions = canonical_ids(&plan.action_ids, &mut bytes)?;
    if plan
        .samples
        .iter()
        .any(|row| !sensors.contains(&row.sensor_id) || !actions.contains(&row.action_id))
    {
        return Err(BindingError::EvidenceSetMismatch);
    }
    owner_commitment(
        b"hepta.operator.tabular-owner-rows.v2\0",
        bytes,
        receipt,
        owner,
    )
}

pub fn world_model_training_signing_payload_v2(
    model_id: &StableId,
    rows: &[WorldModelSampleV1],
    receipt: &DatasetSnapshotReceiptV3,
    owner: &LedgerWriter,
) -> Result<Vec<u8>, BindingError> {
    if rows.is_empty()
        || rows.len() > MAX_SIGNED_OPERATOR_ROWS
        || receipt.snapshot.source_record_digests.len() > MAX_SIGNED_OPERATOR_ROWS
    {
        return Err(BindingError::Bounds);
    }
    verify_evidence_membership(
        &receipt.snapshot.source_record_digests,
        rows.iter().map(|row| row.evidence_digest),
    )?;
    let bytes = canonical_world_model_row_semantics_v1(model_id, rows, receipt)?;
    owner_commitment(
        b"hepta.operator.world-owner-rows.v2\0",
        bytes,
        receipt,
        owner,
    )
}

fn owner_commitment(
    domain: &[u8],
    rows: Vec<u8>,
    receipt: &DatasetSnapshotReceiptV3,
    owner: &LedgerWriter,
) -> Result<Vec<u8>, BindingError> {
    let verifier = owner.verifier();
    if verifier.objective_digest() != receipt.snapshot.objective_digest
        || verifier.scope_digest() != receipt.producer.scope_digest
        || verifier.authority_epoch() != receipt.producer.authority_epoch
    {
        return Err(BindingError::TrustContextMismatch);
    }
    let mut payload = domain.to_vec();
    for digest in [
        Digest32::of_bytes(&rows),
        receipt.snapshot.dataset_digest,
        receipt.snapshot.ledger_head_digest,
        verifier.trust_digest(),
        owner.trust_distribution_digest(),
        verifier.scope_digest(),
        verifier.objective_digest(),
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    payload.extend_from_slice(&owner.trust_generation().to_be_bytes());
    payload.extend_from_slice(&verifier.authority_epoch().to_be_bytes());
    Ok(payload)
}

fn canonical_ids<'a>(
    values: &'a [StableId],
    bytes: &mut Vec<u8>,
) -> Result<BTreeSet<&'a StableId>, BindingError> {
    let ids = values.iter().collect::<BTreeSet<_>>();
    if ids.len() != values.len() {
        return Err(BindingError::DuplicateIdentity);
    }
    bytes.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for id in &ids {
        push_id(bytes, id);
    }
    Ok(ids)
}

pub(super) fn canonical_tabular_row_semantics_v1(
    plan: &TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
) -> Result<Vec<u8>, BindingError> {
    if plan.samples.is_empty() || plan.samples.len() > MAX_SIGNED_OPERATOR_ROWS {
        return Err(BindingError::Bounds);
    }
    let mut rows = plan.samples.iter().collect::<Vec<_>>();
    rows.sort_by(|a, b| a.sample_id.cmp(&b.sample_id));
    if rows
        .windows(2)
        .any(|pair| pair[0].sample_id == pair[1].sample_id)
    {
        return Err(BindingError::DuplicateIdentity);
    }
    let mut bytes = b"hepta.bellman-operator.verified-tabular-rows.v1".to_vec();
    push_id(&mut bytes, &plan.artifact_id);
    push_id(&mut bytes, &plan.producer_id);
    bytes.extend_from_slice(&plan.generation.get().to_be_bytes());
    for digest in [
        plan.objective_digest,
        plan.dataset_digest,
        plan.sensor_core_digest,
        plan.training_profile_digest,
        receipt.snapshot.ledger_head_digest,
        receipt.correction_cut_digest,
        receipt.revocation_cut_digest,
        receipt.inclusion_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(rows.len() as u64).to_be_bytes());
    for row in rows {
        push_id(&mut bytes, &row.sample_id);
        push_id(&mut bytes, &row.sensor_id);
        push_id(&mut bytes, &row.action_id);
        bytes.extend_from_slice(&row.target.raw().to_be_bytes());
        bytes.extend_from_slice(row.evidence_digest.as_array());
    }
    Ok(bytes)
}

pub(super) fn canonical_world_model_row_semantics_v1(
    model_id: &StableId,
    samples: &[WorldModelSampleV1],
    receipt: &DatasetSnapshotReceiptV3,
) -> Result<Vec<u8>, BindingError> {
    if samples.is_empty() || samples.len() > MAX_SIGNED_OPERATOR_ROWS {
        return Err(BindingError::Bounds);
    }
    let mut rows = samples.iter().collect::<Vec<_>>();
    rows.sort_by(|a, b| a.sample_id.cmp(&b.sample_id));
    if rows
        .windows(2)
        .any(|pair| pair[0].sample_id == pair[1].sample_id)
    {
        return Err(BindingError::DuplicateIdentity);
    }
    let mut bytes = b"hepta.bellman-operator.verified-world-model-rows.v1".to_vec();
    push_id(&mut bytes, model_id);
    for digest in [
        receipt.snapshot.objective_digest,
        receipt.snapshot.dataset_digest,
        receipt.snapshot.ledger_head_digest,
        receipt.correction_cut_digest,
        receipt.revocation_cut_digest,
        receipt.inclusion_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(rows.len() as u64).to_be_bytes());
    for row in rows {
        push_id(&mut bytes, &row.sample_id);
        push_id(&mut bytes, &row.state_id);
        push_id(&mut bytes, &row.action_id);
        push_id(&mut bytes, &row.next_state_id);
        bytes.extend_from_slice(&row.outcome.raw().to_be_bytes());
        bytes.extend_from_slice(row.evidence_digest.as_array());
    }
    Ok(bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}
