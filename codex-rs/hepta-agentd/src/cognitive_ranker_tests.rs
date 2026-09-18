use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc::Receiver;
use std::sync::mpsc::Sender;
use std::time::Duration;

use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_strict_v2;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

use super::*;

fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap()
}
fn item(name: &str) -> CognitiveContextItem {
    CognitiveContextItem {
        memory_id: name.to_string(),
        revision: 1,
        content: format!("lemon {name}"),
        content_sha256: hash(name).to_string(),
    }
}

struct ViewGate {
    calls: AtomicUsize,
    block_on_call: usize,
    entered: Sender<()>,
    release: Mutex<Receiver<()>>,
}

struct View {
    current: Mutex<Option<(PathBuf, RegistrySnapshotReceipt)>>,
    gate: Option<ViewGate>,
}

impl CurrentCognitiveRegistry for View {
    fn current(&self) -> Result<(File, RegistrySnapshotReceipt), String> {
        if let Some(gate) = &self.gate
            && gate.calls.fetch_add(1, Ordering::SeqCst) == gate.block_on_call
        {
            gate.entered.send(()).map_err(|error| error.to_string())?;
            gate.release
                .lock()
                .map_err(|_| "current-view gate lock poisoned".to_string())?
                .recv()
                .map_err(|error| error.to_string())?;
        }
        let view = self
            .current
            .lock()
            .map_err(|_| "current-view lock poisoned".to_string())?;
        let (path, receipt) = view.as_ref().ok_or("independent witness unavailable")?;
        Ok((
            File::open(path).map_err(|error| error.to_string())?,
            *receipt,
        ))
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    registry: ArtifactRegistry,
    view: Arc<View>,
    ranker: Arc<PinnedCognitiveRanker>,
}

fn fixture(items: &[CognitiveContextItem], scores: &[i64]) -> Fixture {
    fixture_with_gate(items, scores, None)
}

fn fixture_with_gate(
    items: &[CognitiveContextItem],
    scores: &[i64],
    gate: Option<ViewGate>,
) -> Fixture {
    let directory = tempfile::tempdir().unwrap();
    let sensor = cognitive_sensor_id("lemon").unwrap();
    let actions: Vec<_> = items
        .iter()
        .map(|value| cognitive_action_id(value).unwrap())
        .collect();
    // Measured task benefits are deliberately not claimed: these bounded samples
    // test whether a fitted, stored model reaches the actual read consumer.
    let model = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id("read-ranker"),
        producer_id: id("fixture-trainer"),
        generation: Generation::new(1).unwrap(),
        objective_digest: hash("read-ranking-task"),
        dataset_digest: hash("fixture-dataset"),
        sensor_core_digest: hash("exact-query-revision-v1"),
        training_profile_digest: hash("strict-table-v1"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![sensor.clone()],
        action_ids: actions.clone(),
        samples: actions
            .iter()
            .zip(scores)
            .enumerate()
            .flat_map(|(index, (action, score))| {
                let sensor = sensor.clone();
                [0, 1].map(move |replicate| TabularOperatorSampleV1 {
                    sample_id: id(&format!("sample-{index}-{replicate}")),
                    sensor_id: sensor.clone(),
                    action_id: action.clone(),
                    target: FixedQ32::from_raw(*score),
                    evidence_digest: hash(&format!("observed-{index}-{replicate}")),
                })
            })
            .collect(),
    })
    .unwrap();
    let bytes = encode_tabular_payload_v1(&model).unwrap();
    let model_pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: model.artifact_digest,
        objective_digest: model.objective_digest,
        dataset_digest: model.dataset_digest,
        sensor_core_digest: model.sensor_core_digest,
        training_profile_digest: model.training_profile_digest,
        generation: model.generation,
    };
    let manifest = ArtifactManifest {
        artifact_id: model.artifact_id,
        kind: ArtifactKind::Policy,
        generation: model.generation,
        predecessor_id: None,
        content_digest: model_pin.payload_digest,
        objective_digest: model_pin.objective_digest,
        support_digest: model_pin.dataset_digest,
        producer_id: id("fixture-trainer"),
        compatibility_digest: hash("ranker-consumer-v1"),
        encoded_size_bytes: bytes.len() as u64,
    };
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register"),
            manifest: manifest.clone(),
        })
        .unwrap();
    let payload = directory.path().join("payload");
    write_candidate_payload(
        CreateOnlyArtifactFile::create(&payload).unwrap(),
        &registry,
        &manifest.artifact_id,
        &bytes,
    )
    .unwrap();
    let snapshot = directory.path().join("snapshot");
    let registry_receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot).unwrap(),
        &registry,
        hash("fixture-host-binding"),
    )
    .unwrap();
    let view = Arc::new(View {
        current: Mutex::new(Some((snapshot.clone(), registry_receipt))),
        gate,
    });
    let ranker = Arc::new(
        PinnedCognitiveRanker::load(
            owner(),
            1,
            File::open(snapshot).unwrap(),
            File::open(payload).unwrap(),
            PinnedCandidateSpec {
                registry_receipt,
                manifest,
            },
            model_pin,
            view.clone(),
        )
        .unwrap(),
    );
    Fixture {
        directory,
        registry,
        view,
        ranker,
    }
}

#[test]
fn current_loaded_model_changes_read_order_and_abstains_on_unseen_or_corrected_records() {
    let original = vec![item("one"), item("two")];
    let fixture = fixture(&original, &[0, 10]);
    let mut ranked = original.clone();
    fixture
        .ranker
        .rank(&owner(), 1, "lemon", &mut ranked)
        .unwrap();
    assert_eq!(ranked, vec![original[1].clone(), original[0].clone()]);
    for query in ["unseen", "lemon"] {
        let mut unknown = original.clone();
        if query == "lemon" {
            unknown[0].revision = 2;
        }
        let before = unknown.clone();
        fixture
            .ranker
            .rank(&owner(), 1, query, &mut unknown)
            .unwrap();
        assert_eq!(unknown, before);
    }
    assert!(
        fixture
            .ranker
            .rank(&owner(), 2, "lemon", &mut ranked)
            .is_err()
    );
    let foreign = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(
        fixture
            .ranker
            .rank(&foreign, 1, "lemon", &mut ranked)
            .is_err()
    );
}

#[test]
fn missing_or_revoked_current_witness_closes_ranker_without_baseline_fallback() {
    for revoked in [false, true] {
        let mut items = vec![item("one"), item("two")];
        let mut fixture = fixture(&items, &[0, 10]);
        let original_view = fixture.view.current.lock().unwrap().clone();
        if revoked {
            fixture
                .registry
                .append(ArtifactEvent::Revoke(StateChange {
                    event_id: id("revoke"),
                    artifact_id: id("read-ranker"),
                    evaluator_id: id("independent-fixture-evaluator"),
                    reason_digest: hash("withdrawn"),
                }))
                .unwrap();
            let path = fixture.directory.path().join("revoked");
            let receipt = write_registry_snapshot(
                CreateOnlyArtifactFile::create(&path).unwrap(),
                &fixture.registry,
                hash("fixture-host-binding"),
            )
            .unwrap();
            *fixture.view.current.lock().unwrap() = Some((path, receipt));
        } else {
            *fixture.view.current.lock().unwrap() = None;
        }
        let original = items.clone();
        assert!(
            fixture
                .ranker
                .rank(&owner(), 1, "lemon", &mut items)
                .is_err()
        );
        assert_eq!(items, original);
        *fixture.view.current.lock().unwrap() = original_view;
        assert!(
            fixture
                .ranker
                .rank(&owner(), 1, "lemon", &mut items)
                .is_err()
        );
    }
}

#[tokio::test]
async fn sqlite_read_consumer_uses_fitted_order_before_limit_and_rechecks_deletion() {
    use codex_hepta_memory::CognitiveAccess;
    use codex_hepta_memory::CognitiveScope;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::ForgetMemoryDraft;
    use codex_hepta_memory::LedgerSourceKind;
    use codex_hepta_memory::MemoryDraft;
    use codex_hepta_memory::MemoryLifecycleState;
    use codex_hepta_memory::MemoryRevisionDraft;
    use codex_hepta_memory::MemoryVerification;
    use codex_hepta_memory::SourceDraft;
    use codex_hepta_paths::HeptaFleetRoot;

    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(fleet)
        .unwrap()
        .layout()
        .agent(&owner());
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "ranking-source".to_string(),
                content: b"verified lemon orchard descriptions".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let mut memory_ids = Vec::new();
    for name in ["alpha", "beta"] {
        let memory = store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: name.to_string(),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content: format!("verified lemon orchard {name}"),
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
        memory_ids.push(memory.id.memory_id);
    }
    let baseline = crate::cognitive_context::read(&store, &owner(), 1, 2, "lemon", 4, None)
        .await
        .unwrap();
    assert_eq!(baseline.items.len(), 2);
    let fixture = fixture(&baseline.items, &[0, 10]);
    let ranked =
        crate::cognitive_context::read(&store, &owner(), 1, 2, "lemon", 1, Some(&fixture.ranker))
            .await
            .unwrap();
    assert_eq!(ranked.items, vec![baseline.items[1].clone()]);
    assert!(ranked.plan.as_ref().unwrap().read_allowed);
    // The read owner, not the learned ranker, remains authoritative on deletion.
    let selected_id = memory_ids
        .into_iter()
        .find(|value| value.as_str() == ranked.items[0].memory_id)
        .unwrap();
    store
        .forget_memory(
            &access,
            &selected_id,
            1,
            &ForgetMemoryDraft {
                scope,
                reason: "withdrawn".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    let after =
        crate::cognitive_context::read(&store, &owner(), 1, 2, "lemon", 1, Some(&fixture.ranker))
            .await
            .unwrap();
    assert_eq!(after.items, vec![baseline.items[0].clone()]);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lifecycle_revocation_during_context_read_fails_closed_before_control_delivery() {
    use codex_hepta_fleet::AgentLifecycle;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_memory::CognitiveAccess;
    use codex_hepta_memory::CognitiveScope;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::LedgerSourceKind;
    use codex_hepta_memory::MemoryDraft;
    use codex_hepta_memory::MemoryLifecycleState;
    use codex_hepta_memory::MemoryRevisionDraft;
    use codex_hepta_memory::MemoryVerification;
    use codex_hepta_memory::SourceDraft;
    use codex_hepta_paths::HeptaFleetRoot;

    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
    let lifecycle = FleetRegistry::initialize(fleet_root.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let record = lifecycle
        .register(
            AgentManifest::new(
                owner(),
                WorkspaceBinding::new(workspace.clone(), &fleet_root).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    lifecycle
        .compare_and_transition(&owner(), 0, AgentLifecycle::Starting)
        .unwrap();
    let config = crate::AgentdConfig::load(
        fleet_path,
        owner(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .unwrap();
    let store = Arc::new(CognitiveStore::open(&record.layout).await.unwrap());
    let access = CognitiveAccess::agent_private(owner());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "lifecycle-race-source".to_string(),
                content: b"verified lemon lifecycle evidence".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    for name in ["alpha", "beta"] {
        store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: format!("lifecycle-{name}"),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content: format!("verified lemon lifecycle {name}"),
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
    }
    let baseline =
        crate::cognitive_context::read(&store, &owner(), 1, 2, "lemon", 4, None)
            .await
            .unwrap();

    let (entered_tx, entered_rx) = std::sync::mpsc::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let fixture = fixture_with_gate(
        &baseline.items,
        &[0, 10],
        Some(ViewGate {
            calls: AtomicUsize::new(0),
            block_on_call: 1,
            entered: entered_tx,
            release: Mutex::new(release_rx),
        }),
    );
    let config = config
        .with_cognitive_ranker(Arc::clone(&fixture.ranker))
        .unwrap();
    let attached_ranker = config.cognitive_ranker().unwrap();
    let (identity, registry, _writer_lock) = config.into_parts();
    let state = Arc::new(crate::AgentdState::new(identity, registry, 16).unwrap());
    state.attach_cognitive_store(Arc::clone(&store)).unwrap();
    assert!(state.cognitive_ranker.set(attached_ranker).is_ok());
    lifecycle
        .compare_and_transition(&owner(), 1, AgentLifecycle::Running)
        .unwrap();
    state.refresh_generation().unwrap();
    state.mark_app_server_ready().unwrap();

    let read_state = Arc::clone(&state);
    let read_task = tokio::spawn(async move {
        read_state
            .response(
                700,
                1,
                crate::AgentdMethod::CognitiveContext {
                    query: "lemon".to_string(),
                    limit: 1,
                },
            )
            .await
    });

    let entered = tokio::task::spawn_blocking(move || {
        entered_rx.recv_timeout(Duration::from_secs(5))
    })
    .await
    .unwrap();
    if let Err(error) = entered {
        drop(release_tx.send(()));
        panic!("wait for authoritative read gate: {error}");
    }

    lifecycle
        .compare_and_transition(&owner(), 2, AgentLifecycle::Draining)
        .unwrap();
    release_tx.send(()).unwrap();

    let result = read_task.await.unwrap();
    assert!(matches!(
        result,
        Err(crate::AgentdError::Protocol(message))
            if message.contains("unavailable until this Agent generation is ready")
    ));
}

/// Exercises the actual control socket and lifecycle transition. This is not a
/// provider/App Server startup test or an independent task-benefit experiment.
#[tokio::test]
async fn running_socket_uses_launch_bound_model_and_isolates_ranker_revocation() {
    use codex_hepta_fleet::AgentLifecycle;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_memory::CognitiveAccess;
    use codex_hepta_memory::CognitiveScope;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::ForgetMemoryDraft;
    use codex_hepta_memory::LedgerSourceKind;
    use codex_hepta_memory::MemoryDraft;
    use codex_hepta_memory::MemoryLifecycleState;
    use codex_hepta_memory::MemoryRevisionDraft;
    use codex_hepta_memory::MemoryVerification;
    use codex_hepta_memory::SourceDraft;
    use codex_hepta_paths::HeptaFleetRoot;
    use tokio_util::sync::CancellationToken;

    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
    let lifecycle = FleetRegistry::initialize(fleet_root.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let record = lifecycle
        .register(
            AgentManifest::new(
                owner(),
                WorkspaceBinding::new(workspace.clone(), &fleet_root).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    lifecycle
        .compare_and_transition(&owner(), 0, AgentLifecycle::Starting)
        .unwrap();
    let config = crate::AgentdConfig::load(
        fleet_path,
        owner(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .unwrap();
    let store = Arc::new(CognitiveStore::open(&record.layout).await.unwrap());
    let access = CognitiveAccess::agent_private(owner());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "socket-ranking-source".to_string(),
                content: b"verified lemon orchard descriptions".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let mut memories = Vec::new();
    for name in ["alpha", "beta"] {
        memories.push(
            store
                .remember_memory(
                    &access,
                    &MemoryDraft {
                        stable_key: name.to_string(),
                        revision: MemoryRevisionDraft {
                            scope: scope.clone(),
                            content: format!("verified lemon orchard {name}"),
                            verification: MemoryVerification::Verified,
                            lifecycle: MemoryLifecycleState::Active,
                            valid_from_unix_seconds: 100,
                            valid_to_unix_seconds: None,
                            citations: vec![citation.clone()],
                        },
                    },
                )
                .await
                .unwrap(),
        );
    }
    let baseline = crate::cognitive_context::read(&store, &owner(), 1, 2, "lemon", 4, None)
        .await
        .unwrap();
    assert_eq!(baseline.items.len(), 2);
    let retained = crate::cognitive_context::read(&store, &owner(), 1, 2, "orchard", 4, None)
        .await
        .unwrap();
    let mut fixture = fixture(&baseline.items, &[0, 10]);
    let config = config
        .with_cognitive_ranker(Arc::clone(&fixture.ranker))
        .unwrap();
    let attached_ranker = config.cognitive_ranker().unwrap();
    let (identity, registry, _writer_lock) = config.into_parts();
    let socket = identity.control_socket.clone();
    let state = Arc::new(crate::AgentdState::new(identity, registry, 16).unwrap());
    state.attach_cognitive_store(Arc::clone(&store)).unwrap();
    assert!(state.cognitive_ranker.set(attached_ranker).is_ok());
    // Running is lifecycle generation 2, while this body's identity is still 1.
    lifecycle
        .compare_and_transition(&owner(), 1, AgentLifecycle::Running)
        .unwrap();
    state.mark_app_server_ready().unwrap();
    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let server =
        crate::AgentdControlServer::bind(socket.clone(), Arc::clone(&state), cancellation.clone())
            .await
            .unwrap();
    let task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(socket.clone(), owner(), 1).unwrap();
    assert!(
        crate::AgentdClient::new(socket, owner(), 2)
            .unwrap()
            .cognitive_context("lemon".to_string(), 1)
            .await
            .is_err(),
        "lifecycle epoch must not become a substitute launch identity"
    );
    assert!(client.health().await.unwrap().ready);
    let ranked = client
        .cognitive_context("lemon".to_string(), 1)
        .await
        .unwrap();
    assert_eq!(ranked.items, vec![baseline.items[1].clone()]);
    assert!(ranked.plan.as_ref().unwrap().read_allowed);
    assert_eq!(
        client
            .cognitive_context("orchard".to_string(), 4)
            .await
            .unwrap()
            .items,
        retained.items,
        "unsupported query keeps its previous admitted order"
    );
    let selected = memories
        .iter()
        .find(|memory| memory.id.memory_id.as_str() == ranked.items[0].memory_id)
        .unwrap();
    store
        .forget_memory(
            &access,
            &selected.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope,
                reason: "withdrawn".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    assert_eq!(
        client
            .cognitive_context("lemon".to_string(), 1)
            .await
            .unwrap()
            .items,
        vec![baseline.items[0].clone()]
    );
    fixture
        .registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("socket-revoke"),
            artifact_id: id("read-ranker"),
            evaluator_id: id("independent-fixture-evaluator"),
            reason_digest: hash("withdrawn-model-support"),
        }))
        .unwrap();
    let revoked = fixture.directory.path().join("socket-revoked");
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&revoked).unwrap(),
        &fixture.registry,
        hash("fixture-host-binding"),
    )
    .unwrap();
    *fixture.view.current.lock().unwrap() = Some((revoked, receipt));
    for _ in 0..2 {
        assert!(
            client
                .cognitive_context("lemon".to_string(), 1)
                .await
                .is_err(),
            "revocation closes the ranked read without baseline fallback"
        );
    }
    let other_port = state
        .response(
            100,
            1,
            crate::AgentdMethod::MemoryFederationList { limit: 4 },
        )
        .await
        .unwrap();
    assert_eq!(other_port.spawn_generation, 1);
    assert_eq!(other_port.current_generation, 2);
    assert_eq!(
        other_port.payload,
        crate::AgentdPayload::MemoryFederationCapabilities {
            capabilities: Vec::new(),
        },
        "an optional ranker failure must not detach the canonical SQLite store"
    );
    cancellation.cancel();
    tokio::time::timeout(std::time::Duration::from_secs(2), task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
}
