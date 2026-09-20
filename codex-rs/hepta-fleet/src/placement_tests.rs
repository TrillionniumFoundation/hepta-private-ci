use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;

fn agent(index: usize) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{index:012x}"))
        .expect("valid agent id")
}

fn host(id: &str, domain: &str, generation: u64, turns: u64) -> HostObservation {
    HostObservation {
        host_id: id.into(),
        failure_domain_id: domain.into(),
        generation,
        observed_at_ms: 100,
        valid_until_ms: 10_000,
        capacity: FleetResourceVectorV1 {
            concurrent_turns: turns,
            memory_mib: 8_192,
            tool_processes: 32,
            turn_queue_slots: 128,
        },
    }
}

fn request(id: &str, index: usize, minimum: u64, desired: u64) -> FleetPlacementRequestV1 {
    FleetPlacementRequestV1 {
        allocation_id: format!("allocation.{id}"),
        request_id: format!("request.{id}"),
        agent_id: agent(index),
        weight: 1,
        minimum: FleetResourceVectorV1 {
            concurrent_turns: minimum,
            memory_mib: 256,
            tool_processes: 1,
            turn_queue_slots: 4,
        },
        desired: FleetResourceVectorV1 {
            concurrent_turns: desired,
            memory_mib: 1_024,
            tool_processes: 4,
            turn_queue_slots: 16,
        },
        request_semantic_digest: format!("{:064x}", index + 1),
    }
}

fn store() -> (tempfile::TempDir, FleetAllocationStore) {
    let temp = tempfile::tempdir().expect("tempdir");
    let state_root = temp.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let store = FleetAllocationStore::open_or_initialize(&state_root).expect("store");
    (temp, store)
}

fn authority(
    binding: FinalUseBinding,
    nonce: u8,
) -> (
    tempfile::TempDir,
    FinalUseAuthority,
    SignedFinalUseGrant,
) {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "fleet-authority".into(),
        authority_epoch: 9,
        grant_id: format!("fleet-grant-{nonce}"),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("authority dir");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private authority dir");
    }
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "fleet-authority".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    (
        directory,
        authority,
        SignedFinalUseGrant { grant, signature },
    )
}

#[test]
fn placement_is_deterministic_and_selects_hosts_before_allocation() {
    let (_temp, store) = store();
    let generation = store
        .admit_host(0, 200, host("host-a", "rack-a", 1, 4))
        .expect("host a");
    let generation = store
        .admit_host(generation, 200, host("host-b", "rack-b", 1, 8))
        .expect("host b");
    let requests = vec![request("b", 2, 2, 8), request("a", 1, 2, 8)];
    let expected = plan_placement_v1(&store, 200, 9, 5_000, &requests).expect("plan");
    let mut reversed = requests;
    reversed.reverse();
    let actual = plan_placement_v1(&store, 200, 9, 5_000, &reversed).expect("plan");
    assert_eq!(actual.source_generation(), generation);
    assert_eq!(actual.payload_sha256_hex(), expected.payload_sha256_hex());
    assert_eq!(actual.grants(), expected.grants());
    assert!(actual.grants().iter().all(|grant| grant.resources.concurrent_turns > 0));
}

#[test]
fn exact_final_use_authority_commits_the_complete_plan_generation() {
    let (_temp, store) = store();
    let generation = store
        .admit_host(0, 200, host("host-a", "rack-a", 1, 8))
        .expect("host");
    let plan = plan_placement_v1(&store, 200, 9, 5_000, &[request("a", 1, 1, 4)])
        .expect("plan");
    assert_eq!(plan.source_generation(), generation);
    let binding = placement_authority_binding("fleet-controller", &plan);
    let (_authority_dir, authority, signed) = authority(binding, 5);
    let committed = commit_placement_with_authority(
        &store,
        &authority,
        &signed,
        "fleet-controller",
        200,
        plan,
    )
    .expect("commit");
    assert_eq!(committed.source_generation, 1);
    assert_eq!(committed.committed_generation, 2);
    assert!(store
        .load(200)
        .expect("durable")
        .grant("allocation.a")
        .is_some());
}

#[test]
fn capacity_observation_requires_authority_bound_to_exact_payload() {
    let (_temp, store) = store();
    let observation = host("host-a", "rack-a", 1, 8);
    let binding = capacity_observation_binding("fleet-observer", 0, &observation)
        .expect("binding");
    let (_authority_dir, authority, signed) = authority(binding, 6);
    let mut changed = observation.clone();
    changed.capacity.concurrent_turns = 9;
    assert!(matches!(
        admit_host_with_authority(
            &store,
            &authority,
            &signed,
            "fleet-observer",
            0,
            200,
            changed,
        ),
        Err(FleetPlacementError::Authority(_))
    ));
    assert_eq!(store.load(200).expect("unchanged").generation(), 0);
}
