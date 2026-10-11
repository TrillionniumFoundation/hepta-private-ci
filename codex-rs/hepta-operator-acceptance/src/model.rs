use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityBoundary {
    pub authority: bool,
    pub enforce: bool,
    pub operator_acceptance: bool,
    pub outbound: bool,
    pub promotion: bool,
    pub qualification_authority: bool,
    pub retirement: bool,
}

impl AuthorityBoundary {
    pub(crate) const fn evidence_acceptance_only() -> Self {
        Self {
            authority: false,
            enforce: false,
            operator_acceptance: true,
            outbound: false,
            promotion: false,
            qualification_authority: false,
            retirement: false,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateBinding {
    pub base: String,
    pub bundle_sha256: String,
    pub head: String,
    pub tree: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FrozenProductBinding {
    pub audit_manifest_entry_count: usize,
    pub audit_manifest_sha256: String,
    pub audit_root: String,
    pub binary_relative_path: String,
    pub binary_sha256: String,
    pub binary_size_bytes: u64,
    pub platform: String,
    pub source_commit: String,
    pub source_tree: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OperatorBinding {
    pub acceptance_store_root: String,
    pub allowed_signers_sha256: String,
    pub key_fingerprint: String,
    pub maximum_lifetime_seconds: u64,
    pub principal: String,
    pub trust_policy_scope: String,
    pub trust_policy_sha256: String,
    pub trust_root_id: String,
    pub trust_root_revision: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExcludedGates {
    pub github_gate_run: bool,
    pub memory_gate_run: bool,
    pub proof_gate_run: bool,
    pub s2_gate_run: bool,
    pub s5_gate_run: bool,
    pub windows_gate_run: bool,
}

impl ExcludedGates {
    pub(crate) const fn none_run() -> Self {
        Self {
            github_gate_run: false,
            memory_gate_run: false,
            proof_gate_run: false,
            s2_gate_run: false,
            s5_gate_run: false,
            windows_gate_run: false,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OracleBinding {
    pub commit: String,
    pub corpus_sha256: String,
    pub expected_normalized_receipt_sha256: String,
    pub sample_id_sha256: String,
    pub tree: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationRunBinding {
    pub evidence_set_sha256: String,
    pub index: u8,
    pub manifest_sha256: String,
    pub qualification_report_sha256: String,
    pub run_id: String,
    pub run_root_relative_path: String,
    pub terminal_seal_file_sha256: String,
    pub terminal_seal_sha256: String,
    pub transport_evidence_sha256: String,
    pub transport_manifest_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationReceiptBinding {
    pub candidate_bundle_sha256: String,
    pub git_tree_manifest_sha256: String,
    pub manifest_entry_count: usize,
    pub manifest_root_kind: String,
    pub manifest_sha256: String,
    pub receipt_id: String,
    pub receipt_root: String,
    pub runs: Vec<QualificationRunBinding>,
    pub soak_summary_sha256: String,
    pub status_sha256: String,
    pub tracked_content_manifest_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AcceptanceChallenge {
    pub automatic_transition: bool,
    pub authority: AuthorityBoundary,
    pub candidate: CandidateBinding,
    pub decision: String,
    pub declaration: String,
    pub expires_at_unix_seconds: u64,
    pub excluded_gates: ExcludedGates,
    pub frozen_product: FrozenProductBinding,
    pub issued_at_unix_seconds: u64,
    pub namespace: String,
    pub nonce: String,
    pub not_before_unix_seconds: u64,
    pub operator: OperatorBinding,
    pub oracle: OracleBinding,
    pub qualification_receipt: QualificationReceiptBinding,
    pub schema: String,
    pub schema_version: u32,
    pub scope: String,
    pub signature_algorithm: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignatureBinding {
    pub algorithm: String,
    pub allowed_signers_sha256: String,
    pub detached_signature_sha256: String,
    pub detached_signature_sshsig_base64: String,
    pub key_fingerprint: String,
    pub namespace: String,
    pub principal: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AcceptanceReceipt {
    pub accepted_at_unix_seconds: u64,
    pub authority: AuthorityBoundary,
    pub challenge: AcceptanceChallenge,
    pub challenge_sha256: String,
    pub schema: String,
    pub schema_version: u32,
    pub signature: SignatureBinding,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct PreparedChallenge {
    pub challenge_path: String,
    pub challenge_sha256: String,
    pub expires_at_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SealedAcceptance {
    pub acceptance_receipt_path: String,
    pub acceptance_receipt_sha256: String,
    pub challenge_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NonceClaim {
    pub accepted_at_unix_seconds: u64,
    pub challenge_sha256: String,
    pub detached_signature_sha256: String,
    pub nonce: String,
    pub schema: String,
    pub schema_version: u32,
}
