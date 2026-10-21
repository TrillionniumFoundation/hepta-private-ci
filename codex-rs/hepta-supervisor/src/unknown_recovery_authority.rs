//! A distinct signed decision for abandoning an unresolved effect without
//! inventing a release transaction or certifying successful rollback.
use super::*;
use crate::signed_intent::SignedSupervisorIntent;
use codex_hepta_fleet::ReleaseBinding;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UnknownRecoveryObservation {
    pub release_state_generation: u64,
    pub admission_frontier_sha256: Sha256Digest,
}

pub fn absent_release_transaction_digest() -> Sha256Digest {
    Sha256Digest::for_bytes(b"hepta-supervisor:observed-absent-release-transaction:v2")
}

pub(super) fn valid_namespace(decision: &ProductionRecoveryDecision, unknown: bool) -> bool {
    if unknown {
        decision.schema_version == 2
            && decision.namespace == "hepta:production:recovery:abandon-unknown:v2"
            && decision.release_transaction_sha256 == absent_release_transaction_digest()
            && decision
                .unknown_observation
                .as_ref()
                .is_some_and(|observation| {
                    observation.release_state_generation > 0
                        && Sha256Digest::parse(observation.admission_frontier_sha256.as_str())
                            .is_ok()
                })
    } else {
        decision.schema_version == PRODUCTION_RECOVERY_SCHEMA_VERSION
            && decision.namespace == PRODUCTION_RECOVERY_NAMESPACE
            && decision.unknown_observation.is_none()
    }
}

impl H7H89ProductionGrantSigner {
    #[expect(
        clippy::too_many_arguments,
        reason = "external decision binds each observed owner fence"
    )]
    pub fn sign_abandon_unknown(
        &self,
        intent: &SignedSupervisorIntent,
        source: &ReleaseBinding,
        release_state_generation: u64,
        lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        intent
            .validate()
            .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?;
        if source.release_id.as_str() != intent.source_release || !intent.requires_recovery() {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        let mut decision = ProductionRecoveryDecision {
            schema_version: 2,
            namespace: "hepta:production:recovery:abandon-unknown:v2".to_string(),
            agent_id: intent.agent_id.clone(),
            grant_sha256: intent.grant_sha256.clone(),
            intent_sha256: intent.intent_sha256.clone(),
            release_transaction_sha256: absent_release_transaction_digest(),
            observed_release: intent.source_release.clone(),
            observed_manifest_sha256: Sha256Digest::parse(source.manifest_sha256.clone())
                .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
            observed_agentd_sha256: Sha256Digest::parse(source.agentd_program_sha256.clone())
                .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
            observed_matrixd_sha256: source
                .matrixd_program_sha256
                .as_ref()
                .map(|value| Sha256Digest::parse(value.clone()))
                .transpose()
                .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
            outcome: ProductionRecoveryOutcome::AbandonUnknown,
            unknown_observation: Some(UnknownRecoveryObservation {
                release_state_generation,
                admission_frontier_sha256: Sha256Digest::parse(
                    source.admission_frontier_sha256.clone(),
                )
                .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
            }),
            expected_lifecycle_generation: lifecycle_generation,
            authority_epoch,
            signer_id: self.signer_id.clone(),
            signer_epoch: self.signer_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            signature_base64: String::new(),
            decision_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        decision.decision_sha256 = decision.payload_digest();
        decision.signature_base64 =
            STANDARD.encode(self.signing_key.sign(&decision.signing_bytes()).to_bytes());
        decision.validate_shape()?;
        Ok(decision)
    }
}
