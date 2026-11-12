//! These checks exercise the real local Fleet/State gates. They cannot create
//! a positive Root history capability and do not qualify a cold restoration.

use codex_hepta_fleet::AgentLifecycle;

use super::fixture;
use crate::AgentdError;
use crate::AgentdMethod;
use crate::AgentdPayload;

#[tokio::test]
async fn current_ready_daemon_cannot_promote_missing_completed_history() -> anyhow::Result<()> {
    let (_directory, _registry, state) = fixture()?;
    state.mark_runtime_prerequisites_ready()?;
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

#[test]
fn completed_history_missing_still_requires_current_running_recipient() -> anyhow::Result<()> {
    let (_directory, registry, state) = fixture()?;
    state.mark_runtime_prerequisites_ready()?;
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
