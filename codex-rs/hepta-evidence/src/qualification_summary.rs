use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceDispositionV1;
use crate::EvidenceError;
use crate::EvidenceVerificationProfileV1;
use crate::evidence_set_digest;

pub const EVIDENCE_VERIFICATION_SUMMARY_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceVerificationStateV1 {
    Supported,
    Missing,
    Expired,
    Conflicting,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceVerificationSummaryV1 {
    pub schema_version: u32,
    pub profile: EvidenceVerificationProfileV1,
    pub state: EvidenceVerificationStateV1,
    pub evidence_count: u16,
    pub evidence_set_sha256: Option<Sha256Digest>,
}

impl EvidenceVerificationSummaryV1 {
    pub fn from_disposition(
        profile: EvidenceVerificationProfileV1,
        disposition: &EvidenceDispositionV1,
    ) -> Result<Self, EvidenceError> {
        let (state, evidence) = match disposition {
            EvidenceDispositionV1::Supported { evidence } => {
                (EvidenceVerificationStateV1::Supported, evidence.as_slice())
            }
            EvidenceDispositionV1::Missing => {
                return Ok(Self {
                    schema_version: EVIDENCE_VERIFICATION_SUMMARY_SCHEMA_VERSION,
                    profile,
                    state: EvidenceVerificationStateV1::Missing,
                    evidence_count: 0,
                    evidence_set_sha256: None,
                });
            }
            EvidenceDispositionV1::Expired { evidence } => {
                (EvidenceVerificationStateV1::Expired, evidence.as_slice())
            }
            EvidenceDispositionV1::Conflicting { evidence, .. } => (
                EvidenceVerificationStateV1::Conflicting,
                evidence.as_slice(),
            ),
        };
        let evidence_count = u16::try_from(evidence.len()).map_err(|_| {
            EvidenceError::InvalidRecord(
                "verification summary evidence count exceeds the u16 wire domain".to_string(),
            )
        })?;
        Ok(Self {
            schema_version: EVIDENCE_VERIFICATION_SUMMARY_SCHEMA_VERSION,
            profile,
            state,
            evidence_count,
            evidence_set_sha256: Some(evidence_set_digest(evidence)?),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::EvidenceClaimClassV1;
    use crate::EvidenceId;
    use crate::EvidenceIssuerRoleV1;
    use crate::EvidenceReceiptKindV1;
    use crate::EvidenceReferenceV1;

    fn reference(id: &str) -> EvidenceReferenceV1 {
        EvidenceReferenceV1 {
            evidence_id: EvidenceId::parse(id).expect("evidence id"),
            claim_class: EvidenceClaimClassV1::ExactSource,
            receipt_kind: EvidenceReceiptKindV1::Evidence,
            issuer_role: EvidenceIssuerRoleV1::Architecture,
            issuer_principal_id: "principal:architecture".to_string(),
            payload_sha256: Sha256Digest::for_bytes(b"payload"),
            envelope_sha256: Sha256Digest::for_bytes(id.as_bytes()),
            predecessor_evidence_id: None,
            target_evidence_id: None,
            observed_unix_ms: 1,
            expires_unix_ms: None,
        }
    }

    #[test]
    fn summary_is_profile_bound_and_bounded() {
        let disposition = EvidenceDispositionV1::Supported {
            evidence: vec![reference("evidence:one"), reference("evidence:two")],
        };
        let summary = EvidenceVerificationSummaryV1::from_disposition(
            EvidenceVerificationProfileV1::ExactSourceArchitecture,
            &disposition,
        )
        .expect("summary");
        assert_eq!(summary.schema_version, 1);
        assert_eq!(summary.state, EvidenceVerificationStateV1::Supported);
        assert_eq!(summary.evidence_count, 2);
        assert!(summary.evidence_set_sha256.is_some());
    }

    #[test]
    fn missing_summary_has_no_synthetic_evidence_digest() {
        let summary = EvidenceVerificationSummaryV1::from_disposition(
            EvidenceVerificationProfileV1::ExactSourceArchitecture,
            &EvidenceDispositionV1::Missing,
        )
        .expect("summary");
        assert_eq!(summary.state, EvidenceVerificationStateV1::Missing);
        assert_eq!(summary.evidence_count, 0);
        assert_eq!(summary.evidence_set_sha256, None);
    }
}
