use serde_json::Value;

use super::oracle::FrozenOracle;
use super::semantic_verifier::SemanticVerifier;
use super::verification_primitives::canonical_json;
use crate::QualificationError;
use crate::test_support::dynamic_receipt;

#[test]
fn normalizes_dynamic_identity_and_matches_oracle_bytes() -> Result<(), QualificationError> {
    let oracle = FrozenOracle::load_embedded()?;
    let receipt = dynamic_receipt(&oracle)?;
    let verified = SemanticVerifier::verify(&oracle, &receipt)?;
    assert_eq!(
        verified.normalized_receipt_sha256(),
        oracle.expected_normalized_receipt_sha256()
    );
    assert_eq!(
        verified.oracle_sample_id_sha256(),
        oracle.sample_id_sha256()
    );
    assert_eq!(verified.source_receipt_sha256().len(), 64);
    Ok(())
}

#[test]
fn rejects_semantic_or_identity_divergence() -> Result<(), QualificationError> {
    let oracle = FrozenOracle::load_embedded()?;
    let mut semantic: Value = serde_json::from_slice(&dynamic_receipt(&oracle)?)
        .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    semantic["host_accepted"] = Value::Bool(false);
    assert!(SemanticVerifier::verify(&oracle, &canonical_json(&semantic)?).is_err());

    let mut identity: Value = serde_json::from_slice(&dynamic_receipt(&oracle)?)
        .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    identity["admission"]["action"]["call_id"] = Value::String("changed".to_string());
    assert!(SemanticVerifier::verify(&oracle, &canonical_json(&identity)?).is_err());
    Ok(())
}
