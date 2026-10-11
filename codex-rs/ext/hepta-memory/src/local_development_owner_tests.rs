use std::fs;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::LocalRehydrationReplayDisposition;
use crate::LocalRehydrationWitnessLifecycleInput;
use codex_extension_api::ExtensionData;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CompactCheckpoint;
use codex_hepta_memory::CompactFence;
use codex_hepta_memory::CompactLease;
use codex_hepta_memory::CompactLossReport;
use codex_hepta_memory::CompactParentSnapshot;
use codex_hepta_memory::CompactSummaryReceipt;
use codex_hepta_memory::LocalLeaseAcquire;
use codex_hepta_memory::LocalLeaseState;
use codex_hepta_memory::LocalRehydrationWitnessWrite;
use codex_hepta_memory::checkpoint_digest;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::*;

fn fence() -> CompactFence {
    CompactFence::new(3, 4, 1, "e19-owner-fence").expect("fence")
}

fn checkpoint(fence: CompactFence) -> CompactCheckpoint {
    CompactCheckpoint::new(
        "checkpoint:e19-owner",
        CompactLease::from_snapshot(
            CompactParentSnapshot::new(
                "ctx:e19-owner",
                1,
                2,
                3,
                Sha256Digest::for_bytes(b"state:e19-owner"),
                fence,
            )
            .expect("parent snapshot"),
        ),
        Vec::new(),
        CompactSummaryReceipt::new(
            Sha256Digest::for_bytes(b"summary:e19-owner"),
            Sha256Digest::for_bytes(b"model:e19-owner"),
            Sha256Digest::for_bytes(b"policy:e19-owner"),
        ),
        CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss report"),
        0,
    )
    .expect("checkpoint")
}

async fn prepared_owner_inputs() -> (
    TempDir,
    CognitiveStore,
    ExtensionData,
    codex_hepta_memory::LocalLeaseOutbox,
    codex_hepta_memory::LocalCompactExecutor,
    CompactCheckpoint,
) {
    let temp = TempDir::new().expect("temp");
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet");
    let owner_id = AgentId::parse("00000000-0000-4000-8000-000000000919").expect("owner id");
    let store = CognitiveStore::open(&fleet.layout().agent(&owner_id))
        .await
        .expect("store");
    let current_fence = fence();
    let checkpoint = checkpoint(current_fence.clone());
    let expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + 3_600;
    let lease = match store
        .acquire_local_lease_bound(
            "lease:e19-owner",
            current_fence.authority_epoch,
            current_fence.owner_epoch,
            current_fence.generation,
            current_fence.fencing_token.clone(),
            expires_at,
        )
        .await
        .expect("bound lease")
    {
        LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
    };
    lease
        .admit(
            "occurrence:e19-owner",
            "local.rehydration.witness.v1",
            "{\"external_effect\":false}",
        )
        .await
        .expect("local admission");
    let executor = store
        .open_local_compact_executor_bound("journal:e19-owner", current_fence, &lease)
        .await
        .expect("bound executor");
    let current = checkpoint.lease.snapshot.clone();
    executor
        .append_intent("operation:e19-owner", &checkpoint, &current)
        .await
        .expect("intent");
    let digest = checkpoint_digest(&checkpoint).expect("checkpoint digest");
    executor
        .commit_checkpoint("operation:e19-owner", &digest)
        .await
        .expect("commit");
    (
        temp,
        store,
        ExtensionData::new("turn:e19-owner"),
        lease,
        executor,
        checkpoint,
    )
}

#[test]
fn owner_is_explicit_and_caller_zero() {
    let owner = HeptaLocalDevelopmentLifecycleOwner::qualification_only();
    assert!(owner.policy().permits_explicit_witness_write());
    assert!(!owner.runtime_registered());
    assert!(!owner.production_caller());
}

#[test]
fn owner_rejects_production_policy() {
    let mut policy = LocalDevelopmentLifecyclePolicy::qualification_only();
    policy.production_activation = true;
    assert!(matches!(
        HeptaLocalDevelopmentLifecycleOwner::new(policy),
        Err(HeptaLocalDevelopmentLifecycleOwnerError::Policy(_))
    ));
}

#[tokio::test]
async fn explicit_owner_writes_bound_witness_and_replays_without_registration() {
    let (_temp, store, turn_store, lease, executor, checkpoint) = prepared_owner_inputs().await;
    let owner = HeptaLocalDevelopmentLifecycleOwner::qualification_only();
    let input = || {
        LocalRehydrationWitnessLifecycleInput::new(
            "turn:e19-owner",
            &turn_store,
            "operation:e19-owner",
            0,
            &checkpoint,
            &lease,
            &executor,
        )
    };

    let first = owner
        .write_local_rehydration_witness(input())
        .await
        .expect("first explicit owner write");
    assert_eq!(
        first.observed_disposition,
        LocalRehydrationReplayDisposition::NotStarted
    );
    assert!(!first.witness.replayed);
    assert!(!first.external_effects);
    assert!(!first.kg_write_authority);
    assert!(!first.production_caller);
    assert!(!first.lifecycle_registered);
    assert!(first.policy_gate_bound);

    let second = owner
        .write_local_rehydration_witness(input())
        .await
        .expect("replayed explicit owner write");
    assert_eq!(
        second.observed_disposition,
        LocalRehydrationReplayDisposition::Complete
    );
    assert!(second.witness.replayed);
    assert_eq!(
        second.witness.witness_sequence,
        first.witness.witness_sequence
    );
    assert!(
        executor
            .rehydration("operation:e19-owner")
            .await
            .expect("witness lookup")
            .is_some()
    );
    let snapshot = executor.snapshot().await.expect("compact snapshot");
    assert_eq!(snapshot.entries.len(), 3, "one rehydration witness row");
    assert!(matches!(
        snapshot.entries.last().map(|entry| &entry.kind),
        Some(codex_hepta_memory::CompactPersistenceEventKind::Rehydrated { .. })
    ));
    assert!(matches!(
        codex_hepta_memory::write_local_rehydration_witness(
            &lease,
            &executor,
            "operation:e19-owner",
            &checkpoint,
            0,
        )
        .await
        .expect("core replay"),
        LocalRehydrationWitnessWrite::Replay(_)
    ));
    drop(store);
}

#[tokio::test]
async fn explicit_owner_expires_bound_lease_and_fences_old_witness() {
    let temp = TempDir::new().expect("temp");
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet");
    let owner_id = AgentId::parse("00000000-0000-4000-8000-000000000920").expect("owner id");
    let store = CognitiveStore::open(&fleet.layout().agent(&owner_id))
        .await
        .expect("store");
    let current_fence = CompactFence::new(7, 8, 1, "e21-owner-fence").expect("fence");
    let checkpoint = checkpoint(current_fence.clone());
    let expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + 1;
    let lease = match store
        .acquire_local_lease_bound(
            "lease:e21-owner",
            current_fence.authority_epoch,
            current_fence.owner_epoch,
            current_fence.generation,
            current_fence.fencing_token.clone(),
            expires_at,
        )
        .await
        .expect("bound lease")
    {
        LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
    };
    let executor = store
        .open_local_compact_executor_bound("journal:e21-owner", current_fence, &lease)
        .await
        .expect("bound executor");
    let current = checkpoint.lease.snapshot.clone();
    executor
        .append_intent("operation:e21-owner", &checkpoint, &current)
        .await
        .expect("intent");

    let other_temp = TempDir::new().expect("other temp");
    let other_root = other_temp.path().join("fleet");
    fs::create_dir_all(&other_root).expect("other fleet root");
    let other_fleet = HeptaFleetRoot::parse(other_root).expect("other fleet");
    let other_store = CognitiveStore::open(&other_fleet.layout().agent(&owner_id))
        .await
        .expect("other store");
    let owner = HeptaLocalDevelopmentLifecycleOwner::qualification_only();
    assert!(!owner.runtime_registered());
    assert!(!owner.production_caller());
    assert!(matches!(
        owner.expire_local_lease(&other_store, &lease).await,
        Err(HeptaLocalDevelopmentLifecycleOwnerError::StoreBindingMismatch)
    ));

    for _ in 0..120 {
        if SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs()
            >= expires_at
        {
            break;
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    assert!(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs()
            >= expires_at,
        "test lease did not expire"
    );

    let terminal = owner
        .expire_local_lease(&store, &lease)
        .await
        .expect("owner timeout terminalization");
    assert_eq!(terminal.state, LocalLeaseState::RolledBack);
    let replay = owner
        .expire_local_lease(&store, &lease)
        .await
        .expect("owner timeout replay");
    assert_eq!(replay, terminal);

    assert!(matches!(
        executor
            .append_intent("operation:e21-after-expiry", &checkpoint, &current)
            .await,
        Err(codex_hepta_memory::LocalCompactExecutorError::Lease(
            codex_hepta_memory::LocalLeaseOutboxError::StaleFence(_)
        ))
    ));
    assert!(matches!(
        lease
            .admit("occurrence:e21-after-expiry", "topic", "payload")
            .await,
        Err(codex_hepta_memory::LocalLeaseOutboxError::StaleFence(_))
    ));

    let next_expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + 3_600;
    let next = match store
        .acquire_local_lease_after_head_bound(
            "lease:e21-owner",
            terminal,
            7,
            8,
            2,
            "e21-owner-fence-2",
            next_expires_at,
        )
        .await
        .expect("next generation")
    {
        LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
    };
    assert_eq!(next.generation(), 2);
    assert!(next.is_explicitly_bound());
}

#[tokio::test]
async fn explicit_owner_rejects_unbound_lease_expiry() {
    let temp = TempDir::new().expect("temp");
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet");
    let owner_id = AgentId::parse("00000000-0000-4000-8000-000000000921").expect("owner id");
    let store = CognitiveStore::open(&fleet.layout().agent(&owner_id))
        .await
        .expect("store");
    let lease = match store
        .acquire_local_lease("lease:e21-unbound", 1, "e21-unbound-fence")
        .await
        .expect("unbound lease")
    {
        LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
    };
    let owner = HeptaLocalDevelopmentLifecycleOwner::qualification_only();
    assert!(matches!(
        owner.expire_local_lease(&store, &lease).await,
        Err(HeptaLocalDevelopmentLifecycleOwnerError::Lease(
            LocalLeaseOutboxError::Invalid(message)
        )) if message.contains("explicit authority/owner/expiry binding")
    ));
}
