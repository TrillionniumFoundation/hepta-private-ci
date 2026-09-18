use std::collections::BTreeMap;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::FleetAllocationStore;
use crate::FleetAllocationStoreError;
use crate::FleetResourceVectorV1;
use crate::LocalHostCapacityCandidateV1;
use crate::PlacementError;
use crate::PlacementRequestV1;
use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseError;
use crate::lease_ledger::LeaseReceipt;
use crate::place_and_allocate_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetAllocationRequestV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub eligible_host_ids: Vec<String>,
    pub weight: u32,
    pub minimum: FleetResourceVectorV1,
    pub desired: FleetResourceVectorV1,
    pub lease_expires_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UsageObservationV1 {
    pub allocation_id: String,
    pub host_id: String,
    pub principal_id: String,
    pub lease_generation: u64,
    pub observed_at_ms: u64,
    pub consumed: FleetResourceVectorV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UsageDispositionV1 {
    WithinGrant,
    OverGrant,
}

#[derive(Debug, Error)]
pub enum FleetFlowError {
    #[error(transparent)]
    Store(#[from] FleetAllocationStoreError),
    #[error(transparent)]
    Placement(#[from] PlacementError),
    #[error(transparent)]
    Lease(#[from] LeaseError),
    #[error(transparent)]
    FinalUse(#[from] FinalUseError),
    #[error("missing or mismatched validated authority for request {0}")]
    Authority(String),
    #[error("no fresh authenticated-capacity input is available")]
    NoFreshCapacity,
    #[error("trusted fleet clock is unavailable")]
    Clock,
}

fn allocate_and_commit_prevalidated_v1(
    store: &mut FleetAllocationStore,
    now_ms: u64,
    requests: &[FleetAllocationRequestV1],
    authorities: &[PrevalidatedFleetAuthorityV1],
) -> Result<Vec<LeaseReceipt>, FleetFlowError> {
    let authority_by_request: BTreeMap<_, _> =
        authorities.iter().map(|a| (a.request_id.as_str(), a)).collect();

    for request in requests {
        let Some(authority) = authority_by_request.get(request.request_id.as_str()).copied() else {
            return Err(FleetFlowError::Authority(request.request_id.clone()));
        };
        if authority.authority_epoch == 0
            || authority.principal_id.is_empty()
            || authority.semantic_digest.len() != 64
            || authority.valid_until_ms < request.lease_expires_at_ms
            || request.lease_expires_at_ms <= now_ms
        {
            return Err(FleetFlowError::Authority(request.request_id.clone()));
        }
    }

    let calculation = calculate_current_plan_v1(store, now_ms, requests)?;

    let request_by_id: BTreeMap<_, _> =
        requests.iter().map(|r| (r.request_id.as_str(), r)).collect();
    let host_by_id: BTreeMap<_, _> =
        store.ledger().hosts().map(|h| (h.host_id.as_str(), h)).collect();

    let mut grants = Vec::with_capacity(calculation.shares().len());
    for share in calculation.shares() {
        let request = request_by_id
            .get(share.request_id.as_str())
            .copied()
            .ok_or_else(|| FleetFlowError::Authority(share.request_id.clone()))?;
        let authority = authority_by_request
            .get(share.request_id.as_str())
            .copied()
            .ok_or_else(|| FleetFlowError::Authority(share.request_id.clone()))?;
        let host = host_by_id
            .get(share.host_id.as_str())
            .copied()
            .ok_or(LeaseError::HostNotFound)?;
        grants.push(AllocationGrant {
            allocation_id: request.request_id.clone(),
            request_id: request.request_id.clone(),
            principal_id: authority.principal_id.clone(),
            host_id: share.host_id.clone(),
            failure_domain_id: share.failure_domain_id.clone(),
            host_generation: host.generation,
            authority_epoch: authority.authority_epoch,
            lease_generation: 1,
            expires_at_ms: request.lease_expires_at_ms,
            resources: share.resources,
            semantic_digest: authority.semantic_digest.clone(),
            revoked: false,
        });
    }

    store.issue_batch(now_ms, grants).map_err(Into::into)
}


fn calculate_current_plan_v1(
    store: &FleetAllocationStore,
    now_ms: u64,
    requests: &[FleetAllocationRequestV1],
) -> Result<crate::LocalAllocationCalculationV1, FleetFlowError> {
    let fresh_hosts: Vec<_> = store
        .ledger()
        .hosts()
        .filter(|host| host.observed_at_ms <= now_ms && now_ms < host.valid_until_ms)
        .map(|host| {
            let available = store
                .ledger()
                .available_resources(&host.host_id, now_ms)
                .map_err(FleetFlowError::Lease)?;
            Ok(LocalHostCapacityCandidateV1 {
                host_id: host.host_id.clone(),
                failure_domain_id: host.failure_domain_id.clone(),
                caller_supplied_allocatable: available,
            })
        })
        .collect::<Result<Vec<_>, FleetFlowError>>()?;
    if fresh_hosts.is_empty() {
        return Err(FleetFlowError::NoFreshCapacity);
    }
    let placement_requests: Vec<_> = requests
        .iter()
        .map(|request| PlacementRequestV1 {
            request_id: request.request_id.clone(),
            agent_id: request.agent_id.clone(),
            eligible_host_ids: request.eligible_host_ids.clone(),
            weight: request.weight,
            minimum: request.minimum,
            desired: request.desired,
        })
        .collect();
    place_and_allocate_v1(&fresh_hosts, &placement_requests).map_err(Into::into)
}

fn trusted_now_ms() -> Result<u64, FleetFlowError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| FleetFlowError::Clock)?
        .as_millis();
    u64::try_from(millis).map_err(|_| FleetFlowError::Clock)
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct PrevalidatedFleetAuthorityV1 {
    request_id: String,
    principal_id: String,
    authority_epoch: u64,
    semantic_digest: String,
    valid_until_ms: u64,
}

pub fn fleet_allocation_binding_v1(
    store: &FleetAllocationStore,
    principal_id: &str,
    requests: &[FleetAllocationRequestV1],
) -> Result<FinalUseBinding, FleetFlowError> {
    if principal_id.is_empty() || requests.is_empty() {
        return Err(FleetFlowError::Authority("batch".to_string()));
    }
    let now_ms = trusted_now_ms()?;
    if requests
        .iter()
        .any(|request| request.lease_expires_at_ms <= now_ms)
    {
        return Err(FleetFlowError::Authority("expired_lease".to_string()));
    }
    let calculation = calculate_current_plan_v1(store, now_ms, requests)?;
    let request_sha256 = digest_requests(b"hepta.runtime-fleet.request-set.v1\0", requests, false);
    let mut scope = Sha256::new();
    scope.update(b"hepta.runtime-fleet.scope.v1\0");
    scope.update(store.revision().to_be_bytes());
    push_text(&mut scope, calculation.calculation_content_sha256().as_str());
    let scope_sha256 = scope.finalize().into();

    let mut payload = Sha256::new();
    payload.update(b"hepta.runtime-fleet.final-allocation-batch.v1\0");
    push_text(&mut payload, principal_id);
    push_text(
        &mut payload,
        calculation.calculation_content_sha256().as_str(),
    );
    let mut ordered: Vec<_> = requests.iter().collect();
    ordered.sort_by(|a, b| a.request_id.cmp(&b.request_id).then_with(|| a.agent_id.cmp(&b.agent_id)));
    for request in ordered {
        push_text(&mut payload, &request.request_id);
        payload.update(request.lease_expires_at_ms.to_be_bytes());
    }
    let payload_sha256 = payload.finalize().into();

    Ok(FinalUseBinding {
        subject_id: principal_id.to_string(),
        destination_id: "runtime.fleet/allocation".to_string(),
        request_sha256,
        scope_sha256,
        payload_sha256,
    })
}

pub fn allocate_and_commit_with_verified_use_v1(
    authority: &FinalUseAuthority,
    signed_grant: &SignedFinalUseGrant,
    store: &mut FleetAllocationStore,
    principal_id: &str,
    requests: &[FleetAllocationRequestV1],
) -> Result<Vec<LeaseReceipt>, FleetFlowError> {
    let now_ms = trusted_now_ms()?;
    if requests.iter().any(|request| {
        request.lease_expires_at_ms <= now_ms
            || request.lease_expires_at_ms > signed_grant.grant.expires_at_unix_ms
    }) {
        return Err(FleetFlowError::Authority("lease_horizon".to_string()));
    }
    let expected = fleet_allocation_binding_v1(store, principal_id, requests)?;
    let token = authority.claim(signed_grant, &expected)?;
    let semantic_digest = hex_lower(&expected.payload_sha256);
    let authorities: Vec<_> = requests
        .iter()
        .map(|request| PrevalidatedFleetAuthorityV1 {
            request_id: request.request_id.clone(),
            principal_id: principal_id.to_string(),
            authority_epoch: signed_grant.grant.authority_epoch,
            semantic_digest: semantic_digest.clone(),
            valid_until_ms: signed_grant.grant.expires_at_unix_ms,
        })
        .collect();
    authority.with_verified_use(token, &expected, || {
        allocate_and_commit_prevalidated_v1(store, now_ms, requests, &authorities)
    })?
}

fn digest_requests(
    domain: &[u8],
    requests: &[FleetAllocationRequestV1],
    include_resources: bool,
) -> [u8; 32] {
    let mut ordered: Vec<_> = requests.iter().collect();
    ordered.sort_by(|a, b| a.request_id.cmp(&b.request_id).then_with(|| a.agent_id.cmp(&b.agent_id)));
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update((ordered.len() as u64).to_be_bytes());
    for request in ordered {
        push_text(&mut hasher, &request.request_id);
        push_text(&mut hasher, request.agent_id.as_str());
        let mut hosts = request.eligible_host_ids.clone();
        hosts.sort();
        hosts.dedup();
        hasher.update((hosts.len() as u64).to_be_bytes());
        for host in hosts {
            push_text(&mut hasher, &host);
        }
        hasher.update(request.weight.to_be_bytes());
        hasher.update(request.lease_expires_at_ms.to_be_bytes());
        if include_resources {
            push_resources(&mut hasher, request.minimum);
            push_resources(&mut hasher, request.desired);
        }
    }
    hasher.finalize().into()
}

fn push_text(hasher: &mut Sha256, value: &str) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value.as_bytes());
}

fn push_resources(hasher: &mut Sha256, value: FleetResourceVectorV1) {
    hasher.update(value.concurrent_turns.to_be_bytes());
    hasher.update(value.memory_mib.to_be_bytes());
    hasher.update(value.tool_processes.to_be_bytes());
    hasher.update(value.turn_queue_slots.to_be_bytes());
}

fn hex_lower(bytes: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

pub fn reconcile_usage_v1(
    store: &FleetAllocationStore,
    observation: &UsageObservationV1,
) -> Result<UsageDispositionV1, FleetFlowError> {
    let grant = store.ledger().enforce(
        observation.observed_at_ms,
        &observation.allocation_id,
        &observation.host_id,
        &observation.principal_id,
        observation.lease_generation,
    )?;
    Ok(if observation.consumed.fits(grant.resources) {
        UsageDispositionV1::WithinGrant
    } else {
        UsageDispositionV1::OverGrant
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lease_ledger::HostObservation;

    fn agent() -> AgentId {
        AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent")
    }

    fn vector(turns: u64) -> FleetResourceVectorV1 {
        FleetResourceVectorV1 { concurrent_turns: turns, ..Default::default() }
    }

    #[test]
    fn production_flow_places_commits_reopens_and_reconciles() {
        let temp = tempfile::tempdir().expect("temp");
        let path = temp.path().join("fleet-allocations.json");
        let mut store = FleetAllocationStore::open(&path).expect("store");
        store.admit_host(HostObservation {
            host_id: "host-a".into(),
            failure_domain_id: "rack-a".into(),
            generation: 7,
            observed_at_ms: 10,
            valid_until_ms: 1000,
            capacity: vector(4),
        }).expect("host");

        let requests = vec![FleetAllocationRequestV1 {
            request_id: "request-a".into(),
            agent_id: agent(),
            eligible_host_ids: vec!["host-a".into()],
            weight: 1,
            minimum: vector(1),
            desired: vector(3),
            lease_expires_at_ms: 800,
        }];
        let authorities = vec![PrevalidatedFleetAuthorityV1 {
            request_id: "request-a".into(),
            principal_id: "principal-a".into(),
            authority_epoch: 11,
            semantic_digest: "1".repeat(64),
            valid_until_ms: 900,
        }];

        let receipts = allocate_and_commit_prevalidated_v1(&mut store, 100, &requests, &authorities).expect("allocate");
        assert_eq!(receipts.len(), 1);
        drop(store);

        let reopened = FleetAllocationStore::open(path).expect("reopen");
        let disposition = reconcile_usage_v1(&reopened, &UsageObservationV1 {
            allocation_id: "request-a".into(),
            host_id: "host-a".into(),
            principal_id: "principal-a".into(),
            lease_generation: 1,
            observed_at_ms: 200,
            consumed: vector(2),
        }).expect("reconcile");
        assert_eq!(disposition, UsageDispositionV1::WithinGrant);
    }

    #[test]
    fn fleet_02_restart_and_host_generation_fence_old_lease() {
        let temp = tempfile::tempdir().expect("temp");
        let path = temp.path().join("fleet-allocations.json");
        let mut store = FleetAllocationStore::open(&path).expect("store");
        store.admit_host(HostObservation {
            host_id: "host-a".into(),
            failure_domain_id: "rack-a".into(),
            generation: 1,
            observed_at_ms: 10,
            valid_until_ms: 1000,
            capacity: vector(4),
        }).expect("host");
        let requests = vec![FleetAllocationRequestV1 {
            request_id: "request-a".into(),
            agent_id: agent(),
            eligible_host_ids: vec!["host-a".into()],
            weight: 1,
            minimum: vector(1),
            desired: vector(2),
            lease_expires_at_ms: 800,
        }];
        let authorities = vec![PrevalidatedFleetAuthorityV1 {
            request_id: "request-a".into(),
            principal_id: "principal-a".into(),
            authority_epoch: 3,
            semantic_digest: "2".repeat(64),
            valid_until_ms: 900,
        }];
        allocate_and_commit_prevalidated_v1(&mut store, 100, &requests, &authorities).expect("allocate");
        drop(store);

        let mut reopened = FleetAllocationStore::open(&path).expect("reopen");
        reopened.admit_host(HostObservation {
            host_id: "host-a".into(),
            failure_domain_id: "rack-a".into(),
            generation: 2,
            observed_at_ms: 200,
            valid_until_ms: 1200,
            capacity: vector(4),
        }).expect("new host generation");
        let error = reopened.renew_or_revoke(
            300, "request-a", 1, 3, &"2".repeat(64),
            crate::lease_ledger::LeaseDisposition::Renew { expires_at_ms: 700 },
        ).expect_err("old generation must be fenced");
        assert!(matches!(error, FleetAllocationStoreError::Lease(LeaseError::StaleHost)));
    }

    #[test]
    fn fleet_04_unmatched_authority_cannot_commit_allocation() {
        let temp = tempfile::tempdir().expect("temp");
        let mut store = FleetAllocationStore::open(temp.path().join("fleet-allocations.json")).expect("store");
        store.admit_host(HostObservation {
            host_id: "host-a".into(),
            failure_domain_id: "rack-a".into(),
            generation: 1,
            observed_at_ms: 10,
            valid_until_ms: 1000,
            capacity: vector(4),
        }).expect("host");
        let requests = vec![FleetAllocationRequestV1 {
            request_id: "request-a".into(),
            agent_id: agent(),
            eligible_host_ids: vec!["host-a".into()],
            weight: 1,
            minimum: vector(1),
            desired: vector(2),
            lease_expires_at_ms: 800,
        }];
        let authorities = vec![PrevalidatedFleetAuthorityV1 {
            request_id: "different-request".into(),
            principal_id: "principal-a".into(),
            authority_epoch: 3,
            semantic_digest: "3".repeat(64),
            valid_until_ms: 900,
        }];
        assert!(matches!(
            allocate_and_commit_prevalidated_v1(&mut store, 100, &requests, &authorities),
            Err(FleetFlowError::Authority(id)) if id == "request-a"
        ));
        assert!(store.ledger().get("request-a").is_none());
    }


    #[cfg(unix)]
    #[test]
    fn verified_final_use_authority_guards_atomic_grant_commit() {
        use std::collections::BTreeSet;
        use std::os::unix::fs::PermissionsExt;
        use std::time::{SystemTime, UNIX_EPOCH};

        use codex_hepta_contracts::{FinalUseGrant, FinalUseRevocations};
        use ed25519_dalek::{Signer, SigningKey};

        let now_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis() as u64;
        let temp = tempfile::tempdir().expect("temp");
        let allocation_path = temp.path().join("fleet-allocations.json");
        let authority_dir = temp.path().join("authority");
        std::fs::create_dir(&authority_dir).expect("authority dir");
        std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
            .expect("private authority dir");

        let mut store = FleetAllocationStore::open(&allocation_path).expect("store");
        store
            .admit_host(HostObservation {
                host_id: "host-a".into(),
                failure_domain_id: "rack-a".into(),
                generation: 1,
                observed_at_ms: now_ms - 1_000,
                valid_until_ms: now_ms + 60_000,
                capacity: vector(4),
            })
            .expect("host");

        let requests = vec![FleetAllocationRequestV1 {
            request_id: "request-a".into(),
            agent_id: agent(),
            eligible_host_ids: vec!["host-a".into()],
            weight: 1,
            minimum: vector(1),
            desired: vector(3),
            lease_expires_at_ms: now_ms + 20_000,
        }];
        let binding =
            fleet_allocation_binding_v1(&store, "principal-a", &requests).expect("fleet binding");
        let issuer = SigningKey::from_bytes(&[41; 32]);
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "fleet-security-owner".into(),
            authority_epoch: 7,
            grant_id: "fleet-grant-a".into(),
            nonce: [9; 32],
            binding,
            not_before_unix_ms: now_ms - 1_000,
            expires_at_unix_ms: now_ms + 30_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        let signed = SignedFinalUseGrant { grant, signature };
        let authority = FinalUseAuthority::open_state_dir(
            &authority_dir,
            "fleet-security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("authority");

        let receipts = allocate_and_commit_with_verified_use_v1(
            &authority,
            &signed,
            &mut store,
            "principal-a",
            &requests,
        )
        .expect("authorized commit");
        assert_eq!(receipts.len(), 1);
        assert_eq!(
            authority
                .claim(
                    &signed,
                    &fleet_allocation_binding_v1(&store, "principal-a", &requests).expect("binding"),
                )
                .expect_err("nonce must remain consumed"),
            FinalUseError::AlreadyClaimed
        );
    }

}
