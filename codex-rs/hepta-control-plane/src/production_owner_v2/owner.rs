use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::AuthenticatedOwnerPortV1;
use super::CanonicalProducerEnvelopeV1;
use super::CanonicalProducerVerifierV1;
use super::ControlRuntimeOwnerErrorV1;
use super::FinalUseObservationV1;
use crate::CanonicalDecisionEnvelopeV1;
use crate::CurrentExecutionFenceV1;
use crate::EffectTerminalReceiptV1;
use crate::GrantRequestV1;
use crate::IndependentAuthorizationV1;
use crate::PlannerCheckpointV1;
use crate::PlannerStoreRecordV1;
use crate::PlannerStoreV1;
use crate::ProductExecutionRecordV1;
use crate::planner_execution::ControlRuntimeExecutionConsumerV1;
use crate::planner_execution::validate_current_authorization;
use crate::trusted_clock::FreshnessWindowV1;
use crate::trusted_clock::TrustedClockV1;

pub struct ControlRuntimeOwnerV1<C> {
    owner_id: StableId,
    generation: Generation,
    policy_epoch: u64,
    policy_digest: Digest32,
    clock: C,
    store: PlannerStoreV1,
    execution: ControlRuntimeExecutionConsumerV1,
    consumed_producer_envelopes: BTreeSet<Digest32>,
    requests: BTreeMap<Digest32, GrantRequestV1>,
    authorizations: BTreeMap<Digest32, IndependentAuthorizationV1>,
}

impl<C: TrustedClockV1> ControlRuntimeOwnerV1<C> {
    pub fn open(
        path: impl AsRef<Path>,
        owner_id: StableId,
        generation: Generation,
        policy_epoch: u64,
        policy_digest: Digest32,
        clock: C,
    ) -> Result<Self, ControlRuntimeOwnerErrorV1> {
        if policy_epoch == 0 || policy_digest.is_zero() {
            return Err(ControlRuntimeOwnerErrorV1::InvalidOwnerConfiguration);
        }
        let store = PlannerStoreV1::open(path)?;
        let execution = ControlRuntimeExecutionConsumerV1::recover_from_store(&store)?;
        let requests = execution.requests().clone();
        let authorizations = execution.authorizations().clone();
        Ok(Self {
            owner_id,
            generation,
            policy_epoch,
            policy_digest,
            clock,
            store,
            execution,
            consumed_producer_envelopes: BTreeSet::new(),
            requests,
            authorizations,
        })
    }

    pub fn admit_owner_port(
        &self,
        envelope: &CanonicalProducerEnvelopeV1,
        verifier: &dyn CanonicalProducerVerifierV1,
    ) -> Result<AuthenticatedOwnerPortV1, ControlRuntimeOwnerErrorV1> {
        self.validate_producer_envelope(envelope, self.clock.now_micros()?)?;
        let envelope_digest = envelope.digest();
        let verification = verifier
            .verify(envelope)
            .map_err(ControlRuntimeOwnerErrorV1::ProducerVerification)?;
        if verification.envelope_digest != envelope_digest
            || verification.verification_digest.is_zero()
        {
            return Err(ControlRuntimeOwnerErrorV1::ProducerVerificationBindingMismatch);
        }
        self.validate_producer_envelope(envelope, self.clock.now_micros()?)?;
        Ok(AuthenticatedOwnerPortV1 {
            producer_id: envelope.producer_id.clone(),
            owner_id: envelope.owner_id.clone(),
            owner_generation: envelope.owner_generation,
            policy_epoch: envelope.policy_epoch,
            policy_digest: envelope.policy_digest,
            operation_identity_digest: envelope.operation_identity_digest,
            payload_digest: envelope.payload_digest,
            observed_at_micros: envelope.observed_at_micros,
            expires_at_micros: envelope.expires_at_micros,
            deadline_micros: envelope.deadline_micros,
            envelope_digest,
            verifier_id: verification.verifier_id,
            verification_digest: verification.verification_digest,
        })
    }

    pub fn commit_decision(
        &mut self,
        port: &AuthenticatedOwnerPortV1,
        envelope: &CanonicalDecisionEnvelopeV1,
    ) -> Result<ProductExecutionRecordV1, ControlRuntimeOwnerErrorV1> {
        self.validate_port(port, self.clock.now_micros()?)?;
        if self
            .consumed_producer_envelopes
            .contains(&port.envelope_digest)
        {
            return Err(ControlRuntimeOwnerErrorV1::ProducerPortConsumed);
        }
        let decision_digest = envelope.digest()?;
        if port.operation_identity_digest != envelope.operation_identity_digest
            || port.payload_digest != decision_digest
        {
            return Err(ControlRuntimeOwnerErrorV1::ProducerPayloadMismatch);
        }
        let record = self.execution.commit_decision(&mut self.store, envelope)?;
        self.consumed_producer_envelopes
            .insert(port.envelope_digest);
        Ok(record)
    }

    pub fn record_authority_request(
        &mut self,
        operation_identity_digest: Digest32,
        request: &GrantRequestV1,
    ) -> Result<ProductExecutionRecordV1, ControlRuntimeOwnerErrorV1> {
        let record = self.execution.record_authority_request(
            &mut self.store,
            operation_identity_digest,
            request,
        )?;
        self.requests
            .insert(operation_identity_digest, request.clone());
        Ok(record)
    }

    pub fn consume_independent_authorization(
        &mut self,
        operation_identity_digest: Digest32,
        current: &FinalUseObservationV1,
        grant: &IndependentAuthorizationV1,
    ) -> Result<ProductExecutionRecordV1, ControlRuntimeOwnerErrorV1> {
        let request = self
            .requests
            .get(&operation_identity_digest)
            .cloned()
            .ok_or(ControlRuntimeOwnerErrorV1::MissingAuthorityRequest)?;
        let fence = self.current_fence(current)?;
        let record = self.execution.consume_independent_authorization(
            &mut self.store,
            operation_identity_digest,
            &request,
            &fence,
            grant,
        )?;
        self.authorizations
            .insert(operation_identity_digest, grant.clone());
        Ok(record)
    }

    pub fn mark_dispatched(
        &mut self,
        operation_identity_digest: Digest32,
        current: &FinalUseObservationV1,
        dispatch_receipt: &[u8],
    ) -> Result<ProductExecutionRecordV1, ControlRuntimeOwnerErrorV1> {
        let request = self
            .requests
            .get(&operation_identity_digest)
            .cloned()
            .ok_or(ControlRuntimeOwnerErrorV1::MissingAuthorityRequest)?;
        let grant = self
            .authorizations
            .get(&operation_identity_digest)
            .cloned()
            .ok_or(ControlRuntimeOwnerErrorV1::MissingAuthorization)?;
        let fence = self.current_fence(current)?;
        validate_current_authorization(&request, &fence, &grant)?;
        Ok(self.execution.mark_dispatched(
            &mut self.store,
            operation_identity_digest,
            dispatch_receipt,
        )?)
    }

    pub fn record_terminal(
        &mut self,
        receipt: &EffectTerminalReceiptV1,
    ) -> Result<ProductExecutionRecordV1, ControlRuntimeOwnerErrorV1> {
        Ok(self.execution.record_terminal(&mut self.store, receipt)?)
    }

    pub fn reconcile_indeterminate(
        &mut self,
        receipt: &EffectTerminalReceiptV1,
    ) -> Result<ProductExecutionRecordV1, ControlRuntimeOwnerErrorV1> {
        Ok(self
            .execution
            .reconcile_indeterminate(&mut self.store, receipt)?)
    }

    pub fn append_checkpoint(
        &mut self,
        external_anchor_receipt: &[u8],
    ) -> Result<PlannerCheckpointV1, ControlRuntimeOwnerErrorV1> {
        Ok(self.store.append_checkpoint(external_anchor_receipt)?)
    }

    pub fn backup(
        &mut self,
        destination: impl AsRef<Path>,
    ) -> Result<(), ControlRuntimeOwnerErrorV1> {
        Ok(self.store.backup(destination)?)
    }

    #[must_use]
    pub fn operation(
        &self,
        operation_identity_digest: Digest32,
    ) -> Option<&ProductExecutionRecordV1> {
        self.execution.operation(operation_identity_digest)
    }

    #[must_use]
    pub fn store_records(&self) -> &[PlannerStoreRecordV1] {
        self.store.records()
    }

    fn current_fence(
        &self,
        current: &FinalUseObservationV1,
    ) -> Result<CurrentExecutionFenceV1, ControlRuntimeOwnerErrorV1> {
        if current.snapshot_digest.is_zero()
            || current.revocation_frontier_digest.is_zero()
            || current.final_payload_digest.is_zero()
        {
            return Err(ControlRuntimeOwnerErrorV1::EmptyDigest(
                "final-use observation",
            ));
        }
        Ok(CurrentExecutionFenceV1 {
            snapshot_digest: current.snapshot_digest,
            revocation_frontier_digest: current.revocation_frontier_digest,
            final_payload_digest: current.final_payload_digest,
            now_micros: self.clock.now_micros()?,
        })
    }

    fn validate_producer_envelope(
        &self,
        envelope: &CanonicalProducerEnvelopeV1,
        now_micros: u64,
    ) -> Result<(), ControlRuntimeOwnerErrorV1> {
        if envelope.policy_epoch == 0
            || envelope.policy_digest.is_zero()
            || envelope.operation_identity_digest.is_zero()
            || envelope.payload_digest.is_zero()
            || envelope.evidence_digest.is_zero()
        {
            return Err(ControlRuntimeOwnerErrorV1::EmptyDigest(
                "canonical producer envelope",
            ));
        }
        if envelope.owner_id != self.owner_id {
            return Err(ControlRuntimeOwnerErrorV1::OwnerBindingMismatch);
        }
        if envelope.owner_generation != self.generation {
            return Err(ControlRuntimeOwnerErrorV1::GenerationBindingMismatch);
        }
        if envelope.policy_epoch != self.policy_epoch || envelope.policy_digest != self.policy_digest
        {
            return Err(ControlRuntimeOwnerErrorV1::PolicyBindingMismatch);
        }
        FreshnessWindowV1 {
            observed_at_micros: envelope.observed_at_micros,
            expires_at_micros: envelope.expires_at_micros,
            deadline_micros: envelope.deadline_micros,
        }
        .validate_at(now_micros)?;
        Ok(())
    }

    fn validate_port(
        &self,
        port: &AuthenticatedOwnerPortV1,
        now_micros: u64,
    ) -> Result<(), ControlRuntimeOwnerErrorV1> {
        if port.owner_id != self.owner_id {
            return Err(ControlRuntimeOwnerErrorV1::OwnerBindingMismatch);
        }
        if port.owner_generation != self.generation {
            return Err(ControlRuntimeOwnerErrorV1::GenerationBindingMismatch);
        }
        if port.policy_epoch != self.policy_epoch || port.policy_digest != self.policy_digest {
            return Err(ControlRuntimeOwnerErrorV1::PolicyBindingMismatch);
        }
        if port.verification_digest.is_zero() {
            return Err(ControlRuntimeOwnerErrorV1::ProducerVerificationBindingMismatch);
        }
        FreshnessWindowV1 {
            observed_at_micros: port.observed_at_micros,
            expires_at_micros: port.expires_at_micros,
            deadline_micros: port.deadline_micros,
        }
        .validate_at(now_micros)?;
        Ok(())
    }
}
