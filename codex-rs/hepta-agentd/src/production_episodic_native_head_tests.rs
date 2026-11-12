//! A native owner withdrawal must close dependent episodic reads.
//! This is an owner/socket regression, not a model-benefit experiment.
use std::collections::BTreeMap;
use std::error::Error;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::Ordering;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::EpisodicRecordAdmission;
use codex_hepta_memory::EpisodicSnapshotAdmission;
use codex_hepta_memory::EpisodicSnapshotVerifier;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory::StableMemoryId;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::Fixture;
use super::FixtureSource;
use super::assert_no_issuer_request;
use super::attach_production_operation_host;

// Existing memory INITIAL fixture, preserving its explicit dependency.
const DEPENDENT_SNAPSHOT: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":3,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"9da1fafe5fde75bec5c885139496d8a5efd1c5f4dacfd6802304e546be30a8e7","source_uri":"fixture://route","source_version":"1"},"record_id":"d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f","source_id":"source-a","text":"Use route blue.","version":1,"write_sequence":1},{"dependencies":["d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f"],"key":"derived","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"2a4fbbdb68f1ad47b4a1a4e6e92e8a53ed259cefa076e2d30fe99aa975d01180","source_uri":"fixture://derived","source_version":"1"},"record_id":"cb489b504f4b7e981c8ef505d2927ae89071fe961709c30950acb727cb8afb51","source_id":"source-b","text":"The route evidence says blue.","version":1,"write_sequence":2},{"dependencies":[],"key":"unrelated","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"1160510952698f0c61ba4864a9ab4fcbf7c2c4039971c602816a93d4faea8bfd","source_uri":"fixture://unrelated","source_version":"1"},"record_id":"329bae60950e23696c7caa7ef873d0625e5735ce4161bc5a52e4e9a7dad1d8c7","source_id":"source-c","text":"Use flow gamma.","version":1,"write_sequence":3}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"bb189d0445231bbfa748f26e039f909fa0fe654fb59d08cad8b3e2ecbf9056e8"}"#;

#[tokio::test]
async fn native_predecessor_forget_closes_episodic_context() -> Result<(), Box<dyn Error>> {
    let value: serde_json::Value = serde_json::from_str(DEPENDENT_SNAPSHOT)?;
    let records = value["body"]["records"]
        .as_array()
        .ok_or("fixture records required")?
        .iter()
        .map(|record| {
            let id = record["record_id"].as_str().expect("record id");
            (
                id.to_owned(),
                EpisodicRecordAdmission {
                    source: SourceDraft {
                        scope: CognitiveScope::AgentPrivate,
                        kind: LedgerSourceKind::FileObservation,
                        event_key: id.to_owned(),
                        content: record["text"].as_str().expect("text").as_bytes().to_vec(),
                        observed_at_unix_seconds: 1,
                    },
                    verification: MemoryVerification::Verified,
                },
            )
        })
        .collect::<BTreeMap<_, _>>();
    let source = Arc::new(FixtureSource(
        Mutex::new((
            DEPENDENT_SNAPSHOT.to_owned(),
            EpisodicSnapshotAdmission {
                records,
                withdrawal: None,
            },
        )),
        Mutex::new(None),
    ));
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let host = config.production_writer_host().expect("original writer");
    let mut config =
        config.with_episodic_snapshot_import("bridge-fixture".into(), source.clone())?;
    let ingress = config
        .take_episodic_snapshot_import()
        .expect("source ingress");
    let (identity, registry, _writer_lock) = config.into_parts();
    let state = Arc::new(crate::state::AgentdState::new(
        identity.clone(),
        registry.clone(),
        /*event_capacity*/ 32,
    )?);
    state.attach_cognitive_store(host.cognitive_runtime().available_store().unwrap().clone())?;
    state
        .episodic_snapshot_import
        .set(ingress)
        .ok()
        .expect("single owner");
    registry.compare_and_transition(
        &identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.mark_runtime_prerequisites_ready()?;
    state.mark_app_server_ready()?;
    let cancellation = CancellationToken::new();
    let server = crate::AgentdControlServer::bind(
        identity.control_socket.clone(),
        state,
        cancellation.clone(),
    )
    .await?;
    let server_task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        /*spawn_generation*/ 1,
    )?;
    let imported = client
        .import_episodic_snapshot(DEPENDENT_SNAPSHOT.to_owned())
        .await?;
    assert_eq!((imported.active_records, imported.retired_records), (3, 0));
    let before = client
        .cognitive_context("route".into(), /*limit*/ 4)
        .await?;
    let predecessor = before
        .items
        .iter()
        .find(|item| item.content == "Use route blue.")
        .ok_or("predecessor positive control required")?;
    assert!(
        before
            .items
            .iter()
            .any(|item| item.content == "The route evidence says blue.")
    );
    let child_only = client
        .cognitive_context("evidence".into(), /*limit*/ 1)
        .await?;
    assert_eq!(child_only.items.len(), 1);
    assert_eq!(child_only.items[0].content, "The route evidence says blue.");
    assert_eq!(
        client
            .revalidate_cognitive_context(&child_only)
            .await?
            .verified_item_count,
        1
    );
    let access = CognitiveAccess::agent_private(identity.agent_id.clone());
    let source_event = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "native-owner-withdraws-episodic-predecessor".into(),
        content: b"Withdraw the route assertion.".to_vec(),
        observed_at_unix_seconds: 2,
    };
    let withdrawn = host
        .forget_with_kg(
            &access,
            &StableMemoryId::parse(&predecessor.memory_id)?,
            predecessor.revision,
            &source_event,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "Withdraw the route assertion.".into(),
                valid_from_unix_seconds: 2,
                citations: Vec::new(),
            },
        )
        .await?;
    assert_eq!(withdrawn.write.memory.id.revision, predecessor.revision + 1);
    let cut = host.writer().recovery_anchor().await?;
    // The source verifier itself has not changed; the original native writer
    // has validly withdrawn a prerequisite of the committed source mapping.
    assert!(source.verify_current(DEPENDENT_SNAPSHOT).is_ok());
    let next = crate::AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        /*spawn_generation*/ 1,
    )?;
    let after = next
        .cognitive_context("route evidence".into(), /*limit*/ 4)
        .await;
    let revalidation = next.revalidate_cognitive_context(&child_only).await;
    assert_eq!(host.writer().recovery_anchor().await?, cut);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(peer)?;
    cancellation.cancel();
    server_task.await??;
    for (operation, result) in [
        ("fresh context", after.map(|_| ())),
        ("retained child-only context", revalidation.map(|_| ())),
    ] {
        match result {
            Err(crate::AgentdError::Protocol(message)) => assert!(
                message.contains("canonical episodic head changed outside the bridge"),
                "{operation} failed for another reason: {message}",
            ),
            other => panic!("{operation} did not reject the original native head drift: {other:?}"),
        }
    }
    Ok(())
}
