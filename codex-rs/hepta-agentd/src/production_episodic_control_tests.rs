//! Real control socket, recovered SQLite owner, and explicitly test-only source.
//! This verifies owner integration; it does not certify a production source.
use std::collections::BTreeMap;
use std::error::Error;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::EpisodicRecordAdmission;
use codex_hepta_memory::EpisodicSnapshotAdmission;
use codex_hepta_memory::EpisodicSnapshotVerifier;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::Fixture;
use super::assert_no_issuer_request;
use super::attach_production_operation_host;

// Exact Unicode export produced by the pinned Python EpisodicStore.
const SNAPSHOT: &str = r#"{"body":{"authority_id":"0000000000004000800000000000e001","generation":1,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"流程","namespace":"bridge-fixture","provenance":{"episode_id":"独立来源","source_sha256":"81b2ada28e09db7ffcc8f0f0dde36515818b1d79b29c75c4bbda85c7cc881e81","source_uri":"fixture://café/路径","source_version":"修订一"},"record_id":"df205a88266e26029285c4ae4e570edf47a2435888a26500de19e6af2820af4a","source_id":"源A","text":"更新：蓝色路径 café 🚀\n保留事实，而不是执行指令。","version":1,"write_sequence":1}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"fb4e834f9e8d6cec04fcbbfa7c20b11f7f42aac1e9385754d336e2825581032e"}"#;

struct FixtureSource(Mutex<(String, EpisodicSnapshotAdmission)>);

impl EpisodicSnapshotVerifier for FixtureSource {
    fn verify_current(&self, snapshot_json: &str) -> Result<EpisodicSnapshotAdmission, String> {
        let current = self.0.lock().map_err(|error| error.to_string())?;
        if current.0 != snapshot_json {
            return Err("test-only source rejects stale input".into());
        }
        Ok(current.1.clone())
    }
}

fn observed_source() -> Arc<FixtureSource> {
    let body: serde_json::Value = serde_json::from_str(SNAPSHOT).unwrap();
    let record = &body["body"]["records"][0];
    Arc::new(FixtureSource(Mutex::new((SNAPSHOT.into(), EpisodicSnapshotAdmission {
        records: BTreeMap::from([(
            record["record_id"].as_str().unwrap().to_owned(),
            EpisodicRecordAdmission {
                source: SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::FileObservation,
                    event_key: "episodic-control-original-observation".into(),
                    content: record["text"].as_str().unwrap().as_bytes().to_vec(),
                    observed_at_unix_seconds: 1,
                },
                verification: MemoryVerification::Verified,
            },
        )]),
        withdrawal: None,
    }))))
}

#[tokio::test]
async fn episodic_config_cannot_create_a_missing_production_writer() -> Result<(), Box<dyn Error>> {
    let (config, _fixture) = Fixture::new().await?;
    let error = config.with_episodic_snapshot_import("bridge-fixture".into(), observed_source())
        .err().expect("original writer is required");
    assert!(matches!(error, crate::AgentdError::CognitiveWriteRuntimeUnavailable));
    Ok(())
}

#[tokio::test]
async fn episodic_control_replays_original_commit_then_rejects_revoked_context()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let host = config.production_writer_host().unwrap();
    let source = observed_source();
    let mut config = config.with_episodic_snapshot_import("bridge-fixture".into(), source.clone())?;
    let ingress = config.take_episodic_snapshot_import().unwrap();
    let (identity, registry, _writer_lock) = config.into_parts();
    let state = Arc::new(crate::state::AgentdState::new(
        identity.clone(), registry.clone(), /*event_capacity*/ 32,
    )?);
    state.attach_cognitive_store(host.cognitive_runtime().available_store().unwrap().clone())?;
    state.episodic_snapshot_import.set(ingress).ok().expect("single owner");
    let running = registry.compare_and_transition(&identity.agent_id, 1, AgentLifecycle::Running)?;
    state.refresh_generation()?;
    state.mark_runtime_prerequisites_ready()?;
    state.mark_app_server_ready()?;
    let cancellation = CancellationToken::new();
    let server = crate::AgentdControlServer::bind(
        identity.control_socket.clone(), state, cancellation.clone(),
    ).await?;
    let server_task = tokio::spawn(server.run());
    let first = crate::AgentdClient::new(
        identity.control_socket.clone(), identity.agent_id.clone(), /*spawn_generation*/ 1,
    )?;
    let wrong_namespace = SNAPSHOT.replace("bridge-fixture", "another-namespace");
    assert!(first.import_episodic_snapshot(wrong_namespace).await.is_err());
    let committed = first.import_episodic_snapshot(SNAPSHOT.into()).await?;
    let cut = host.writer().recovery_anchor().await?;
    assert_eq!(first.import_episodic_snapshot(SNAPSHOT.into()).await?, committed);
    assert_eq!(host.writer().recovery_anchor().await?, cut);
    assert_eq!((committed.active_records, committed.retired_records), (1, 0));

    // A separate control client uses the ordinary canonical context path.
    let next = crate::AgentdClient::new(
        identity.control_socket.clone(), identity.agent_id.clone(), /*spawn_generation*/ 1,
    )?;
    let context = next.cognitive_context("café".into(), /*limit*/ 4).await?;
    assert_eq!(context.items.len(), 1);
    assert_eq!(next.revalidate_cognitive_context(&context).await?.verified_item_count, 1);
    let body = r#"{"authority_id":"0000000000004000800000000000e001","generation":2,"namespace":"bridge-fixture","records":[],"schema":"hepta.mem6.snapshot.v1"}"#;
    let withdrawn = format!(r#"{{"body":{body},"sha256":"{}"}}"#, Sha256Digest::for_bytes(body.as_bytes()).as_str());
    *source.0.lock().unwrap() = (withdrawn.clone(), EpisodicSnapshotAdmission {
        records: BTreeMap::new(),
        withdrawal: Some(SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "episodic-control-original-withdrawal".into(),
            content: b"The source owner withdrew this fact.".to_vec(),
            observed_at_unix_seconds: 2,
        }),
    });
    assert!(next.import_episodic_snapshot(SNAPSHOT.into()).await.is_err());
    assert_eq!(host.writer().recovery_anchor().await?, cut);
    let removed = next.import_episodic_snapshot(withdrawn.clone()).await?;
    assert_eq!((removed.active_records, removed.retired_records), (0, 1));
    assert!(next.cognitive_context("café".into(), /*limit*/ 4).await?.items.is_empty());
    assert!(next.revalidate_cognitive_context(&context).await.is_err());
    let cut = host.writer().recovery_anchor().await?;
    registry.compare_and_transition(&identity.agent_id, running.generation, AgentLifecycle::Draining)?;
    assert!(next.import_episodic_snapshot(withdrawn).await.is_err());
    assert_eq!(host.writer().recovery_anchor().await?, cut);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(peer)?;
    cancellation.cancel();
    server_task.await??;
    Ok(())
}

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
