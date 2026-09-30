use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CanonicalDecisionEnvelopeV1;
use crate::CurrentExecutionFenceV1;
use crate::EffectTerminalReceiptV1;
use crate::GrantRequestV1;
use crate::IndependentAuthorizationV1;
use crate::PlannerCheckpointV1;
use crate::PlannerStoreError;
use crate::PlannerStoreRecordV1;
use crate::PlannerStoreV1;
use crate::ProductExecutionErrorV1;
use crate::ProductExecutionRecordV1;
use crate::planner_execution::ControlRuntimeExecutionConsumerV1;
use crate::planner_execution::validate_current_authorization;
use crate::trusted_clock::FreshnessWindowV1;
use crate::trusted_clock::TrustedClockErrorV1;
use crate::trusted_clock::TrustedClockV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalProducerEnvelopeV1 {
    pub producer_id: StableId,
    pub owner_id: StableId,
    pub owner_generation: Generation,
    pub policy_epoch: u64,
    pub policy_digest: Digest32,
    pub operation_identity_digest: Digest32,
    pub payload_digest: Digest32,
    pub evidence_digest: Digest32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
    pub deadline_micros: u64,
}

impl CanonicalProducerEnvelopeV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.control.canonical-producer-envelope.v1\0".to_vec();
        push_id(&mut bytes, &self.producer_id);
        push_id(&mut bytes, &self.owner_id);
        bytes.extend_from_slice(&self.owner_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.policy_epoch.to_be_bytes());
        bytes.extend_from_slice(self.policy_digest.as_array());
        bytes.extend_from_slice(self.operation_identity_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(self.evidence_digest.as_array());
        bytes.extend_from_slice(&self.observed_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.deadline_micros.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalProducerVerificationErrorV1 {
    Rejected,
    Unavailable,
}

impl fmt::Display for CanonicalProducerVerificationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalProducerVerificationErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalProducerVerificationV1 {
    pub verifier_id: StableId,
    pub envelope_digest: Digest32,
    pub verification_digest: Digest32,
}

pub trait CanonicalProducerVerifierV1: Send + Sync {
    fn verify(
        &self,
        envelope: &CanonicalProducerEnvelopeV1,
    ) -> Result<CanonicalProducerVerificationV1, CanonicalProducerVerificationErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalUseObservationV1 {
    pub snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub final_payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOwnerPortV1 {
    producer_id: StableId,
    owner_id: StableId,
    owner_generation: Generation,
    policy_epoch: u64,
    policy_digest: Digest32,
    operation_identity_digest: Digest32,
    payload_digest: Digest32,
    observed_at_micros: u64,
    expires_at_micros: u64,
    deadline_micros: u64,
    envelope_digest: Digest32,
    verifier_id: StableId,
    verification_digest: Digest32,
}

impl AuthenticatedOwnerPortV1 {
    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.producer_id
    }

    #[must_use]
    pub fn operation_identity_digest(&self) -> Digest32 {
        self.operation_identity_digest
    }

    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub fn verifier_id(&self) -> &StableId {
        &self.verifier_id
    }

    #[must_use]
    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlRuntimeOwnerErrorV1 {
    InvalidOwnerConfiguration,
    EmptyDigest(&'static str),
    OwnerBindingMismatch,
    GenerationBindingMismatch,
    PolicyBindingMismatch,
    ProducerVerification(CanonicalProducerVerificationErrorV1),
    ProducerVerificationBindingMismatch,
    ProducerPortConsumed,
    ProducerPayloadMismatch,
    MissingAuthorityRequest,
    MissingAuthorization,
    Clock(TrustedClockErrorV1),
    Store(String),
    Execution(ProductExecutionErrorV1),
}

impl fmt::Display for ControlRuntimeOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ControlRuntimeOwnerErrorV1 {}

impl From<TrustedClockErrorV1> for ControlRuntimeOwnerErrorV1 {
    fn from(error: TrustedClockErrorV1) -> Self {
        Self::Clock(error)
    }
}

impl From<PlannerStoreError> for ControlRuntimeOwnerErrorV1 {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error.to_string())
    }
}

impl From<ProductExecutionErrorV1> for ControlRuntimeOwnerErrorV1 {
    fn from(error: ProductExecutionErrorV1) -> Self {
        Self::Execution(error)
    }
}

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
        Ok(Self {
            owner_id,
            generation,
            policy_epoch,
            policy_digest,
            clock,
            store: PlannerStoreV1::open(path)?,
            execution: ControlRuntimeExecutionConsumerV1::new(),
            consumed_producer_envelopes: BTreeSet::new(),
            requests: BTreeMap::new(),
            authorizations: BTreeMap::new(),
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

    pub fn compact(&mut self, retain_last: usize) -> Result<(), ControlRuntimeOwnerErrorV1> {
        Ok(self.store.compact(retain_last)?)
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

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::EffectTerminalDispositionV1;
    use crate::ManualTrustedClockV1;

    struct AcceptingVerifier;

    impl CanonicalProducerVerifierV1 for AcceptingVerifier {
        fn verify(
            &self,
            envelope: &CanonicalProducerEnvelopeV1,
        ) -> Result<CanonicalProducerVerificationV1, CanonicalProducerVerificationErrorV1>
        {
            Ok(CanonicalProducerVerificationV1 {
                verifier_id: StableId::new("test-verifier").expect("verifier"),
                envelope_digest: envelope.digest(),
                verification_digest: Digest32::of_bytes(b"verification"),
            })
        }
    }

    struct AdvancingVerifier {
        clock: ManualTrustedClockV1,
    }

    impl CanonicalProducerVerifierV1 for AdvancingVerifier {
        fn verify(
            &self,
            envelope: &CanonicalProducerEnvelopeV1,
        ) -> Result<CanonicalProducerVerificationV1, CanonicalProducerVerificationErrorV1>
        {
            self.clock
                .advance_to(envelope.expires_at_micros)
                .expect("advance");
            Ok(CanonicalProducerVerificationV1 {
                verifier_id: StableId::new("slow-verifier").expect("verifier"),
                envelope_digest: envelope.digest(),
                verification_digest: Digest32::of_bytes(b"slow-verification"),
            })
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn decision() -> CanonicalDecisionEnvelopeV1 {
        CanonicalDecisionEnvelopeV1 {
            operation_identity_digest: digest("operation-identity"),
            snapshot_bytes: b"snapshot".to_vec(),
            prepared_plan_bytes: b"prepared".to_vec(),
            ndu_evaluation_bytes: b"ndu".to_vec(),
            plan_receipt_bytes: b"receipt".to_vec(),
            grant_request_set_bytes: b"requests".to_vec(),
        }
    }

    fn request() -> GrantRequestV1 {
        GrantRequestV1 {
            operation_id: id("execute"),
            candidate_id: id("candidate"),
            plan_digest: digest("plan"),
            final_payload_digest: digest("payload"),
            objective_digest: digest("objective"),
            snapshot_digest: digest("snapshot"),
            revocation_frontier_digest: digest("frontier"),
            expires_at_micros: 100,
        }
    }

    fn grant(request: &GrantRequestV1) -> IndependentAuthorizationV1 {
        IndependentAuthorizationV1 {
            authority_principal: id("kernel-authority"),
            signed_grant_digest: digest("signed-grant"),
            operation_id: request.operation_id.clone(),
            candidate_id: request.candidate_id.clone(),
            plan_digest: request.plan_digest,
            final_payload_digest: request.final_payload_digest,
            snapshot_digest: request.snapshot_digest,
            revocation_frontier_digest: request.revocation_frontier_digest,
            expires_at_micros: request.expires_at_micros,
        }
    }

    fn producer_envelope(
        owner_id: &StableId,
        generation: Generation,
        policy_digest: Digest32,
        decision: &CanonicalDecisionEnvelopeV1,
    ) -> CanonicalProducerEnvelopeV1 {
        CanonicalProducerEnvelopeV1 {
            producer_id: id("canonical-planner"),
            owner_id: owner_id.clone(),
            owner_generation: generation,
            policy_epoch: 7,
            policy_digest,
            operation_identity_digest: decision.operation_identity_digest,
            payload_digest: decision.digest().expect("decision digest"),
            evidence_digest: digest("producer-evidence"),
            observed_at_micros: 10,
            expires_at_micros: 80,
            deadline_micros: 70,
        }
    }

    fn observation(request: &GrantRequestV1) -> FinalUseObservationV1 {
        FinalUseObservationV1 {
            snapshot_digest: request.snapshot_digest,
            revocation_frontier_digest: request.revocation_frontier_digest,
            final_payload_digest: request.final_payload_digest,
        }
    }

    #[test]
    fn owner_rechecks_time_after_verification_and_before_dispatch() {
        let directory = tempfile::tempdir().expect("tempdir");
        let owner_id = id("control-runtime-owner");
        let generation = Generation::new(3).expect("generation");
        let policy_digest = digest("policy");
        let clock = ManualTrustedClockV1::new(20);
        let mut owner = ControlRuntimeOwnerV1::open(
            directory.path().join("planner.store"),
            owner_id.clone(),
            generation,
            7,
            policy_digest,
            clock.clone(),
        )
        .expect("owner");
        let decision = decision();
        let producer = producer_envelope(&owner_id, generation, policy_digest, &decision);
        let port = owner
            .admit_owner_port(&producer, &AcceptingVerifier)
            .expect("port");
        owner
            .commit_decision(&port, &decision)
            .expect("decision");
        assert_eq!(
            owner.commit_decision(&port, &decision),
            Err(ControlRuntimeOwnerErrorV1::ProducerPortConsumed)
        );

        let request = request();
        let identity = decision.operation_identity_digest;
        owner
            .record_authority_request(identity, &request)
            .expect("request");
        owner
            .consume_independent_authorization(identity, &observation(&request), &grant(&request))
            .expect("authorization");
        clock.advance_to(100).expect("expire grant");
        assert_eq!(
            owner.mark_dispatched(identity, &observation(&request), b"dispatch"),
            Err(ControlRuntimeOwnerErrorV1::Execution(
                ProductExecutionErrorV1::GrantExpired
            ))
        );
    }

    #[test]
    fn producer_evidence_expiring_during_verification_is_rejected() {
        let directory = tempfile::tempdir().expect("tempdir");
        let owner_id = id("control-runtime-owner");
        let generation = Generation::new(3).expect("generation");
        let policy_digest = digest("policy");
        let clock = ManualTrustedClockV1::new(20);
        let owner = ControlRuntimeOwnerV1::open(
            directory.path().join("planner.store"),
            owner_id.clone(),
            generation,
            7,
            policy_digest,
            clock.clone(),
        )
        .expect("owner");
        let decision = decision();
        let producer = producer_envelope(&owner_id, generation, policy_digest, &decision);
        assert_eq!(
            owner.admit_owner_port(
                &producer,
                &AdvancingVerifier {
                    clock: clock.clone(),
                },
            ),
            Err(ControlRuntimeOwnerErrorV1::Clock(
                TrustedClockErrorV1::EvidenceExpired
            ))
        );
    }

    #[test]
    fn terminal_receipts_remain_bound_to_the_exact_attempt() {
        let directory = tempfile::tempdir().expect("tempdir");
        let owner_id = id("control-runtime-owner");
        let generation = Generation::new(3).expect("generation");
        let policy_digest = digest("policy");
        let clock = ManualTrustedClockV1::new(20);
        let mut owner = ControlRuntimeOwnerV1::open(
            directory.path().join("planner.store"),
            owner_id.clone(),
            generation,
            7,
            policy_digest,
            clock,
        )
        .expect("owner");
        let decision = decision();
        let producer = producer_envelope(&owner_id, generation, policy_digest, &decision);
        let port = owner
            .admit_owner_port(&producer, &AcceptingVerifier)
            .expect("port");
        owner
            .commit_decision(&port, &decision)
            .expect("decision");
        let request = request();
        let identity = decision.operation_identity_digest;
        owner
            .record_authority_request(identity, &request)
            .expect("request");
        owner
            .consume_independent_authorization(identity, &observation(&request), &grant(&request))
            .expect("authorization");
        owner
            .mark_dispatched(identity, &observation(&request), b"dispatch")
            .expect("dispatch");
        let record = owner
            .record_terminal(&EffectTerminalReceiptV1 {
                operation_identity_digest: identity,
                observed_outcome_digest: digest("unknown"),
                disposition: EffectTerminalDispositionV1::Indeterminate,
            })
            .expect("terminal");
        assert_eq!(record.operation_identity_digest, identity);
    }
}
