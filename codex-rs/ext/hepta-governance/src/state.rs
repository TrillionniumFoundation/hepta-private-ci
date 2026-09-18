use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;

use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyError;
use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_contracts::IndependentDecisionReceiptV1;
use codex_hepta_evidence::AppendDisposition;
use codex_hepta_evidence::AuthenticatedEvidenceIssuerV1;
use codex_hepta_evidence::EvidenceCandidateV1;
use codex_hepta_evidence::EvidenceClaimClassV1;
use codex_hepta_evidence::EvidenceDispositionV1;
use codex_hepta_evidence::EvidenceError;
use codex_hepta_evidence::EvidenceExternalCheckpointV1;
use codex_hepta_evidence::EvidenceId;
use codex_hepta_evidence::EvidenceIssuerAuthorityV1;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceReferenceV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::SignedEvidenceIssuerCertificateV1;
use codex_hepta_evidence::SignedEvidenceIssuerKeyRevocationV1;
use codex_hepta_evidence::SignedQualificationEvidenceEnvelopeV1;

#[derive(Default)]
pub(crate) struct InProcessClaims {
    /// Actions whose first durable admission insert was won by this process.
    ///
    /// This is deliberately only an execution witness. The SQLite evidence is
    /// authoritative for the decision and receipt material.
    pub(crate) owned: BTreeMap<ActionId, String>,
    /// Policy blocks caused by a replay must not finalize the original action.
    pub(crate) blocked_replays: BTreeSet<(ActionId, String)>,
}

pub struct GovernanceState {
    pub(crate) enabled: bool,
    pub(crate) mode: GovernanceMode,
    pub(crate) evidence: Result<Arc<HeptaEvidenceStore>, Arc<str>>,
    pub(crate) qualification_authority: Option<Arc<EvidenceIssuerAuthorityV1>>,
    pub(crate) claims: Mutex<InProcessClaims>,
}

impl GovernanceState {
    pub(crate) fn disabled() -> Self {
        Self {
            enabled: false,
            mode: GovernanceMode::Shadow,
            evidence: Err(Arc::from("governance disabled")),
            qualification_authority: None,
            claims: Mutex::new(InProcessClaims::default()),
        }
    }

    pub(crate) fn enabled(
        mode: GovernanceMode,
        evidence: Result<Arc<HeptaEvidenceStore>, Arc<str>>,
    ) -> Self {
        Self {
            enabled: true,
            mode,
            evidence,
            qualification_authority: None,
            claims: Mutex::new(InProcessClaims::default()),
        }
    }

    pub(crate) fn enabled_with_qualification_authority(
        mode: GovernanceMode,
        evidence: Result<Arc<HeptaEvidenceStore>, Arc<str>>,
        qualification_authority: Arc<EvidenceIssuerAuthorityV1>,
    ) -> Self {
        Self {
            enabled: true,
            mode,
            evidence,
            qualification_authority: Some(qualification_authority),
            claims: Mutex::new(InProcessClaims::default()),
        }
    }

    fn qualification_store(&self) -> Result<Arc<HeptaEvidenceStore>, EvidenceError> {
        if !self.enabled {
            return Err(EvidenceError::Unavailable(
                "governance product host is disabled".to_string(),
            ));
        }
        self.evidence.clone().map_err(|detail| {
            EvidenceError::Unavailable(format!(
                "governance product host evidence store is unavailable: {detail}"
            ))
        })
    }

    fn qualification_authority(&self) -> Result<&EvidenceIssuerAuthorityV1, EvidenceError> {
        self.qualification_authority.as_deref().ok_or_else(|| {
            EvidenceError::Unavailable(
                "qualification issuer trust root is not configured by the product host".to_string(),
            )
        })
    }

    pub fn authenticate_qualification_issuer(
        &self,
        signed: SignedEvidenceIssuerCertificateV1,
        now_unix_ms: u64,
    ) -> Result<AuthenticatedEvidenceIssuerV1, EvidenceError> {
        if !self.enabled {
            return Err(EvidenceError::Unavailable(
                "governance product host is disabled".to_string(),
            ));
        }
        self.qualification_authority()?
            .authenticate(signed, now_unix_ms)
    }

    pub async fn append_qualification_receipt(
        &self,
        signed: &SignedQualificationEvidenceEnvelopeV1,
        issuer: &AuthenticatedEvidenceIssuerV1,
    ) -> Result<EvidenceId, EvidenceError> {
        let store = self.qualification_store()?;
        let authority = self.qualification_authority()?;
        authority.revalidate_authenticated(issuer, signed.envelope.observed_unix_ms)?;
        store.verify_qualification_trust(authority).await?;
        store.append_receipt(signed, issuer).await
    }

    pub async fn append_independent_decision_receipt(
        &self,
        signed: &SignedQualificationEvidenceEnvelopeV1,
        issuer: &AuthenticatedEvidenceIssuerV1,
        decision: &IndependentDecisionReceiptV1,
    ) -> Result<AppendDisposition, EvidenceError> {
        let store = self.qualification_store()?;
        let authority = self.qualification_authority()?;
        authority.revalidate_authenticated(issuer, signed.envelope.observed_unix_ms)?;
        store.verify_qualification_trust(authority).await?;
        store
            .append_independent_decision_receipt(signed, issuer, decision)
            .await
    }

    pub async fn append_qualification_issuer_key_revocation(
        &self,
        signed: &SignedEvidenceIssuerKeyRevocationV1,
        authority: &AuthenticatedEvidenceIssuerV1,
    ) -> Result<AppendDisposition, EvidenceError> {
        let store = self.qualification_store()?;
        let qualification_authority = self.qualification_authority()?;
        qualification_authority
            .revalidate_authenticated(authority, signed.revocation.observed_unix_ms)?;
        store
            .verify_qualification_trust(qualification_authority)
            .await?;
        store.append_issuer_key_revocation(signed, authority).await
    }

    pub async fn query_qualification_claim(
        &self,
        candidate: &EvidenceCandidateV1,
        claim_class: EvidenceClaimClassV1,
    ) -> Result<Vec<EvidenceReferenceV1>, EvidenceError> {
        self.qualification_store()?
            .query_claim_with_authority(candidate, claim_class, self.qualification_authority()?)
            .await
    }

    pub async fn verify_qualification_chain(
        &self,
        candidate: &EvidenceCandidateV1,
        required_roles: &[EvidenceIssuerRoleV1],
        now_unix_ms: u64,
    ) -> Result<EvidenceDispositionV1, EvidenceError> {
        self.qualification_store()?
            .verify_chain_with_authority(
                candidate,
                required_roles,
                now_unix_ms,
                self.qualification_authority()?,
            )
            .await
    }

    pub async fn capture_evidence_external_checkpoint(
        &self,
    ) -> Result<EvidenceExternalCheckpointV1, EvidenceError> {
        let store = self.qualification_store()?;
        store
            .verify_qualification_trust(self.qualification_authority()?)
            .await?;
        store.capture_external_checkpoint().await
    }

    pub async fn verify_evidence_external_checkpoint(
        &self,
        checkpoint: &EvidenceExternalCheckpointV1,
    ) -> Result<(), EvidenceError> {
        let store = self.qualification_store()?;
        store
            .verify_qualification_trust(self.qualification_authority()?)
            .await?;
        store.verify_external_checkpoint(checkpoint).await
    }

    pub(crate) fn owns_action(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<bool, ToolPolicyError> {
        self.claims
            .lock()
            .map(|claims| {
                claims
                    .owned
                    .get(action_id)
                    .is_some_and(|owned_attempt| owned_attempt == attempt_id)
            })
            .map_err(|_| {
                ToolPolicyError::new(
                    "hepta_governance_state_poisoned",
                    "in-process governance claim lock is poisoned",
                )
            })
    }

    fn release_action(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        self.claims
            .lock()
            .map(|mut claims| {
                if claims
                    .owned
                    .get(action_id)
                    .is_some_and(|owned_attempt| owned_attempt == attempt_id)
                {
                    claims.owned.remove(action_id);
                }
            })
            .map_err(|_| {
                ToolPolicyError::new(
                    "hepta_governance_state_poisoned",
                    "in-process governance claim lock is poisoned",
                )
            })
    }

    pub(crate) fn release_action_for_mode(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.release_action(action_id, attempt_id) {
            Ok(()) => Ok(()),
            Err(error) if self.mode == GovernanceMode::Shadow => {
                tracing::warn!(
                    reason_code = error.reason_code(),
                    detail = error.detail(),
                    "shadow governance could not release an in-process claim"
                );
                Ok(())
            }
            Err(error) => Err(error),
        }
    }

    pub(crate) fn replay_or_shadow(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
        phase: PolicyPhase,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        let reason_code = match phase {
            PolicyPhase::Admission => "hepta_action_replay",
            PolicyPhase::Authorization => "hepta_authorization_replay",
        };
        match self.mode {
            GovernanceMode::Shadow => {
                tracing::warn!(
                    action_id = action_id.as_str(),
                    phase = phase.as_str(),
                    "shadow governance observed a durable action replay"
                );
                Ok(ToolPolicyDecision::Allow)
            }
            GovernanceMode::Enforce => {
                let mut claims = self.claims.lock().map_err(|_| {
                    ToolPolicyError::new(
                        "hepta_governance_state_poisoned",
                        "in-process governance claim lock is poisoned",
                    )
                })?;
                if !claims
                    .blocked_replays
                    .insert((action_id.clone(), attempt_id.to_string()))
                {
                    return Err(ToolPolicyError::new(
                        "hepta_replay_attempt_conflict",
                        "one policy attempt tried to claim the same replay twice",
                    ));
                }
                Ok(ToolPolicyDecision::Block {
                    reason_code: reason_code.to_string(),
                    message: "Hepta blocked a replay of an existing durable tool action"
                        .to_string(),
                })
            }
        }
    }

    pub(crate) fn consume_blocked_replay(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<bool, ToolPolicyError> {
        let mut claims = self.claims.lock().map_err(|_| {
            ToolPolicyError::new(
                "hepta_governance_state_poisoned",
                "in-process governance claim lock is poisoned",
            )
        })?;
        Ok(claims
            .blocked_replays
            .remove(&(action_id.clone(), attempt_id.to_string())))
    }

    pub(crate) fn unavailable_or_shadow(
        &self,
        detail: &Arc<str>,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(
                "hepta_evidence_unavailable",
                detail.to_string(),
            )),
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance evidence backend is unavailable");
                Ok(ToolPolicyDecision::Allow)
            }
        }
    }

    pub(crate) fn storage_failure_or_shadow(
        &self,
        detail: String,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => {
                Err(ToolPolicyError::new("hepta_evidence_write_failed", detail))
            }
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance evidence write failed");
                Ok(ToolPolicyDecision::Allow)
            }
        }
    }

    pub(crate) fn integrity_failure_or_shadow(
        &self,
        reason_code: &'static str,
        detail: &'static str,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(reason_code, detail)),
            GovernanceMode::Shadow => {
                tracing::warn!(
                    reason_code,
                    detail,
                    "shadow governance integrity check failed"
                );
                Ok(ToolPolicyDecision::Allow)
            }
        }
    }

    pub(crate) fn terminal_unavailable_or_shadow(
        &self,
        detail: &Arc<str>,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(
                "hepta_evidence_unavailable",
                detail.to_string(),
            )),
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance terminal evidence is unavailable");
                self.release_action_for_mode(action_id, attempt_id)?;
                Ok(())
            }
        }
    }

    pub(crate) fn terminal_storage_failure_or_shadow_with_action(
        &self,
        detail: String,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => {
                // Retain the in-process claim. The durable authorized decision
                // remains pending and any replay is blocked on the next admit.
                Err(ToolPolicyError::new("hepta_evidence_write_failed", detail))
            }
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance terminal evidence write failed");
                self.release_action_for_mode(action_id, attempt_id)?;
                Ok(())
            }
        }
    }

    pub(crate) fn terminal_integrity_failure_or_shadow(
        &self,
        reason_code: &'static str,
        detail: &'static str,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(reason_code, detail)),
            GovernanceMode::Shadow => {
                tracing::warn!(
                    reason_code,
                    detail,
                    "shadow terminal integrity check failed"
                );
                self.release_action_for_mode(action_id, attempt_id)?;
                Ok(())
            }
        }
    }
}
