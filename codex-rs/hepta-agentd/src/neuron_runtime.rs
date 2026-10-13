//! Agentd-owned neuron runtime with mandatory signed final-use admission.
//!
//! A bare digest cannot authenticate an NDU read receipt. This product owner
//! denies the old unsigned entry, verifies a pinned issuer grant and consumes
//! one durable nonce for every model invocation. Low-level neuron.tick remains
//! a mechanism for independent qualification, never an Agentd serving port.

use crate::neuron_ndu_read::NduReadVerifierV1;
use crate::neuron_ndu_read::SignedNduSnapshotReadV1;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::DurableNeuronEffectIntentV1;
use codex_hepta_neuron::NeuronEffectIntentStatusV1;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::NduSnapshotRefV1;
use codex_hepta_types::StableId;

pub struct AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    runtime: NeuronRuntime<W>,
    inference_control: P,
    final_use: Option<FinalUseAuthority>,
    neuron_owner_id: Option<StableId>,
    ndu_read_verifier: Option<NduReadVerifierV1>,
    effect_intent: Option<DurableNeuronEffectIntentV1>,
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
    let snapshot_ref_digest = snapshot
        .semantic_digest()
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
            ndu_read_verifier: None,
            effect_intent: None,
        }
    }

    /// Retained for source compatibility only: lacking the independent durable
    /// business-tick effect journal, tick_bound fails closed. New serving
    /// compositions must use new_authorized_durable instead.
    pub fn new_authorized(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        neuron_owner_id: StableId,
        final_use: FinalUseAuthority,
        ndu_read_verifier: NduReadVerifierV1,
    ) -> Self {
        Self {
            runtime,
            inference_control,
            final_use: Some(final_use),
            neuron_owner_id: Some(neuron_owner_id),
            ndu_read_verifier: Some(ndu_read_verifier),
            effect_intent: None,
        }
    }

    /// The verified NDU read and independent final-use nonce are joined to a
    /// distinct durable tick-intent fence. The caller must obtain this journal
    /// from the Control-owned scope/generation bootstrap, using owner-only
    /// storage whose parent directory entry is durably synchronized.
    pub fn new_authorized_durable(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        neuron_owner_id: StableId,
        final_use: FinalUseAuthority,
        ndu_read_verifier: NduReadVerifierV1,
        effect_intent: DurableNeuronEffectIntentV1,
    ) -> Self {
        Self {
            runtime,
            inference_control,
            final_use: Some(final_use),
            neuron_owner_id: Some(neuron_owner_id),
            ndu_read_verifier: Some(ndu_read_verifier),
            effect_intent: Some(effect_intent),
        }
    }

    /// Read-only reconciliation diagnostics; unresolved work must be
    /// independently inspected, never automatically replayed.
    pub fn effect_intent_status(&self) -> Option<NeuronEffectIntentStatusV1> {
        self.effect_intent.as_ref().map(DurableNeuronEffectIntentV1::status)
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
        signed_read: &SignedNduSnapshotReadV1,
        signed_grant: &SignedFinalUseGrant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let read_verifier = self
            .ndu_read_verifier
            .as_ref()
            .ok_or(NeuronRuntimeError::InvalidInput)?;
        let authenticated_read_receipt_digest = read_verifier
            .verify(signed_read)
            .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        let snapshot = &signed_read.snapshot;
        let input_digest = input.semantic_digest()?;
        let effect_intent = self
            .effect_intent
            .as_ref()
            .ok_or(NeuronRuntimeError::PendingReconciliation)?;
        if !effect_intent.matches_tick_scope(
            &input.subject_id,
            input.objective_digest,
            snapshot.generation,
        ) {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        effect_intent
            .can_prepare(input_digest)
            .map_err(|_| NeuronRuntimeError::PendingReconciliation)?;
        let authority = self
            .final_use
            .as_ref()
            .ok_or(NeuronRuntimeError::InvalidInput)?;
        let owner_id = self
            .neuron_owner_id
            .as_ref()
            .ok_or(NeuronRuntimeError::InvalidInput)?;
        if signed_grant.grant.authority_epoch != snapshot.revocation_epoch {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        let binding = neuron_ndu_final_use_binding_v1(
            owner_id,
            &input,
            snapshot,
            authenticated_read_receipt_digest,
        )?;
        let token = FinalUseAuthority::claim(authority, signed_grant, &binding)
            .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        // Claim persistence may advance past an NDU read cutover/expiry.
        // Consume the nonce but deny the model effect if the live frontier or
        // the protected clock changed while authority was being claimed.
        let still_current = read_verifier
            .verify(signed_read)
            .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        if still_current != authenticated_read_receipt_digest {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        let previous_checkpoint = input.checkpoint_digest;
        let effect_intent = self
            .effect_intent
            .as_mut()
            .ok_or(NeuronRuntimeError::PendingReconciliation)?;
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        let outcome = FinalUseAuthority::with_verified_effect(authority, token, &binding, || {
            // Sync business-tick Prepare while holding the independently
            // verified effect fence, before the physical encoder/Head call.
            // Even a driver error or process crash now leaves an unresolved
            // durable intent. A freshly signed nonce cannot replay that tick.
            effect_intent
                .prepare(input_digest, previous_checkpoint)
                .map_err(|_| NeuronRuntimeError::PendingReconciliation)?;
            self.runtime.tick_with_ndu_snapshot_guarded(
                &mut model,
                input,
                snapshot,
                authenticated_read_receipt_digest,
                || {
                    let observed = read_verifier
                        .verify(signed_read)
                        .map_err(|_| NeuronRuntimeError::NduStaleAfterEffect)?;
                    if observed == authenticated_read_receipt_digest {
                        Ok(())
                    } else {
                        Err(NeuronRuntimeError::NduStaleAfterEffect)
                    }
                },
            )
        })
        .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        let output = outcome?;
        // Never publish a successful serving result if CNS/NDU advanced
        // during checkpoint persistence. In this case the durable Prepare
        // deliberately remains unresolved for independent reconciliation.
        let observed = read_verifier
            .verify(signed_read)
            .map_err(|_| NeuronRuntimeError::NduStaleAfterEffect)?;
        if observed != authenticated_read_receipt_digest {
            return Err(NeuronRuntimeError::NduStaleAfterEffect);
        }
        // Resolve only after the checkpoint, witness, and post-effect live NDU
        // frontier are independently verified. A sync failure cannot erase the
        // unresolved Prepare; never retry the model on this failure.
        effect_intent
            .resolve(input_digest, output.tick.checkpoint_after)
            .map_err(|_| NeuronRuntimeError::PendingReconciliation)?;
        Ok(output)
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
