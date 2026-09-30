//! Read-only public transfer of authenticated custody cuts; no signing service.
use super::files::ReviewResult;
use super::generator_wire::PrincipalWire;
use super::generator_wire::decode_hex;
use super::generator_wire::encode_hex;
use crate::DatasetSnapshotReceiptV3;
use crate::DatasetSnapshotV2;
use crate::LearningEvidenceRoleV1;
use crate::LearningEvidenceTrustV1;
use crate::LearningTrustDistributionV1;
use crate::LearningTrustRootV1;
use crate::SignedLearningEvidenceV1;
use crate::SignedLearningTrustDistributionV1;
use crate::TrustedLearningSignerV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewEvidenceWireV1 {
    pub evidence_id: String,
    pub principal_id: String,
    pub role: String,
    pub trust_digest: String,
    pub scope_digest: String,
    pub objective_digest: String,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub payload_digest: String,
    pub signature_hex: String,
}
impl ReviewEvidenceWireV1 {
    pub fn from_native(value: &SignedLearningEvidenceV1) -> Self {
        Self {
            evidence_id: value.evidence_id.to_string(),
            principal_id: value.principal_id.to_string(),
            role: role_name(value.role).to_owned(),
            trust_digest: value.trust_digest.to_string(),
            scope_digest: value.scope_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            authority_epoch: value.authority_epoch,
            issued_at: value.issued_at,
            expires_at: value.expires_at,
            payload_digest: value.payload_digest.to_string(),
            signature_hex: encode_hex(&value.signature),
        }
    }
    pub fn native(&self) -> ReviewResult<SignedLearningEvidenceV1> {
        Ok(SignedLearningEvidenceV1 {
            evidence_id: StableId::new(self.evidence_id.clone())?,
            principal_id: StableId::new(self.principal_id.clone())?,
            role: role(&self.role)?,
            trust_digest: self.trust_digest.parse()?,
            scope_digest: self.scope_digest.parse()?,
            objective_digest: self.objective_digest.parse()?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            payload_digest: self.payload_digest.parse()?,
            signature: decode_hex(&self.signature_hex)?,
        })
    }
}
fn role_name(value: LearningEvidenceRoleV1) -> &'static str {
    match value {
        LearningEvidenceRoleV1::Generator => "generator",
        LearningEvidenceRoleV1::Observer => "observer",
        LearningEvidenceRoleV1::Evaluator => "evaluator",
        _ => "unsupported",
    }
}
fn role(value: &str) -> ReviewResult<LearningEvidenceRoleV1> {
    match value {
        "generator" => Ok(LearningEvidenceRoleV1::Generator),
        "observer" => Ok(LearningEvidenceRoleV1::Observer),
        "evaluator" => Ok(LearningEvidenceRoleV1::Evaluator),
        _ => Err("review transfer role unsupported".into()),
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewSignerWireV1 {
    pub principal: PrincipalWire,
    pub controller_id: String,
    pub verifying_key_hex: String,
    pub role: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewTrustWireV1 {
    pub root_id: String,
    pub root_verifying_key_hex: String,
    pub root_valid_from: u64,
    pub root_expires_at: u64,
    pub distribution_id: String,
    pub generation: u64,
    pub effective_at: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub scope_digest: String,
    pub objective_digest: String,
    pub authority_epoch: u64,
    pub signers: Vec<ReviewSignerWireV1>,
    pub signature_hex: String,
}
impl ReviewTrustWireV1 {
    pub(super) fn from_native(
        root: &LearningTrustRootV1,
        signed: &SignedLearningTrustDistributionV1,
    ) -> Self {
        Self {
            root_id: root.root_id.to_string(),
            root_verifying_key_hex: encode_hex(&root.verifying_key),
            root_valid_from: root.valid_from,
            root_expires_at: root.expires_at,
            distribution_id: signed.distribution.distribution_id.to_string(),
            generation: signed.distribution.generation,
            effective_at: signed.distribution.effective_at,
            issued_at: signed.issued_at,
            expires_at: signed.expires_at,
            scope_digest: signed.distribution.trust.scope_digest.to_string(),
            objective_digest: signed.distribution.trust.objective_digest.to_string(),
            authority_epoch: signed.distribution.trust.authority_epoch,
            signers: signed
                .distribution
                .trust
                .signers
                .iter()
                .map(|s| ReviewSignerWireV1 {
                    principal: PrincipalWire::from_principal(&s.principal),
                    controller_id: s.controller_id.to_string(),
                    verifying_key_hex: encode_hex(&s.verifying_key),
                    role: role_name(s.roles[0]).to_owned(),
                })
                .collect(),
            signature_hex: encode_hex(&signed.signature),
        }
    }
    pub fn native(&self) -> ReviewResult<(LearningTrustRootV1, SignedLearningTrustDistributionV1)> {
        if self.signers.len() != 4 {
            return Err("fixed review requires four admitted signers".into());
        }
        let scope: Digest32 = self.scope_digest.parse()?;
        let root = LearningTrustRootV1 {
            root_id: StableId::new(self.root_id.clone())?,
            scope_digest: scope,
            verifying_key: decode_hex(&self.root_verifying_key_hex)?,
            valid_from: self.root_valid_from,
            expires_at: self.root_expires_at,
            revoked_at: None,
        };
        let mut signers = Vec::new();
        for s in &self.signers {
            signers.push(TrustedLearningSignerV1 {
                principal: s.principal.principal()?,
                controller_id: StableId::new(s.controller_id.clone())?,
                verifying_key: decode_hex(&s.verifying_key_hex)?,
                roles: vec![role(&s.role)?],
                revoked_at: None,
            });
        }
        let signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: StableId::new(self.distribution_id.clone())?,
                generation: self.generation,
                effective_at: self.effective_at,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: scope,
                    objective_digest: self.objective_digest.parse()?,
                    authority_epoch: self.authority_epoch,
                    signers,
                },
            },
            root_id: root.root_id.clone(),
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            signature: decode_hex(&self.signature_hex)?,
        };
        Ok((root, signed))
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewDatasetWireV1 {
    pub snapshot_id: String,
    pub ledger_head_digest: String,
    pub objective_digest: String,
    pub eligible_frontier: u64,
    pub outcome_watermark: u64,
    pub source_record_digests: Vec<String>,
    pub pending_outcomes: u32,
    pub censored_outcomes: u32,
    pub dataset_digest: String,
    pub authority_grants_any: bool,
    pub producer: PrincipalWire,
    pub correction_cut_digest: String,
    pub revocation_cut_digest: String,
    pub inclusion_policy_digest: String,
}
impl ReviewDatasetWireV1 {
    pub(super) fn from_native(v: &DatasetSnapshotReceiptV3) -> Self {
        Self {
            snapshot_id: v.snapshot.snapshot_id.to_string(),
            ledger_head_digest: v.snapshot.ledger_head_digest.to_string(),
            objective_digest: v.snapshot.objective_digest.to_string(),
            eligible_frontier: v.snapshot.eligible_frontier,
            outcome_watermark: v.snapshot.outcome_watermark,
            source_record_digests: v
                .snapshot
                .source_record_digests
                .iter()
                .map(ToString::to_string)
                .collect(),
            pending_outcomes: v.snapshot.pending_outcomes,
            censored_outcomes: v.snapshot.censored_outcomes,
            dataset_digest: v.snapshot.dataset_digest.to_string(),
            authority_grants_any: false,
            producer: PrincipalWire::from_principal(&v.producer),
            correction_cut_digest: v.correction_cut_digest.to_string(),
            revocation_cut_digest: v.revocation_cut_digest.to_string(),
            inclusion_policy_digest: v.inclusion_policy_digest.to_string(),
        }
    }
    pub fn native(&self) -> ReviewResult<DatasetSnapshotReceiptV3> {
        if self.authority_grants_any || self.source_record_digests.len() > 4096 {
            return Err("review dataset authority/bound".into());
        }
        Ok(DatasetSnapshotReceiptV3 {
            snapshot: DatasetSnapshotV2 {
                snapshot_id: StableId::new(self.snapshot_id.clone())?,
                ledger_head_digest: self.ledger_head_digest.parse()?,
                objective_digest: self.objective_digest.parse()?,
                eligible_frontier: self.eligible_frontier,
                outcome_watermark: self.outcome_watermark,
                source_record_digests: self
                    .source_record_digests
                    .iter()
                    .map(|s| s.parse())
                    .collect::<Result<Vec<_>, _>>()?,
                pending_outcomes: self.pending_outcomes,
                censored_outcomes: self.censored_outcomes,
                dataset_digest: self.dataset_digest.parse()?,
                authority: AuthorityPosture::DENY_ALL,
            },
            producer: self.producer.principal()?,
            correction_cut_digest: self.correction_cut_digest.parse()?,
            revocation_cut_digest: self.revocation_cut_digest.parse()?,
            inclusion_policy_digest: self.inclusion_policy_digest.parse()?,
        })
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedCalibrationCutV1 {
    pub schema: String,
    pub observer_program_digest: String,
    pub ledger_binding_digest: String,
    pub ledger_file_digest: String,
    pub acknowledged_sequence: u64,
    pub acknowledged_head: String,
    pub candidate_manifest_digest: String,
    pub baseline_manifest_digest: String,
    pub candidate_weights_digest: String,
    pub baseline_weights_digest: String,
    pub audit_digest: String,
    pub dataset: ReviewDatasetWireV1,
    pub generator_payload_hex: String,
    pub generator_evidence: ReviewEvidenceWireV1,
    pub freeze_evidence: ReviewEvidenceWireV1,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedCalibrationPublicationV1 {
    pub cut: FixedCalibrationCutV1,
    pub observer_evidence: ReviewEvidenceWireV1,
    pub trust: ReviewTrustWireV1,
}
pub fn decode_review_payload_hex(value: &str) -> ReviewResult<Vec<u8>> {
    if value.len() > 2 * 1024 * 1024
        || !value.len().is_multiple_of(2)
        || !value.bytes().all(|b| b.is_ascii_hexdigit())
    {
        return Err("review payload hex bound".into());
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|s| Ok(u8::from_str_radix(std::str::from_utf8(s)?, 16)?))
        .collect()
}

impl FixedCalibrationCutV1 {
    pub fn binding(&self) -> ReviewResult<crate::CalibrationCutBindingV1> {
        let generator = self.generator_evidence.native()?;
        let freeze = self.freeze_evidence.native()?;
        let authentication = |evidence: &SignedLearningEvidenceV1| {
            let mut bytes = evidence.signing_bytes();
            bytes.extend_from_slice(&evidence.signature);
            Digest32::of_bytes(&bytes)
        };
        Ok(crate::CalibrationCutBindingV1 {
            observer_program_digest: self.observer_program_digest.parse()?,
            ledger_binding_digest: self.ledger_binding_digest.parse()?,
            ledger_file_digest: self.ledger_file_digest.parse()?,
            acknowledged_sequence: self.acknowledged_sequence,
            acknowledged_head: self.acknowledged_head.parse()?,
            candidate_manifest_digest: self.candidate_manifest_digest.parse()?,
            baseline_manifest_digest: self.baseline_manifest_digest.parse()?,
            candidate_weights_digest: self.candidate_weights_digest.parse()?,
            baseline_weights_digest: self.baseline_weights_digest.parse()?,
            audit_digest: self.audit_digest.parse()?,
            dataset_digest: self.dataset.dataset_digest.parse()?,
            generator_payload_digest: Digest32::of_bytes(&decode_review_payload_hex(
                &self.generator_payload_hex,
            )?),
            generator_authentication_digest: authentication(&generator),
            freeze_payload_digest: freeze.payload_digest,
            freeze_authentication_digest: authentication(&freeze),
        })
    }
    pub fn signing_payload(&self) -> ReviewResult<Vec<u8>> {
        Ok(crate::calibration_cut_signing_payload_v1(&self.binding()?))
    }
}
