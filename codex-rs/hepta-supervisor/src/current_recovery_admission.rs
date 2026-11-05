//! A current recovery admission can observe and publish facts. The explicit
//! reconciliation variant can never become a process or mutation admission.
use crate::H7H89ProductionGrantVerifier;
use crate::ProductionRecoveryDecision;
use crate::SupervisorError;
use crate::signed_intent_policy::authority_milliseconds;
use crate::signed_intent_policy::digest_bytes;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::CurrentProtocolConfigurationAdmission;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::PendingIntentReconciliationAdmission;
use codex_hepta_fleet::ReleaseBinding;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ReleaseIntentAnchorV1;

pub(crate) enum CurrentRecoveryAdmission {
    Ordinary(Box<CurrentProtocolConfigurationAdmission>),
    Reconciliation(Box<PendingIntentReconciliationAdmission>),
}

pub(crate) enum RecoveryPublicationState {
    Ordinary,
    ReopenRequired,
}

impl CurrentRecoveryAdmission {
    pub(crate) fn acquire(
        registry: &FleetRegistry,
        verifier: &H7H89ProductionGrantVerifier,
    ) -> Result<Self, SupervisorError> {
        let policy = verifier.policy_sha256().ok_or_else(|| {
            SupervisorError::ProductionAuthority(
                "current recovery requires the explicit PQ policy".to_string(),
            )
        })?;
        let policy = digest_bytes(policy)?;
        if registry.is_release_intent_reconciliation() {
            Ok(Self::Reconciliation(Box::new(
                registry.admit_pending_intent_reconciliation(policy)?,
            )))
        } else {
            Ok(Self::Ordinary(Box::new(
                registry.admit_protocol_configuration(policy)?,
            )))
        }
    }

    pub(crate) fn now_seconds(&self) -> Result<u64, SupervisorError> {
        Ok(match self {
            Self::Ordinary(guard) => guard.revalidate()?,
            Self::Reconciliation(guard) => guard.revalidate()?,
        } / 1000)
    }

    pub(crate) fn check_window(
        &self,
        decision: &ProductionRecoveryDecision,
    ) -> Result<(), SupervisorError> {
        check_window(self.now_seconds()?, decision)
    }

    fn with_verified_window(
        self,
        decision: &ProductionRecoveryDecision,
    ) -> Result<Self, SupervisorError> {
        let not_before = authority_milliseconds(decision.issued_at_unix_seconds)?;
        let expires = authority_milliseconds(decision.expires_at_unix_seconds)?;
        Ok(match self {
            Self::Ordinary(guard) => Self::Ordinary(Box::new(
                (*guard).with_verified_decision_window(not_before, expires)?,
            )),
            Self::Reconciliation(guard) => Self::Reconciliation(Box::new(
                (*guard).with_verified_decision_window(not_before, expires)?,
            )),
        })
    }

    pub(crate) fn expected(
        &self,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, SupervisorError> {
        match self {
            Self::Ordinary(guard) => Ok(guard.intent_anchor(agent)?),
            Self::Reconciliation(guard) => Ok(guard.expected_intent_anchor().cloned()),
        }
    }

    pub(crate) fn previous_closed(
        &self,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, SupervisorError> {
        match self {
            Self::Ordinary(guard) => Ok(guard.previous_closed_intent_anchor(agent)?),
            Self::Reconciliation(guard) => Ok(guard.previous_closed_intent_anchor().cloned()),
        }
    }

    pub(crate) fn pending(&self) -> Option<&ReleaseIntentAnchorV1> {
        match self {
            Self::Ordinary(_) => None,
            Self::Reconciliation(guard) => Some(guard.pending_intent_anchor()),
        }
    }

    pub(crate) fn replacement(&self) -> Option<&ReleaseIntentAnchorV1> {
        match self {
            Self::Ordinary(_) => None,
            Self::Reconciliation(guard) => guard.replacement_intent_anchor(),
        }
    }

    pub(crate) fn replacement_publication_sha256(
        &self,
    ) -> Result<Option<[u8; 32]>, SupervisorError> {
        match self {
            Self::Ordinary(_) => Ok(None),
            Self::Reconciliation(guard) => Ok(guard.replacement_publication_sha256()?),
        }
    }

    pub(crate) fn retained_reconciliation_sha256(
        &self,
    ) -> Result<Option<[u8; 32]>, SupervisorError> {
        match self {
            Self::Ordinary(_) => Ok(None),
            Self::Reconciliation(guard) => Ok(guard.retained_reconciliation_sha256()?),
        }
    }

    pub(crate) fn pending_publication_sha256(&self) -> Result<[u8; 32], SupervisorError> {
        match self {
            Self::Reconciliation(guard) => Ok(guard.pending_publication_sha256()?),
            Self::Ordinary(_) => Err(SupervisorError::ProductionAuthority(
                "completion confirmation requires its retained uncertain proposal".to_string(),
            )),
        }
    }

    pub(crate) fn binding(
        &self,
        registry: &FleetRegistry,
        agent: &AgentId,
        release: &ReleaseId,
    ) -> Result<ReleaseBinding, SupervisorError> {
        match self {
            Self::Ordinary(guard) => {
                Ok(registry.release_binding_with_protocol_configuration(guard, agent, release)?)
            }
            Self::Reconciliation(guard) => Ok(guard.release_binding(agent, release)?),
        }
    }

    pub(crate) fn commit_unknown(
        self,
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
        decision: &ProductionRecoveryDecision,
        original_decision_sha256: [u8; 32],
        confirmation_sha256: Option<[u8; 32]>,
        expected_sha256: [u8; 32],
    ) -> Result<RecoveryPublicationState, SupervisorError> {
        self.check_window(decision)?;
        match self.with_verified_window(decision)? {
            Self::Reconciliation(guard) => {
                (*guard).reconcile_abandon_unknown(
                    next,
                    original_decision_sha256,
                    confirmation_sha256,
                    expected_sha256,
                )?;
                Ok(RecoveryPublicationState::ReopenRequired)
            }
            Self::Ordinary(guard) => {
                let guard = if let Some(confirmation) = confirmation_sha256 {
                    let expected = expected.ok_or_else(|| {
                        SupervisorError::SignedIntentRecoveryRequired(next.agent_id.clone())
                    })?;
                    (*guard).confirm_abandon_unknown_publication(
                        expected,
                        next,
                        confirmation,
                        expected_sha256,
                    )?
                } else if let Some(expected) =
                    expected.filter(|anchor| anchor.grant_sha256 != next.grant_sha256)
                {
                    (*guard).recover_unanchored_intent(
                        expected,
                        next,
                        original_decision_sha256,
                        expected_sha256,
                    )?
                } else {
                    (*guard).recover_intent(expected, next, original_decision_sha256)?
                };
                check_window(guard.revalidate()? / 1000, decision)?;
                Ok(RecoveryPublicationState::Ordinary)
            }
        }
    }

    pub(crate) fn commit_completion(
        self,
        next: &ReleaseIntentAnchorV1,
        decision: &ProductionRecoveryDecision,
        material_sha256: [u8; 32],
        expected_sha256: [u8; 32],
        pending_sha256: [u8; 32],
    ) -> Result<RecoveryPublicationState, SupervisorError> {
        self.check_window(decision)?;
        let Self::Reconciliation(guard) = self.with_verified_window(decision)? else {
            return Err(SupervisorError::ProductionAuthority(
                "completion confirmation requires explicit reconciliation mode".to_string(),
            ));
        };
        (*guard).reconcile_completed_publication(
            next,
            material_sha256,
            expected_sha256,
            pending_sha256,
        )?;
        Ok(RecoveryPublicationState::ReopenRequired)
    }

    pub(crate) fn retry_retained(
        self,
        decision: &ProductionRecoveryDecision,
        expected: [u8; 32],
        original: [u8; 32],
        replacement: [u8; 32],
        retained: [u8; 32],
    ) -> Result<(), SupervisorError> {
        self.check_window(decision)?;
        let Self::Reconciliation(guard) = self.with_verified_window(decision)? else {
            return Err(SupervisorError::ProductionAuthority(
                "retained publication retry requires explicit reconciliation mode".to_string(),
            ));
        };
        (*guard).retry_retained_publication(
            digest_bytes(decision.digest())?,
            expected,
            original,
            replacement,
            retained,
        )?;
        Ok(())
    }
}

fn check_window(now: u64, decision: &ProductionRecoveryDecision) -> Result<(), SupervisorError> {
    if now < decision.issued_at_unix_seconds || now >= decision.expires_at_unix_seconds {
        return Err(SupervisorError::ProductionAuthority(
            "recovery decision is outside the current trusted-clock window".to_string(),
        ));
    }
    Ok(())
}
