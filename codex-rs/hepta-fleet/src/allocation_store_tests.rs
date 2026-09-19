use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::*;

const CAPACITY_SIGNER_ID: &str = "fleet-capacity-owner";
const AUTHORITY_SIGNER_ID: &str = "fleet-authority-owner";

struct Fixture {
    _temp: TempDir,
    registry: FleetRegistry,
    store: FleetAllocationStore,
    agent_id: AgentId,
    capacity_signer: SigningKey,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let temp = tempfile::tempdir()?;
        let fleet_root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet_root)?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
        registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, registry.layout().fleet_root())?,
            ResourceBudget {
                max_concurrent_turns: 8,
                memory_limit_mib: 8_192,
                max_tool_processes: 32,
                turn_queue_capacity: 512,
            },
        )?)?;
        let store = FleetAllocationStore::initialize(&registry)?;
        Ok(Self {
            _temp: temp,
            registry,
            store,
            agent_id,
            capacity_signer: SigningKey::from_bytes(&[41; 32]),
        })
    }

    fn record_capacity(
        &self,
        expected_generation: u64,
        host_generation: u64,
        now: u64,
        turns: u64,
    ) -> Result<FleetAllocationSnapshotV1, FleetAllocationStoreError> {
        let observation = FleetHostCapacityObservationV1::new(
            "host-a".to_string(),
            "rack-a".to_string(),
            host_generation,
            7,
            now.saturating_sub(1_000),
            now + 60_000,
            vector(turns, 8_192, 32, 512),
        )?;
        let signature = self
            .capacity_signer
            .sign(&observation.signing_bytes(CAPACITY_SIGNER_ID)?)
            .to_bytes()
            .to_vec();
        let signed = SignedFleetHostCapacityObservationV1 {
            signer_id: CAPACITY_SIGNER_ID.to_string(),
            observation,
            signature,
        };
        let verifier = FleetCapacityVerifierV1::new(
            CAPACITY_SIGNER_ID.to_string(),
            self.capacity_signer.verifying_key().to_bytes(),
        )?;
        self.store
            .record_capacity(expected_generation, verifier.verify(&signed)?)
    }

    fn request(
        &self,
        id: &str,
        minimum_turns: u64,
        desired_turns: u64,
    ) -> FleetPlacementRequestV1 {
        FleetPlacementRequestV1 {
            request_id: id.to_string(),
            agent_id: self.agent_id.clone(),
            principal_id: "principal-a".to_string(),
            weight: 1,
            minimum: vector(minimum_turns, 128, 1, 1),
            desired: vector(desired_turns, 1_024, 4, 32),
        }
    }

    fn policy(&self) -> FleetPlacementPolicyV1 {
        FleetPlacementPolicyV1 {
            policy_id: "fleet-default".to_string(),
            revision: 1,
            content_sha256: Sha256Digest::for_bytes(b"fleet-default-v1"),
            authority_epoch: 7,
            lease_ttl_ms: 30_000,
        }
    }

    fn final_use(
        &self,
        plan: &FleetAllocationPlanV1,
        nonce: [u8; 32],
        grant_id: &str,
        now: u64,
    ) -> Result<(FinalUseAuthority, SignedFinalUseGrant), Box<dyn std::error::Error>> {
        let signer = SigningKey::from_bytes(&[47; 32]);
        let directory = self._temp.path().join(format!("authority-{grant_id}"));
        std::fs::create_dir(&directory)?;
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))?;
        let binding = plan.final_use_binding("runtime.fleet:primary")?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: AUTHORITY_SIGNER_ID.to_string(),
            authority_epoch: plan.authority_epoch,
            grant_id: grant_id.to_string(),
            nonce,
            binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = signer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        let authority = FinalUseAuthority::open_state_dir(
            &directory,
            AUTHORITY_SIGNER_ID.to_string(),
            signer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: plan.authority_epoch,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        Ok((authority, SignedFinalUseGrant { grant, signature }))
    }
}

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_millis(),
    )
    .expect("millisecond clock fits u64")
}

fn vector(turns: u64, memory_mib: u64, tools: u64, queue: u64) -> FleetResourceVectorV1 {
    FleetResourceVectorV1 {
        concurrent_turns: turns,
        memory_mib,
        tool_processes: tools,
        turn_queue_slots: queue,
    }
}

#[test]
fn fleet_01_durable_commit_conserves_capacity_survives_restart_and_reclaims_terminal_state()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let now = now_ms();
    let capacity = fixture.record_capacity(0, 1, now, 8)?;
    assert_eq!(capacity.generation, 1);

    let (generation, plan) =
        fixture
            .store
            .calculate_plan(&[fixture.request("request-a", 2, 6)], &fixture.policy(), now)?;
    assert_eq!(generation, 1);
    let (authority, signed) = fixture.final_use(&plan, [5; 32], "fleet-commit-1", now)?;
    let committed = fixture.store.commit_plan_with_authority(
        &authority,
        &signed,
        "runtime.fleet:primary",
        generation,
        &plan,
        now,
    )?;
    assert_eq!(committed.generation, 2);
    assert_eq!(committed.allocations.len(), 1);
    let grant = committed.allocations[0].clone();

    let reopened = FleetAllocationStore::open_existing(&fixture.registry)?;
    assert_eq!(
        reopened
            .validate_runtime_grant(
                &grant.allocation_id,
                &fixture.agent_id,
                vector(1, 128, 1, 1),
                now,
            )?
            .plan_sha256,
        plan.plan_sha256
    );

    let held = reopened.reconcile_holder(
        2,
        &grant.allocation_id,
        1,
        FleetAllocationHolderStateV1::Held,
        now + 1,
    )?;
    assert_eq!(held.generation, 3);
    let revoked = reopened.revoke(3, &grant.allocation_id, 1, now + 2)?;
    assert_eq!(revoked.generation, 4);
    assert_eq!(revoked.grant.lease_generation, 2);
    assert!(matches!(
        reopened.validate_runtime_grant(
            &grant.allocation_id,
            &fixture.agent_id,
            vector(1, 128, 1, 1),
            now + 3,
        ),
        Err(FleetAllocationStoreError::GrantNotLive)
    ));
    let released = reopened.reconcile_holder(
        4,
        &grant.allocation_id,
        2,
        FleetAllocationHolderStateV1::Released,
        now + 3,
    )?;
    assert_eq!(released.generation, 5);
    let collected = reopened.garbage_collect(5, now + 4)?;
    assert_eq!(collected.generation, 6);
    assert!(collected.grants.is_empty());

    assert_eq!(reopened.prune_snapshots(2)?, 5);
    let compacted = FleetAllocationStore::open_existing(&fixture.registry)?;
    assert_eq!(compacted.snapshot()?.generation, 6);
    Ok(())
}

#[test]
fn fleet_02_new_host_generation_never_reallocates_uncertain_old_capacity()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let now = now_ms();
    fixture.record_capacity(0, 1, now, 8)?;
    let (generation, plan) =
        fixture
            .store
            .calculate_plan(&[fixture.request("request-a", 2, 6)], &fixture.policy(), now)?;
    let (authority, signed) = fixture.final_use(&plan, [6; 32], "fleet-commit-2", now)?;
    let committed = fixture.store.commit_plan_with_authority(
        &authority,
        &signed,
        "runtime.fleet:primary",
        generation,
        &plan,
        now,
    )?;
    let grant = committed.allocations[0].clone();

    let rollover = fixture.record_capacity(2, 2, now + 1, 8)?;
    assert_eq!(rollover.generation, 3);
    assert!(matches!(
        fixture.store.validate_runtime_grant(
            &grant.allocation_id,
            &fixture.agent_id,
            vector(1, 128, 1, 1),
            now + 2,
        ),
        Err(FleetAllocationStoreError::StaleHostGeneration { .. })
    ));

    assert!(matches!(
        fixture.store.calculate_plan(
            &[fixture.request("request-b", 3, 3)],
            &fixture.policy(),
            now + 2,
        ),
        Err(FleetAllocationStoreError::Placement(
            FleetPlacementError::NoFeasibleHost(_)
        ))
    ));
    Ok(())
}

#[test]
fn immutable_generation_cas_rejects_stale_writers_and_unregistered_agents()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let now = now_ms();
    fixture.record_capacity(0, 1, now, 8)?;
    assert!(matches!(
        fixture.record_capacity(0, 2, now + 1, 8),
        Err(FleetAllocationStoreError::StaleGeneration {
            expected: 0,
            current: 1
        })
    ));

    let unregistered = FleetPlacementRequestV1 {
        request_id: "request-unregistered".to_string(),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000099")?,
        principal_id: "principal-a".to_string(),
        weight: 1,
        minimum: vector(1, 128, 1, 1),
        desired: vector(1, 128, 1, 1),
    };
    assert!(matches!(
        fixture
            .store
            .calculate_plan(&[unregistered], &fixture.policy(), now),
        Err(FleetAllocationStoreError::Registry(_))
    ));
    Ok(())
}
