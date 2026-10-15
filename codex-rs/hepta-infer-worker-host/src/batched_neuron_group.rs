//! Read-only exact group-signature proposal for the ORIGINAL native Batch owner.
//!
//! This module is deliberately under batched_neuron, not a second executor.
//! The resulting FinalUseBinding MUST be signed by the independently operated
//! issuer; this function supplies no signature, nonce, loaded-model proof,
//! original Evidence WAL effect intent, CNS currentness or production consent.
//!
//! A batch of separately signed Head members is NOT thereby an authorized
//! combined group operation. This contract names the additional exact ordered
//! group grant required for future original-owner admission.

use std::collections::BTreeSet;
use std::str::FromStr;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_infer_core::SharedFeatureBufferV1;
use codex_hepta_infer_core::microbatch::MAX_MICROBATCH_SIZE;
use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::BatchWorkerErrorV1;
use super::neuron_batch_final_use_binding_with_slice_v1;
use crate::model_worker::NeuronFeatureRequest;

/// Original Worker pending metadata plus its already sealed, immutable Q24
/// input. No additional Q24 Vec is created by the aggregate signature path.
#[derive(Clone, Copy)]
pub struct NativeBatchGroupMemberV1<'a> {
    pub key: &'a MicrobatchKeyV1,
    pub request: &'a NeuronFeatureRequest,
    pub feature: &'a SharedFeatureBufferV1,
}

/// This is a signature *proposal*, NOT a capability, effect receipt or
/// durable batch authorization. A real signer must approve exactly these
/// bytes, and final-use MUST independently check all signed member grants.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NonAuthorizingNativeBatchGroupV1 {
    pub ordered_digest: Digest32,
    pub group_binding: FinalUseBinding,
    pub member_bindings: Vec<FinalUseBinding>,
    pub authority: AuthorityPosture,
}

/// Produce the exact additional FinalUseBinding for one proposed physical
/// cohort. The signer may deny it. No input here is automatically trusted,
/// and the legacy Batch scheduler/executor does not consume this proof yet.
///
/// A complete physical-effect integration must source members from the
/// original scheduler, revalidate the live Control/CNS and ArtifactLoad
/// owners, include one independent aggregate grant in the SAME original
/// durable FinalUseAuthority::claim_batch, and cross ONE driver boundary
/// inside the original with_verified_effect_batch guard.
pub fn prepare_original_native_batch_group_v1(
    worker_id: &str,
    model_id: &str,
    members: &[NativeBatchGroupMemberV1<'_>],
) -> Result<NonAuthorizingNativeBatchGroupV1, BatchWorkerErrorV1> {
    if members.len() < 2 || members.len() > MAX_MICROBATCH_SIZE {
        return Err(BatchWorkerErrorV1::Capacity);
    }
    if StableId::new(worker_id.to_string()).is_err()
        || StableId::new(model_id.to_string()).is_err()
    {
        return Err(BatchWorkerErrorV1::InvalidRequest);
    }
    let destination = format!("neuron.native-batch:{model_id}");
    if destination.len() > 128 {
        return Err(BatchWorkerErrorV1::InvalidBinding);
    }

    let selected = members[0].key;
    if selected.route_fence == 0 || selected.authority_epoch == 0 {
        return Err(BatchWorkerErrorV1::InvalidBinding);
    }
    let mut ordered = b"hepta.infer-worker.original-native-cohort.v1".to_vec();
    add_field(&mut ordered, worker_id)?;
    add_field(&mut ordered, model_id)?;
    ordered.extend_from_slice(selected.model_digest.as_array());
    ordered.extend_from_slice(&selected.generation.get().to_be_bytes());
    ordered.extend_from_slice(&selected.authority_epoch.to_be_bytes());
    ordered.extend_from_slice(
        &u32::try_from(members.len())
            .map_err(|_| BatchWorkerErrorV1::Capacity)?
            .to_be_bytes(),
    );

    let mut scopes = b"hepta.infer-worker.original-native-cohort-scopes.v1".to_vec();
    let mut payloads = b"hepta.infer-worker.original-native-cohort-payloads.v1".to_vec();
    let mut seen_requests = BTreeSet::new();
    let mut seen_reservations = BTreeSet::new();
    let mut bindings = Vec::with_capacity(members.len());

    for member in members {
        let auth = &member.request.authorization;
        if member.key.route_fence == 0
            || !selected.physical_compatible_with(member.key)
            || member.key.scope_id.as_str().is_empty()
            || auth.cancelled
            || auth.deadline_ms == 0
            || auth.maximum_tokens == 0
            || auth.reservation_model_digest != auth.model_digest
            || Digest32::from_str(&auth.model_digest).ok() != Some(member.key.model_digest)
            || StableId::new(auth.request_id.clone()).is_err()
            || StableId::new(auth.reservation_id.clone()).is_err()
            || [
                &member.request.encoder_digest,
                &member.request.head_digest,
                &member.request.weights_digest,
                &member.request.input_digest,
            ]
            .into_iter()
            .any(|digest| Digest32::from_str(digest).is_err())
            || auth.reservation_maximum_tokens < auth.maximum_tokens
            || auth.request_id.is_empty()
            || auth.reservation_id.is_empty()
            || !seen_requests.insert(auth.request_id.as_str())
            || !seen_reservations.insert(auth.reservation_id.as_str())
            || !member.request.feature_vector_q24.is_empty()
        {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        let original_binding = neuron_batch_final_use_binding_with_slice_v1(
            worker_id,
            member.key,
            member.request,
            member.feature.as_slice(),
        )?;
        add_field(&mut ordered, &auth.request_id)?;
        add_field(&mut ordered, &auth.reservation_id)?;
        add_field(&mut ordered, member.key.scope_id.as_str())?;
        ordered.extend_from_slice(&member.key.route_fence.to_be_bytes());
        add_field(&mut ordered, &member.request.head_digest)?;
        add_field(&mut ordered, &member.request.weights_digest)?;
        add_field(&mut ordered, &original_binding.subject_id)?;
        add_field(&mut ordered, &original_binding.destination_id)?;
        ordered.extend_from_slice(&original_binding.request_sha256);
        ordered.extend_from_slice(&original_binding.scope_sha256);
        ordered.extend_from_slice(&original_binding.payload_sha256);

        scopes.extend_from_slice(&original_binding.scope_sha256);
        payloads.extend_from_slice(&original_binding.payload_sha256);
        bindings.push(original_binding);
    }
    let ordered_digest = Digest32::of_bytes(&ordered);
    Ok(NonAuthorizingNativeBatchGroupV1 {
        ordered_digest,
        group_binding: FinalUseBinding {
            subject_id: worker_id.to_string(),
            destination_id: destination,
            request_sha256: ordered_digest.into_array(),
            scope_sha256: Digest32::of_bytes(&scopes).into_array(),
            payload_sha256: Digest32::of_bytes(&payloads).into_array(),
        },
        member_bindings: bindings,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn add_field(bytes: &mut Vec<u8>, field: &str) -> Result<(), BatchWorkerErrorV1> {
    let data = field.as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(data.len())
            .map_err(|_| BatchWorkerErrorV1::Capacity)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(data);
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "batched_neuron_group_tests.rs"]
mod tests;
