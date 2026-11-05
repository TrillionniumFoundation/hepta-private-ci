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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub predecessor: Option<UnknownRecoveryPredecessorV1>,
}

/// Explicit observation of the externally anchored predecessor. Constructing
/// these bytes is not a current-owner admission; the recovery owner rechecks it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UnknownRecoveryPredecessorV1 {
    pub schema_version: u32,
    pub anchor_generation: u64,
    pub anchor_sha256: Sha256Digest,
}

impl UnknownRecoveryPredecessorV1 {
    pub fn from_anchor(
        anchor: &codex_hepta_fleet::ReleaseIntentAnchorV1,
    ) -> Result<Self, ProductionAuthorityError> {
        let digest = anchor
            .sha256()
            .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?;
        Ok(Self {
            schema_version: 1,
            anchor_generation: anchor.generation,
            anchor_sha256: Sha256Digest::from_sha256_output(digest.into()),
        })
    }

    /// Explicit absence must come from a fresh external owner observation.
    /// A missing local file is never sufficient to construct live permission.
    pub fn from_absent(agent_id: &AgentId) -> Self {
        let digest = codex_hepta_fleet::ReleaseIntentAnchorV1::absent_sha256(agent_id);
        Self {
            schema_version: 1,
            anchor_generation: 0,
            anchor_sha256: Sha256Digest::from_sha256_output(digest.into()),
        }
    }

    pub fn valid_for(&self, agent_id: &AgentId) -> bool {
        self.schema_version == 1
            && Sha256Digest::parse(self.anchor_sha256.as_str()).is_ok()
            && (self.anchor_generation > 0 || self == &Self::from_absent(agent_id))
    }
}

pub fn absent_release_transaction_digest() -> Sha256Digest {
    Sha256Digest::for_bytes(b"hepta-supervisor:observed-absent-release-transaction:v2")
}

pub(super) fn valid_namespace(decision: &ProductionRecoveryDecision, unknown: bool) -> bool {
    if decision.completion_observation.is_some()
        || decision.retained_publication_observation.is_some()
        || matches!(
            decision.outcome,
            ProductionRecoveryOutcome::ConfirmUnknownPublication
                | ProductionRecoveryOutcome::ConfirmCommittedPublication
                | ProductionRecoveryOutcome::ConfirmRolledBackPublication
                | ProductionRecoveryOutcome::RetryRetainedPublication
        )
    {
        return false;
    }
    if unknown {
        decision.schema_version == 2
            && decision.namespace == "hepta:production:recovery:abandon-unknown:v2"
            && decision.release_transaction_sha256 == absent_release_transaction_digest()
            && decision
                .unknown_observation
                .as_ref()
                .is_some_and(|observation| {
                    observation.predecessor.is_none()
                        && observation.release_state_generation > 0
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
        let mut decision = super::unsigned::abandon_unknown(
            &self.signer_id,
            self.signer_epoch,
            intent,
            source,
            release_state_generation,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        decision.decision_sha256 = decision.payload_digest();
        decision.signature_base64 =
            STANDARD.encode(self.signing_key.sign(&decision.signing_bytes()).to_bytes());
        decision.validate_shape()?;
        Ok(decision)
    }
}
