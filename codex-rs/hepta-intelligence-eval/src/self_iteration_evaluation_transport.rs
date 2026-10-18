//! Transfer one original independently signed evaluation to the durable cycle.
//! Decoding remains inside Eval's private codec until current trust, the exact
//! frozen consumer and the Evaluator's use attestation have all been checked.

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationError;
use crate::SignedEligibilityAdmissionReceiptV1;
use crate::SignedEvaluationEvidenceV1;
use crate::admit_signed_eligibility_v2;
use crate::recorded_publication::archive::codec::Reader;
use crate::recorded_publication::archive::codec::Wire;
use crate::recorded_publication::archive::codec::Writer;
use crate::recorded_publication::archive::codec::structure;

pub const MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES: usize = 1024 * 1024;
const PROFILE: &[u8] = b"hepta.eval.self-iteration-evaluation-transport.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
struct Publication {
    frozen_consumer: Digest32,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: SignedEvaluationEvidenceV1,
    use_attestation: SignedLearningEvidenceV1,
}
structure!(Publication {
    frozen_consumer,
    bundle,
    roles,
    evidence,
    use_attestation
});

/// An authenticated transfer, not a product qualification or selection grant.
/// The durable owner must check the native values again at their actual use.
pub struct VerifiedSelfIterationEvaluationTransportV1 {
    publication: Publication,
    admission: SignedEligibilityAdmissionReceiptV1,
}
impl VerifiedSelfIterationEvaluationTransportV1 {
    pub fn admission(&self) -> &SignedEligibilityAdmissionReceiptV1 {
        &self.admission
    }

    pub fn into_parts(
        self,
    ) -> (
        IndependentEvaluationBundleV1,
        Vec<MetricRoleContractV2>,
        SignedEvaluationEvidenceV1,
        SignedLearningEvidenceV1,
    ) {
        let Publication {
            bundle,
            roles,
            evidence,
            use_attestation,
            ..
        } = self.publication;
        (bundle, roles, evidence, use_attestation)
    }
}

/// The existing durable Agentd stage payload. The same bytes are used by Eval,
/// Selector and the original cycle owner; no transport field can redefine it.
pub fn self_iteration_evaluation_use_payload_v1(
    frozen_consumer: Digest32,
    authentication_digest: Digest32,
) -> Vec<u8> {
    let mut bytes = b"hepta.agentd.self-iteration-stage.v1\0".to_vec();
    bytes.extend_from_slice(frozen_consumer.as_array());
    bytes.extend_from_slice(authentication_digest.as_array());
    bytes
}

/// Publish only an already independently authenticated evaluation and its
/// separately signed exact consumer use. No signing capability is accepted.
pub fn encode_self_iteration_evaluation_transport_v1(
    frozen_consumer: Digest32,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: SignedEvaluationEvidenceV1,
    use_attestation: SignedLearningEvidenceV1,
    trust: &ActivatedLearningTrustV1,
    now_unix_ms: u64,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let publication = Publication {
        frozen_consumer,
        bundle,
        roles,
        evidence,
        use_attestation,
    };
    authenticate(&publication, frozen_consumer, trust, now_unix_ms)?;
    encode(&publication)
}

/// Authenticate inside the original Eval owner before returning any decoded
/// native receipt. The expected binding and trust come from the installed host.
pub fn decode_self_iteration_evaluation_transport_v1(
    bytes: &[u8],
    expected_frozen_consumer: Digest32,
    trust: &ActivatedLearningTrustV1,
    now_unix_ms: u64,
) -> Result<VerifiedSelfIterationEvaluationTransportV1, ProductEvaluationError> {
    if bytes.is_empty() || bytes.len() > MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES {
        return Err(invalid());
    }
    let mut reader = Reader::new(bytes)?;
    if reader.take(PROFILE.len())? != PROFILE {
        return Err(invalid());
    }
    let publication = Publication::read(&mut reader)?;
    reader.finish()?;
    if encode(&publication)? != bytes {
        return Err(invalid());
    }
    let admission = authenticate(&publication, expected_frozen_consumer, trust, now_unix_ms)?;
    Ok(VerifiedSelfIterationEvaluationTransportV1 {
        publication,
        admission,
    })
}

fn authenticate(
    publication: &Publication,
    expected: Digest32,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> Result<SignedEligibilityAdmissionReceiptV1, ProductEvaluationError> {
    if expected.is_zero() || publication.frozen_consumer != expected {
        return Err(invalid());
    }
    trust.revalidate_at(now).map_err(|_| invalid())?;
    let admitted = admit_signed_eligibility_v2(
        publication.bundle.clone(),
        publication.roles.clone(),
        &publication.evidence,
        trust.verifier(),
        expected,
        now,
    )
    .map_err(|_| invalid())?;
    admitted.validate_integrity().map_err(|_| invalid())?;
    let evaluator = trust
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &publication.use_attestation,
            &self_iteration_evaluation_use_payload_v1(
                expected,
                admitted.decision.authentication_digest,
            ),
            now,
        )
        .map_err(|_| invalid())?;
    if evaluator.principal() != &publication.bundle.evaluator {
        return Err(invalid());
    }
    Ok(admitted)
}

fn encode(publication: &Publication) -> Result<Vec<u8>, ProductEvaluationError> {
    let mut writer = Writer::default();
    writer.put(PROFILE)?;
    publication.write(&mut writer)?;
    let bytes = writer.finish();
    if bytes.len() > MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES {
        return Err(invalid());
    }
    Ok(bytes)
}

fn invalid() -> ProductEvaluationError {
    ProductEvaluationError::Integrity("current consumer-bound self-iteration evaluation transport")
}

#[cfg(test)]
#[path = "self_iteration_evaluation_transport_tests.rs"]
mod tests;
