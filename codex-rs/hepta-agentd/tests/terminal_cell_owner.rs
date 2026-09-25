use codex_hepta_bellman_operator::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use codex_hepta_learning_artifacts as artifacts;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use std::fs::File;

#[path = "support/terminal_cell_owner.rs"]
mod support;
use support::Fixture;
use support::decision;
use support::digest;
use support::id;
use support::outcome;
use support::sign;

fn collect(owner: &mut LedgerWriter, prefix: &str, selected: &str, value: i64) {
    collect_with_support(owner, prefix, selected, value, decision().support_digest);
}

fn collect_with_support(
    owner: &mut LedgerWriter,
    prefix: &str,
    selected: &str,
    value: i64,
    support_digest: Digest32,
) {
    let mut request = decision();
    request.support_digest = support_digest;
    request.record_id = id(&format!("{prefix}.decision"));
    request.episode_id = id(&format!("{prefix}.episode"));
    request.selected_candidate_id = id(selected);
    let signed = sign(
        owner.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let predecessor = owner.witness_frontier().unwrap().anchor.chain_digest;
    let receipt = owner
        .append_decision(predecessor, request, &signed, 50)
        .unwrap();
    let mut observed = outcome(
        &format!("{prefix}.result-record"),
        &format!("{prefix}.result"),
        None,
        value,
    );
    observed.episode_id = id(&format!("{prefix}.episode"));
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    owner
        .append_outcome(receipt.chain_digest, observed, &signed, 50)
        .unwrap();
}

fn freeze(owner: &LedgerWriter, name: &str) -> DatasetSnapshotReceiptV3 {
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id(name),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("all-active-owner-episodes"),
    };
    let payload = dataset_freeze_signing_payload_v2(&owner.snapshot().unwrap(), &plan).unwrap();
    let signed = sign(
        owner.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    owner.freeze_dataset(plan, &signed, 50).unwrap()
}

fn profile(generation: u64) -> TerminalCellProfileV1 {
    TerminalCellProfileV1 {
        artifact_id: id(&format!("local.cell.generation.{generation}")),
        producer_id: id("operator.native.owner"),
        generation: Generation::new(generation).unwrap(),
        sensor_id: id("single-approved-state"),
        objective_digest: digest("objective"),
        run_snapshot_digest: digest("run-snapshot"),
        unit_profile_digest: digest("reward-units"),
        action_ids: vec![id("abstain"), id("read")],
        minimum_samples_per_action: 1,
    }
}

fn persist_reload(
    root: &std::path::Path,
    registry: &mut artifacts::ArtifactRegistry,
    trained: &TabularOperatorArtifactV1,
    predecessor: Option<StableId>,
) -> LoadedTabularOperatorV1 {
    let bytes = encode_tabular_payload_v1(trained).unwrap();
    let manifest = artifacts::ArtifactManifest {
        artifact_id: trained.artifact_id.clone(),
        kind: artifacts::ArtifactKind::Policy,
        generation: trained.generation,
        predecessor_id: predecessor,
        content_digest: Digest32::of_bytes(&bytes),
        objective_digest: trained.objective_digest,
        support_digest: trained.dataset_digest,
        producer_id: trained.producer_id.clone(),
        compatibility_digest: trained.training_profile_digest,
        encoded_size_bytes: bytes.len() as u64,
    };
    registry
        .append(artifacts::ArtifactEvent::Register {
            event_id: id(&format!("register.{}", trained.generation.get())),
            manifest: manifest.clone(),
        })
        .unwrap();
    let payload = root.join(format!("payload-{}", trained.generation.get()));
    let snapshot = root.join(format!("registry-{}", trained.generation.get()));
    artifacts::write_candidate_payload(
        artifacts::CreateOnlyArtifactFile::create(&payload).unwrap(),
        registry,
        &manifest.artifact_id,
        &bytes,
    )
    .unwrap();
    let receipt = artifacts::write_registry_snapshot(
        artifacts::CreateOnlyArtifactFile::create(&snapshot).unwrap(),
        registry,
        digest("host-artifact-binding"),
    )
    .unwrap();
    let retained = artifacts::PinnedCandidateSpec {
        registry_receipt: receipt,
        manifest,
    };
    let loaded = artifacts::load_pinned_candidate(
        File::open(snapshot).unwrap(),
        File::open(payload).unwrap(),
        retained,
    )
    .unwrap();
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: trained.artifact_digest,
        objective_digest: trained.objective_digest,
        dataset_digest: trained.dataset_digest,
        sensor_core_digest: trained.sensor_core_digest,
        training_profile_digest: trained.training_profile_digest,
        generation: trained.generation,
    };
    LoadedTabularOperatorV1::from_pinned_payload(loaded.bytes(), &pin).unwrap()
}

#[test]
fn real_owner_decision_outcome_freeze_fit_registry_reload_and_withdrawal() {
    let fixture = Fixture::new();
    let mut owner = fixture.writer();
    collect(&mut owner, "initial-a", "read", 0);
    collect(&mut owner, "initial-stop", "abstain", 0);
    let initial = freeze(&owner, "dataset.initial");
    let frozen = freeze_terminal_cell_from_owner_v1(&owner, &initial, profile(1), 50).unwrap();
    assert_eq!(frozen.sample_count(), 2);
    let trained = fit_terminal_cell_from_owner_v1(&owner, frozen, 50).unwrap();
    let mut registry = artifacts::ArtifactRegistry::new();
    let first = persist_reload(&fixture.root, &mut registry, &trained, None);
    for index in 0..5 {
        collect(
            &mut owner,
            &format!("learn-{index}-a"),
            "read",
            FixedQ32::ONE.raw(),
        );
        collect(&mut owner, &format!("learn-{index}-stop"), "abstain", 0);
    }
    let next = freeze(&owner, "dataset.next");
    assert_eq!(
        freeze_terminal_cell_from_owner_v1(&owner, &initial, profile(2), 50)
            .unwrap()
            .sample_count(),
        2,
        "new observations do not silently enter the old immutable dataset"
    );
    let pending = freeze_terminal_cell_from_owner_v1(&owner, &next, profile(2), 50).unwrap();
    let trained_next = fit_terminal_cell_from_owner_v1(&owner, pending.clone(), 50).unwrap();
    let second = persist_reload(
        &fixture.root,
        &mut registry,
        &trained_next,
        Some(trained.artifact_id.clone()),
    );
    let sensor = id("single-approved-state");
    let read = id("read");
    let abstain = id("abstain");
    assert_eq!(
        first.predict(&sensor, &read).unwrap().value,
        FixedQ32::ZERO,
        "loaded predecessor was not mutated"
    );
    assert!(
        second.predict(&sensor, &read).unwrap().value
            > second.predict(&sensor, &abstain).unwrap().value
    );
    assert!(
        !second
            .predict(&sensor, &read)
            .unwrap()
            .authority
            .grants_any()
    );
    // Fresh independent observer episodes, not training targets supplied by fit.
    let evaluation = Fixture::new();
    let mut evaluator = evaluation.writer();
    collect(&mut evaluator, "held-out-a", "read", FixedQ32::ONE.raw());
    collect(&mut evaluator, "held-out-stop", "abstain", 0);
    let heldout = freeze(&evaluator, "dataset.heldout");
    let target = fit_terminal_cell_from_owner_v1(
        &evaluator,
        freeze_terminal_cell_from_owner_v1(&evaluator, &heldout, profile(3), 50).unwrap(),
        50,
    )
    .unwrap();
    assert!(
        target
            .cells
            .iter()
            .find(|cell| cell.action_id == read)
            .unwrap()
            .mean_target
            > target
                .cells
                .iter()
                .find(|cell| cell.action_id == abstain)
                .unwrap()
                .mean_target
    );
    let squared_error = |model: &LoadedTabularOperatorV1| -> u128 {
        target
            .cells
            .iter()
            .map(|cell| {
                let estimate = model
                    .predict(&cell.sensor_id, &cell.action_id)
                    .unwrap()
                    .value
                    .raw();
                let delta = i128::from(estimate) - i128::from(cell.mean_target.raw());
                delta.unsigned_abs().pow(2)
            })
            .sum()
    };
    assert!(
        squared_error(&second) < squared_error(&first),
        "the independently frozen held-out observations must favor the trained candidate"
    );

    // A real authenticated correction invalidates the frozen training cut.
    let mut correction = outcome(
        "correction.record",
        "correction.result",
        Some("learn-0-a.result"),
        0,
    );
    correction.episode_id = id("learn-0-a.episode");
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&correction),
    );
    let head = owner.witness_frontier().unwrap().anchor.chain_digest;
    owner.append_outcome(head, correction, &signed, 50).unwrap();
    assert!(fit_terminal_cell_from_owner_v1(&owner, pending, 50).is_err());
    registry
        .append(artifacts::ArtifactEvent::Revoke(artifacts::StateChange {
            event_id: id("revoke.contaminated-parent"),
            artifact_id: trained.artifact_id,
            evaluator_id: id("independent.dataset-owner"),
            reason_digest: digest("source-withdrawal"),
        }))
        .unwrap();
    assert!(
        !registry.is_eligible(&trained_next.artifact_id),
        "withdrawal propagates through candidate lineage"
    );
}

#[test]
#[ignore = "explicit local-host history/concurrent training profile, not an SLO"]
fn durable_owner_history_and_concurrent_training_profile() {
    use std::time::Instant;
    for (agents, pairs) in [(1, 32), (1, 128), (1, 512), (4, 128)] {
        let started = Instant::now();
        let reports = std::thread::scope(|scope| {
            let jobs=(0..agents).map(|agent| scope.spawn(move || {
                let fixture=Fixture::new();let mut writer=fixture.writer_with_limit(4096);
                let mut append_latencies=Vec::new();
                for index in 0..pairs {
                    let t=Instant::now();
                    collect(&mut writer,&format!("profile-{agent}-{index}"),if index%2==0 { "read" } else { "abstain" },if index%2==0 { FixedQ32::ONE.raw() } else { 0 });
                    append_latencies.push(t.elapsed().as_micros());
                }
                let t=Instant::now();
                let data=freeze(&writer,&format!("profile.dataset.{agent}"));
                let frozen=freeze_terminal_cell_from_owner_v1(&writer,&data,profile(1),50).unwrap();
                let trained=fit_terminal_cell_from_owner_v1(&writer,frozen,50).unwrap();
                let mut registry=artifacts::ArtifactRegistry::new();
                let loaded=persist_reload(&fixture.root,&mut registry,&trained,None);
                assert!(loaded.predict(&id("single-approved-state"),&id("read")).is_ok());
                let fit_and_reload_us=t.elapsed().as_micros();
                let cut=writer.witness_frontier().unwrap();drop(writer);
                let bytes=std::fs::metadata(fixture.root.join("ledger")).unwrap().len();
                let t=Instant::now();let recovered=fixture.recover_writer(4096,cut);let recovery_us=t.elapsed().as_micros();
                assert_eq!(recovered.witness_frontier().unwrap().anchor.sequence, (pairs*2) as u64);
                let t=Instant::now();assert_eq!(recovered.read_dataset_records(&data,50).unwrap().len(),pairs*2);let page_us=t.elapsed().as_micros();
                append_latencies.sort_unstable();
                format!("OWNER_HISTORY_PROFILE agents={agents} agent={agent} records={} ledger_bytes={bytes} decision_outcome_p50_us={} p95_us={} p99_us={} fit_registry_reload_us={fit_and_reload_us} full_recovery_us={recovery_us} indexed_dataset_read_us={page_us} recovery_profile=complete_authenticated_history not_cold_compaction=true",pairs*2,append_latencies[pairs/2],append_latencies[(pairs*95/100).min(pairs-1)],append_latencies[(pairs*99/100).min(pairs-1)])
            })).collect::<Vec<_>>();
            jobs.into_iter()
                .map(|job| job.join().unwrap())
                .collect::<Vec<_>>()
        });
        for report in reports {
            println!("{report}");
        }
        println!(
            "OWNER_HISTORY_GROUP agents={agents} records_per_owner={} elapsed_ms={}",
            pairs * 2,
            started.elapsed().as_millis()
        );
    }
}

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
    let mut registry = artifacts::ArtifactRegistry::new();
    let _ = persist_reload(&fixture.root, &mut registry, candidate.artifact(), None);
    let payload = std::fs::read(fixture.root.join("payload-1")).unwrap();
    let model = host
        .load(candidate.clone(), &ledger, &registry, &payload, 50)
        .await
        .unwrap();
    let read = host
        .predict(
            &model,
            &ledger,
            &registry,
            &id("single-approved-state"),
            &id("read"),
            50,
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
            50,
        )
        .await
        .unwrap();
    assert!(read.value > stop.value);
    assert_eq!(
        read.authority,
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );
    let mut tampered = payload.clone();
    tampered[0] ^= 1;
    assert!(
        host.load(candidate.clone(), &ledger, &registry, &tampered, 50)
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
            .train(replay.policy_id(), &ledger, &data, profile(1), 50)
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
    .unwrap();
    assert!(
        wrong_workspace
            .load(candidate.clone(), &ledger, &registry, &payload, 50)
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
            50
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
    assert!(matches!(
        host.predict(
            &model,
            &ledger,
            &withdrawn,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await,
        Err(codex_hepta_agentd::SharedTerminalCellError::Binding(
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
    assert!(
        host.predict(
            &model,
            &ledger,
            &registry,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await
        .is_err()
    );
    assert!(
        host.load(candidate.clone(), &ledger, &registry, &payload, 50)
            .await
            .is_err()
    );
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
