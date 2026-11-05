//! Explicit operator recovery, separate from ordinary current-use admissions.

use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;

use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::FleetReleaseTrustConfig;
use crate::ReleaseBinding;
use crate::ReleaseId;
use crate::ReleaseIntentAnchorV1;
use crate::release_authority::PendingIntentReconciliation;
use crate::release_authority::ReleaseAuthority;
use crate::release_authority::invalid;
use crate::release_intent_reconciliation_record::IntentReconciliationKind;
use crate::release_registry::ReleaseMode;

/// Holds the existing recovery lock and current PQ policy. It cannot be
/// converted into a launch admission. Successful reconciliation does not
/// unfence its Registry; an ordinary authenticated reopen is still mandatory.
pub struct PendingIntentReconciliationAdmission {
    registry: FleetRegistry,
    owner: Arc<ReleaseAuthority>,
    pending: PendingIntentReconciliation,
}

impl FleetRegistry {
    /// Explicit recovery mode only. Normal open never calls this constructor.
    /// A pending root/configuration/allowance/revocation update is ineligible.
    pub fn open_existing_for_release_intent_recovery(
        root: HeptaFleetRoot,
        trust: FleetReleaseTrustConfig,
    ) -> Result<Self, FleetRegistryError> {
        let mut registry = Self::open_existing(root)?;
        registry.release_authority = ReleaseMode::Pq(Arc::new(
            ReleaseAuthority::open_intent_recovery(registry.layout().state_root(), trust)?,
        ));
        Ok(registry)
    }

    pub fn is_release_intent_reconciliation(&self) -> bool {
        matches!(&self.release_authority, ReleaseMode::Pq(owner) if owner.is_intent_reconciliation())
    }

    pub fn admit_pending_intent_reconciliation(
        &self,
        policy_sha256: [u8; 32],
    ) -> Result<PendingIntentReconciliationAdmission, FleetRegistryError> {
        let ReleaseMode::Pq(owner) = &self.release_authority else {
            return Err(FleetRegistryError::ReleaseAuthorityRequired);
        };
        let pending = owner.admit_intent_reconciliation(policy_sha256)?;
        Ok(PendingIntentReconciliationAdmission {
            registry: self.clone(),
            owner: Arc::clone(owner),
            pending,
        })
    }
}

impl PendingIntentReconciliationAdmission {
    /// The H7 owner supplies only the exact window from the fresh, verified
    /// recovery/confirmation/retry signature. It is required for consumption,
    /// checked now and checked again after durable preparation before CAS.
    pub fn with_verified_decision_window(
        mut self,
        not_before_ms: u64,
        expires_at_ms: u64,
    ) -> Result<Self, FleetRegistryError> {
        self.pending
            .bind_decision_window(not_before_ms, expires_at_ms)?;
        self.revalidate()?;
        Ok(self)
    }

    pub fn expected_intent_anchor(&self) -> Option<&ReleaseIntentAnchorV1> {
        self.pending.expected_intent_anchor()
    }
    pub fn pending_intent_anchor(&self) -> &ReleaseIntentAnchorV1 {
        self.pending.pending_intent_anchor()
    }
    pub fn previous_closed_intent_anchor(&self) -> Option<&ReleaseIntentAnchorV1> {
        self.pending.previous_closed_intent_anchor()
    }
    pub fn pending_publication_sha256(&self) -> Result<[u8; 32], FleetRegistryError> {
        self.pending.pending_publication_sha256()
    }
    pub fn replacement_intent_anchor(&self) -> Option<&ReleaseIntentAnchorV1> {
        self.pending.replacement_intent_anchor()
    }
    pub fn replacement_publication_sha256(&self) -> Result<Option<[u8; 32]>, FleetRegistryError> {
        self.pending.replacement_publication_sha256()
    }
    pub fn retained_reconciliation_sha256(&self) -> Result<Option<[u8; 32]>, FleetRegistryError> {
        self.pending.retained_reconciliation_sha256()
    }
    pub fn revalidate(&self) -> Result<u64, FleetRegistryError> {
        self.owner.recheck_intent_reconciliation(&self.pending)
    }

    /// Exact signed-recovery observation under the one held recovery lock.
    /// No process permission is returned and both roles are freshly checked
    /// again after the actual catalog/manifest/program bytes have been read.
    pub fn release_binding(
        &self,
        agent: &AgentId,
        release: &ReleaseId,
    ) -> Result<ReleaseBinding, FleetRegistryError> {
        let projection =
            self.owner
                .reconciliation_member_projection(&self.pending, agent, release)?;
        let binding = self.registry.observe_reconciliation_release_binding(
            agent,
            release,
            &projection.0,
            projection.1,
        )?;
        if self
            .owner
            .reconciliation_member_projection(&self.pending, agent, release)?
            != projection
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        Ok(binding)
    }

    /// The H7 owner must first verify the fresh signed unknown disposition (or
    /// separate publication confirmation), exact actual state/transaction,
    /// original intent proof and full retained history. This method preserves
    /// the original failed attempt and performs only one competing CAS.
    pub fn reconcile_abandon_unknown(
        self,
        next: &ReleaseIntentAnchorV1,
        original_decision_sha256: [u8; 32],
        publication_confirmation_sha256: Option<[u8; 32]>,
        expected_anchor_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        self.owner.reconcile_intent(
            self.pending,
            next,
            IntentReconciliationKind::AbandonUnknown,
            Some(original_decision_sha256),
            publication_confirmation_sha256,
            expected_anchor_sha256,
        )
    }

    /// Confirms publication of an actual retained terminal result. The new
    /// snapshot must equal the original terminal anchor field-for-field except
    /// for the fresh signed confirmation-material digest. No effect is retried.
    pub fn reconcile_completed_publication(
        self,
        next: &ReleaseIntentAnchorV1,
        confirmation_material_sha256: [u8; 32],
        expected_anchor_sha256: [u8; 32],
        pending_publication_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        if self.pending.pending_publication_sha256()? != pending_publication_sha256 {
            return Err(invalid(
                "completion confirmation names a different pending publication",
            ));
        }
        let decision = self
            .pending
            .pending_intent_anchor()
            .terminal_witness
            .as_ref()
            .and_then(|witness| witness.recovery_decision_sha256);
        self.owner.reconcile_intent(
            self.pending,
            next,
            IntentReconciliationKind::ConfirmCompletion,
            decision,
            Some(confirmation_material_sha256),
            expected_anchor_sha256,
        )
    }

    /// Requires a separate fresh signed retry decision, bound to the complete
    /// retained observations. It performs at most one CAS of the same retained
    /// expected/proposed pair and cannot allocate a third proposal or retry an
    /// application effect. An uncertain response preserves both attempts.
    pub fn retry_retained_publication(
        self,
        fresh_decision_sha256: [u8; 32],
        expected_anchor_sha256: [u8; 32],
        original_pending_sha256: [u8; 32],
        replacement_pending_sha256: [u8; 32],
        retained_state_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        self.owner.retry_retained_intent_publication(
            self.pending,
            fresh_decision_sha256,
            expected_anchor_sha256,
            original_pending_sha256,
            replacement_pending_sha256,
            retained_state_sha256,
        )
    }
}
