use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PreverifiedAuthEnvelope;
use codex_hepta_authbus::ReplayWindow;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::TrustedReplayContext;
use codex_hepta_fleet::lease_ledger::LeaseLedger;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::EvaluatedPlanV1;
use crate::GlobalStateSnapshotV1;
use crate::GrantRequestSetV1;
use crate::NduPlanningError;
use crate::NduPlanningInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::canonical_resource_profile_digest;
use crate::collect_snapshot;
use crate::evaluate_prepared_plan_with_ndu;
use crate::prepare_plan;
use crate::request_execution_grants;

pub const FLEET_CPU_MILLIS_AXIS: &str = "fleet-cpu-millis";
pub const FLEET_MEMORY_MIB_AXIS: &str = "fleet-memory-mib";
pub const FLEET_ACCELERATOR_MILLIS_AXIS: &str = "fleet-accelerator-millis";

const MIB: u64 = 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedOwnerSummaryV1 {
    summary: OwnerSummaryV1,
    admission_digest: Digest32,
}

impl AdmittedOwnerSummaryV1 {
    #[must_use]
    pub fn summary(&self) -> &OwnerSummaryV1 {
        &self.summary
    }

    #[must_use]
    pub const fn admission_digest(&self) -> Digest32 {
        self.admission_digest
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct FleetEssentialFloorsV1 {
    pub cpu_millis: u64,
    pub memory_bytes: u64,
    pub accelerator_millis: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetOwnerAdmissionV1 {
    owner: AdmittedOwnerSummaryV1,
    resource_reservations: Vec<ResourceReservationV1>,
}

impl FleetOwnerAdmissionV1 {
    #[must_use]
    pub fn owner(&self) -> &AdmittedOwnerSummaryV1 {
        &self.owner
    }

    #[must_use]
    pub fn resource_reservations(&self) -> &[ResourceReservationV1] {
        &self.resource_reservations
    }

    #[must_use]
    pub fn resource_profile_digest(&self) -> Digest32 {
        canonical_resource_profile_digest(&self.resource_reservations)
            .expect("fleet owner admission is constructed only from validated reservations")
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlobalControlPlanV1 {
    pub snapshot: GlobalStateSnapshotV1,
    pub prepared: PreparedPlanInputV1,
    pub evaluation: EvaluatedPlanV1,
    pub grant_requests: Option<GrantRequestSetV1>,
}

#[derive(Debug)]
pub enum GlobalPlaneError {
    Planner(PlannerError),
    Ndu(NduPlanningError),
    Authentication(codex_hepta_authbus::Error),
    InvalidOwnerBinding,
    OwnerSetMismatch,
    ClockDomainMismatch,
    FleetAllocationMissing,
    FleetPrincipalMismatch,
    FleetAllocationRevoked,
    FleetAllocationExpired,
    FleetSemanticDigest,
    FleetResourceFloor,
    Arithmetic,
}

impl fmt::Display for GlobalPlaneError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GlobalPlaneError {}

impl From<PlannerError> for GlobalPlaneError {
    fn from(error: PlannerError) -> Self {
        Self::Planner(error)
    }
}

impl From<NduPlanningError> for GlobalPlaneError {
    fn from(error: NduPlanningError) -> Self {
        Self::Ndu(error)
    }
}

impl From<codex_hepta_authbus::Error> for GlobalPlaneError {
    fn from(error: codex_hepta_authbus::Error) -> Self {
        Self::Authentication(error)
    }
}

/// Domain-separated scope signed by a non-fleet owner before its summary can
/// enter the global planner. Scope includes the owner and immutable planning
/// generation/configuration, so a valid message cannot be moved to another run.
pub fn owner_summary_scope_digest_v1(summary: &OwnerSummaryV1) -> Digest32 {
    let mut bytes = b"hepta.control.owner-summary-scope.v1\0".to_vec();
    push_id(&mut bytes, &summary.owner_id);
    push_digest(&mut bytes, summary.objective_digest);
    push_u64(&mut bytes, summary.body_generation.get());
    push_digest(&mut bytes, summary.configuration_digest);
    Digest32::of_bytes(&bytes)
}

/// Canonical payload digest authenticated by the owner message.
pub fn owner_summary_payload_digest_v1(summary: &OwnerSummaryV1) -> Digest32 {
    let mut bytes = b"hepta.control.owner-summary-payload.v1\0".to_vec();
    push_id(&mut bytes, &summary.owner_id);
    push_u64(&mut bytes, summary.revision.get());
    push_digest(&mut bytes, summary.objective_digest);
    push_u64(&mut bytes, summary.body_generation.get());
    push_digest(&mut bytes, summary.configuration_digest);
    push_u64(&mut bytes, summary.observed_at_micros);
    push_u64(&mut bytes, summary.expires_at_micros);
    bytes.push(readiness_tag(summary.readiness));
    push_digest(&mut bytes, summary.source_frontier_digest);
    push_digest(&mut bytes, summary.support_digest);
    Digest32::of_bytes(&bytes)
}

/// Verify an owner-signed summary before admitting it to global planning.
///
/// The caller-owned replay window consumes the admitted sequence after
/// cryptographic verification. Durable replay persistence remains an AuthBus
/// host responsibility; control.runtime does not become that state owner.
/// AuthBus signature expiry is wall-clock policy at ingress. The summary's
/// observation/expiry values remain in the caller's separate monotonic planner
/// domain and are revalidated by collect_snapshot/prepare_plan.
pub fn authenticate_owner_summary_v1(
    mut summary: OwnerSummaryV1,
    signed: &SignedMessage,
    issuer: &IssuerRegistration,
    replay: &mut ReplayWindow,
    now_unix_ms: u64,
) -> Result<AdmittedOwnerSummaryV1, GlobalPlaneError> {
    if signed.claims.subject_id != summary.owner_id {
        return Err(GlobalPlaneError::InvalidOwnerBinding);
    }
    let expected_scope = owner_summary_scope_digest_v1(&summary);
    let expected_payload = owner_summary_payload_digest_v1(&summary);
    let authenticated =
        signed.authenticate(issuer, expected_scope, expected_payload, now_unix_ms)?;
    if authenticated.claims().subject_id != summary.owner_id {
        return Err(GlobalPlaneError::InvalidOwnerBinding);
    }
    let replay_receipt = replay.verify(
        TrustedReplayContext {
            issuer_id: issuer.issuer_id.clone(),
            key_epoch: issuer.key_epoch,
            now_ms: now_unix_ms,
            revoked: issuer.revoked,
        },
        PreverifiedAuthEnvelope {
            message_id: signed.claims.message_id.clone(),
            subject_id: signed.claims.subject_id.clone(),
            scope_digest: signed.claims.scope_digest,
            payload_digest: signed.claims.payload_digest,
            signature_digest: Digest32::of_bytes(&signed.signature),
            sequence: signed.claims.sequence,
            expires_at_ms: signed.claims.expires_at_ms,
        },
        expected_scope,
        expected_payload,
    )?;

    let admission_digest = replay_receipt.envelope_digest;
    summary.support_digest = bind_admission_support(summary.support_digest, admission_digest);
    Ok(AdmittedOwnerSummaryV1 {
        summary,
        admission_digest,
    })
}

/// Admit one exact allocation grant from the runtime.fleet owner and project
/// its committed resource vector into the planner's canonical resource axes.
///
/// The fleet lease uses wall-clock expiry. The trusted host supplies a
/// request-local monotonic observation/expiry for planning; both domains are
/// checked independently and never converted by control.runtime.
#[allow(clippy::too_many_arguments)]
pub fn admit_fleet_allocation_owner_v1(
    ledger: &LeaseLedger,
    allocation_id: &str,
    expected_principal_id: &str,
    objective_digest: Digest32,
    body_generation: Generation,
    configuration_digest: Digest32,
    now_unix_ms: u64,
    observed_at_micros: u64,
    expires_at_micros: u64,
    floors: FleetEssentialFloorsV1,
) -> Result<FleetOwnerAdmissionV1, GlobalPlaneError> {
    if objective_digest.is_zero() || configuration_digest.is_zero() {
        return Err(GlobalPlaneError::InvalidOwnerBinding);
    }
    if expires_at_micros <= observed_at_micros {
        return Err(GlobalPlaneError::ClockDomainMismatch);
    }
    let grant = ledger
        .get(allocation_id)
        .ok_or(GlobalPlaneError::FleetAllocationMissing)?;
    if grant.principal_id != expected_principal_id {
        return Err(GlobalPlaneError::FleetPrincipalMismatch);
    }
    if grant.revoked {
        return Err(GlobalPlaneError::FleetAllocationRevoked);
    }
    if now_unix_ms >= grant.expires_at_ms {
        return Err(GlobalPlaneError::FleetAllocationExpired);
    }

    let source_frontier_digest = Digest32::from_str(&grant.semantic_digest)
        .map_err(|_| GlobalPlaneError::FleetSemanticDigest)?;
    let owner_id =
        StableId::new("runtime.fleet").map_err(|_| GlobalPlaneError::InvalidOwnerBinding)?;
    let revision =
        Revision::new(grant.lease_generation).map_err(|_| GlobalPlaneError::InvalidOwnerBinding)?;
    let admission_digest = fleet_grant_digest_v1(grant);
    let owner = AdmittedOwnerSummaryV1 {
        summary: OwnerSummaryV1 {
            owner_id,
            revision,
            objective_digest,
            body_generation,
            configuration_digest,
            observed_at_micros,
            expires_at_micros,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest,
            support_digest: bind_admission_support(source_frontier_digest, admission_digest),
        },
        admission_digest,
    };

    let memory_endowment_mib = grant.resources.memory_bytes / MIB;
    let memory_floor_mib = ceil_div(floors.memory_bytes, MIB)?;
    if floors.cpu_millis > grant.resources.cpu_millis
        || floors.accelerator_millis > grant.resources.accelerator_millis
        || memory_floor_mib > memory_endowment_mib
    {
        return Err(GlobalPlaneError::FleetResourceFloor);
    }

    let resource_reservations = vec![
        ResourceReservationV1 {
            axis: stable(FLEET_CPU_MILLIS_AXIS)?,
            endowment: q32_u64(grant.resources.cpu_millis)?,
            essential_floor: q32_u64(floors.cpu_millis)?,
        },
        ResourceReservationV1 {
            axis: stable(FLEET_MEMORY_MIB_AXIS)?,
            endowment: q32_u64(memory_endowment_mib)?,
            essential_floor: q32_u64(memory_floor_mib)?,
        },
        ResourceReservationV1 {
            axis: stable(FLEET_ACCELERATOR_MILLIS_AXIS)?,
            endowment: q32_u64(grant.resources.accelerator_millis)?,
            essential_floor: q32_u64(floors.accelerator_millis)?,
        },
    ];
    canonical_resource_profile_digest(&resource_reservations)?;

    Ok(FleetOwnerAdmissionV1 {
        owner,
        resource_reservations,
    })
}

/// Full authority-free global planning composition over authenticated/admitted
/// owner facts and a committed fleet allocation.
///
/// The fleet allocation is the source of the exact endowment/floor profile.
/// utility.ndu is invoked through its real owner implementation. Any resulting
/// GrantRequestSetV1 remains DENY_ALL and must be independently authorized.
pub fn compose_global_plan_with_fleet_v1(
    snapshot_request: SnapshotRequestV1,
    fleet: FleetOwnerAdmissionV1,
    other_owners: Vec<AdmittedOwnerSummaryV1>,
    mut planning_request: PlanningRequestV1,
    ndu_input: NduPlanningInputV1,
    now_micros: u64,
) -> Result<GlobalControlPlanV1, GlobalPlaneError> {
    if snapshot_request.collected_at_micros != now_micros {
        return Err(GlobalPlaneError::ClockDomainMismatch);
    }

    let mut owners = Vec::with_capacity(other_owners.len() + 1);
    owners.push(fleet.owner.summary.clone());
    owners.extend(other_owners.into_iter().map(|owner| owner.summary));

    let mut expected_owner_ids: Vec<_> =
        owners.iter().map(|summary| summary.owner_id.clone()).collect();
    expected_owner_ids.sort();
    if expected_owner_ids.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(GlobalPlaneError::OwnerSetMismatch);
    }
    let mut required_owner_ids = snapshot_request.required_owner_ids.clone();
    required_owner_ids.sort();
    if required_owner_ids != expected_owner_ids {
        return Err(GlobalPlaneError::OwnerSetMismatch);
    }

    planning_request.now_micros = now_micros;
    planning_request.resource_reservations = fleet.resource_reservations;
    planning_request.resource_profile_digest =
        canonical_resource_profile_digest(&planning_request.resource_reservations)?;

    let snapshot = collect_snapshot(snapshot_request, owners)?;
    let prepared = prepare_plan(&snapshot, planning_request)?;
    let evaluation =
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, ndu_input, now_micros)?;

    let grant_requests = if evaluation.plan.chosen_candidate_id().is_some() {
        Some(request_execution_grants(
            &snapshot,
            &prepared,
            &evaluation.plan,
            now_micros,
        )?)
    } else {
        None
    };

    Ok(GlobalControlPlanV1 {
        snapshot,
        prepared,
        evaluation,
        grant_requests,
    })
}

fn fleet_grant_digest_v1(grant: &codex_hepta_fleet::lease_ledger::AllocationGrant) -> Digest32 {
    let mut bytes = b"hepta.control.fleet-allocation-admission.v1\0".to_vec();
    push_string(&mut bytes, &grant.allocation_id);
    push_string(&mut bytes, &grant.request_id);
    push_string(&mut bytes, &grant.principal_id);
    push_string(&mut bytes, &grant.host_id);
    push_string(&mut bytes, &grant.failure_domain_id);
    push_u64(&mut bytes, grant.host_generation);
    push_u64(&mut bytes, grant.authority_epoch);
    push_u64(&mut bytes, grant.lease_generation);
    push_u64(&mut bytes, grant.expires_at_ms);
    push_u64(&mut bytes, grant.resources.cpu_millis);
    push_u64(&mut bytes, grant.resources.memory_bytes);
    push_u64(&mut bytes, grant.resources.accelerator_millis);
    push_string(&mut bytes, &grant.semantic_digest);
    bytes.push(u8::from(grant.revoked));
    Digest32::of_bytes(&bytes)
}

fn bind_admission_support(support: Digest32, admission: Digest32) -> Digest32 {
    let mut bytes = b"hepta.control.admitted-owner-support.v1\0".to_vec();
    push_digest(&mut bytes, support);
    push_digest(&mut bytes, admission);
    Digest32::of_bytes(&bytes)
}

fn q32_u64(value: u64) -> Result<FixedQ32, GlobalPlaneError> {
    let raw = i128::from(value)
        .checked_mul(1_i128 << 32)
        .ok_or(GlobalPlaneError::Arithmetic)?;
    let raw = i64::try_from(raw).map_err(|_| GlobalPlaneError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

fn ceil_div(value: u64, divisor: u64) -> Result<u64, GlobalPlaneError> {
    if divisor == 0 {
        return Err(GlobalPlaneError::Arithmetic);
    }
    Ok(value.div_ceil(divisor))
}

fn stable(value: &str) -> Result<StableId, GlobalPlaneError> {
    StableId::new(value).map_err(|_| GlobalPlaneError::InvalidOwnerBinding)
}

fn readiness_tag(readiness: OwnerReadinessV1) -> u8 {
    match readiness {
        OwnerReadinessV1::Ready => 0,
        OwnerReadinessV1::Degraded => 1,
        OwnerReadinessV1::Unavailable => 2,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_string(bytes, value.as_str());
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    let length = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "global_plane_tests.rs"]
mod tests;
