use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence_eval::NduConvergenceCertificateV1;
use codex_hepta_intelligence_eval::NduConvergenceDecisionV1;
use codex_hepta_intelligence_eval::NduWellPosednessCertificateV1;
use codex_hepta_intelligence_eval::NduWellPosednessDecisionV1;
use codex_hepta_learning_artifacts::ArtifactAdmissionError;
use codex_hepta_learning_artifacts::ArtifactClosureError;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactLifecycleJournalError;
use codex_hepta_learning_artifacts::ArtifactLifecycleStateV1;
use codex_hepta_learning_artifacts::PinnedCandidateLoadError;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_learning_artifacts::verify_artifact_admission_v3;
use codex_hepta_ndu::AdmittedNduCoefficientProfileV1;
use codex_hepta_ndu::NduCoefficientProjectionV1;
use codex_hepta_ndu::validate_ndu_coefficient_projection_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug)]
pub struct NduStochasticAdmissionRequestV1<'a> {
    pub artifact_admission: &'a WithdrawalBoundArtifactAdmissionV3,
    pub current_withdrawal_head: Digest32,
    pub coefficient_profile: &'a AdmittedNduCoefficientProfileV1,
    pub projection: &'a NduCoefficientProjectionV1,
    pub convergence: &'a NduConvergenceCertificateV1,
    pub well_posedness: &'a NduWellPosednessCertificateV1,
    pub objective_class_digest: Digest32,
    pub operating_domain_digest: Digest32,
    pub expected_compatibility_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduStochasticAdmissionReceiptV1 {
    pub artifact_manifest_digest: Digest32,
    pub artifact_bytes_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub coefficient_profile_digest: Digest32,
    pub q24_output_digest: Digest32,
    pub solver_digest: Digest32,
    pub convergence_certificate_digest: Digest32,
    pub well_posedness_certificate_digest: Digest32,
    pub admission_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduStochasticAdmissionError {
    EmptyDigest(&'static str),
    ArtifactAdmission(ArtifactAdmissionError),
    CurrentArtifact(PinnedCandidateLoadError),
    ArtifactMismatch(&'static str),
    CoefficientProfileMismatch,
    ProjectionMismatch,
    AuthorityEscalation(&'static str),
    Expired(&'static str),
    ConvergenceNotAccepted,
    WellPosednessNotAccepted,
    ObjectiveClassMismatch,
    OperatingDomainMismatch,
    SolverMismatch,
    ProducerMismatch,
    TrustMismatch,
    WithdrawalSnapshot(ArtifactClosureError),
    LifecycleSnapshot(ArtifactLifecycleJournalError),
    WithdrawalHeadMismatch,
    ArtifactWithdrawn,
    ArtifactRevoked,
    ArtifactNotSelected(ArtifactLifecycleStateV1),
    SelectionMismatch(&'static str),
}

impl fmt::Display for NduStochasticAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for NduStochasticAdmissionError {}

impl From<ArtifactAdmissionError> for NduStochasticAdmissionError {
    fn from(error: ArtifactAdmissionError) -> Self {
        Self::ArtifactAdmission(error)
    }
}
impl From<PinnedCandidateLoadError> for NduStochasticAdmissionError {
    fn from(error: PinnedCandidateLoadError) -> Self {
        Self::CurrentArtifact(error)
    }
}

pub fn canonical_ndu_stochastic_solver_digest_v1(
    coefficient_profile: &AdmittedNduCoefficientProfileV1,
    projection: &NduCoefficientProjectionV1,
) -> Result<Digest32, NduStochasticAdmissionError> {
    for (field, digest) in [
        ("coefficient_profile", coefficient_profile.digest()),
        (
            "artifact_manifest",
            coefficient_profile.artifact_manifest_digest(),
        ),
        (
            "covariance_profile",
            coefficient_profile.covariance_profile_digest(),
        ),
        (
            "z_conversion_profile",
            coefficient_profile.z_conversion_profile_digest(),
        ),
        ("projection_source", projection.source_evidence_digest),
        (
            "projection_conversion",
            projection.conversion_receipt_digest,
        ),
        ("projection_output", projection.output_digest),
    ] {
        require_digest(digest, field)?;
    }
    if projection.authority.grants_any() {
        return Err(NduStochasticAdmissionError::AuthorityEscalation(
            "coefficient_projection",
        ));
    }
    if projection.coefficient_profile_digest != coefficient_profile.digest() {
        return Err(NduStochasticAdmissionError::ProjectionMismatch);
    }
    if projection.q24_raw.len() != coefficient_profile.utility_dimension()
        || projection
            .q24_raw
            .iter()
            .any(|row| row.len() != coefficient_profile.driver_dimension())
    {
        return Err(NduStochasticAdmissionError::ProjectionMismatch);
    }

    validate_ndu_coefficient_projection_v1(coefficient_profile, projection)
        .map_err(|_| NduStochasticAdmissionError::ProjectionMismatch)?;

    let mut bytes = b"hepta.intelligence.ndu-stochastic-solver.v2\0".to_vec();
    for digest in [
        coefficient_profile.digest(),
        coefficient_profile.artifact_manifest_digest(),
        coefficient_profile.covariance_profile_digest(),
        coefficient_profile.z_conversion_profile_digest(),
        projection.source_evidence_digest,
        projection.conversion_receipt_digest,
        projection.output_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Performs final-use artifact currentness before composing the numeric and
/// independent evaluation evidence. Successful admission remains DENY_ALL and
/// is not artifact selection, activation, promotion or release authority.
pub fn admit_ndu_stochastic_candidate_v1(
    candidate: &mut RevalidatingCandidate,
    current_registry_view: VerifiedCurrentRegistryViewV1,
    request: NduStochasticAdmissionRequestV1<'_>,
    now: u64,
) -> Result<NduStochasticAdmissionReceiptV1, NduStochasticAdmissionError> {
    for (field, digest) in [
        ("withdrawal_head", request.current_withdrawal_head),
        ("objective_class", request.objective_class_digest),
        ("operating_domain", request.operating_domain_digest),
        ("compatibility", request.expected_compatibility_digest),
    ] {
        if field != "withdrawal_head" || !digest.is_zero() {
            require_digest(digest, field)?;
        }
    }

    verify_artifact_admission_v3(
        request.artifact_admission,
        request.current_withdrawal_head,
        now,
    )?;
    if request.artifact_admission.authority.grants_any()
        || request
            .artifact_admission
            .validated_manifest
            .authority
            .grants_any()
    {
        return Err(NduStochasticAdmissionError::AuthorityEscalation(
            "artifact_admission",
        ));
    }

    let v2 = &request.artifact_admission.validated_manifest;
    let manifest = &v2.manifest;
    if manifest.kind != ArtifactKind::Parameters {
        return Err(NduStochasticAdmissionError::ArtifactMismatch(
            "artifact kind",
        ));
    }
    if v2.manifest_digest != request.coefficient_profile.artifact_manifest_digest()
        || manifest.normalization_digest != request.coefficient_profile.normalization_digest()
        || manifest.runtime_tuple_digest != request.coefficient_profile.runtime_tuple_digest()
    {
        return Err(NduStochasticAdmissionError::CoefficientProfileMismatch);
    }
    if manifest.objective_class_digest != request.objective_class_digest {
        return Err(NduStochasticAdmissionError::ObjectiveClassMismatch);
    }
    if manifest.compatibility_digest != request.expected_compatibility_digest {
        return Err(NduStochasticAdmissionError::ArtifactMismatch(
            "compatibility",
        ));
    }
    if now >= request.coefficient_profile.expires_unix_ms()
        || request.coefficient_profile.expires_unix_ms() > manifest.expires_at
    {
        return Err(NduStochasticAdmissionError::Expired("coefficient_profile"));
    }

    let v1 = &candidate.spec().manifest;
    if v1.artifact_id != manifest.artifact_id
        || v1.kind != manifest.kind
        || v1.generation != manifest.generation
        || v1.content_digest != manifest.bytes_digest
        || v1.producer_id != manifest.producer_id
        || v1.compatibility_digest != manifest.compatibility_digest
        || v1.encoded_size_bytes != manifest.encoded_size_bytes
    {
        return Err(NduStochasticAdmissionError::ArtifactMismatch(
            "pinned manifest",
        ));
    }
    let registry_head_digest = current_registry_view.receipt().head_digest;
    let artifact_bytes_digest =
        candidate.with_current(current_registry_view, Digest32::of_bytes)?;
    if artifact_bytes_digest != manifest.bytes_digest {
        return Err(NduStochasticAdmissionError::ArtifactMismatch(
            "payload digest",
        ));
    }

    if request.projection.authority.grants_any()
        || request.convergence.authority().grants_any()
        || request.well_posedness.authority().grants_any()
    {
        return Err(NduStochasticAdmissionError::AuthorityEscalation(
            "qualification evidence",
        ));
    }
    if request.convergence.decision() != NduConvergenceDecisionV1::Accepted {
        return Err(NduStochasticAdmissionError::ConvergenceNotAccepted);
    }
    if request.well_posedness.decision() != NduWellPosednessDecisionV1::Accepted {
        return Err(NduStochasticAdmissionError::WellPosednessNotAccepted);
    }
    if now >= request.well_posedness.expires_unix_ms() {
        return Err(NduStochasticAdmissionError::Expired("well_posedness"));
    }
    if request.convergence.objective_class_digest() != request.objective_class_digest
        || request.well_posedness.objective_class_digest() != request.objective_class_digest
    {
        return Err(NduStochasticAdmissionError::ObjectiveClassMismatch);
    }
    if request.well_posedness.operating_domain_digest() != request.operating_domain_digest {
        return Err(NduStochasticAdmissionError::OperatingDomainMismatch);
    }
    if request.well_posedness.artifact_manifest_digest() != v2.manifest_digest {
        return Err(NduStochasticAdmissionError::CoefficientProfileMismatch);
    }
    if request.convergence.candidate_producer_identity() != &manifest.producer_id
        || request.well_posedness.candidate_producer_identity() != &manifest.producer_id
    {
        return Err(NduStochasticAdmissionError::ProducerMismatch);
    }
    if request.convergence.trust_digest() != request.well_posedness.trust_digest() {
        return Err(NduStochasticAdmissionError::TrustMismatch);
    }

    let solver_digest =
        canonical_ndu_stochastic_solver_digest_v1(request.coefficient_profile, request.projection)?;
    if request.convergence.solver_digest() != solver_digest {
        return Err(NduStochasticAdmissionError::SolverMismatch);
    }

    let convergence_certificate_digest = request.convergence.certificate_digest();
    let well_posedness_certificate_digest = request.well_posedness.certificate_digest();
    let mut bytes = b"hepta.intelligence.ndu-stochastic-admission.v2\0".to_vec();
    for digest in [
        v2.manifest_digest,
        artifact_bytes_digest,
        registry_head_digest,
        request.current_withdrawal_head,
        request.coefficient_profile.digest(),
        request.projection.output_digest,
        solver_digest,
        convergence_certificate_digest,
        well_posedness_certificate_digest,
        request.expected_compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }

    Ok(NduStochasticAdmissionReceiptV1 {
        artifact_manifest_digest: v2.manifest_digest,
        artifact_bytes_digest,
        registry_head_digest,
        withdrawal_head_digest: request.current_withdrawal_head,
        coefficient_profile_digest: request.coefficient_profile.digest(),
        q24_output_digest: request.projection.output_digest,
        solver_digest,
        convergence_certificate_digest,
        well_posedness_certificate_digest,
        admission_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduStochasticAdmissionError> {
    if value.is_zero() {
        Err(NduStochasticAdmissionError::EmptyDigest(field))
    } else {
        Ok(())
    }
}

#[path = "ndu_stochastic_lifecycle.rs"]
mod lifecycle;

#[cfg(all(test, unix))]
#[path = "ndu_stochastic_admission_tests.rs"]
mod tests;
