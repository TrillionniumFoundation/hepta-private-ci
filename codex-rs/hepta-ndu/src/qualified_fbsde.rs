use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AdmittedCovarianceProfileV1;
use crate::ConditionalMomentsV1;
use crate::CovarianceError;
use crate::ZEstimateV1;
use crate::solve_backward_regression;

const Q24_SCALE: f64 = 16_777_216.0;

/// Externally owned evidence required before the native covariance kernel may be
/// consumed as a qualified FBSDE regression candidate. Digests name immutable
/// artifacts; this crate never verifies signatures or revocation by itself.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeEvidenceBundleV1 {
    pub coefficient_artifact_digest: Digest32,
    pub coefficient_profile_digest: Digest32,
    pub source_digest: Digest32,
    pub conditioning_digest: Digest32,
    pub conditioning_identification_digest: Digest32,
    pub coordinate_manifest_digest: Digest32,
    pub q24_conversion_profile_digest: Digest32,
    pub consumer_admission_digest: Digest32,
    pub independent_qualification_digest: Digest32,
}

/// Embeddings must verify ownership, signatures, freshness, revocation and the
/// independent qualification record before returning Ok.
pub trait NduFbsdeEvidenceVerifierV1 {
    fn verify(
        &self,
        evidence: &NduFbsdeEvidenceBundleV1,
        covariance_profile_digest: Digest32,
    ) -> Result<(), CovarianceError>;
}

impl<F> NduFbsdeEvidenceVerifierV1 for F
where
    F: Fn(&NduFbsdeEvidenceBundleV1, Digest32) -> Result<(), CovarianceError>,
{
    fn verify(
        &self,
        evidence: &NduFbsdeEvidenceBundleV1,
        covariance_profile_digest: Digest32,
    ) -> Result<(), CovarianceError> {
        self(evidence, covariance_profile_digest)
    }
}

/// Opaque result of external evidence admission. Callers cannot construct it
/// directly or swap the admitted profile/evidence after verification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedNduFbsdeEvidenceV1 {
    covariance_profile_digest: Digest32,
    evidence: NduFbsdeEvidenceBundleV1,
    evidence_digest: Digest32,
}

impl AdmittedNduFbsdeEvidenceV1 {
    pub fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct NduQ24ConversionReceiptV1 {
    pub z_q24: Vec<Vec<i64>>,
    pub maximum_absolute_error: f64,
    pub source_regression_digest: Digest32,
    pub conversion_profile_digest: Digest32,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, PartialEq)]
pub struct QualifiedZEstimateV1 {
    pub shadow: ZEstimateV1,
    pub q24: NduQ24ConversionReceiptV1,
    pub admitted_evidence_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn admit_fbsde_evidence_v1(
    evidence: NduFbsdeEvidenceBundleV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
    verifier: &impl NduFbsdeEvidenceVerifierV1,
) -> Result<AdmittedNduFbsdeEvidenceV1, CovarianceError> {
    for digest in [
        evidence.coefficient_artifact_digest,
        evidence.coefficient_profile_digest,
        evidence.source_digest,
        evidence.conditioning_digest,
        evidence.conditioning_identification_digest,
        evidence.coordinate_manifest_digest,
        evidence.q24_conversion_profile_digest,
        evidence.consumer_admission_digest,
        evidence.independent_qualification_digest,
    ] {
        if digest.is_zero() {
            return Err(CovarianceError::MissingDigest);
        }
    }
    verifier.verify(&evidence, covariance_profile.digest())?;

    let mut bytes = b"hepta.ndu.fbsde-evidence-admission.v1".to_vec();
    bytes.extend_from_slice(covariance_profile.digest().as_array());
    for digest in [
        evidence.coefficient_artifact_digest,
        evidence.coefficient_profile_digest,
        evidence.source_digest,
        evidence.conditioning_digest,
        evidence.conditioning_identification_digest,
        evidence.coordinate_manifest_digest,
        evidence.q24_conversion_profile_digest,
        evidence.consumer_admission_digest,
        evidence.independent_qualification_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(AdmittedNduFbsdeEvidenceV1 {
        covariance_profile_digest: covariance_profile.digest(),
        evidence,
        evidence_digest: Digest32::of_bytes(&bytes),
    })
}

/// Consume the already admitted external evidence, solve in the bounded native
/// profile, and publish an explicit signed-Q24 nearest/ties-to-even projection.
/// This remains an authority-free numerical receipt, not a convergence,
/// selection, activation or release certificate.
pub fn solve_qualified_backward_regression_v1(
    moments: &ConditionalMomentsV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
    admitted: &AdmittedNduFbsdeEvidenceV1,
) -> Result<QualifiedZEstimateV1, CovarianceError> {
    if admitted.covariance_profile_digest != covariance_profile.digest()
        || moments.source_digest != admitted.evidence.source_digest
        || moments.conditioning_digest != admitted.evidence.conditioning_digest
    {
        return Err(CovarianceError::QualificationMismatch);
    }

    let shadow = solve_backward_regression(moments, covariance_profile)?;
    let q24 = convert_z_to_q24(&shadow, admitted.evidence.q24_conversion_profile_digest)?;

    let mut bytes = b"hepta.ndu.qualified-backward-regression.v1".to_vec();
    bytes.extend_from_slice(admitted.evidence_digest.as_array());
    bytes.extend_from_slice(shadow.evidence_digest.as_array());
    bytes.extend_from_slice(q24.evidence_digest.as_array());
    let receipt_digest = Digest32::of_bytes(&bytes);

    Ok(QualifiedZEstimateV1 {
        shadow,
        q24,
        admitted_evidence_digest: admitted.evidence_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn convert_z_to_q24(
    shadow: &ZEstimateV1,
    conversion_profile_digest: Digest32,
) -> Result<NduQ24ConversionReceiptV1, CovarianceError> {
    if conversion_profile_digest.is_zero() {
        return Err(CovarianceError::MissingDigest);
    }
    let mut z_q24 = Vec::with_capacity(shadow.z.len());
    let mut maximum_absolute_error = 0.0_f64;
    for row in &shadow.z {
        let mut converted = Vec::with_capacity(row.len());
        for value in row {
            let raw = round_q24_ties_even(*value)?;
            let reconstructed = raw as f64 / Q24_SCALE;
            maximum_absolute_error = maximum_absolute_error.max((value - reconstructed).abs());
            converted.push(raw);
        }
        z_q24.push(converted);
    }
    let maximum_allowed = 0.5 / Q24_SCALE;
    if !maximum_absolute_error.is_finite()
        || maximum_absolute_error > maximum_allowed + f64::EPSILON
    {
        return Err(CovarianceError::Q24Conversion);
    }

    let mut bytes = b"hepta.ndu.z-q24-rne-conversion.v1".to_vec();
    bytes.extend_from_slice(shadow.evidence_digest.as_array());
    bytes.extend_from_slice(conversion_profile_digest.as_array());
    bytes.extend_from_slice(&maximum_absolute_error.to_bits().to_be_bytes());
    bytes.extend_from_slice(&(z_q24.len() as u64).to_be_bytes());
    for row in &z_q24 {
        bytes.extend_from_slice(&(row.len() as u64).to_be_bytes());
        for value in row {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Ok(NduQ24ConversionReceiptV1 {
        z_q24,
        maximum_absolute_error,
        source_regression_digest: shadow.evidence_digest,
        conversion_profile_digest,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn round_q24_ties_even(value: f64) -> Result<i64, CovarianceError> {
    if !value.is_finite() {
        return Err(CovarianceError::NonFinite);
    }
    let scaled = value * Q24_SCALE;
    if !scaled.is_finite()
        || scaled < i64::MIN as f64
        || scaled > i64::MAX as f64
    {
        return Err(CovarianceError::Q24Conversion);
    }
    let floor = scaled.floor();
    let fraction = scaled - floor;
    let floor_i128 = floor as i128;
    let rounded = if fraction < 0.5 {
        floor_i128
    } else if fraction > 0.5 || floor_i128.rem_euclid(2) != 0 {
        floor_i128
            .checked_add(1)
            .ok_or(CovarianceError::Q24Conversion)?
    } else {
        floor_i128
    };
    i64::try_from(rounded).map_err(|_| CovarianceError::Q24Conversion)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ConditionalMomentSampleV1;
    use crate::CovarianceConventionV1;
    use crate::NduCovarianceProfileV1;
    use crate::admit_covariance_profile;
    use crate::estimate_conditional_moments;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn profile() -> AdmittedCovarianceProfileV1 {
        admit_covariance_profile(NduCovarianceProfileV1 {
            units_digest: digest("units"),
            driver_dimension: 1,
            utility_dimension: 1,
            convention: CovarianceConventionV1::Increment,
            minimum_increment_eigenvalue: 1e-12,
            maximum_condition: 1e6,
            maximum_absolute_sample: 100.0,
            maximum_absolute_z: 100.0,
            maximum_relative_residual: 1e-10,
        })
        .expect("profile")
    }

    fn evidence(source: Digest32, conditioning: Digest32) -> NduFbsdeEvidenceBundleV1 {
        NduFbsdeEvidenceBundleV1 {
            coefficient_artifact_digest: digest("coefficient-artifact"),
            coefficient_profile_digest: digest("coefficient-profile"),
            source_digest: source,
            conditioning_digest: conditioning,
            conditioning_identification_digest: digest("identification"),
            coordinate_manifest_digest: digest("original-coordinates"),
            q24_conversion_profile_digest: digest("signed-q24-rne-v1"),
            consumer_admission_digest: digest("consumer-admission"),
            independent_qualification_digest: digest("independent-qualification"),
        }
    }

    fn moments(
        profile: &AdmittedCovarianceProfileV1,
        source: Digest32,
        conditioning: Digest32,
    ) -> ConditionalMomentsV1 {
        let samples = [
            ConditionalMomentSampleV1 {
                conditioning_digest: conditioning,
                duration_micros: 1_000_000,
                increment: vec![-1.0],
                utility: vec![-2.0],
            },
            ConditionalMomentSampleV1 {
                conditioning_digest: conditioning,
                duration_micros: 1_000_000,
                increment: vec![1.0],
                utility: vec![2.0],
            },
        ];
        estimate_conditional_moments(&samples, source, profile).expect("moments")
    }

    #[test]
    fn qualified_regression_consumes_external_evidence_and_emits_q24() {
        let profile = profile();
        let source = digest("source");
        let conditioning = digest("conditioning");
        let verifier = |_: &NduFbsdeEvidenceBundleV1, profile_digest: Digest32| {
            (profile_digest == profile.digest())
                .then_some(())
                .ok_or(CovarianceError::EvidenceRejected)
        };
        let admitted =
            admit_fbsde_evidence_v1(evidence(source, conditioning), &profile, &verifier)
                .expect("admission");
        let receipt = solve_qualified_backward_regression_v1(
            &moments(&profile, source, conditioning),
            &profile,
            &admitted,
        )
        .expect("qualified solve");

        assert_eq!(receipt.q24.z_q24, vec![vec![2_i64 << 24]]);
        assert_eq!(receipt.q24.maximum_absolute_error, 0.0);
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    }

    #[test]
    fn admitted_evidence_cannot_be_reused_for_other_conditioning() {
        let profile = profile();
        let source = digest("source");
        let conditioning = digest("conditioning");
        let verifier = |_: &NduFbsdeEvidenceBundleV1, _: Digest32| Ok(());
        let admitted =
            admit_fbsde_evidence_v1(evidence(source, conditioning), &profile, &verifier)
                .expect("admission");
        let other = moments(&profile, source, digest("other-conditioning"));
        assert_eq!(
            solve_qualified_backward_regression_v1(&other, &profile, &admitted),
            Err(CovarianceError::QualificationMismatch)
        );
    }

    #[test]
    fn external_verifier_rejection_fails_closed() {
        let profile = profile();
        let source = digest("source");
        let conditioning = digest("conditioning");
        let verifier = |_: &NduFbsdeEvidenceBundleV1, _: Digest32| {
            Err(CovarianceError::EvidenceRejected)
        };
        assert_eq!(
            admit_fbsde_evidence_v1(evidence(source, conditioning), &profile, &verifier),
            Err(CovarianceError::EvidenceRejected)
        );
    }

    #[test]
    fn q24_rounding_is_signed_nearest_ties_even() {
        let half = 0.5 / Q24_SCALE;
        assert_eq!(round_q24_ties_even(2.0 / Q24_SCALE + half), Ok(2));
        assert_eq!(round_q24_ties_even(3.0 / Q24_SCALE + half), Ok(4));
        assert_eq!(round_q24_ties_even(-2.0 / Q24_SCALE - half), Ok(-2));
        assert_eq!(round_q24_ties_even(-3.0 / Q24_SCALE - half), Ok(-4));
    }
}
