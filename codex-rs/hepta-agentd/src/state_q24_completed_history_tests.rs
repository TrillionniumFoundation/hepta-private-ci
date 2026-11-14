//! These checks exercise the real local Fleet/State gates. They cannot create
//! a positive Root history capability and do not qualify a cold restoration.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;

use super::fixture;
use crate::AgentdError;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdState;

async fn ready_fixture() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let (directory, registry, previous) = fixture()?;
    let identity = previous.identity().clone();
    drop(previous);
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    state.refresh_generation()?;
    fs::set_permissions(
        &state.identity().home_root,
        fs::Permissions::from_mode(0o700),
    )?;
    let cognitive = DurableCognitiveStore::open(&state.identity().layout).await?;
    state.attach_cognitive_store(Arc::new(cognitive))?;
    state.mark_runtime_prerequisites_ready()?;
    state.mark_app_server_ready()?;
    Ok((directory, registry, state))
}

#[test]
fn completed_history_rejects_recipient_without_critical_store() -> anyhow::Result<()> {
    let (_directory, _registry, state) = fixture()?;
    state.mark_runtime_prerequisites_ready()?;
    assert!(matches!(
        state.read_original_q24_terminal_acceptance(),
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(matches!(
        state.read_original_q24_completed_history(),
        Err(AgentdError::GenerationFenced(_))
    ));
    Ok(())
}

#[tokio::test]
async fn current_ready_daemon_cannot_promote_missing_terminal_acknowledgement() -> anyhow::Result<()>
{
    let (_directory, _registry, state) = ready_fixture().await?;
    let response = state
        .response(
            /*request_id*/ 1,
            state.identity().spawn_generation,
            AgentdMethod::OriginalQ24TerminalAcceptance {},
        )
        .await?;
    assert_eq!(
        Some(response.current_generation),
        state.identity().spawn_generation.checked_add(1)
    );
    assert!(matches!(
        response.payload,
        AgentdPayload::OriginalQ24TerminalAcceptance { data: None }
    ));
    assert!(state.read_original_q24_completed_history()?.is_none());
    Ok(())
}

#[tokio::test]
async fn terminal_acknowledgement_query_requires_the_actual_running_recipient() -> anyhow::Result<()>
{
    let (_directory, registry, state) = ready_fixture().await?;
    assert!(state.read_original_q24_terminal_acceptance()?.is_none());
    let running = registry.load_agent(&state.identity().agent_id)?.lifecycle;
    assert_eq!(running.lifecycle, AgentLifecycle::Running);
    assert_eq!(
        Some(running.generation),
        state.identity().spawn_generation.checked_add(1)
    );
    registry.compare_and_transition(
        &state.identity().agent_id,
        running.generation,
        AgentLifecycle::Draining,
    )?;
    assert!(matches!(
        state.read_original_q24_terminal_acceptance(),
        Err(AgentdError::GenerationFenced(_))
    ));
    Ok(())
}

#[tokio::test]
async fn current_ready_daemon_cannot_promote_missing_completed_history() -> anyhow::Result<()> {
    let (_directory, _registry, state) = ready_fixture().await?;
    let response = state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            AgentdMethod::OriginalQ24CompletedHistory {},
        )
        .await?;
    assert_eq!(
        Some(response.current_generation),
        state.identity().spawn_generation.checked_add(1)
    );
    assert!(matches!(
        response.payload,
        AgentdPayload::OriginalQ24CompletedHistory { data: None }
    ));
    let capabilities = state
        .response(
            /*request_id*/ 2,
            /*spawn_generation*/ 1,
            AgentdMethod::Capabilities,
        )
        .await?;
    let encoded = serde_json::to_string(&capabilities.payload)?;
    assert!(!encoded.contains(codex_hepta_agent_protocol::AGENTD_Q24_COMPLETED_HISTORY_CAPABILITY));
    Ok(())
}

#[tokio::test]
async fn completed_history_missing_still_requires_current_running_recipient() -> anyhow::Result<()>
{
    let (_directory, registry, state) = ready_fixture().await?;
    assert!(state.read_original_q24_completed_history()?.is_none());
    let running = registry.load_agent(&state.identity().agent_id)?.lifecycle;
    assert_eq!(running.lifecycle, AgentLifecycle::Running);
    assert_eq!(
        Some(running.generation),
        state.identity().spawn_generation.checked_add(1)
    );
    registry.compare_and_transition(
        &state.identity().agent_id,
        running.generation,
        AgentLifecycle::Draining,
    )?;
    assert!(matches!(
        state.read_original_q24_completed_history(),
        Err(AgentdError::GenerationFenced(_))
    ));
    Ok(())
}
