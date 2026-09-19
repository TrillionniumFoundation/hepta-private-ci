//! Cross-owner admission of an NDU stochastic candidate.
//!
//! This adapter composes facts owned by learning.artifacts, learning.eval and
//! utility.ndu. It grants no selection, activation or effect authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence_eval::NduConditionalIdentificationDecisionV1;
use codex_hepta_intelligence_eval::NduConditionalIdentificationReceiptV1;
use codex_hepta_intelligence_eval::NduConvergenceCertificateV1;
use codex_hepta_intelligence_eval::NduConvergenceDecisionV1;
use codex_hepta_intelligence_eval::NduWellPosednessCertificateV1;
use codex_hepta_intelligence_eval::NduWellPosednessDecisionV1;
use codex_hepta_intelligence_eval::canonical_ndu_conditional_identification_receipt_digest_v1;
use codex_hepta_intelligence_eval::canonical_ndu_convergence_certificate_digest_v1;
use codex_hepta_intelligence_eval::canonical_ndu_well_posedness_certificate_digest_v1;
use codex_hepta_learning_artifacts::ArtifactAdmissionError;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_learning_artifacts::validate_artifact_publication_v3;
use codex_hepta_ndu::AdmittedCovarianceProfileV1;
use codex_hepta_ndu::AdmittedNduStochasticEvidenceV1;
use codex_hepta_ndu::AdmittedZConversionProfileV1;
use codex_hepta_ndu::NduStochasticAdmissionError;
use codex_hepta_ndu::NduStochasticEvidenceBindingV1;
use codex_hepta_ndu::ZQ24ConversionReceiptV1;
use codex_hepta_ndu::admit_stochastic_evidence_binding_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// Frozen typed evidence needed to admit a stochastic NDU candidate for further
/// composition. The withdrawal registry must be the caller's current owner view.
pub struct NduStochasticCompositionRequestV1<'a> {
    pub artifact_admission: &'a WithdrawalBoundArtifactAdmissionV3,
    pub withdrawal_registry: &'a DatasetWithdrawalRegistry,
    pub coefficient_manifest_digest: Digest32,
    pub expected_objective_class_digest: Digest32,
    pub covariance_profile: &'a AdmittedCovarianceProfileV1,
    pub z_conversion_profile: &'a AdmittedZConversionProfileV1,
    pub z_conversion_receipt: &'a ZQ24ConversionReceiptV1,
    pub conditional_identification: &'a NduConditionalIdentificationReceiptV1,
    pub well_posedness: &'a NduWellPosednessCertificateV1,
    pub convergence: &'a NduConvergenceCertificateV1,
    pub now_unix_ms: u64,
}

/// Authority-free composition receipt. This proves that the supplied typed
/// source decisions agreed at this call boundary; it is not activation evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduStochasticCompositionReceiptV1 {
    pub artifact_manifest_digest: Digest32,
    pub artifact_admission_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub conditional_identification_digest: Digest32,
    pub well_posedness_digest: Digest32,
    pub convergence_digest: Digest32,
    pub z_conversion_digest: Digest32,
    pub stochastic_admission: AdmittedNduStochasticEvidenceV1,
    pub composition_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduStochasticCompositionError {
    Artifact(ArtifactAdmissionError),
    Ndu(NduStochasticAdmissionError),
    Binding(&'static str),
}

impl fmt::Display for NduStochasticCompositionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduStochasticCompositionError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Artifact(error) => Some(error),
            Self::Ndu(error) => Some(error),
            Self::Binding(_) => None,
        }
    }
}

impl From<ArtifactAdmissionError> for NduStochasticCompositionError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Artifact(value)
    }
}

impl From<NduStochasticAdmissionError> for NduStochasticCompositionError {
    fn from(value: NduStochasticAdmissionError) -> Self {
        Self::Ndu(value)
    }
}

/// Revalidates current artifact provenance and consumes only accepted
/// learning.eval decisions before asking utility.ndu for its owner-local
/// stochastic admission. Every returned authority posture remains DENY_ALL.
pub fn admit_ndu_stochastic_product_candidate_v1(
    request: NduStochasticCompositionRequestV1<'_>,
) -> Result<NduStochasticCompositionReceiptV1, NduStochasticCompositionError> {
    use NduStochasticCompositionError as E;

    validate_artifact_publication_v3(
        request.artifact_admission,
        request.withdrawal_registry,
        request.now_unix_ms,
    )?;
    if request.artifact_admission.authority.grants_any()
        || request
            .artifact_admission
            .validated_manifest
            .authority
            .grants_any()
    {
        return Err(E::Binding("artifact authority"));
    }

    let validated = &request.artifact_admission.validated_manifest;
    let manifest = &validated.manifest;
    if !matches!(manifest.kind, ArtifactKind::Model | ArtifactKind::Parameters) {
        return Err(E::Binding("artifact kind"));
    }
    if request.coefficient_manifest_digest.is_zero()
        || !manifest
            .lineage_digests
            .contains(&request.coefficient_manifest_digest)
    {
        return Err(E::Binding("coefficient manifest lineage"));
    }
    if manifest.objective_class_digest != request.expected_objective_class_digest {
        return Err(E::Binding("objective class"));
    }

    if request.covariance_profile.units_digest()
        != request.z_conversion_profile.units_digest()
        || request.covariance_profile.driver_dimension()
            != request.z_conversion_profile.driver_dimension()
        || request.covariance_profile.utility_dimension()
            != request.z_conversion_profile.utility_dimension()
    {
        return Err(E::Binding("numeric profile compatibility"));
    }

    let z = request.z_conversion_receipt;
    if z.profile_digest() != request.z_conversion_profile.digest()
        || z.source_digest().is_zero()
        || z.receipt_digest().is_zero()
        || z.authority().grants_any()
        || z.original_z().len() != request.z_conversion_profile.utility_dimension()
        || z.q24_raw().len() != request.z_conversion_profile.utility_dimension()
        || z.original_z()
            .iter()
            .any(|row| row.len() != request.z_conversion_profile.driver_dimension())
        || z.q24_raw()
            .iter()
            .any(|row| row.len() != request.z_conversion_profile.driver_dimension())
    {
        return Err(E::Binding("z conversion"));
    }

    let identification = request.conditional_identification;
    if identification.decision() != NduConditionalIdentificationDecisionV1::Accepted
        || identification.coefficient_manifest_digest() != request.coefficient_manifest_digest
        || identification.objective_class_digest() != request.expected_objective_class_digest
        || identification.expires_unix_ms() <= request.now_unix_ms
        || identification.evaluator_identity() == &manifest.producer_id
    {
        return Err(E::Binding("conditional identification"));
    }

    let well_posedness = request.well_posedness;
    if well_posedness.decision() != NduWellPosednessDecisionV1::Accepted
        || well_posedness.manifest_digest() != request.coefficient_manifest_digest
        || well_posedness.expires_unix_ms() <= request.now_unix_ms
        || well_posedness.evaluator_identity() == &manifest.producer_id
    {
        return Err(E::Binding("well posedness"));
    }

    let convergence = request.convergence;
    if convergence.decision() != NduConvergenceDecisionV1::Accepted
        || convergence.objective_class_digest() != request.expected_objective_class_digest
        || convergence.evaluator_identity() == &manifest.producer_id
    {
        return Err(E::Binding("convergence"));
    }

    let conditional_identification_digest =
        canonical_ndu_conditional_identification_receipt_digest_v1(identification);
    let well_posedness_digest =
        canonical_ndu_well_posedness_certificate_digest_v1(well_posedness);
    let convergence_digest = canonical_ndu_convergence_certificate_digest_v1(convergence);
    let rollback_digest = rollback_binding_digest(
        &manifest.artifact_id,
        manifest.rollback_predecessor.as_ref(),
    );
    let expires_unix_ms = manifest
        .expires_at
        .min(identification.expires_unix_ms())
        .min(well_posedness.expires_unix_ms());

    let stochastic_admission = admit_stochastic_evidence_binding_v1(
        NduStochasticEvidenceBindingV1 {
            artifact_id: manifest.artifact_id.clone(),
            objective_class_digest: request.expected_objective_class_digest,
            coefficient_manifest_digest: request.coefficient_manifest_digest,
            normalization_digest: manifest.normalization_digest,
            runtime_tuple_digest: manifest.runtime_tuple_digest,
            conditioning_spec_digest: identification.conditioning_spec_digest(),
            q24_conversion_evidence_digest: z.receipt_digest(),
            conditional_identification_evidence_digest: conditional_identification_digest,
            well_posedness_certificate_digest: well_posedness_digest,
            independent_convergence_certificate_digest: convergence_digest,
            rollback_digest,
            expires_unix_ms,
        },
        request.covariance_profile,
        request.expected_objective_class_digest,
        request.now_unix_ms,
    )?;

    let withdrawal_head_digest = request.withdrawal_registry.snapshot().head_digest;
    let mut bytes = b"hepta.intelligence.ndu-stochastic-composition.v1".to_vec();
    for digest in [
        validated.manifest_digest,
        request.artifact_admission.admission_digest,
        withdrawal_head_digest,
        request.coefficient_manifest_digest,
        request.covariance_profile.digest(),
        request.z_conversion_profile.digest(),
        z.receipt_digest(),
        conditional_identification_digest,
        well_posedness_digest,
        convergence_digest,
        stochastic_admission.admission_digest(),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.now_unix_ms.to_be_bytes());
    let composition_digest = Digest32::of_bytes(&bytes);

    Ok(NduStochasticCompositionReceiptV1 {
        artifact_manifest_digest: validated.manifest_digest,
        artifact_admission_digest: request.artifact_admission.admission_digest,
        withdrawal_head_digest,
        conditional_identification_digest,
        well_posedness_digest,
        convergence_digest,
        z_conversion_digest: z.receipt_digest(),
        stochastic_admission,
        composition_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn rollback_binding_digest(
    artifact_id: &StableId,
    predecessor: Option<&StableId>,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.ndu-rollback-binding.v1".to_vec();
    push_id(&mut bytes, artifact_id);
    match predecessor {
        Some(value) => {
            bytes.push(1);
            push_id(&mut bytes, value);
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_stochastic_tests.rs"]
mod tests;
