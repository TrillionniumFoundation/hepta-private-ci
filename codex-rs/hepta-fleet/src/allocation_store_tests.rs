use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::*;

struct Fixture {
    _temp: TempDir,
    registry: FleetRegistry,
    first: AgentId,
    second: AgentId,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let temp = tempfile::tempdir()?;
        let fleet_root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        let first = register(
            &registry,
            &fleet_root,
            temp.path(),
            1,
            "workspace-first",
        )?;
        let second = register(
            &registry,
            &fleet_root,
            temp.path(),
            2,
            "workspace-second",
        )?;
        Ok(Self {
            _temp: temp,
            registry,
            first,
            second,
        })
    }

    fn authority(
        &self,
        epoch: u64,
    ) -> Result<(FinalUseAuthority, SigningKey), Box<dyn std::error::Error>> {
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let directory = self._temp.path().join(format!("authority-{epoch}"));
        std::fs::create_dir(&directory)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(
                &directory,
                std::fs::Permissions::from_mode(/*mode*/ 0o700),
            )?;
        }
        let authority = FinalUseAuthority::open_state_dir(
            &directory,
            "fleet-authority".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: epoch,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        Ok((authority, issuer))
    }
}

fn register(
    registry: &FleetRegistry,
    fleet_root: &HeptaFleetRoot,
    parent: &std::path::Path,
    index: usize,
    workspace_name: &str,
) -> Result<AgentId, Box<dyn std::error::Error>> {
    let workspace = parent.join(workspace_name);
    std::fs::create_dir(&workspace)?;
    let agent = agent(index);
    registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace.canonicalize()?, fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    Ok(agent)
}

fn agent(index: usize) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{index:012x}")).expect("valid test AgentId")
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock")
        .as_millis() as u64
}

fn resources(turns: u64, memory_mib: u64) -> FleetResourceVectorV1 {
    FleetResourceVectorV1 {
        concurrent_turns: turns,
        memory_mib,
        tool_processes: 1,
        turn_queue_slots: 1,
    }
}

fn host(
    id: &str,
    domain: &str,
    now: u64,
    capacity: FleetResourceVectorV1,
) -> FleetHostObservationV1 {
    FleetHostObservationV1::new(
        id.to_string(),
        domain.to_string(),
        1,
        1,
        now.saturating_sub(1),
        now + 120_000,
        FleetCapacityObservationSourceV1::EnrolledHostAdapter,
        capacity,
    )
    .expect("host observation")
}

fn request(
    allocation_id: &str,
    request_id: &str,
    agent_id: AgentId,
    turns: u64,
) -> FleetPlacementRequestV1 {
    FleetPlacementRequestV1 {
        allocation_id: allocation_id.to_string(),
        request_id: request_id.to_string(),
        agent_id,
        caller_supplied_weight: 1,
        minimum: resources(1, 256),
        desired: resources(turns, 1_024),
        allowed_failure_domains: Vec::new(),
    }
}

fn signed_for(
    prepared: &FleetPreparedAllocationV1,
    issuer: &SigningKey,
    nonce_byte: u8,
    grant_id: &str,
) -> SignedFinalUseGrant {
    let now = now_ms();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "fleet-authority".to_string(),
        authority_epoch: prepared.authority_epoch,
        grant_id: grant_id.to_string(),
        nonce: [nonce_byte; 32],
        binding: prepared.final_use_binding.clone(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

#[test]
fn fleet_01_over_capacity_batch_preserves_floors_and_durable_conservation(
) -> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let now = now_ms();
    let store = FleetAllocationStore::open(&fixture.registry)?;
    store.admit_host(host("host-a", "rack-a", now, resources(2, 4_096)))?;

    let requests = vec![
        request("allocation-a", "request-a", fixture.first.clone(), 2),
        request("allocation-b", "request-b", fixture.second.clone(), 2),
    ];
    let prepared = store.prepare_allocation("principal.1", 7, &requests, 20_000, now)?;
    assert_eq!(prepared.grants.len(), 2);
    assert!(
        prepared
            .grants
            .iter()
            .all(|grant| grant.resources.concurrent_turns >= 1)
    );
    assert_eq!(
        prepared
            .grants
            .iter()
            .map(|grant| grant.resources.concurrent_turns)
            .sum::<u64>(),
        2
    );

    let (authority, issuer) = fixture.authority(7)?;
    let signed = signed_for(&prepared, &issuer, 1, "fleet-01");
    let token = authority.claim(&signed, &prepared.final_use_binding)?;
    let committed = store.commit_prepared(&authority, token, &prepared, now)?;
    assert_eq!(committed.len(), 2);
    drop(store);

    let reopened = FleetAllocationStore::open(&fixture.registry)?;
    let state = reopened.load()?;
    assert_eq!(state.grants.len(), 2);
    assert_eq!(
        state
            .grants
            .values()
            .map(|grant| grant.resources.concurrent_turns)
            .sum::<u64>(),
        2
    );
    Ok(())
}

#[test]
fn fleet_02_expiry_or_restart_uncertainty_never_double_allocates_hard_capacity(
) -> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let now = now_ms();
    let store = FleetAllocationStore::open(&fixture.registry)?;
    store.admit_host(host("host-a", "rack-a", now, resources(2, 4_096)))?;

    let first = vec![request(
        "allocation-a",
        "request-a",
        fixture.first.clone(),
        2,
    )];
    let prepared = store.prepare_allocation("principal.1", 7, &first, 1_000, now)?;
    let (authority, issuer) = fixture.authority(7)?;
    let signed = signed_for(&prepared, &issuer, 2, "fleet-02");
    let token = authority.claim(&signed, &prepared.final_use_binding)?;
    let grants = store.commit_prepared(&authority, token, &prepared, now)?;
    let grant = grants[0].clone();
    store.reconcile_consumption(FleetConsumptionObservationV1 {
        allocation_id: grant.allocation_id.clone(),
        lease_generation: grant.lease_generation,
        host_generation: grant.host_generation,
        observed_at_unix_ms: now,
        observer_id: "test.runtime".to_string(),
        disposition: FleetConsumptionDispositionV1::Holding,
    })?;
    drop(store);

    let reopened = FleetAllocationStore::open(&fixture.registry)?;
    let second = vec![request(
        "allocation-b",
        "request-b",
        fixture.second.clone(),
        2,
    )];
    let after_expiry = now + 2_000;
    assert!(matches!(
        reopened.prepare_allocation("principal.1", 7, &second, 1_000, after_expiry),
        Err(FleetAllocationStoreError::Placement(
            LocalAllocationError::NoEligibleHost(_)
        ))
    ));

    reopened.reconcile_consumption(FleetConsumptionObservationV1 {
        allocation_id: grant.allocation_id,
        lease_generation: grant.lease_generation,
        host_generation: grant.host_generation,
        observed_at_unix_ms: after_expiry,
        observer_id: "test.runtime".to_string(),
        disposition: FleetConsumptionDispositionV1::Released,
    })?;
    let next = reopened.prepare_allocation("principal.1", 7, &second, 1_000, after_expiry)?;
    assert_eq!(next.grants.len(), 1);
    assert_eq!(next.grants[0].agent_id, fixture.second);
    Ok(())
}

#[test]
fn fleet_03_permuted_requests_and_hosts_produce_identical_placement_digest() {
    let now = now_ms();
    let mut hosts = vec![
        LocalHostCapacityCandidateV1 {
            host_id: "host-b".to_string(),
            failure_domain_id: "rack-b".to_string(),
            caller_supplied_allocatable: resources(2, 4_096),
        },
        LocalHostCapacityCandidateV1 {
            host_id: "host-a".to_string(),
            failure_domain_id: "rack-a".to_string(),
            caller_supplied_allocatable: resources(2, 4_096),
        },
    ];
    let mut requests = vec![
        request("allocation-b", "request-b", agent(2), 2),
        request("allocation-a", "request-a", agent(1), 2),
    ];
    let expected = place_and_allocate_v1(&hosts, &requests).expect("placement");
    hosts.reverse();
    requests.reverse();
    let actual = place_and_allocate_v1(&hosts, &requests).expect("placement");
    assert_eq!(actual, expected);
    assert_ne!(now, 0);
}

#[test]
fn fleet_04_requests_cannot_invent_enrollment_or_inherit_final_use_authority(
) -> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let now = now_ms();
    let store = FleetAllocationStore::open(&fixture.registry)?;
    let requests = vec![request(
        "allocation-a",
        "request-a",
        fixture.first.clone(),
        1,
    )];
    assert!(matches!(
        store.prepare_allocation("principal.1", 7, &requests, 1_000, now),
        Err(FleetAllocationStoreError::Placement(
            LocalAllocationError::NoEligibleHost(_)
        ))
    ));

    store.admit_host(host("host-a", "rack-a", now, resources(2, 4_096)))?;
    let prepared = store.prepare_allocation("principal.1", 7, &requests, 1_000, now)?;
    let (authority, issuer) = fixture.authority(7)?;
    let mut wrong = prepared.final_use_binding.clone();
    wrong.destination_id = "runtime.fleet/attacker".to_string();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "fleet-authority".to_string(),
        authority_epoch: 7,
        grant_id: "fleet-04".to_string(),
        nonce: [4; 32],
        binding: wrong,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: issuer
            .sign(&grant.signing_bytes()?)
            .to_bytes()
            .to_vec(),
        grant,
    };
    assert_eq!(
        authority
            .claim(&signed, &prepared.final_use_binding)
            .expect_err("wrong binding must not authorize"),
        FinalUseError::BindingMismatch
    );
    assert!(store.load()?.grants.is_empty());
    Ok(())
}
