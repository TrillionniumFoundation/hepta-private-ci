//! Original public evidence transfer only. Parsing never authenticates issuance.
use crate::LearningEvidenceRoleV1;
use crate::SignedLearningEvidenceV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
type ReviewResult<T> = Result<T, Box<dyn std::error::Error>>;
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
pub(crate) fn role_name(value: LearningEvidenceRoleV1) -> &'static str {
    match value {
        LearningEvidenceRoleV1::Generator => "generator",
        LearningEvidenceRoleV1::Observer => "observer",
        LearningEvidenceRoleV1::Evaluator => "evaluator",
        LearningEvidenceRoleV1::Selector => "selector",
        LearningEvidenceRoleV1::UnlearningAuthority => "unlearning_authority",
        _ => "unsupported",
    }
}
pub(crate) fn role(value: &str) -> ReviewResult<LearningEvidenceRoleV1> {
    match value {
        "generator" => Ok(LearningEvidenceRoleV1::Generator),
        "observer" => Ok(LearningEvidenceRoleV1::Observer),
        "evaluator" => Ok(LearningEvidenceRoleV1::Evaluator),
        "selector" => Ok(LearningEvidenceRoleV1::Selector),
        "unlearning_authority" => Ok(LearningEvidenceRoleV1::UnlearningAuthority),
        _ => Err("review transfer role unsupported".into()),
    }
}

pub(crate) fn encode_hex(bytes: &[u8]) -> String {
    bytes.iter().map(|value| format!("{value:02x}")).collect()
}
pub(crate) fn decode_hex<const N: usize>(value: &str) -> ReviewResult<[u8; N]> {
    if value.len() != N * 2 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("invalid fixed-width hexadecimal value".into());
    }
    let mut output = [0; N];
    for (index, byte) in output.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)?;
    }
    Ok(output)
}
