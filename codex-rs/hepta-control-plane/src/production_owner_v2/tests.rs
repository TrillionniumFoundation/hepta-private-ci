use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;
use crate::CanonicalDecisionEnvelopeV1;
use crate::EffectTerminalDispositionV1;
use crate::EffectTerminalReceiptV1;
use crate::GrantRequestV1;
use crate::IndependentAuthorizationV1;
use crate::ManualTrustedClockV1;
use crate::ProductExecutionErrorV1;
use crate::ProductExecutionPhaseV1;
use crate::TrustedClockErrorV1;

struct AcceptingVerifier;

impl CanonicalProducerVerifierV1 for AcceptingVerifier {
    fn verify(
        &self,
        envelope: &CanonicalProducerEnvelopeV1,
    ) -> Result<CanonicalProducerVerificationV1, CanonicalProducerVerificationErrorV1> {
        Ok(CanonicalProducerVerificationV1 {
            verifier_id: id("test-verifier"),
            envelope_digest: envelope.digest(),
            verification_digest: digest("verification"),
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
    ) -> Result<CanonicalProducerVerificationV1, CanonicalProducerVerificationErrorV1> {
        self.clock
            .advance_to(envelope.expires_at_micros)
            .expect("advance");
        Ok(CanonicalProducerVerificationV1 {
            verifier_id: id("slow-verifier"),
            envelope_digest: envelope.digest(),
            verification_digest: digest("slow-verification"),
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
    owner.commit_decision(&port, &decision).expect("decision");
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
fn indeterminate_attempt_survives_owner_restart() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("planner.store");
    let owner_id = id("control-runtime-owner");
    let generation = Generation::new(3).expect("generation");
    let policy_digest = digest("policy");
    let identity;
    {
        let mut owner = ControlRuntimeOwnerV1::open(
            &path,
            owner_id.clone(),
            generation,
            7,
            policy_digest,
            ManualTrustedClockV1::new(20),
        )
        .expect("owner");
        let decision = decision();
        identity = decision.operation_identity_digest;
        let producer = producer_envelope(&owner_id, generation, policy_digest, &decision);
        let port = owner
            .admit_owner_port(&producer, &AcceptingVerifier)
            .expect("port");
        owner.commit_decision(&port, &decision).expect("decision");
        let request = request();
        owner
            .record_authority_request(identity, &request)
            .expect("request");
        owner
            .consume_independent_authorization(identity, &observation(&request), &grant(&request))
            .expect("authorization");
        owner
            .mark_dispatched(identity, &observation(&request), b"dispatch")
            .expect("dispatch");
        owner
            .record_terminal(&EffectTerminalReceiptV1 {
                operation_identity_digest: identity,
                observed_outcome_digest: digest("unknown"),
                disposition: EffectTerminalDispositionV1::Indeterminate,
            })
            .expect("terminal");
    }

    let reopened = ControlRuntimeOwnerV1::open(
        &path,
        owner_id,
        generation,
        7,
        policy_digest,
        ManualTrustedClockV1::new(30),
    )
    .expect("reopen owner");
    assert_eq!(
        reopened
            .operation(identity)
            .expect("recovered attempt")
            .phase,
        ProductExecutionPhaseV1::Indeterminate
    );
}
