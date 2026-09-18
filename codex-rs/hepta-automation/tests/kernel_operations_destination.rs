#![cfg(unix)]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationOperationDisposition;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::automation_task_operation_intent;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_operations::DispatchBoundaryResult;
use codex_hepta_operations::DurableDispatcher;
use codex_hepta_operations::DurableOperationState;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn source_config(temp: &tempfile::TempDir) -> SqliteConfig {
    let home =
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute source sqlite home");
    SqliteConfig::new_for_testing(home)
}

fn automation_fixture() -> (tempfile::TempDir, codex_hepta_paths::HeptaAgentLayout) {
    let temp = tempfile::tempdir().expect("temp root");
    let root = temp.path().canonicalize().expect("canonical temp root");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let workspace = workspace.canonicalize().expect("canonical workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
    let manifest = AgentManifest::new(
        agent_id,
        WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let layout = registry.register(manifest).expect("register agent").layout;
    (temp, layout)
}

fn draft() -> AutomationTaskDraft {
    AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "cross-owner durable operation",
        AutomationSchedule::Once,
        20_000,
        10_000,
    )
}

fn signed_grant(
    record: &codex_hepta_operations::DurableOperationRecord,
    authority_epoch: u64,
) -> (FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir) {
    let signing_key = SigningKey::from_bytes(&[71; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_string(),
        authority_epoch,
        grant_id: format!("operation-grant:{}", record.operation_id),
        nonce: [29; 32],
        binding: record.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing_key
        .sign(&grant.signing_bytes().expect("grant signing bytes"))
        .to_bytes()
        .to_vec();
    let state_dir = tempfile::tempdir().expect("authority state dir");
    std::fs::set_permissions(state_dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("secure authority state dir");
    let authority = FinalUseAuthority::open_state_dir(
        state_dir.path(),
        "security-owner".to_string(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("open authority");
    (authority, SignedFinalUseGrant { grant, signature }, state_dir)
}

#[tokio::test]
async fn cross_owner_lost_ack_applies_once_and_reconciles_terminal() {
    let (_fleet_temp, layout) = automation_fixture();
    let destination = AutomationStore::open(&layout)
        .await
        .expect("open automation destination");
    let draft = draft();
    let operation = automation_task_operation_intent(
        destination.owner_agent_id(),
        &draft,
        generation(7),
        generation(9),
    )
    .expect("operation intent");

    let source_temp = tempfile::tempdir().expect("source temp");
    let source = DurableOperationStore::open(&source_config(&source_temp))
        .await
        .expect("open operation source");
    let prepared = source.prepare_intent(&operation).await.expect("prepare operation");
    assert_eq!(prepared.state, DurableOperationState::Pending);

    let dispatcher = DurableDispatcher::new(
        source.clone(),
        stable_id("worker:automation-taskflow"),
        generation(7),
        30_000,
    )
    .expect("dispatcher");
    let mut claims = dispatcher.claim_ready(1).await.expect("claim ready");
    let lease = claims.pop().expect("one dispatch lease");
    assert!(claims.is_empty());

    let record = source
        .get_operation(&operation.scope, &operation.operation_id)
        .await
        .expect("source read")
        .expect("operation exists");
    let (authority, signed, _authority_state) = signed_grant(&record, 9);

    let mut admitted = false;
    let result = dispatcher
        .dispatch_authorized(
            &authority,
            &signed,
            &lease,
            Digest32::of_bytes(b"automation-owner-queue-admission"),
            |claimed| {
                assert_eq!(claimed.operation_id, operation.operation_id);
                admitted = true;
                // The destination owner accepted the request but the source did
                // not receive a trustworthy acknowledgement.
                DispatchBoundaryResult::<()>::Indeterminate {
                    reason_digest: Digest32::of_bytes(b"automation-queue-ack-lost"),
                }
            },
        )
        .await
        .expect("authorized dispatch");
    assert!(admitted);
    assert!(matches!(
        result,
        DispatchBoundaryResult::Indeterminate { .. }
    ));
    assert_eq!(
        source
            .get_operation(&operation.scope, &operation.operation_id)
            .await
            .expect("source state")
            .expect("operation")
            .state,
        DurableOperationState::Indeterminate
    );

    let applied = destination
        .create_task_from_operation(&operation, &draft)
        .await
        .expect("destination apply");
    assert_eq!(applied.disposition, AutomationOperationDisposition::Applied);

    let terminal = source
        .reconcile_destination_receipt(
            &operation.scope,
            &operation.operation_id,
            generation(7),
            &applied.destination_receipt,
        )
        .await
        .expect("terminal reconciliation");
    assert_eq!(terminal.state, DurableOperationState::Applied);

    let replay = destination
        .create_task_from_operation(&operation, &draft)
        .await
        .expect("exact destination replay");
    assert_eq!(
        replay.disposition,
        AutomationOperationDisposition::AlreadyApplied
    );
    assert_eq!(
        replay.destination_receipt,
        applied.destination_receipt,
        "destination replay must return the same durable evidence"
    );
    assert_eq!(
        destination.list_tasks(8).await.expect("list tasks").len(),
        1,
        "exact cross-owner replay must not create a second domain row"
    );

    let path = destination.path().to_path_buf();
    destination.close().await;
    drop(destination);
    let reopened = AutomationStore::open(&layout)
        .await
        .expect("reopen automation destination");
    assert_eq!(reopened.path(), path.as_path());
    assert_eq!(
        reopened
            .observe_task_operation(&operation)
            .await
            .expect("observe durable receipt"),
        Some(applied.destination_receipt)
    );
}

#[tokio::test]
async fn destination_payload_drift_conflicts_without_second_task() {
    let (_fleet_temp, layout) = automation_fixture();
    let destination = AutomationStore::open(&layout)
        .await
        .expect("open automation destination");
    let first = draft();
    let operation = automation_task_operation_intent(
        destination.owner_agent_id(),
        &first,
        generation(7),
        generation(9),
    )
    .expect("operation intent");
    destination
        .create_task_from_operation(&operation, &first)
        .await
        .expect("first apply");

    let mut changed = first.clone();
    changed.prompt = "changed payload".to_string();
    assert!(destination
        .create_task_from_operation(&operation, &changed)
        .await
        .is_err());
    assert_eq!(
        destination.list_tasks(8).await.expect("list tasks").len(),
        1
    );
}
