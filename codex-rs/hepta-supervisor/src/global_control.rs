//! Named typed host for the global control.runtime composition.
//!
//! This module intentionally does not add a network protocol. The supervisor
//! owns host-selected trust, durable AuthBus replay, planner durability and
//! the independent final-use verifier; callers must still supply an admitted
//! runtime.fleet ledger and typed planning inputs.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_control_plane::AuthorityBridgeError;
use codex_hepta_control_plane::FleetEssentialFloorsV1;
use codex_hepta_control_plane::GlobalControlPlanV1;
use codex_hepta_control_plane::GlobalPlaneError;
use codex_hepta_control_plane::GrantRequestV1;
use codex_hepta_control_plane::NduPlanningInputV1;
use codex_hepta_control_plane::OwnerSummaryV1;
use codex_hepta_control_plane::PlannerJournalError;
use codex_hepta_control_plane::PlannerJournalStoreV1;
use codex_hepta_control_plane::PlannerJournalV1;
use codex_hepta_control_plane::PlannerStoreError;
use codex_hepta_control_plane::PlanningRequestV1;
use codex_hepta_control_plane::SnapshotRequestV1;
use codex_hepta_control_plane::admit_durable_owner_summary_v1;
use codex_hepta_control_plane::admit_fleet_allocation_owner_v1;
use codex_hepta_control_plane::compose_global_plan_with_fleet_v1;
use codex_hepta_control_plane::owner_summary_payload_digest_v1;
use codex_hepta_control_plane::owner_summary_scope_digest_v1;
use codex_hepta_control_plane::with_authorized_grant_request_v1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_fleet::lease_ledger::LeaseLedger;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_NON_FLEET_OWNER_TRUSTS: usize = 31;
const FLEET_OWNER_ID: &str = "runtime.fleet";

pub struct GlobalOwnerTrustV1 {
    pub owner_id: StableId,
    pub issuer: IssuerRegistration,
}

pub struct SignedGlobalOwnerSummaryV1 {
    pub summary: OwnerSummaryV1,
    pub message: SignedMessage,
}

pub struct GlobalControlHostRequestV1 {
    pub snapshot_request: SnapshotRequestV1,
    pub planning_request: PlanningRequestV1,
    pub ndu_input: NduPlanningInputV1,
    pub signed_owner_summaries: Vec<SignedGlobalOwnerSummaryV1>,
    pub fleet_allocation_id: String,
    pub fleet_principal_id: String,
    pub fleet_floors: FleetEssentialFloorsV1,
    /// Monotonic planner time in the same domain as every summary in this
    /// request. Wall-clock authentication time is sampled by the host.
    pub now_micros: u64,
}

pub struct GlobalControlHostV1 {
    evidence: HeptaEvidenceStore,
    planner_store: PlannerJournalStoreV1,
    journal: PlannerJournalV1,
    authority: FinalUseAuthority,
    owner_trust: BTreeMap<StableId, IssuerRegistration>,
}

impl fmt::Debug for GlobalControlHostV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("GlobalControlHostV1([PINNED TRUST + DURABLE STATE])")
    }
}

#[derive(Debug)]
pub enum GlobalControlHostError {
    TooManyOwnerTrusts,
    DuplicateOwnerTrust(StableId),
    FleetOwnerTrustReserved,
    UnknownOwnerTrust(StableId),
    WallClockUnavailable,
    Evidence(String),
    Plane(GlobalPlaneError),
    Journal(PlannerJournalError),
    Store(PlannerStoreError),
    Authority(AuthorityBridgeError),
    FinalUse(codex_hepta_contracts::FinalUseError),
}

impl fmt::Display for GlobalControlHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GlobalControlHostError {}

impl From<GlobalPlaneError> for GlobalControlHostError {
    fn from(error: GlobalPlaneError) -> Self {
        Self::Plane(error)
    }
}

impl From<PlannerJournalError> for GlobalControlHostError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

impl From<PlannerStoreError> for GlobalControlHostError {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error)
    }
}

impl From<AuthorityBridgeError> for GlobalControlHostError {
    fn from(error: AuthorityBridgeError) -> Self {
        Self::Authority(error)
    }
}

impl From<codex_hepta_contracts::FinalUseError> for GlobalControlHostError {
    fn from(error: codex_hepta_contracts::FinalUseError) -> Self {
        Self::FinalUse(error)
    }
}

impl GlobalControlHostV1 {
    pub fn open(
        evidence: HeptaEvidenceStore,
        planner_root: &Path,
        planner_recovery_floor: &[Digest32],
        authority: FinalUseAuthority,
        owner_trust: Vec<GlobalOwnerTrustV1>,
    ) -> Result<Self, GlobalControlHostError> {
        if owner_trust.len() > MAX_NON_FLEET_OWNER_TRUSTS {
            return Err(GlobalControlHostError::TooManyOwnerTrusts);
        }
        let mut trusted = BTreeMap::new();
        for binding in owner_trust {
            if binding.owner_id.as_str() == FLEET_OWNER_ID {
                return Err(GlobalControlHostError::FleetOwnerTrustReserved);
            }
            if trusted.insert(binding.owner_id.clone(), binding.issuer).is_some() {
                return Err(GlobalControlHostError::DuplicateOwnerTrust(binding.owner_id));
            }
        }
        let (planner_store, journal) =
            PlannerJournalStoreV1::open(planner_root, planner_recovery_floor)?;
        Ok(Self {
            evidence,
            planner_store,
            journal,
            authority,
            owner_trust: trusted,
        })
    }

    /// Runs the complete typed global plan path and durably records the
    /// resulting snapshot/decision/selection before returning it.
    ///
    /// Durable AuthBus replay is consumed before a summary enters Control.
    /// Failure after replay consumption is fail-closed: retry requires a new
    /// signed sequence and cannot infer an external effect.
    pub async fn plan(
        &mut self,
        fleet_ledger: &LeaseLedger,
        request: GlobalControlHostRequestV1,
    ) -> Result<GlobalControlPlanV1, GlobalControlHostError> {
        let wall_now_ms = host_wall_now_ms()?;
        let fleet = admit_fleet_allocation_owner_v1(
            fleet_ledger,
            &request.fleet_allocation_id,
            &request.fleet_principal_id,
            request.snapshot_request.objective_digest,
            request.snapshot_request.body_generation,
            request.snapshot_request.configuration_digest,
            wall_now_ms,
            request.now_micros,
            request.snapshot_request.expires_at_micros,
            request.fleet_floors,
        )?;

        let mut admitted = Vec::with_capacity(request.signed_owner_summaries.len());
        for signed_owner in request.signed_owner_summaries {
            let owner_id = signed_owner.summary.owner_id.clone();
            let issuer = self
                .owner_trust
                .get(&owner_id)
                .ok_or_else(|| GlobalControlHostError::UnknownOwnerTrust(owner_id.clone()))?;
            let scope = owner_summary_scope_digest_v1(&signed_owner.summary);
            let payload = owner_summary_payload_digest_v1(&signed_owner.summary);
            let durable_receipt = self
                .evidence
                .admit_authbus_message(issuer, &signed_owner.message, scope, payload)
                .await
                .map_err(|error| GlobalControlHostError::Evidence(error.to_string()))?;
            admitted.push(admit_durable_owner_summary_v1(
                signed_owner.summary,
                &signed_owner.message,
                issuer,
                &durable_receipt,
                wall_now_ms,
            )?);
        }

        let plan = compose_global_plan_with_fleet_v1(
            request.snapshot_request,
            fleet,
            admitted,
            request.planning_request,
            request.ndu_input,
            request.now_micros,
        )?;

        let mut next = self.journal.clone();
        next.record_snapshot(&plan.snapshot)?;
        next.record_decision(&plan.evaluation.plan)?;
        if plan.evaluation.plan.chosen_candidate_id().is_some() {
            next.select_plan(
                selection_identity(plan.evaluation.plan.receipt_digest()),
                &plan.evaluation.plan,
            )?;
        }
        self.planner_store.persist(&next)?;
        self.journal = next;
        Ok(plan)
    }

    /// Records a current authoritative decision revocation and syncs it before
    /// returning. The recovery floor supplied at open remains an additional
    /// anti-rollback requirement.
    pub fn revoke_decision(
        &mut self,
        revocation_identity: Digest32,
        decision_digest: Digest32,
    ) -> Result<(), GlobalControlHostError> {
        let mut next = self.journal.clone();
        next.revoke(revocation_identity, decision_digest)?;
        self.planner_store.persist(&next)?;
        self.journal = next;
        Ok(())
    }

    pub fn update_final_use_revocations(
        &self,
        head: FinalUseRevocations,
    ) -> Result<(), GlobalControlHostError> {
        self.authority.update_revocations(head)?;
        Ok(())
    }

    /// Preferred effect-boundary path. The effect closure is entered only
    /// after durable nonce claim and the final live revocation/time fence.
    pub fn with_authorized_request<T>(
        &self,
        signed_grant: &SignedFinalUseGrant,
        request: &GrantRequestV1,
        subject_id: &StableId,
        destination_id: &StableId,
        scope_digest: Digest32,
        dispatch: impl FnOnce() -> T,
    ) -> Result<T, GlobalControlHostError> {
        with_authorized_grant_request_v1(
            &self.authority,
            signed_grant,
            request,
            subject_id,
            destination_id,
            scope_digest,
            dispatch,
        )
        .map_err(Into::into)
    }

    #[must_use]
    pub fn journal(&self) -> &PlannerJournalV1 {
        &self.journal
    }
}

fn selection_identity(receipt_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta.supervisor.global-control-selection.v1\0".to_vec();
    bytes.extend_from_slice(receipt_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn host_wall_now_ms() -> Result<u64, GlobalControlHostError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| GlobalControlHostError::WallClockUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| GlobalControlHostError::WallClockUnavailable)
}

#[cfg(all(test, unix))]
#[path = "global_control_tests.rs"]
mod tests;
