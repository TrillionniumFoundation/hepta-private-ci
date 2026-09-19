use serde::Deserialize;
use serde::Serialize;

pub const MAX_KERNEL_EVIDENCE_ENVELOPE_BYTES: usize = 48 * 1024;
pub const MAX_KERNEL_EVIDENCE_REQUIRED_ROLES: usize = 32;

/// Signed qualification evidence append request. The signature is over the
/// canonical kernel.evidence envelope, not this transport wrapper.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceAppendIngress {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub signature_hex: String,
    pub envelope_json: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceCandidateV1 {
    pub candidate_id: String,
    pub source_commit: String,
    pub source_tree: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceQueryV1 {
    pub candidate: KernelEvidenceCandidateV1,
    pub claim_class: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceVerifyV1 {
    pub candidate: KernelEvidenceCandidateV1,
    pub claim_class: String,
    pub required_roles: Vec<String>,
    pub now_unix_ms: u64,
}

/// JSON is the canonical serde representation of the kernel.evidence native
/// result. Keeping storage-owned enums out of this transport crate avoids a
/// protocol -> state-store dependency while preserving strict frame bounds.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceResult {
    pub json: String,
}
