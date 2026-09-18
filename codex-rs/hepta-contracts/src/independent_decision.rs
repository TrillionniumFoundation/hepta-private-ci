use serde::Deserialize;
use serde::Serialize;

use crate::Sha256Digest;

pub const INDEPENDENT_DECISION_MAX_ENCODED_BYTES: usize = 262_144;
pub const INDEPENDENT_DECISION_MAX_CONDITIONS_BYTES: usize = 32_768;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IndependentDecisionReceiptV1 {
    pub decision_id: String,
    pub candidate_id: String,
    pub role: String,
    pub principal_id: String,
    pub signing_identity_digest: Sha256Digest,
    pub evidence_set_digest: Sha256Digest,
    pub decision: String,
    pub conditions: Vec<String>,
    pub expires_unix_ms: u64,
}

impl IndependentDecisionReceiptV1 {
    pub fn validate(&self) -> Result<(), String> {
        self.validate_shallow()?;
        let encoded = self.canonical_bytes()?;
        if encoded.len() > INDEPENDENT_DECISION_MAX_ENCODED_BYTES {
            return Err("independent decision exceeds the registered protocol bound".to_string());
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, String> {
        serde_json::to_vec(self)
            .map_err(|error| format!("independent decision serialization failed: {error}"))
    }

    pub fn semantic_digest(&self) -> Result<Sha256Digest, String> {
        self.validate()?;
        Ok(Sha256Digest::for_bytes(&self.canonical_bytes()?))
    }

    fn validate_shallow(&self) -> Result<(), String> {
        bounded_identifier(&self.decision_id, 128, "decisionId")?;
        bounded_identifier(&self.candidate_id, 128, "candidateId")?;
        bounded_identifier(&self.principal_id, 128, "principalId")?;
        if !matches!(
            self.role.as_str(),
            "independent_evaluator" | "architecture_reviewer" | "security_reviewer"
        ) {
            return Err("role is not a registered independent decision role".to_string());
        }
        if !matches!(self.decision.as_str(), "accept" | "reject" | "conditional") {
            return Err("decision is not a registered independent decision value".to_string());
        }
        if self.expires_unix_ms == 0 {
            return Err("expiresUnixMs must be non-zero".to_string());
        }
        let conditions = serde_json::to_vec(&self.conditions)
            .map_err(|error| format!("conditions are not serializable: {error}"))?;
        if conditions.len() > INDEPENDENT_DECISION_MAX_CONDITIONS_BYTES {
            return Err("conditions exceed the registered protocol bound".to_string());
        }
        Ok(())
    }
}

fn bounded_identifier(value: &str, max: usize, label: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > max
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-:/".contains(&byte))
    {
        return Err(format!("{label} is not a bounded identifier"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> IndependentDecisionReceiptV1 {
        IndependentDecisionReceiptV1 {
            decision_id: "decision:kernel-evidence:1".to_string(),
            candidate_id: "candidate:kernel-evidence:1".to_string(),
            role: "independent_evaluator".to_string(),
            principal_id: "principal:evaluator-a".to_string(),
            signing_identity_digest: Sha256Digest::for_bytes(b"signing-identity"),
            evidence_set_digest: Sha256Digest::for_bytes(b"evidence-set"),
            decision: "accept".to_string(),
            conditions: vec!["exact source and merge checks passed".to_string()],
            expires_unix_ms: 1_800_000_000_000,
        }
    }

    #[test]
    fn independent_decision_round_trips_and_has_stable_digest() {
        let receipt = fixture();
        receipt.validate().expect("valid receipt");
        let encoded = receipt.canonical_bytes().expect("encode");
        let decoded: IndependentDecisionReceiptV1 =
            serde_json::from_slice(&encoded).expect("decode");
        assert_eq!(decoded, receipt);
        assert_eq!(
            receipt.semantic_digest().expect("digest"),
            decoded.semantic_digest().expect("decoded digest")
        );
    }

    #[test]
    fn independent_decision_rejects_unknown_fields_and_unregistered_roles() {
        let mut value = serde_json::to_value(fixture()).expect("value");
        value
            .as_object_mut()
            .expect("object")
            .insert("authority".to_string(), serde_json::Value::Bool(true));
        assert!(serde_json::from_value::<IndependentDecisionReceiptV1>(value).is_err());

        let mut invalid = fixture();
        invalid.role = "generator".to_string();
        assert!(invalid.validate().is_err());
    }

    #[test]
    fn independent_decision_conditions_are_bounded() {
        let mut invalid = fixture();
        invalid.conditions = vec!["x".repeat(INDEPENDENT_DECISION_MAX_CONDITIONS_BYTES)];
        assert!(invalid.validate().is_err());
    }
}
