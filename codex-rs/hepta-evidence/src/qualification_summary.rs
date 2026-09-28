use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceDispositionV1;
use crate::EvidenceError;
use crate::EvidenceVerificationProfileV1;
use crate::QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS;
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
    /// Project an already verified disposition into a bounded wire response.
    /// This rejects inconsistent inputs but does not itself authenticate evidence
    /// or establish role independence; callers must run the store verifier first.
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
        // Check the store's bound before evidence_set_digest clones or hashes
        // any references. A wider integer wire field must not widen this budget.
        if evidence.len() > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
            return Err(EvidenceError::InvalidRecord(
                "verification summary exceeds the bounded evidence reference capacity".to_string(),
            ));
        }
        let mut ids = BTreeSet::new();
        if evidence.iter().any(|reference| {
            reference.claim_class != profile.claim_class() || !ids.insert(&reference.evidence_id)
        }) {
            return Err(EvidenceError::InvalidRecord(
                "verification summary has duplicate evidence or a mismatched claim profile"
                    .to_string(),
            ));
        }
        if state == EvidenceVerificationStateV1::Supported
            && (evidence.is_empty()
                || evidence.iter().any(|reference| {
                    reference.receipt_kind == crate::EvidenceReceiptKindV1::Revocation
                })
                || profile.required_roles().iter().any(|role| {
                    !evidence
                        .iter()
                        .any(|reference| reference.issuer_role == *role)
                }))
        {
            return Err(EvidenceError::InvalidRecord(
                "supported verification summary lacks active evidence for its required roles"
                    .to_string(),
            ));
        }
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

    #[test]
    fn supported_summary_rejects_empty_or_role_incomplete_evidence() {
        let mut wrong_role = reference("evidence:wrong-role");
        wrong_role.issuer_role = EvidenceIssuerRoleV1::Generator;
        for evidence in [vec![], vec![wrong_role]] {
            assert!(
                EvidenceVerificationSummaryV1::from_disposition(
                    EvidenceVerificationProfileV1::ExactSourceArchitecture,
                    &EvidenceDispositionV1::Supported { evidence },
                )
                .is_err()
            );
        }
    }

    #[test]
    fn summary_cannot_relabel_evidence_as_another_profile() {
        assert!(
            EvidenceVerificationSummaryV1::from_disposition(
                EvidenceVerificationProfileV1::SyntheticMergeArchitecture,
                &EvidenceDispositionV1::Supported {
                    evidence: vec![reference("evidence:exact-source")],
                },
            )
            .is_err()
        );
    }

    #[test]
    fn supported_summary_cannot_promote_a_weaker_role_profile() {
        let mut generator = reference("evidence:generator");
        generator.claim_class = EvidenceClaimClassV1::MandatoryTests;
        generator.issuer_role = EvidenceIssuerRoleV1::Generator;
        let mut evaluator = reference("evidence:evaluator");
        evaluator.claim_class = EvidenceClaimClassV1::MandatoryTests;
        evaluator.issuer_role = EvidenceIssuerRoleV1::Evaluator;
        let disposition = EvidenceDispositionV1::Supported {
            evidence: vec![generator, evaluator],
        };
        assert!(
            EvidenceVerificationSummaryV1::from_disposition(
                EvidenceVerificationProfileV1::MandatoryTestsGeneratorEvaluator,
                &disposition,
            )
            .is_ok()
        );
        assert!(
            EvidenceVerificationSummaryV1::from_disposition(
                EvidenceVerificationProfileV1::MandatoryTestsReviewed,
                &disposition,
            )
            .is_err()
        );
    }

    #[test]
    fn summary_rejects_duplicate_evidence_and_positive_revocations() {
        let item = reference("evidence:duplicate");
        let mut revoked = reference("evidence:revoked");
        revoked.receipt_kind = EvidenceReceiptKindV1::Revocation;
        for evidence in [vec![item.clone(), item], vec![revoked]] {
            assert!(
                EvidenceVerificationSummaryV1::from_disposition(
                    EvidenceVerificationProfileV1::ExactSourceArchitecture,
                    &EvidenceDispositionV1::Supported { evidence },
                )
                .is_err()
            );
        }
    }

    #[test]
    fn summary_reference_limit_matches_the_store_instead_of_u16_capacity() {
        let evidence = (0..QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS)
            .map(|index| reference(&format!("evidence:{index}")))
            .collect::<Vec<_>>();
        let accepted = EvidenceVerificationSummaryV1::from_disposition(
            EvidenceVerificationProfileV1::ExactSourceArchitecture,
            &EvidenceDispositionV1::Supported {
                evidence: evidence.clone(),
            },
        )
        .expect("maximum bounded summary");
        assert_eq!(usize::from(accepted.evidence_count), evidence.len());
        let mut excessive = evidence;
        excessive.push(reference("evidence:overflow"));
        for disposition in [
            EvidenceDispositionV1::Supported {
                evidence: excessive.clone(),
            },
            EvidenceDispositionV1::Expired {
                evidence: excessive.clone(),
            },
            EvidenceDispositionV1::Conflicting {
                evidence: excessive,
                reason: "bounded even when negative".to_string(),
            },
        ] {
            assert!(
                EvidenceVerificationSummaryV1::from_disposition(
                    EvidenceVerificationProfileV1::ExactSourceArchitecture,
                    &disposition,
                )
                .is_err()
            );
        }
    }
}
