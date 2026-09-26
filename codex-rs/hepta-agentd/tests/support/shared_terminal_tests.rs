#![allow(clippy::unwrap_used)]
use super::current_artifacts::Artifacts;
use super::*;

#[tokio::test]
async fn clean_agent_recall_replay_training_load_and_source_withdrawal() {
    use codex_hepta_agentd::AgentdSharedReplayHostV1;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_memory::CognitiveAccess;
    use codex_hepta_memory::CognitiveScope;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::FederationConsumerAccess;
    use codex_hepta_memory::LedgerSourceKind;
    use codex_hepta_memory::MemoryDraft;
    use codex_hepta_memory::MemoryLifecycleState;
    use codex_hepta_memory::MemoryRevisionDraft;
    use codex_hepta_memory::MemoryVerification;
    use codex_hepta_memory::SharedExperienceGrantV1;
    use codex_hepta_memory::SharedExperiencePurposeV1;
    use codex_hepta_memory::SourceDraft;
    use codex_hepta_paths::HeptaFleetRoot;
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
    let artifact_owner = Artifacts::open(&fixture.root.join("artifacts"), None);
    let host = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),
        consumer.clone(),
        "domain.terminal".into(),
        receiver_id.clone(),
    )
    .unwrap()
    .with_artifact_owner(
        Arc::clone(&artifact_owner.owner),
        artifact_owner.selector.clone(),
    );
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
            50
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
        host.train(recall.policy_id(), &ledger, &data, profile(1), 50)
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
        host.train(twin_use.policy_id(), &ledger, &data, profile(1), 50)
            .await,
        Err(codex_hepta_agentd::SharedTerminalCellError::Binding(
            "decision source support"
        ))
    ));
    // Replay-only: no Recall grant, but a real learner consumes source-bound owner
    // records, writes through the artifact owner, and loads the resulting bytes.
    assert!(source.revalidate_shared_experience(&recall).await.is_err());
    let candidate = host
        .train(replay.policy_id(), &ledger, &data, profile(1), 50)
        .await
        .unwrap();
    let payload = candidate.encode_payload().unwrap();
    assert!(!String::from_utf8_lossy(&payload).contains(&memory.content));
    super::shared_manifest_tests::rejects_mismatched_admitted_lineage(
        Arc::clone(&source),
        consumer.clone(),
        receiver_id.clone(),
        &ledger,
        &candidate,
        &fixture.root,
    )
    .await;
    let selection = artifact_owner.publish(candidate.artifact(), &payload);
    let selection_digest = artifact_owner
        .owner
        .lock()
        .unwrap()
        .persist_selected_descriptor(&artifact_owner.selector, &selection, 50)
        .unwrap();
    // A damaged descriptor never falls back to retraining.
    let descriptor_path = artifact_owner
        .root
        .join("transactions")
        .join(format!("{selection_digest}.selection"));
    let descriptor = std::fs::read(&descriptor_path).unwrap();
    std::fs::rename(&descriptor_path, descriptor_path.with_extension("offline")).unwrap();
    assert!(host.restore(&ledger, selection_digest, 50).await.is_err());
    std::fs::rename(descriptor_path.with_extension("offline"), &descriptor_path).unwrap();
    std::fs::write(&descriptor_path, &descriptor[..descriptor.len() - 1]).unwrap();
    assert!(host.restore(&ledger, selection_digest, 50).await.is_err());
    std::fs::write(&descriptor_path, &descriptor).unwrap();
    let mut model = host.load(&ledger, selection.clone(), 50).await.unwrap();
    let read = host
        .predict(
            &mut model,
            &ledger,
            &id("single-approved-state"),
            &id("read"),
            50,
        )
        .await
        .unwrap();
    let stop = host
        .predict(
            &mut model,
            &ledger,
            &id("single-approved-state"),
            &id("abstain"),
            50,
        )
        .await
        .unwrap();
    assert!(read.value > stop.value);
    assert_eq!(
        read.authority,
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );

    // Tampering with the descriptor and missing bundle bytes are not recovery fallbacks.
    let path = artifact_owner.payload_path(&selection);
    let mut tampered = payload.clone();
    tampered[0] ^= 1;
    std::fs::write(&path, tampered).unwrap();
    assert!(host.load(&ledger, selection.clone(), 50).await.is_err());
    std::fs::write(&path, &payload).unwrap();
    std::fs::rename(&path, path.with_extension("offline")).unwrap();
    assert!(host.load(&ledger, selection.clone(), 50).await.is_err());
    std::fs::rename(path.with_extension("offline"), &path).unwrap();

    let wrong_scope = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),
        consumer.clone(),
        "global.base".into(),
        receiver_id.clone(),
    )
    .unwrap()
    .with_artifact_owner(
        Arc::clone(&artifact_owner.owner),
        artifact_owner.selector.clone(),
    );
    assert!(
        wrong_scope
            .load(&ledger, selection.clone(), 50)
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
    .with_artifact_owner(
        Arc::clone(&artifact_owner.owner),
        artifact_owner.selector.clone(),
    );
    assert!(
        wrong_workspace
            .load(&ledger, selection.clone(), 50)
            .await
            .is_err()
    );
    drop(wrong_scope);
    drop(wrong_workspace);

    // Drop every training/runtime object and reopen the actual durable owners.
    // Restoring the selected bundle never calls train or fit.
    let frontier = ledger.witness_frontier().unwrap();
    let anchor = artifact_owner.head();
    let artifact_root = artifact_owner.root.clone();
    drop(model);
    drop(candidate);
    drop(host);
    drop(artifact_owner);
    drop(ledger);
    drop(source);
    let case_path = fixture.root.join("process-restore-case.json");
    let mut case = serde_json::json!({
        "ledger_root": fixture.root,
        "ledger_sequence": frontier.anchor.sequence,
        "ledger_head": frontier.anchor.chain_digest.to_string(),
        "artifact_root": artifact_root,
        "artifact_head": anchor.witness.head_digest.to_string(),
        "fleet_root": temp.path(),
        "owner_id": owner_id.as_str(),
        "receiver_id": receiver_id.as_str(),
        "workspace": consumer.workspace_sha256().as_str(),
        "selection_digest": selection_digest.to_string(),
        "value_raw": read.value.raw(),
    });
    std::fs::write(&case_path, serde_json::to_vec(&case).unwrap()).unwrap();
    super::shared_process_tests::child(&case_path, "success");
    super::shared_process_tests::child(&case_path, "trust-changed");
    let ledger = fixture.recover_writer(64, frontier);
    let source = Arc::new(CognitiveStore::open(&fleet.agent(&owner_id)).await.unwrap());
    let artifact_owner = Artifacts::open(&artifact_root, Some(anchor));
    let host = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),
        consumer.clone(),
        "domain.terminal".into(),
        receiver_id.clone(),
    )
    .unwrap()
    .with_artifact_owner(
        Arc::clone(&artifact_owner.owner),
        artifact_owner.selector.clone(),
    );
    let mut model = host.restore(&ledger, selection_digest, 50).await.unwrap();
    assert_eq!(
        host.predict(
            &mut model,
            &ledger,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await
        .unwrap(),
        read
    );

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
            &mut model,
            &ledger,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await
        .unwrap(),
        read
    );

    // The old signed view is genuinely valid, but is not live CURRENT after revocation.
    let stale_view = artifact_owner
        .owner
        .lock()
        .unwrap()
        .current_registry_view(50)
        .unwrap();
    let stale_registry = artifact_owner
        .owner
        .lock()
        .unwrap()
        .recover_current_registry(50)
        .unwrap();
    artifact_owner.revoke(&selection.artifact_id);
    assert!(stale_registry.is_eligible(&selection.artifact_id));
    assert!(
        artifact_owner
            .selector
            .verify(&selection, &stale_view, 50)
            .is_ok()
    );
    source.revalidate_shared_experience(&replay).await.unwrap();
    ledger.revalidate_dataset_snapshot(&data, 50).unwrap();
    assert!(matches!(
        host.predict(
            &mut model,
            &ledger,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await,
        Err(codex_hepta_agentd::SharedTerminalCellError::Binding(
            "current artifact selection"
        ))
    ));
    assert!(matches!(
        host.predict(
            &mut model,
            &ledger,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await,
        Err(codex_hepta_agentd::SharedTerminalCellError::Binding(
            "model consumer closed"
        ))
    ));
    assert!(host.load(&ledger, selection.clone(), 50).await.is_err());
    let newer_but_revoked = artifact_owner.select(&selection.artifact_id);
    assert!(host.load(&ledger, newer_but_revoked, 50).await.is_err());

    // A separately trained successor remains source-bound; source correction is
    // checked independently of registry revocation or a previously closed model.
    let next = host
        .train(replay.policy_id(), &ledger, &data, profile(2), 50)
        .await
        .unwrap();
    let next_selection = artifact_owner.publish(next.artifact(), &next.encode_payload().unwrap());
    let next_descriptor = artifact_owner
        .owner
        .lock()
        .unwrap()
        .persist_selected_descriptor(&artifact_owner.selector, &next_selection, 50)
        .unwrap();
    let mut current_model = host
        .load(&ledger, next_selection.clone(), 50)
        .await
        .unwrap();
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
    assert!(
        host.predict(
            &mut current_model,
            &ledger,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await
        .is_err()
    );
    assert!(host.load(&ledger, next_selection, 50).await.is_err());
    let final_head = artifact_owner.head();
    drop(current_model);
    drop(model);
    drop(host);
    drop(artifact_owner);
    drop(ledger);
    drop(source);
    case["artifact_head"] = serde_json::json!(final_head.witness.head_digest.to_string());
    std::fs::write(&case_path, serde_json::to_vec(&case).unwrap()).unwrap();
    super::shared_process_tests::child(&case_path, "selection-withdrawn");
    case["selection_digest"] = serde_json::json!(next_descriptor.to_string());
    std::fs::write(&case_path, serde_json::to_vec(&case).unwrap()).unwrap();
    super::shared_process_tests::child(&case_path, "source-withdrawn");
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
