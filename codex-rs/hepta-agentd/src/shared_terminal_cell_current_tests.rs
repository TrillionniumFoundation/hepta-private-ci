#![allow(
    clippy::unwrap_used,
    reason = "actual local Memory and ledger fixture assertions"
)]
use codex_hepta_agent_components::learning_artifacts as artifacts;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::FixedQ32;
use std::sync::Mutex;
#[path = "../tests/support/terminal_cell_model.rs"]
mod model_support;
#[path = "../tests/support/terminal_cell_owner.rs"]
mod support;
use model_support::collect_with_support;
use model_support::freeze;
use model_support::persist_reload;
use model_support::profile;
use support::Fixture;
use support::NOW;
use support::digest;
use support::id;
#[path = "shared_terminal_cell_current_test_source.rs"]
mod current_source;
use current_source::current_fixture;

#[tokio::test]
async fn clean_agent_recall_replay_training_load_and_source_withdrawal() {
    use crate::AgentdSharedReplayHostV1;
    use codex_hepta_agent_components::contracts::AgentId;
    use codex_hepta_agent_components::contracts::Sha256Digest;
    use codex_hepta_agent_components::memory::CognitiveAccess;
    use codex_hepta_agent_components::memory::CognitiveScope;
    use codex_hepta_agent_components::memory::CognitiveStore;
    use codex_hepta_agent_components::memory::FederationConsumerAccess;
    use codex_hepta_agent_components::memory::LedgerSourceKind;
    use codex_hepta_agent_components::memory::MemoryDraft;
    use codex_hepta_agent_components::memory::MemoryLifecycleState;
    use codex_hepta_agent_components::memory::MemoryRevisionDraft;
    use codex_hepta_agent_components::memory::MemoryVerification;
    use codex_hepta_agent_components::memory::SharedExperienceGrantV1;
    use codex_hepta_agent_components::memory::SharedExperiencePurposeV1;
    use codex_hepta_agent_components::memory::SourceDraft;
    use codex_hepta_agent_components::paths::HeptaFleetRoot;
    use std::sync::Arc;

    let temp = tempfile::tempdir().unwrap();
    let fleet = HeptaFleetRoot::parse(temp.path().to_path_buf())
        .unwrap()
        .layout();
    let owner_id = AgentId::parse("00000000-0000-4000-8000-000000000011").unwrap();
    let receiver_id = AgentId::parse("00000000-0000-4000-8000-000000000012").unwrap();
    let source = Arc::new(CognitiveStore::open(&fleet.agent(&owner_id)).await.unwrap());
    let receiver = CognitiveStore::open(&fleet.agent(&receiver_id))
        .await
        .unwrap();
    let access = CognitiveAccess::agent_private(owner_id.clone());
    let consumer = FederationConsumerAccess::new(
        receiver_id.clone(),
        Sha256Digest::for_bytes(b"clean-workspace"),
    );
    let citation = source
        .append_source(
            &access,
            &SourceDraft {
                scope: CognitiveScope::AgentPrivate,
                kind: LedgerSourceKind::PersistedToolResult,
                event_key: "tool.verified.training.support".into(),
                content: b"observed tool responses for one fixed approved state".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let memory = source
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "training.support".into(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "observed tool responses for one fixed approved state".into(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await
        .unwrap();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let initial_grant = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id.clone(),
        memory_revision: memory.id.revision,
        consumer: consumer.clone(),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now + 3600,
    };
    let initial_use = source
        .grant_shared_experience(&access, &initial_grant, 0)
        .await
        .unwrap();
    let support: Digest32 = initial_use
        .source_support_digest()
        .as_str()
        .parse()
        .unwrap();
    source
        .revoke_shared_experience(&access, &initial_use)
        .await
        .unwrap();
    let fixture = Fixture::new();
    let mut ledger = fixture.writer();
    collect_with_support(
        &mut ledger,
        "shared.read",
        "read",
        FixedQ32::ONE.raw(),
        support,
    );
    collect_with_support(&mut ledger, "shared.stop", "abstain", 0, support);
    let data = freeze(&ledger, "shared.dataset");
    let host = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),
        consumer.clone(),
        "domain.terminal".into(),
        receiver_id.clone(),
    )
    .unwrap();
    // No sharing: neither the receiver's store nor the training host gains input.
    assert!(
        receiver
            .latest_memory(
                &CognitiveAccess::agent_private(receiver_id.clone()),
                &memory.id.memory_id
            )
            .await
            .is_err()
    );
    assert!(
        host.train(
            &Sha256Digest::for_bytes(b"absent-policy"),
            &ledger,
            &data,
            profile(1),
            NOW
        )
        .await
        .is_err()
    );
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let recall_request = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id.clone(),
        memory_revision: memory.id.revision,
        consumer: consumer.clone(),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now + 3600,
    };
    let recall = source
        .grant_shared_experience(&access, &recall_request, 2)
        .await
        .unwrap();
    // Recall-only: readable evidence, no permission to train.
    assert_eq!(
        source
            .read_shared_experience(
                &consumer,
                recall.policy_id(),
                &SharedExperiencePurposeV1::Recall
            )
            .await
            .unwrap()
            .memory(),
        &memory
    );
    assert!(
        host.train(recall.policy_id(), &ledger, &data, profile(1), NOW)
            .await
            .is_err()
    );
    source
        .revoke_shared_experience(&access, &recall)
        .await
        .unwrap();
    let mut replay_request = recall_request.clone();
    replay_request.purpose = SharedExperiencePurposeV1::Replay {
        parameter_scope: "domain.terminal".into(),
        artifact_consumer: receiver_id.clone(),
    };
    let replay = source
        .grant_shared_experience(&access, &replay_request, 0)
        .await
        .unwrap();
    // Equal content under a different source ID cannot authorize these decisions.
    let twin = source
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "same-content.different-source".into(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: memory.content.clone(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await
        .unwrap();
    assert_eq!(twin.content_sha256, memory.content_sha256);
    let mut twin_request = replay_request.clone();
    twin_request.memory_id = twin.id.memory_id;
    let twin_use = source
        .grant_shared_experience(&access, &twin_request, 0)
        .await
        .unwrap();
    assert_ne!(
        twin_use.source_support_digest(),
        replay.source_support_digest()
    );
    assert!(matches!(
        host.train(twin_use.policy_id(), &ledger, &data, profile(1), NOW)
            .await,
        Err(crate::SharedTerminalCellError::Binding(
            "decision source support"
        ))
    ));
    // Replay-only: no Recall grant, but a real learner consumes source-bound owner
    // records, writes through the artifact owner, and loads the resulting bytes.
    assert!(source.revalidate_shared_experience(&recall).await.is_err());
    let candidate = host
        .train(replay.policy_id(), &ledger, &data, profile(1), NOW)
        .await
        .unwrap();
    let mut registry = artifacts::ArtifactRegistry::new();
    let _ = persist_reload(&fixture.root, &mut registry, candidate.artifact(), None);
    let payload = std::fs::read(fixture.root.join("payload-1")).unwrap();
    assert!(matches!(
        host.load(candidate.clone(), &ledger, &registry, &payload, NOW)
            .await,
        Err(crate::SharedTerminalCellError::Binding(
            "artifact CURRENT not configured"
        ))
    ));
    let live_registry = Arc::new(Mutex::new(registry.clone()));
    let host = host.with_current_artifacts(current_fixture(Arc::clone(&live_registry)));
    let model = host
        .load(candidate.clone(), &ledger, &registry, &payload, NOW)
        .await
        .unwrap();
    let read = host
        .predict(
            &model,
            &ledger,
            &registry,
            &id("single-approved-state"),
            &id("read"),
            NOW,
        )
        .await
        .unwrap();
    let stop = host
        .predict(
            &model,
            &ledger,
            &registry,
            &id("single-approved-state"),
            &id("abstain"),
            NOW,
        )
        .await
        .unwrap();
    assert!(read.value > stop.value);
    assert_eq!(
        read.authority,
        codex_hepta_agent_components::types::AuthorityPosture::DENY_ALL
    );
    let unavailable = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),
        consumer.clone(),
        "domain.terminal".into(),
        receiver_id.clone(),
    )
    .unwrap()
    .with_current_artifacts(crate::CurrentArtifactRegistrySourceV1::fixture(|_| {
        Err("protected CURRENT unavailable".into())
    }));
    assert!(matches!(
        unavailable
            .predict(
                &model,
                &ledger,
                &registry,
                &id("single-approved-state"),
                &id("read"),
                NOW
            )
            .await,
        Err(crate::SharedTerminalCellError::Binding(
            "artifact CURRENT unavailable"
        ))
    ));
    let mut tampered = payload.clone();
    tampered[0] ^= 1;
    assert!(
        host.load(candidate.clone(), &ledger, &registry, &tampered, NOW)
            .await
            .is_err()
    );
    let wrong_scope = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),
        consumer.clone(),
        "global.base".into(),
        receiver_id.clone(),
    )
    .unwrap();
    assert!(
        wrong_scope
            .train(replay.policy_id(), &ledger, &data, profile(1), NOW)
            .await
            .is_err()
    );
    let wrong_workspace = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),
        FederationConsumerAccess::new(
            receiver_id.clone(),
            Sha256Digest::for_bytes(b"other-workspace"),
        ),
        "domain.terminal".into(),
        receiver_id.clone(),
    )
    .unwrap()
    .with_current_artifacts(current_fixture(Arc::clone(&live_registry)));
    assert!(
        wrong_workspace
            .load(candidate.clone(), &ledger, &registry, &payload, NOW)
            .await
            .is_err()
    );
    // Both: enabling Recall changes evidence visibility, not stored model bytes.
    let combined_recall = source
        .grant_shared_experience(&access, &recall_request, 4)
        .await
        .unwrap();
    source
        .revalidate_shared_experience(&combined_recall)
        .await
        .unwrap();
    assert_eq!(
        host.predict(
            &model,
            &ledger,
            &registry,
            &id("single-approved-state"),
            &id("read"),
            NOW
        )
        .await
        .unwrap(),
        read
    );
    // Independent artifact withdrawal is enforced even while source permission
    // and dataset remain valid. This is not masked by a source-read rejection.
    let mut withdrawn = registry.clone();
    withdrawn
        .append(artifacts::ArtifactEvent::Revoke(artifacts::StateChange {
            event_id: id("independent.artifact.withdrawal"),
            artifact_id: candidate.artifact().artifact_id.clone(),
            evaluator_id: id("artifact-owner"),
            reason_digest: digest("artifact-review"),
        }))
        .unwrap();
    *live_registry.lock().unwrap() = withdrawn;
    // The caller keeps the original eligible snapshot and loaded bytes. Only
    // the separately authenticated CURRENT observes the later withdrawal.
    assert!(matches!(
        host.predict(
            &model,
            &ledger,
            &registry,
            &id("single-approved-state"),
            &id("read"),
            NOW
        )
        .await,
        Err(crate::SharedTerminalCellError::Binding(
            "artifact revoked or incompatible"
        ))
    ));
    assert!(matches!(
        host.load(candidate.clone(), &ledger, &registry, &payload, NOW)
            .await,
        Err(crate::SharedTerminalCellError::Binding(
            "artifact revoked or incompatible"
        ))
    ));

    // A source correction blocks even an already-loaded model before another use.
    source
        .correct_memory(
            &access,
            &memory.id.memory_id,
            1,
            &MemoryRevisionDraft {
                scope: CognitiveScope::AgentPrivate,
                content: "support withdrawn after independent review".into(),
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 100,
                valid_to_unix_seconds: None,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    assert!(matches!(
        host.predict(
            &model,
            &ledger,
            &registry,
            &id("single-approved-state"),
            &id("read"),
            NOW
        )
        .await,
        Err(crate::SharedTerminalCellError::Source(_))
    ));
    assert!(matches!(
        host.load(candidate.clone(), &ledger, &registry, &payload, NOW)
            .await,
        Err(crate::SharedTerminalCellError::Source(_))
    ));
    registry
        .append(artifacts::ArtifactEvent::Revoke(artifacts::StateChange {
            event_id: id("source.withdrawal"),
            artifact_id: candidate.artifact().artifact_id.clone(),
            evaluator_id: id("source-owner"),
            reason_digest: digest("source-correction"),
        }))
        .unwrap();
    assert!(!registry.is_eligible(&candidate.artifact().artifact_id));
    assert!(
        receiver
            .latest_memory(
                &CognitiveAccess::agent_private(receiver_id),
                &memory.id.memory_id
            )
            .await
            .is_err()
    );
}
