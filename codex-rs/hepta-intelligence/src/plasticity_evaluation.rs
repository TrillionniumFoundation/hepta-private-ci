//! Sign the current governed use of a sealed owner qualification.

use codex_hepta_intelligence_eval::ProductQualificationReceiptV1;
use codex_hepta_types::Digest32;

use crate::ParameterPlasticityProductErrorV1;
use crate::PlasticityAdmissionEvidenceV1;
use crate::plasticity_admission_signing_payload_v1;

/// Bind the terminal qualification to the exact current proposal admission.
/// The evaluator's signature is checked against current host trust before the
/// product writer can append; this payload creates no statistical qualification.
pub fn plasticity_evaluation_signing_payload_v1(
    qualification: &ProductQualificationReceiptV1,
    admission: &PlasticityAdmissionEvidenceV1,
) -> Result<Vec<u8>, ParameterPlasticityProductErrorV1> {
    qualification
        .validate_integrity()
        .map_err(ParameterPlasticityProductErrorV1::Qualification)?;
    let mut bytes = b"hepta.intelligence.plasticity-qualified-use.v1\0".to_vec();
    bytes.extend_from_slice(qualification.evidence_digest.as_array());
    bytes.extend_from_slice(qualification.publication_digest.as_array());
    bytes.extend_from_slice(
        Digest32::of_bytes(&plasticity_admission_signing_payload_v1(admission)).as_array(),
    );
    Ok(bytes)
}
