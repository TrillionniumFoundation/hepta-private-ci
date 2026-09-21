//! Named typed host for the global control.runtime composition.
//!
//! This module intentionally does not add a network protocol. The supervisor
//! owns host-selected trust, durable AuthBus replay, planner durability and
//! the independent final-use verifier and one host-pinned runtime.fleet state
//! source. Request callers supply typed planning inputs but cannot swap the fleet
//! authority source between plan and final-use revalidation.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::sync::Arc;
use std::sync::RwLock;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_control_plane::AuthorityBridgeError;
use codex_hepta_control_plane::EffectBindingV1;
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
use codex_hepta_control_plane::bind_planner_observation_window_v1;
use codex_hepta_control_plane::canonical_ndu_planning_policy_digest;
use codex_hepta_control_plane::compose_global_plan_with_fleet_v1;
use codex_hepta_control_plane::owner_summary_payload_digest_v1;
use codex_hepta_control_plane::owner_summary_scope_digest_v1;
use codex_hepta_control_plane::revalidate_fleet_allocation_for_plan_v1;
use codex_hepta_control_plane::with_authorized_grant_request_v1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_fleet::lease_ledger::LeaseLedger;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_OWNER_TRUSTS: usize = 32;
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
}

/// Host-owned global planner policy. Callers may supply candidates and signed
/// owner facts, but cannot relax freshness, plan lifetime, fleet principal or
/// essential resource floors for one request.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlobalControlHostPolicyV1 {
    pub fleet_principal_id: StableId,
    pub fleet_floors: FleetEssentialFloorsV1,
    pub required_owner_ids: Vec<StableId>,
    pub evaluation_policy_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub maximum_owner_age_micros: u64,
    pub maximum_plan_lifetime_micros: u64,
    pub snapshot_policy_digest: Digest32,
}

pub struct GlobalControlHostV1 {
    evidence: HeptaEvidenceStore,
    planner_store: PlannerJournalStoreV1,
    journal: PlannerJournalV1,
    authority: FinalUseAuthority,
    fleet_ledger: Arc<RwLock<LeaseLedger>>,
    owner_trust: BTreeMap<StableId, IssuerRegistration>,
    policy: GlobalControlHostPolicyV1,
    planner_clock_origin: Instant,
    issued_plan_receipts: BTreeSet<Digest32>,
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
    MissingFleetOwnerTrust,
    MissingRequiredOwnerTrust(StableId),
    MissingFleetOwnerSummary,
    DuplicateFleetOwnerSummary,
    UnknownOwnerTrust(StableId),
    InvalidHostPolicy,
    PlannerClockOverflow,
    PlannerPlanExpired,
    PlannerPlanNotCurrent,
    PlanNotIssuedByCurrentHost,
    NduPolicyMismatch,
    FleetSubjectMismatch,
    WallClockUnavailable,
    FleetStatePoisoned,
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
        fleet_ledger: Arc<RwLock<LeaseLedger>>,
        policy: GlobalControlHostPolicyV1,
        owner_trust: Vec<GlobalOwnerTrustV1>,
    ) -> Result<Self, GlobalControlHostError> {
        let mut policy = policy;
        if policy.maximum_owner_age_micros == 0
            || policy.maximum_plan_lifetime_micros == 0
            || policy.snapshot_policy_digest.is_zero()
            || policy.evaluation_policy_digest.is_zero()
            || policy.revocation_frontier_digest.is_zero()
            || policy.required_owner_ids.is_empty()
            || policy.required_owner_ids.len() > MAX_OWNER_TRUSTS
        {
            return Err(GlobalControlHostError::InvalidHostPolicy);
        }
        policy.required_owner_ids.sort();
        if policy
            .required_owner_ids
            .windows(2)
            .any(|pair| pair[0] == pair[1])
            || !policy
                .required_owner_ids
                .iter()
                .any(|owner| owner.as_str() == FLEET_OWNER_ID)
        {
            return Err(GlobalControlHostError::InvalidHostPolicy);
        }
        if owner_trust.len() > MAX_OWNER_TRUSTS {
            return Err(GlobalControlHostError::TooManyOwnerTrusts);
        }
        let mut trusted = BTreeMap::new();
        for binding in owner_trust {
            if trusted
                .insert(binding.owner_id.clone(), binding.issuer)
                .is_some()
            {
                return Err(GlobalControlHostError::DuplicateOwnerTrust(
                    binding.owner_id,
                ));
            }
        }
        let fleet_owner_id = StableId::new(FLEET_OWNER_ID)
            .map_err(|_| GlobalControlHostError::MissingFleetOwnerTrust)?;
        if !trusted.contains_key(&fleet_owner_id) {
            return Err(GlobalControlHostError::MissingFleetOwnerTrust);
        }
        for owner_id in &policy.required_owner_ids {
            if !trusted.contains_key(owner_id) {
                return Err(GlobalControlHostError::MissingRequiredOwnerTrust(
                    owner_id.clone(),
                ));
            }
        }
        let (planner_store, journal) =
            PlannerJournalStoreV1::open(planner_root, planner_recovery_floor)?;
        Ok(Self {
            evidence,
            planner_store,
            journal,
            authority,
            fleet_ledger,
            owner_trust: trusted,
            policy,
            planner_clock_origin: Instant::now(),
            issued_plan_receipts: BTreeSet::new(),
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
        request: GlobalControlHostRequestV1,
    ) -> Result<GlobalControlPlanV1, GlobalControlHostError> {
        let GlobalControlHostRequestV1 {
            mut snapshot_request,
            mut planning_request,
            ndu_input,
            signed_owner_summaries,
            fleet_allocation_id,
        } = request;
        let actual_ndu_policy = canonical_ndu_planning_policy_digest(&ndu_input)
            .map_err(|_| GlobalControlHostError::NduPolicyMismatch)?;
        if actual_ndu_policy != self.policy.evaluation_policy_digest {
            return Err(GlobalControlHostError::NduPolicyMismatch);
        }
        let wall_now_ms = host_wall_now_ms()?;
        let now_micros = self.planner_now_micros()?;
        let expires_at_micros = now_micros
            .checked_add(self.policy.maximum_plan_lifetime_micros)
            .ok_or(GlobalControlHostError::PlannerClockOverflow)?;
        let owner_expires_at_micros = now_micros
            .checked_add(self.policy.maximum_owner_age_micros)
            .ok_or(GlobalControlHostError::PlannerClockOverflow)?;
        snapshot_request.collected_at_micros = now_micros;
        snapshot_request.maximum_owner_age_micros = self.policy.maximum_owner_age_micros;
        snapshot_request.expires_at_micros = expires_at_micros;
        snapshot_request.snapshot_policy_digest = self.policy.snapshot_policy_digest;
        snapshot_request.revocation_frontier_digest = self.policy.revocation_frontier_digest;
        snapshot_request.required_owner_ids = self.policy.required_owner_ids.clone();
        planning_request.now_micros = now_micros;
        planning_request.deadline_micros = expires_at_micros;
        planning_request.evaluation_policy_digest = self.policy.evaluation_policy_digest;

        let mut admitted = Vec::with_capacity(signed_owner_summaries.len());
        let mut fleet_owner = None;
        for signed_owner in signed_owner_summaries {
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
            let admitted_owner = admit_durable_owner_summary_v1(
                signed_owner.summary,
                &signed_owner.message,
                issuer,
                &durable_receipt,
                wall_now_ms,
            )?;
            let admitted_owner = bind_planner_observation_window_v1(
                admitted_owner,
                now_micros,
                owner_expires_at_micros,
            )?;
            if owner_id.as_str() == FLEET_OWNER_ID {
                if fleet_owner.replace(admitted_owner).is_some() {
                    return Err(GlobalControlHostError::DuplicateFleetOwnerSummary);
                }
            } else {
                admitted.push(admitted_owner);
            }
        }
        let fleet_owner = fleet_owner.ok_or(GlobalControlHostError::MissingFleetOwnerSummary)?;
        let fleet = {
            let fleet_ledger = self
                .fleet_ledger
                .read()
                .map_err(|_| GlobalControlHostError::FleetStatePoisoned)?;
            admit_fleet_allocation_owner_v1(
                &fleet_ledger,
                &fleet_allocation_id,
                self.policy.fleet_principal_id.as_str(),
                fleet_owner,
                wall_now_ms,
                self.policy.fleet_floors,
            )?
        };

        let plan = compose_global_plan_with_fleet_v1(
            snapshot_request,
            fleet,
            admitted,
            planning_request,
            ndu_input,
            now_micros,
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
        self.issued_plan_receipts
            .insert(plan.evaluation.plan.receipt_digest());
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
        self.issued_plan_receipts.remove(&decision_digest);
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
        plan: &GlobalControlPlanV1,
        signed_grant: &SignedFinalUseGrant,
        request: &GrantRequestV1,
        effect_binding: &EffectBindingV1,
        dispatch: impl FnOnce() -> T,
    ) -> Result<T, GlobalControlHostError> {
        if self.planner_store.is_poisoned() {
            return Err(GlobalControlHostError::Store(
                PlannerStoreError::Indeterminate,
            ));
        }
        let receipt_digest = plan.evaluation.plan.receipt_digest();
        if !self.issued_plan_receipts.contains(&receipt_digest) {
            return Err(GlobalControlHostError::PlanNotIssuedByCurrentHost);
        }
        if self.journal.selected_plan_digest() != Some(receipt_digest) {
            return Err(GlobalControlHostError::PlannerPlanNotCurrent);
        }
        if effect_binding.subject_id.as_str() != plan.fleet_execution_fence.principal_id()
            || effect_binding.subject_id.as_str() != self.policy.fleet_principal_id.as_str()
        {
            return Err(GlobalControlHostError::FleetSubjectMismatch);
        }
        let now_micros = self.planner_now_micros()?;
        if now_micros >= request.expires_at_micros
            || now_micros >= plan.snapshot.expires_at_micros()
        {
            return Err(GlobalControlHostError::PlannerPlanExpired);
        }
        {
            let fleet_ledger = self
                .fleet_ledger
                .read()
                .map_err(|_| GlobalControlHostError::FleetStatePoisoned)?;
            revalidate_fleet_allocation_for_plan_v1(
                &fleet_ledger,
                plan,
                request,
                host_wall_now_ms()?,
            )?;
        }
        with_authorized_grant_request_v1(
            &self.authority,
            signed_grant,
            request,
            effect_binding,
            dispatch,
        )
        .map_err(Into::into)
    }

    pub fn planner_now_micros(&self) -> Result<u64, GlobalControlHostError> {
        u64::try_from(self.planner_clock_origin.elapsed().as_micros())
            .map_err(|_| GlobalControlHostError::PlannerClockOverflow)
    }

    #[must_use]
    pub fn policy(&self) -> &GlobalControlHostPolicyV1 {
        &self.policy
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
