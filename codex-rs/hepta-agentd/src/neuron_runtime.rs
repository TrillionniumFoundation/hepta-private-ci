//! Agentd-owned neuron runtime with mandatory signed final-use admission.
//!
//! A bare digest cannot authenticate an NDU read receipt. This product owner
//! denies the old unsigned entry, verifies a pinned issuer grant and consumes
//! one durable nonce for every model invocation. Low-level neuron.tick remains
//! a mechanism for independent qualification, never an Agentd serving port.

use codex_hepta_contracts::{
    FinalUseAuthority, FinalUseBinding, SignedFinalUseGrant,
};
use codex_hepta_neuron::{
    AnchorWitnessStore, InferenceControlModelPort, NeuronInferenceControlPort,
    NeuronRuntime, NeuronRuntimeError, NeuronRuntimeOutputV1, NeuronTickInputV1,
};
use codex_hepta_types::{Digest32, NduSnapshotRefV1, StableId};

pub struct AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    runtime: NeuronRuntime<W>,
    inference_control: P,
    final_use: Option<FinalUseAuthority>,
    neuron_owner_id: Option<StableId>,
}

/// The kernel-authority issuer signs this exact complete binding after
/// independently verifying the NDU owner and selected immutable snapshot.
pub fn neuron_ndu_final_use_binding_v1(
    neuron_owner_id: &StableId,
    input: &NeuronTickInputV1,
    snapshot: &NduSnapshotRefV1,
    authenticated_read_receipt_digest: Digest32,
) -> Result<FinalUseBinding, NeuronRuntimeError> {
    if snapshot.scope_id != input.subject_id
        || snapshot.snapshot_digest != input.ndu_snapshot_digest
        || authenticated_read_receipt_digest.is_zero()
    {
        return Err(NeuronRuntimeError::InvalidInput);
    }
    let tick_digest = input.semantic_digest()?;
    let snapshot_ref_digest = snapshot.semantic_digest()
        .map_err(|_| NeuronRuntimeError::InvalidInput)?;
    let mut payload = b"hepta.agentd.neuron-final-use.v1".to_vec();
    payload.extend_from_slice(tick_digest.as_array());
    payload.extend_from_slice(snapshot_ref_digest.as_array());
    payload.extend_from_slice(authenticated_read_receipt_digest.as_array());
    let owner = neuron_owner_id.as_str().as_bytes();
    payload.extend_from_slice(&(owner.len() as u64).to_be_bytes());
    payload.extend_from_slice(owner);
    Ok(FinalUseBinding {
        subject_id: input.subject_id.to_string(),
        destination_id: neuron_owner_id.to_string(),
        request_sha256: *tick_digest.as_array(),
        scope_sha256: *snapshot_ref_digest.as_array(),
        payload_sha256: *Digest32::of_bytes(&payload).as_array(),
    })
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    /// Legacy source-only constructor deliberately has no serving authority.
    pub fn new(runtime: NeuronRuntime<W>, inference_control: P) -> Self {
        Self {
            runtime,
            inference_control,
            final_use: None,
            neuron_owner_id: None,
        }
    }

    /// Production composition requires independently configured pinned issuer
    /// trust, durable nonce state and a protected revocation frontier.
    pub fn new_authorized(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        neuron_owner_id: StableId,
        final_use: FinalUseAuthority,
    ) -> Self {
        Self {
            runtime,
            inference_control,
            final_use: Some(final_use),
            neuron_owner_id: Some(neuron_owner_id),
        }
    }

    /// The old unsigned entry is not a serving path.
    #[deprecated(note = "unsigned Agentd neuron ticks are denied; use tick_bound")]
    pub fn tick(
        &mut self,
        _input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        Err(NeuronRuntimeError::InvalidInput)
    }

    /// One independently issuer-signed grant permits one snapshot-bound tick.
    /// The token is revalidated at physical effect entry; revocation during
    /// a synchronous invocation is fenced by with_verified_effect.
    pub fn tick_bound(
        &mut self,
        input: NeuronTickInputV1,
        snapshot: &NduSnapshotRefV1,
        authenticated_read_receipt_digest: Digest32,
        signed_grant: &SignedFinalUseGrant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let authority = self.final_use.as_ref().ok_or(NeuronRuntimeError::InvalidInput)?;
        let owner_id = self.neuron_owner_id.as_ref().ok_or(NeuronRuntimeError::InvalidInput)?;
        if signed_grant.grant.authority_epoch != snapshot.revocation_epoch {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        let binding = neuron_ndu_final_use_binding_v1(
            owner_id, &input, snapshot, authenticated_read_receipt_digest,
        )?;
        let token = FinalUseAuthority::claim(authority, signed_grant, &binding)
            .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        FinalUseAuthority::with_verified_effect(authority, token, &binding, || {
            self.runtime.tick_with_ndu_snapshot(
                &mut model, input, snapshot, authenticated_read_receipt_digest,
            )
        })
        .map_err(|_| NeuronRuntimeError::InvalidInput)?
    }

    /// Read-only diagnostics. Mutable runtime/worker access is intentionally
    /// not exposed: it would bypass the exact signed owner entry.
    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
