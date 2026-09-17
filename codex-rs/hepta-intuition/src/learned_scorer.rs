//! Contract between the upstream learned scorer and `intuition.policy`.
//!
//! Model inference is intentionally NOT owned by this crate. The scorer owner
//! produces calibrated candidate fields; this crate validates qualification,
//! completeness, policy thresholds and intervention selection. Keeping that
//! boundary explicit prevents an advisory policy crate from silently loading or
//! mutating models at decision time.

use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScorerContractV1 {
    pub contract_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub model_artifact_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub score_semantics_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: u64,
}

pub fn canonical_learned_scorer_contract_digest_v1(
    contract: &LearnedScorerContractV1,
) -> Digest32 {
    let mut bytes = b"hepta.intuition.learned-scorer-contract.v1".to_vec();
    for digest in [
        contract.feature_schema_digest,
        contract.model_artifact_digest,
        contract.calibration_artifact_digest,
        contract.ood_artifact_digest,
        contract.score_semantics_digest,
        contract.policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&contract.policy_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearnedScorerContractError {
    EmptyDigest(&'static str),
    ContractDigestMismatch,
}

pub fn validate_learned_scorer_contract_v1(
    contract: &LearnedScorerContractV1,
) -> Result<(), LearnedScorerContractError> {
    for (name, digest) in [
        ("feature schema", contract.feature_schema_digest),
        ("model artifact", contract.model_artifact_digest),
        ("calibration artifact", contract.calibration_artifact_digest),
        ("ood artifact", contract.ood_artifact_digest),
        ("score semantics", contract.score_semantics_digest),
        ("policy", contract.policy_digest),
    ] {
        if digest.is_zero() {
            return Err(LearnedScorerContractError::EmptyDigest(name));
        }
    }
    if canonical_learned_scorer_contract_digest_v1(contract) != contract.contract_digest {
        return Err(LearnedScorerContractError::ContractDigestMismatch);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }

    #[test]
    fn scorer_contract_binds_model_features_calibration_and_semantics() {
        let base = LearnedScorerContractV1 {
            contract_digest: Digest32::ZERO,
            feature_schema_digest: digest("features"),
            model_artifact_digest: digest("model"),
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
            score_semantics_digest: digest("semantics"),
            policy_digest: digest("policy"),
            policy_generation: 7,
        };
        let contract = LearnedScorerContractV1 {
            contract_digest: canonical_learned_scorer_contract_digest_v1(&base),
            ..base
        };
        assert_eq!(validate_learned_scorer_contract_v1(&contract), Ok(()));

        let mut changed = contract;
        changed.model_artifact_digest = digest("different-model");
        assert_eq!(
            validate_learned_scorer_contract_v1(&changed),
            Err(LearnedScorerContractError::ContractDigestMismatch)
        );
    }
}
