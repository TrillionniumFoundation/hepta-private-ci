//! Real UDS refusal when the original writer has no configured source ingress.
use std::error::Error;
use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::Fixture;
use super::assert_no_issuer_request;
use super::attach_production_operation_host;

// Exact Unicode export produced by the pinned Python EpisodicStore.
const SNAPSHOT: &str = r#"{"body":{"authority_id":"0000000000004000800000000000e001","generation":1,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"流程","namespace":"bridge-fixture","provenance":{"episode_id":"独立来源","source_sha256":"81b2ada28e09db7ffcc8f0f0dde36515818b1d79b29c75c4bbda85c7cc881e81","source_uri":"fixture://café/路径","source_version":"修订一"},"record_id":"df205a88266e26029285c4ae4e570edf47a2435888a26500de19e6af2820af4a","source_id":"源A","text":"更新：蓝色路径 café 🚀\n保留事实，而不是执行指令。","version":1,"write_sequence":1}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"fb4e834f9e8d6cec04fcbbfa7c20b11f7f42aac1e9385754d336e2825581032e"}"#;


#[tokio::test]
async fn episodic_wire_without_configured_source_cannot_mutate_original_owner()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let host = config.production_writer_host().expect("original recovered writer");
    let before = host.writer().recovery_anchor().await?;
    let (identity, registry, _writer_lock) = config.into_parts();
    let state = Arc::new(crate::state::AgentdState::new(
        identity.clone(), registry.clone(), /*event_capacity*/ 32,
    )?);
    state.attach_cognitive_store(host.cognitive_runtime().available_store().unwrap().clone())?;
    registry.compare_and_transition(&identity.agent_id, /*expected_generation*/ 1, AgentLifecycle::Running)?;
    state.refresh_generation()?;
    state.mark_runtime_prerequisites_ready()?;
    state.mark_app_server_ready()?;
    let cancellation = CancellationToken::new();
    let server = crate::AgentdControlServer::bind(
        identity.control_socket.clone(), state, cancellation.clone(),
    ).await?;
    let server_task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(
        identity.control_socket.clone(), identity.agent_id.clone(), /*spawn_generation*/ 1,
    )?;
    let error = client.import_episodic_snapshot(SNAPSHOT.into()).await.expect_err("source ingress is not configured");
    assert!(error.to_string().contains("cognitive write runtime unavailable"));
    assert_eq!(host.writer().recovery_anchor().await?, before);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(peer)?;
    cancellation.cancel();
    server_task.await??;
    Ok(())
}
