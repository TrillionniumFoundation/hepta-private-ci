//! Controlled port-boundary tests, not neural training or independent efficacy.
//! The real SmolLM driver is exercised separately with pinned model material.

use std::path::PathBuf;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;

use super::*;

const PARAMETERS: &[u8] = b"CONTROLLED PORT DOUBLE; NOT MODEL WEIGHTS";

fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}
fn id(text: &str) -> StableId {
    StableId::new(text).unwrap()
}
fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap()
}
fn pin() -> NeuralCognitivePinV1 {
    NeuralCognitivePinV1 {
        payload_digest: Digest32::of_bytes(PARAMETERS),
        objective_digest: digest("controlled-neural-objective"),
        dataset_digest: digest("controlled-neural-dataset"),
        generation: Generation::new(1).unwrap(),
        family_digest: digest("controlled-port-family"),
        execution_profile_digest: digest("controlled-port-execution"),
    }
}

struct Port {
    calls: AtomicUsize,
    corrupt: usize,
}
impl NeuralCognitiveInferencePortV1 for Port {
    fn execute(
        &self,
        request: &NeuralCognitiveRequestV1,
        parameters: &[u8],
        _execution: &NeuralCognitiveExecutionV1,
    ) -> Result<NeuralCognitiveObservationV1, String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        assert_eq!(parameters, PARAMETERS);
        assert_eq!(request.owner_id, owner());
        assert_eq!(request.body_generation, 1);
        assert_eq!(request.query, "lemon");
        assert_eq!(request.query_digest, digest("lemon"));
        let mut observed = NeuralCognitiveObservationV1 {
            request: request.clone(),
            scores_q32: Some((0..request.action_ids.len()).map(|n| n as i64).collect()),
            execution_receipt_digest: digest("controlled-port-observation"),
            authority: AuthorityPosture::DENY_ALL,
        };
        match self.corrupt {
            0 => {}
            1 => observed.request.query = "substituted query".to_owned(),
            2 => observed.request.pin.payload_digest = digest("other weights"),
            3 => observed.request.action_ids.reverse(),
            4 => observed.scores_q32 = Some(vec![]),
            5 => observed.execution_receipt_digest = Digest32::ZERO,
            6 => observed.request.pin.execution_profile_digest = digest("other profile"),
            7 => {
                observed.request.owner_id =
                    AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap()
            }
            8 => observed.request.body_generation += 1,
            _ => observed.scores_q32 = None,
        }
        Ok(observed)
    }
}

struct Current {
    snapshot: PathBuf,
    receipt: RegistrySnapshotReceipt,
}
impl CurrentCognitiveRegistry for Current {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        verified_fixture_current_view(
            File::open(&self.snapshot).map_err(|error| error.to_string())?,
            self.receipt,
            Digest32::ZERO,
        )
    }
}

fn fixture(port: Arc<Port>) -> (tempfile::TempDir, Arc<PinnedCognitiveRanker>) {
    let directory = tempfile::tempdir().unwrap();
    let pin = pin();
    let manifest = ArtifactManifest {
        artifact_id: id("controlled-neural-parameters"),
        kind: ArtifactKind::Parameters,
        generation: pin.generation,
        predecessor_id: None,
        content_digest: pin.payload_digest,
        objective_digest: pin.objective_digest,
        support_digest: pin.dataset_digest,
        producer_id: id("controlled-port-test"),
        compatibility_digest: pin.execution_profile_digest,
        encoded_size_bytes: PARAMETERS.len() as u64,
    };
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register"),
            manifest: manifest.clone(),
        })
        .unwrap();
    let payload = directory.path().join("parameters");
    write_candidate_payload(
        CreateOnlyArtifactFile::create(&payload).unwrap(),
        &registry,
        &manifest.artifact_id,
        PARAMETERS,
    )
    .unwrap();
    let snapshot = directory.path().join("snapshot");
    let registry_receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot).unwrap(),
        &registry,
        digest("controlled-neural-registry"),
    )
    .unwrap();
    let current = Arc::new(Current {
        snapshot: snapshot.clone(),
        receipt: registry_receipt,
    });
    let loaded = load_pinned_candidate(
        File::open(snapshot).unwrap(),
        File::open(payload).unwrap(),
        PinnedCandidateSpec {
            registry_receipt,
            manifest,
        },
    )
    .unwrap();
    let current_owner_trust_digest = current.current().unwrap().trust_digest();
    let ranker = PinnedCognitiveRanker {
        owner: owner(),
        body_generation: 1,
        policy_digest: pin.payload_digest,
        model: CognitiveRankModel::Neural(NeuralCognitiveModelV1 {
            pin,
            parameters: loaded.bytes().to_vec(),
            inference: port,
        }),
        current,
        current_owner_trust_digest,
        // Only this private test fixture bypasses product qualification. The
        // public neural constructor has no HostPinned compatibility path.
        admission: RankerEvaluationAdmission::HostPinned,
        source_window: None,
        cache: Mutex::new(Some(RevalidatingCandidate::new(loaded))),
    };
    (directory, Arc::new(ranker))
}

#[test]
fn substituted_owner_body_query_weights_profile_actions_or_partial_scores_close_before_reordering()
{
    for corrupt in 1..=8 {
        let port = Arc::new(Port {
            calls: AtomicUsize::new(0),
            corrupt,
        });
        let (_directory, ranker) = fixture(port.clone());
        let mut items = ["first", "second"].map(|name| CognitiveContextItem {
            memory_id: name.to_owned(),
            revision: 1,
            content: String::new(),
            content_sha256: digest(name).to_string(),
        });
        let before = items.clone();
        assert!(ranker.rank(&owner(), 1, "lemon", &mut items).is_err());
        assert_eq!(items, before);
        assert!(ranker.rank(&owner(), 1, "lemon", &mut items).is_err());
        assert_eq!(port.calls.load(Ordering::SeqCst), 1);
    }
}

#[tokio::test]
async fn ordinary_sqlite_read_uses_neural_port_before_result_limit() {
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
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(fleet.canonicalize().unwrap())
        .unwrap()
        .layout()
        .agent(&owner());
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner());
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: CognitiveScope::AgentPrivate,
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "neural-port-source".to_owned(),
                content: b"verified lemon orchard descriptions".to_vec(),
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
                    stable_key: name.to_owned(),
                    revision: MemoryRevisionDraft {
                        scope: CognitiveScope::AgentPrivate,
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
    }
    let baseline = crate::cognitive_context::read(&store, &owner(), 1, "lemon", 4, None)
        .await
        .unwrap();
    let port = Arc::new(Port {
        calls: AtomicUsize::new(0),
        corrupt: 0,
    });
    let (_artifact_directory, ranker) = fixture(port.clone());
    let actual = crate::cognitive_context::read(&store, &owner(), 1, "lemon", 1, Some(&ranker))
        .await
        .unwrap();
    assert_eq!(actual.items, vec![baseline.items[1].clone()]);
    assert_eq!(port.calls.load(Ordering::SeqCst), 1);
    assert!(actual.plan.unwrap().read_allowed);
}


#[test]
fn expired_or_cancelled_read_at_current_boundaries_never_publishes_late_ranking() {
    struct GatedCurrent {
        inner: Arc<dyn CurrentCognitiveRegistry>,
        started: std::sync::mpsc::Sender<()>,
        release: Mutex<std::sync::mpsc::Receiver<()>>,
        calls: AtomicUsize,
        gate_at: usize,
    }
    impl CurrentCognitiveRegistry for GatedCurrent {
        fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
            if self.calls.fetch_add(1, Ordering::SeqCst) == self.gate_at {
                self.started.send(()).map_err(|error| error.to_string())?;
                self.release.lock().map_err(|error| error.to_string())?
                    .recv_timeout(std::time::Duration::from_secs(4)).map_err(|error| error.to_string())?;
            }
            self.inner.current()
        }
    }
    for (cancel, gate_at) in [(false, 0), (true, 0), (false, 1), (true, 1)] {
        let port = Arc::new(Port { calls: AtomicUsize::new(0), corrupt: 0 });
        let (_directory, ranker) = fixture(port.clone());
        let mut ranker = Arc::try_unwrap(ranker).ok().unwrap();
        let (started_tx, started_rx) = std::sync::mpsc::channel();
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        ranker.current = Arc::new(GatedCurrent { inner: ranker.current.clone(), started: started_tx, release: Mutex::new(release_rx), calls: AtomicUsize::new(0), gate_at });
        let token = tokio_util::sync::CancellationToken::new();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
        let execution = NeuralCognitiveExecutionV1::with_deadline(deadline, token.clone());
        let worker = std::thread::spawn(move || {
            let mut items = ["first", "second"].map(|name| CognitiveContextItem { memory_id: name.to_owned(), revision: 1, content: String::new(), content_sha256: digest(name).to_string() });
            let before = items.clone();
            assert!(ranker.rank_with_execution(&owner(), 1, "lemon", &mut items, &execution).is_err());
            assert_eq!(items, before);
        });
        started_rx.recv_timeout(std::time::Duration::from_secs(1)).unwrap();
        if cancel { token.cancel(); } else { std::thread::sleep(deadline.saturating_duration_since(std::time::Instant::now()) + std::time::Duration::from_millis(1)); }
        release_tx.send(()).unwrap();
        worker.join().unwrap();
        assert_eq!(port.calls.load(Ordering::SeqCst), gate_at);
    }
}

#[test]
fn cancelled_blocking_queue_keeps_original_execution_window() {
    let runtime = tokio::runtime::Builder::new_multi_thread().worker_threads(1).max_blocking_threads(1).enable_all().build().unwrap();
    let port = Arc::new(Port { calls: AtomicUsize::new(0), corrupt: 0 });
    let (_directory, ranker) = fixture(port.clone());
    let (started_tx, started_rx) = std::sync::mpsc::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let occupied = runtime.spawn_blocking(move || { started_tx.send(()).unwrap(); release_rx.recv_timeout(std::time::Duration::from_secs(2)).unwrap(); });
    started_rx.recv_timeout(std::time::Duration::from_secs(1)).unwrap();
    let cancellation = tokio_util::sync::CancellationToken::new();
    let execution = NeuralCognitiveExecutionV1::with_deadline(std::time::Instant::now() + std::time::Duration::from_secs(2), cancellation.clone());
    let queued = runtime.spawn_blocking(move || {
        ranker.rank_with_execution(&owner(), 1, "lemon", &mut [], &execution)
    });
    cancellation.cancel();
    release_tx.send(()).unwrap();
    runtime.block_on(occupied).unwrap();
    assert!(runtime.block_on(queued).unwrap().is_err());
    assert_eq!(port.calls.load(Ordering::SeqCst), 0);
}
