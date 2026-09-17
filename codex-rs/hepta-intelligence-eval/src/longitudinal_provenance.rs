//! External provenance binding for longitudinal qualification admission.
//!
//! V3 authenticates observed window timing and an independent observer. V4
//! additionally binds three host-owned receipts that must originate outside this
//! evaluator: plan preregistration, collection provenance and trusted-clock
//! attestation. These digests do not make synthetic time real; they give the
//! qualification plane concrete, signed references to evidence it can verify
//! independently and prevent an otherwise valid V3 fixture from being admitted
//! as production longitudinal evidence by omission.

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;

use crate::EvaluationClaimScopeV1;
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_independently_v2;
use crate::evaluation_signing_payload_v2;
use crate::longitudinal_time::LongitudinalTimeEvidenceV1;
use crate::longitudinal_time::validate_observed_windows;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LongitudinalEvidenceProvenanceV1 {
    /// Receipt proving the host durably registered the frozen plan before the
    /// confirmatory collection window became available.
    pub preregistration_receipt_digest: Digest32,
    /// Receipt naming/authenticating the external outcome collection source.
    pub collection_receipt_digest: Digest32,
    /// Receipt binding the trusted clock/currentness source used by the host.
    pub clock_attestation_digest: Digest32,
}

/// Canonical bytes for the external provenance triplet. Each evidence class must
/// be nonzero and independently addressable; one digest cannot stand in for two
/// different qualification obligations.
pub fn longitudinal_provenance_signing_bytes_v1(
    provenance: &LongitudinalEvidenceProvenanceV1,
) -> Result<Vec<u8>, SignedEvaluationError> {
    let digests = [
        provenance.preregistration_receipt_digest,
        provenance.collection_receipt_digest,
        provenance.clock_attestation_digest,
    ];
    if digests.iter().any(Digest32::is_zero)
        || digests[0] == digests[1]
        || digests[0] == digests[2]
        || digests[1] == digests[2]
    {
        return Err(SignedEvaluationError::Timing("external_provenance"));
    }
    let mut bytes = b"hepta.intelligence-eval.longitudinal-provenance.v1\0".to_vec();
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

/// Observer payload for qualification-grade longitudinal evidence. The observer
/// attests both the V3 observed-window bytes and the external provenance refs.
pub fn future_window_signing_payload_v2(
    bundle: &IndependentEvaluationBundleV1,
    timing: &LongitudinalTimeEvidenceV1,
    provenance: &LongitudinalEvidenceProvenanceV1,
    minimum_window_micros: u64,
) -> Result<Vec<u8>, SignedEvaluationError> {
    if bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
        return Err(SignedEvaluationError::Timing("scope_or_bounds"));
    }
    let mut bytes = b"hepta.intelligence-eval.observed-future-windows.v2\0".to_vec();
    bytes.extend_from_slice(&crate::future_window_signing_payload_v1(
        bundle,
        timing,
        minimum_window_micros,
    )?);
    bytes.extend_from_slice(&longitudinal_provenance_signing_bytes_v1(provenance)?);
    Ok(bytes)
}

pub fn longitudinal_evaluation_signing_payload_v4(
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
    timing: &LongitudinalTimeEvidenceV1,
    provenance: &LongitudinalEvidenceProvenanceV1,
    minimum_window_micros: u64,
) -> Result<Vec<u8>, SignedEvaluationError> {
    let mut bytes = b"hepta.intelligence-eval.signed-request.v4\0".to_vec();
    bytes.extend_from_slice(&evaluation_signing_payload_v2(bundle, roles)?);
    bytes.extend_from_slice(&future_window_signing_payload_v2(
        bundle,
        timing,
        provenance,
        minimum_window_micros,
    )?);
    bytes.extend_from_slice(&timing.observer.signing_bytes());
    bytes.extend_from_slice(&timing.observer.signature);
    Ok(bytes)
}

/// Qualification entrypoint for real longitudinal evidence. Repository fixtures
/// can exercise this parser and signature path, but they cannot self-issue the
/// three external receipts or thereby close the future-calendar evidence gate.
pub fn decide_with_signed_longitudinal_evidence_v4(
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    timing: &LongitudinalTimeEvidenceV1,
    provenance: &LongitudinalEvidenceProvenanceV1,
    minimum_window_micros: u64,
    verifier: &LearningEvidenceVerifierV1,
    now_unix_micros: u64,
) -> Result<SignedEvaluationDecisionV1, SignedEvaluationError> {
    longitudinal_provenance_signing_bytes_v1(provenance)?;
    let payload = longitudinal_evaluation_signing_payload_v4(
        &bundle,
        &roles,
        timing,
        provenance,
        minimum_window_micros,
    )?;
    let authentication = crate::signed_evaluation::authenticate(
        &bundle,
        evidence,
        verifier,
        &payload,
        now_unix_micros,
    )?;
    let observer_payload = future_window_signing_payload_v2(
        &bundle,
        timing,
        provenance,
        minimum_window_micros,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &timing.observer,
        &observer_payload,
        now_unix_micros,
    )?;
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evidence.generator_plan,
        bundle.frozen_plan.plan_digest.as_array(),
        now_unix_micros,
    )?;
    verify_signed_role_separation(&generator, &observer, now_unix_micros)?;
    validate_observed_windows(
        &bundle,
        timing,
        evidence.generator_plan.issued_at,
        minimum_window_micros,
        now_unix_micros,
    )?;
    let mut authenticated = authentication.as_array().to_vec();
    authenticated.extend_from_slice(&timing.observer.signature);
    authenticated.extend_from_slice(&longitudinal_provenance_signing_bytes_v1(provenance)?);
    Ok(SignedEvaluationDecisionV1 {
        decision: decide_independently_v2(bundle, roles, now_unix_micros)?,
        trust_digest: verifier.trust_digest(),
        authentication_digest: Digest32::of_bytes(&authenticated),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn provenance() -> LongitudinalEvidenceProvenanceV1 {
        LongitudinalEvidenceProvenanceV1 {
            preregistration_receipt_digest: digest("preregistered-plan"),
            collection_receipt_digest: digest("external-collector"),
            clock_attestation_digest: digest("trusted-clock"),
        }
    }

    #[test]
    fn external_provenance_is_domain_bound_and_complete() {
        let first = provenance();
        let first_bytes = longitudinal_provenance_signing_bytes_v1(&first).unwrap();
        let mut changed = first;
        changed.clock_attestation_digest = digest("other-clock");
        let changed_bytes = longitudinal_provenance_signing_bytes_v1(&changed).unwrap();
        assert_ne!(Digest32::of_bytes(&first_bytes), Digest32::of_bytes(&changed_bytes));

        for invalid in [
            LongitudinalEvidenceProvenanceV1 {
                preregistration_receipt_digest: Digest32::ZERO,
                ..first
            },
            LongitudinalEvidenceProvenanceV1 {
                collection_receipt_digest: first.preregistration_receipt_digest,
                ..first
            },
            LongitudinalEvidenceProvenanceV1 {
                clock_attestation_digest: first.collection_receipt_digest,
                ..first
            },
        ] {
            assert!(longitudinal_provenance_signing_bytes_v1(&invalid).is_err());
        }
    }
}
