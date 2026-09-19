use std::fs;

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AgentdPayload;
use crate::LifecycleSnapshot;

fn fixture() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    registry.compare_and_transition(
        &state.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    Ok((temp, registry, state))
}

#[tokio::test]
async fn serving_agent_survives_unrelated_registry_corruption() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let peer = registry
        .layout()
        .agents_root()
        .join("019153a4-3088-7e03-a56a-9b1964f75dd3");
    fs::create_dir(peer).expect("incomplete peer");
    assert!(registry.load().is_err());
    state
        .refresh_generation()
        .expect("local generation remains valid");
    let response = state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::Lifecycle,
        )
        .await
        .expect("serving control response");
    assert_eq!(
        serde_json::to_value(response.payload).expect("serialize actual lifecycle"),
        serde_json::to_value(AgentdPayload::Lifecycle(LifecycleSnapshot {
            lifecycle: AgentLifecycle::Running,
            app_server_ready: true,
            fenced: false,
        }))
        .expect("serialize expected lifecycle")
    );
}

#[tokio::test]
async fn live_control_routes_run_lifecycle_through_agentd_state() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    let now_ms = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("millisecond clock");
    let snapshot = RunSnapshot {
        run_id: "run.live.1".to_string(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 2,
        deadline_ms: now_ms + 60_000,
    };
    let start = state
        .response(
            10,
            1,
            crate::AgentdMethod::RunStart {
                snapshot: snapshot.clone(),
            },
        )
        .await
        .expect("run start");
    let admitted = match start.payload {
        AgentdPayload::RunReceipt(receipt) => receipt,
        payload => panic!("unexpected start payload: {payload:?}"),
    };
    assert_eq!(admitted.phase, RunPhase::Admitted);

    let attachment = ContextAttachment {
        run_id: snapshot.run_id.clone(),
        request_digest: snapshot.request_digest,
        objective_digest: snapshot.objective_digest,
        body_digest: snapshot.body_digest,
        artifact_set_digest: snapshot.artifact_set_digest,
        authority_epoch: snapshot.authority_epoch,
        deadline_ms: snapshot.deadline_ms,
        context_digest: "5".repeat(64),
        compilation_receipt_digest: "6".repeat(64),
    };
    let attached = state
        .response(
            11,
            1,
            crate::AgentdMethod::RunAttachContext {
                expected_revision: admitted.revision,
                attachment,
            },
        )
        .await
        .expect("attach context");
    let attached = match attached.payload {
        AgentdPayload::RunReceipt(receipt) => receipt,
        payload => panic!("unexpected attach payload: {payload:?}"),
    };
    assert_eq!(attached.phase, RunPhase::ContextAttached);

    let dispatch_binding = RunDispatchBinding::new(
        "run.live.1",
        "5".repeat(64),
        "thread.live.1",
        "7".repeat(64),
    )
    .expect("valid dispatch binding");
    let dispatched = state
        .response(
            12,
            1,
            crate::AgentdMethod::RunMarkDispatched {
                run_id: "run.live.1".to_string(),
                expected_revision: attached.revision,
                binding: dispatch_binding,
            },
        )
        .await
        .expect("mark dispatched");
    let dispatched = match dispatched.payload {
        AgentdPayload::RunReceipt(receipt) => receipt,
        payload => panic!("unexpected dispatch payload: {payload:?}"),
    };
    assert_eq!(dispatched.phase, RunPhase::Dispatched);

    state.mark_draining().expect("begin drain");
    let new_snapshot = RunSnapshot {
        run_id: "run.live.2".to_string(),
        request_digest: "a".repeat(64),
        objective_digest: "b".repeat(64),
        body_digest: "c".repeat(64),
        artifact_set_digest: "d".repeat(64),
        authority_epoch: 2,
        deadline_ms: now_ms + 60_000,
    };
    assert!(
        state
            .response(
                13,
                1,
                crate::AgentdMethod::RunStart {
                    snapshot: new_snapshot,
                },
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn deadline_monitor_path_persists_cancellation_before_lost_interrupt_ack() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    let now_ms = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("millisecond clock");
    let deadline_ms = now_ms.checked_add(100).expect("deadline");
    let snapshot = RunSnapshot {
        run_id: "run.deadline.bound.1".to_string(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 2,
        deadline_ms,
    };
    let admitted = state.run_start(now_ms, snapshot.clone()).expect("start");
    let attached = state
        .run_attach_context(
            now_ms + 1,
            admitted.revision,
            ContextAttachment {
                run_id: snapshot.run_id.clone(),
                request_digest: snapshot.request_digest.clone(),
                objective_digest: snapshot.objective_digest.clone(),
                body_digest: snapshot.body_digest.clone(),
                artifact_set_digest: snapshot.artifact_set_digest.clone(),
                authority_epoch: snapshot.authority_epoch,
                deadline_ms: snapshot.deadline_ms,
                context_digest: "5".repeat(64),
                compilation_receipt_digest: "6".repeat(64),
            },
        )
        .expect("attach");
    let dispatch = RunDispatchBinding::new(
        snapshot.run_id.clone(),
        "5".repeat(64),
        "thread.deadline.bound.1",
        "7".repeat(64),
    )
    .expect("dispatch binding");
    let dispatched = state
        .run_mark_dispatched(
            now_ms + 2,
            &snapshot.run_id,
            attached.revision,
            dispatch.clone(),
        )
        .expect("dispatch");
    let execution = RunExecutionBinding::new(
        snapshot.run_id.clone(),
        dispatch.binding_digest,
        dispatch.thread_id,
        "turn.deadline.bound.1",
    )
    .expect("execution binding");
    state
        .run_bind_execution(now_ms + 3, &snapshot.run_id, dispatched.revision, execution)
        .expect("bind execution");

    // No App Server is listening in this fixture. The interrupt transport is
    // therefore lost, but the durable lifecycle transition must still win.
    state
        .expire_run_deadlines_and_interrupt(deadline_ms)
        .await
        .expect("deadline processing");
    let status = state
        .run_status(&snapshot.run_id)
        .expect("status")
        .expect("retained run");
    assert_eq!(status.phase, RunPhase::Cancelling);
    assert_eq!(status.cancel_reason.as_deref(), Some("deadline_exceeded"));
    assert!(status.cancellation_ack_deadline_ms.is_some());
}

#[test]
fn missing_local_record_immediately_fences_the_serving_agent() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    fs::remove_file(state.identity.layout.agent_config()).expect("remove local manifest");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(state.is_fenced().expect("fenced state"));
}

#[test]
fn targeted_read_preserves_lifecycle_and_resource_fences() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let mut identity = state.identity.clone();
    identity.resources.turn_queue_capacity += 1;
    let changed = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16);
    assert!(
        matches!(changed, Err(AgentdError::Protocol(message)) if message.contains("InvalidGeneration")),
        "same-generation composition drift reached a serving Agentd"
    );
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("draining");
    state.refresh_generation().expect("drain remains valid");
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 3,
            AgentLifecycle::Stopped,
        )
        .expect("stopped");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
}

#[cfg(unix)]
mod durable_operations_control {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_automation::AutomationSchedule;
    use codex_hepta_automation::AutomationStore;
    use codex_hepta_automation::AutomationTaskDraft;
    use codex_hepta_automation::automation_task_operation_intent;
    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use codex_hepta_types::Generation;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;
    use crate::AgentdOperationsError;
    use crate::AgentdOperationsHost;
    use crate::AutomationGrantProvider;

    struct SigningGrantProvider {
        issuer: SigningKey,
    }

    impl AutomationGrantProvider for SigningGrantProvider {
        fn signed_grant(
            &self,
            intent: &codex_hepta_operations::OperationIntentV1,
        ) -> Result<SignedFinalUseGrant, AgentdOperationsError> {
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|error| AgentdOperationsError::Grant(error.to_string()))?
                .as_millis() as u64;
            let grant = FinalUseGrant {
                schema_version: 1,
                signer_id: "automation-security-owner".to_string(),
                authority_epoch: 7,
                grant_id: format!("grant:{}", intent.operation_id),
                nonce: intent.semantic_digest().into_array(),
                binding: intent.final_use_binding(),
                not_before_unix_ms: now.saturating_sub(1_000),
                expires_at_unix_ms: now.saturating_add(30_000),
            };
            let signature = self
                .issuer
                .sign(
                    &grant
                        .signing_bytes()
                        .map_err(|error| AgentdOperationsError::Grant(error.to_string()))?,
                )
                .to_bytes()
                .to_vec();
            Ok(SignedFinalUseGrant { grant, signature })
        }
    }

    #[tokio::test]
    async fn automation_create_uses_configured_durable_operations_host() -> anyhow::Result<()> {
        let (temp, _registry, state) = fixture()?;
        let automation = AutomationStore::open(&state.identity.layout).await?;
        state.attach_automation_store(automation.clone())?;

        let issuer = SigningKey::from_bytes(&[91; 32]);
        let authority_dir = temp.path().join("automation-final-use");
        fs::create_dir(&authority_dir)?;
        fs::set_permissions(&authority_dir, fs::Permissions::from_mode(0o700))?;
        let authority = FinalUseAuthority::open_state_dir(
            &authority_dir,
            "automation-security-owner".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        let operations_path = state
            .identity
            .layout
            .agent_root()
            .join("kernel-operations")
            .join("automation.sqlite3");
        let host = AgentdOperationsHost::open(
            &operations_path,
            automation.clone(),
            authority,
            Arc::new(SigningGrantProvider { issuer }),
            Generation::new(1)?,
        )
        .await?;
        state.attach_automation_operations(Arc::new(host))?;

        let draft = AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "route through durable operations",
            AutomationSchedule::FixedInterval { interval_ms: 5_000 },
            20_000,
            10_000,
        );
        let intent = automation_task_operation_intent(
            automation.owner_agent_id(),
            &draft,
            Generation::new(1)?,
        )?;
        let response = state
            .response(
                41,
                1,
                crate::AgentdMethod::AutomationCreate {
                    draft: draft.clone(),
                },
            )
            .await?;
        let first = match response.payload {
            AgentdPayload::AutomationTask(task) => task,
            payload => anyhow::bail!("unexpected AutomationCreate payload: {payload:?}"),
        };

        let host = state
            .automation_operations()
            .expect("configured durable operations host");
        let source = host
            .source_store()
            .operation(&intent.scope_id, &intent.operation_id)
            .await?
            .expect("source operation persisted");
        assert!(source.state.is_terminal());

        let replay = state
            .response(42, 1, crate::AgentdMethod::AutomationCreate { draft })
            .await?;
        assert_eq!(replay.payload, AgentdPayload::AutomationTask(first));
        assert_eq!(automation.list_tasks(10).await?.len(), 1);
        Ok(())
    }
}
