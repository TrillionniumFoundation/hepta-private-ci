//! Actual owner reopen and AF_UNIX observation. The enclosing dispatch test
//! mocks only HTTP; this does not claim Supervisord or native Chain acceptance.
use super::*;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use tokio_util::sync::CancellationToken;

pub(super) async fn observe_reopened_terminal_through_socket(
    original_identity: &AgentdIdentity,
    host_file: &Path,
    intent: &AuthorizedEffectIntent,
    receipt: &TaskFlowStepReceipt,
    now_ms: u64,
) -> anyhow::Result<()> {
    let fleet =
        FleetRegistry::open_existing(HeptaFleetRoot::parse(original_identity.fleet_root.clone())?)?;
    for (generation, lifecycle) in [
        (0, AgentLifecycle::Starting),
        (1, AgentLifecycle::Running),
        (2, AgentLifecycle::Draining),
        (3, AgentLifecycle::Stopped),
        (4, AgentLifecycle::Starting),
    ] {
        fleet.compare_and_transition(&original_identity.agent_id, generation, lifecycle)?;
    }
    let config = crate::AgentdConfig::load(
        original_identity.fleet_root.clone(),
        original_identity.agent_id.clone(),
        5,
        original_identity.home_root.clone(),
        original_identity.run_root.clone(),
        original_identity.home_root.clone(),
        original_identity.workspace.clone(),
    )?;
    let (identity, registry, _writer_lock) = config.into_parts();
    let store = AutomationStore::open(&identity.layout).await?;
    let host = AgentdAutomationEffectHost::open(&identity, host_file)?;
    assert!(
        host.reconcile(
            &store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + 60_001
        )
        .await
        .is_err(),
        "terminal observation must not relax the expired/cleared live owner fence"
    );
    match host
        .observe_terminal(&store, intent, "agentd-product-effect-dispatch")
        .await?
    {
        AgentdAutomationEffectReconcileOutcome::Observed {
            receipt: actual,
            chain,
        } => {
            assert_eq!(*actual, *receipt);
            assert!(chain.is_none(), "HTTP is not Chain evidence");
        }
        AgentdAutomationEffectReconcileOutcome::Indeterminate
        | AgentdAutomationEffectReconcileOutcome::ProvenAbsent => {
            panic!("settled receipt was lost on reopen")
        }
    }
    let cognitive = Arc::new(codex_hepta_memory::CognitiveStore::open(&identity.layout).await?);
    let socket = identity.control_socket.clone();
    let owner = identity.agent_id.clone();
    let host = Arc::new(host);
    let state = Arc::new(crate::AgentdState::new(identity, registry, 16)?);
    state.attach_cognitive_store(cognitive)?;
    state.attach_automation_store(store)?;
    state.attach_automation_effect_host(Arc::clone(&host))?;
    state.mark_runtime_prerequisites_ready()?;
    fleet.compare_and_transition(&owner, 5, AgentLifecycle::Running)?;
    state.mark_app_server_ready()?;
    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let server =
        crate::AgentdControlServer::bind(socket.clone(), state, cancellation.clone()).await?;
    let task = tokio::spawn(server.run());
    let current = crate::AgentdClient::new(socket.clone(), owner.clone(), 5)?;
    let expected = crate::AutomationEffectReconcileSnapshot {
        state: crate::AutomationEffectReconcileState::Terminal,
        effect: Some(crate::AutomationEffectSnapshot {
            run_id: receipt.run_id.clone(),
            step_id: receipt.step_id.clone(),
            attempt: receipt.attempt,
            event_seq: receipt.event_seq,
            receipt_digest: receipt.receipt_digest.clone(),
            observation: crate::AutomationEffectObservation::Succeeded,
        }),
        chain: None,
    };
    assert_eq!(
        current
            .automation_observe_effect(intent.clone(), "agentd-product-effect-dispatch".to_owned())
            .await?,
        expected
    );
    assert!(
        current
            .automation_observe_effect(intent.clone(), "different-command".to_owned())
            .await
            .is_err()
    );
    assert!(
        crate::AgentdClient::new(socket, owner, 1)?
            .automation_observe_effect(intent.clone(), "agentd-product-effect-dispatch".to_owned())
            .await
            .is_err()
    );
    assert_eq!(
        host.authority.capacity()?.used_nonces,
        1,
        "readback must not consume or refund authority"
    );
    cancellation.cancel();
    task.await??;
    Ok(())
}
