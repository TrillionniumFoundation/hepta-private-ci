//! Authenticated observation boundary for structural plasticity canaries.
//!
//! The plasticity crate owns a deterministic observation state machine, but a
//! deployed host must not accept caller-asserted safety/rollback booleans. This
//! adapter requires a current trusted Observer signature over the exact canary
//! plan and every observation field before forwarding it to the controller.
//! Authentication does not apply topology or grant activation authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::{
    LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedEvidenceError,
    SignedLearningEvidenceV1,
};
use codex_hepta_plasticity::{
    StructuralCanaryControllerV1, StructuralCanaryErrorV1, StructuralCanaryObservationV1,
    StructuralCanaryReceiptV1,
};
use codex_hepta_types::{Digest32, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedStructuralCanaryReceiptV1 {
    pub canary: StructuralCanaryReceiptV1,
    pub observer_id: StableId,
    pub observer_authentication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthenticatedStructuralCanaryErrorV1 {
    InvalidPlan,
    Evidence(SignedEvidenceError),
    Canary(StructuralCanaryErrorV1),
}

impl fmt::Display for AuthenticatedStructuralCanaryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AuthenticatedStructuralCanaryErrorV1 {}

/// Canonical bytes that the independently trusted canary Observer signs.
pub fn structural_canary_observation_signing_payload_v1(
    plan_digest: Digest32,
    observation: &StructuralCanaryObservationV1,
) -> Result<Vec<u8>, AuthenticatedStructuralCanaryErrorV1> {
    if plan_digest.is_zero() {
        return Err(AuthenticatedStructuralCanaryErrorV1::InvalidPlan);
    }
    let mut bytes = b"hepta.intelligence.structural-canary-observation.v1\0".to_vec();
    bytes.extend_from_slice(plan_digest.as_array());
    bytes.extend_from_slice(&observation.sequence.to_be_bytes());
    bytes.extend_from_slice(observation.health_digest.as_array());
    bytes.extend_from_slice(observation.evidence_digest.as_array());
    bytes.extend_from_slice(&observation.regression_count.to_be_bytes());
    bytes.push(u8::from(observation.safety_violation));
    bytes.push(u8::from(observation.lineage_mismatch));
    bytes.push(u8::from(observation.rollback_verified));
    Ok(bytes)
}

pub fn observe_authenticated_structural_canary_v1(
    controller: &mut StructuralCanaryControllerV1,
    observation: StructuralCanaryObservationV1,
    observer_attestation: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedStructuralCanaryReceiptV1, AuthenticatedStructuralCanaryErrorV1> {
    let payload =
        structural_canary_observation_signing_payload_v1(controller.plan_digest(), &observation)?;
    let verified = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            observer_attestation,
            &payload,
            now,
        )
        .map_err(AuthenticatedStructuralCanaryErrorV1::Evidence)?;
    let canary = controller
        .observe(observation)
        .map_err(AuthenticatedStructuralCanaryErrorV1::Canary)?;

    let mut authentication =
        b"hepta.intelligence.structural-canary-observer-authentication.v1\0".to_vec();
    authentication.extend_from_slice(verifier.trust_digest().as_array());
    authentication.extend_from_slice(verified.payload_digest().as_array());
    let principal = verified.principal();
    push_id(&mut authentication, &principal.principal_id);
    authentication.extend_from_slice(principal.credential_chain_digest.as_array());
    authentication.extend_from_slice(principal.signing_key_digest.as_array());
    authentication.extend_from_slice(&observer_attestation.signature);

    Ok(AuthenticatedStructuralCanaryReceiptV1 {
        canary,
        observer_id: principal.principal_id.clone(),
        observer_authentication_digest: Digest32::of_bytes(&authentication),
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[test]
    fn payload_binds_every_caller_asserted_canary_fact() {
        let observation = StructuralCanaryObservationV1 {
            sequence: 3,
            health_digest: digest(b"health"),
            evidence_digest: digest(b"evidence"),
            regression_count: 1,
            safety_violation: false,
            lineage_mismatch: false,
            rollback_verified: true,
        };
        let plan = digest(b"plan");
        let expected =
            structural_canary_observation_signing_payload_v1(plan, &observation).expect("payload");

        let mutations: [fn(&mut StructuralCanaryObservationV1); 6] = [
            |value| value.sequence += 1,
            |value| value.health_digest = digest(b"other-health"),
            |value| value.evidence_digest = digest(b"other-evidence"),
            |value| value.regression_count += 1,
            |value| value.safety_violation = true,
            |value| value.rollback_verified = false,
        ];
        for mutate in mutations {
            let mut changed = observation.clone();
            mutate(&mut changed);
            assert_ne!(
                structural_canary_observation_signing_payload_v1(plan, &changed)
                    .expect("changed payload"),
                expected
            );
        }

        let mut changed = observation;
        changed.lineage_mismatch = true;
        assert_ne!(
            structural_canary_observation_signing_payload_v1(plan, &changed)
                .expect("lineage payload"),
            expected
        );
    }
}
