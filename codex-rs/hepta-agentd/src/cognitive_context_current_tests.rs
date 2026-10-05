//! Real SQLite and signed CURRENT barriers at both final owner boundaries.

use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_strict_v2;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
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
use codex_hepta_memory::SourceRevisionId;
use codex_hepta_memory::StableMemoryId;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextSnapshot;
use crate::CurrentCognitiveRegistry;
use crate::PinnedCognitiveRanker;
use crate::cognitive_action_id;
use crate::cognitive_ranker::verified_fixture_current_view;
use crate::cognitive_sensor_id;

const BARRIER_TIMEOUT: Duration = Duration::from_secs(10);

fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap()
}

struct BlockingCurrent {
    snapshot: PathBuf,
    receipt: RegistrySnapshotReceipt,
    calls: AtomicUsize,
    block_on_call: AtomicUsize,
    entered: mpsc::Sender<usize>,
    release: Mutex<mpsc::Receiver<()>>,
}

impl CurrentCognitiveRegistry for BlockingCurrent {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        if call == self.block_on_call.load(Ordering::SeqCst) {
            self.entered.send(call).map_err(|error| error.to_string())?;
            self.release
                .lock()
                .map_err(|error| error.to_string())?
                .recv_timeout(BARRIER_TIMEOUT)
                .map_err(|error| error.to_string())?;
        }
        // Only scheduling is controlled: CURRENT verification, files, receipt,
        // signature and the ranker's native selected payload remain real.
        verified_fixture_current_view(
            File::open(&self.snapshot).map_err(|error| error.to_string())?,
            self.receipt,
            Digest32::ZERO,
        )
    }
}

struct RankerFixture {
    _directory: tempfile::TempDir,
    view: Arc<BlockingCurrent>,
    ranker: Arc<PinnedCognitiveRanker>,
    entered: Option<mpsc::Receiver<usize>>,
    release: mpsc::Sender<()>,
}

impl RankerFixture {
    fn arm_on_current_call(&self, call: usize) {
        self.view.calls.store(0, Ordering::SeqCst);
        self.view.block_on_call.store(call, Ordering::SeqCst);
    }

    async fn wait_until_blocked(&mut self, expected_call: usize) {
        let entered = self.entered.take().unwrap();
        let actual = tokio::task::spawn_blocking(move || entered.recv_timeout(BARRIER_TIMEOUT))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(actual, expected_call);
    }
}

fn ranker_fixture(items: &[CognitiveContextItem], scores: &[i64]) -> RankerFixture {
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
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let view = Arc::new(BlockingCurrent {
        snapshot: snapshot.clone(),
        receipt: registry_receipt,
        calls: AtomicUsize::new(0),
        block_on_call: AtomicUsize::new(0),
        entered: entered_tx,
        release: Mutex::new(release_rx),
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
    RankerFixture {
        _directory: directory,
        view,
        ranker,
        entered: Some(entered_rx),
        release: release_tx,
    }
}

struct MemoryFixture {
    _directory: tempfile::TempDir,
    store: Arc<CognitiveStore>,
    access: CognitiveAccess,
    citation: SourceRevisionId,
    memory_ids: Vec<StableMemoryId>,
    baseline: CognitiveContextSnapshot,
}

async fn memory_fixture() -> MemoryFixture {
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(fleet.canonicalize().unwrap())
        .unwrap()
        .layout()
        .agent(&owner());
    let store = Arc::new(CognitiveStore::open(&layout).await.unwrap());
    let access = CognitiveAccess::agent_private(owner());
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: CognitiveScope::AgentPrivate,
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "current-barrier-source".to_string(),
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
        memory_ids.push(memory.id.memory_id);
    }
    let baseline = super::read(&store, &owner(), 1, "lemon", 2, None)
        .await
        .unwrap();
    assert_eq!(baseline.items.len(), 2);
    MemoryFixture {
        _directory: directory,
        store,
        access,
        citation,
        memory_ids,
        baseline,
    }
}

impl MemoryFixture {
    async fn forget(&self, item: &CognitiveContextItem) {
        let memory_id = self
            .memory_ids
            .iter()
            .find(|memory_id| memory_id.as_str() == item.memory_id)
            .unwrap();
        tokio::time::timeout(
            BARRIER_TIMEOUT,
            self.store.forget_memory(
                &self.access,
                memory_id,
                1,
                &ForgetMemoryDraft {
                    scope: CognitiveScope::AgentPrivate,
                    reason: "withdrawn during signed CURRENT verification".to_string(),
                    valid_from_unix_seconds: 200,
                    citations: vec![self.citation.clone()],
                },
            ),
        )
        .await
        .unwrap()
        .unwrap();
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn final_use_rechecks_sqlite_owner_after_signed_current_provider_wait() {
    let memory = memory_fixture().await;
    let mut native = ranker_fixture(&memory.baseline.items, &[0, 10]);
    let context = super::read(&memory.store, &owner(), 1, "lemon", 1, Some(&native.ranker))
        .await
        .unwrap();
    assert_eq!(context.items, vec![memory.baseline.items[1].clone()]);
    let selected = context.items[0].clone();
    native.arm_on_current_call(1);
    let store = Arc::clone(&memory.store);
    let ranker = Arc::clone(&native.ranker);
    let validation = tokio::spawn(async move {
        super::revalidate(
            &store,
            &owner(),
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            context.plan.as_ref(),
            Some(&ranker),
        )
        .await
    });
    native.wait_until_blocked(1).await;
    memory.forget(&selected).await;
    native.release.send(()).unwrap();
    let result = tokio::time::timeout(BARRIER_TIMEOUT, validation)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(native.view.calls.load(Ordering::SeqCst), 1);
    assert!(
        matches!(result, Err(super::CognitiveContextError::Store(_))),
        "final use must reject a committed tombstone after CURRENT finishes"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn read_rechecks_sqlite_owner_after_second_signed_current_provider_wait() {
    let memory = memory_fixture().await;
    let mut native = ranker_fixture(&memory.baseline.items, &[0, 10]);
    // First CURRENT ranks the candidate set; second CURRENT is the existing
    // read-bottom model check after the owner cut was already revalidated.
    native.arm_on_current_call(2);
    let store = Arc::clone(&memory.store);
    let ranker = Arc::clone(&native.ranker);
    let reading =
        tokio::spawn(
            async move { super::read(&store, &owner(), 1, "lemon", 1, Some(&ranker)).await },
        );
    native.wait_until_blocked(2).await;
    memory.forget(&memory.baseline.items[1]).await;
    native.release.send(()).unwrap();
    let result = tokio::time::timeout(BARRIER_TIMEOUT, reading)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(native.view.calls.load(Ordering::SeqCst), 2);
    assert!(
        matches!(result, Err(super::CognitiveContextError::Store(_))),
        "read must reject a committed tombstone after its final CURRENT check"
    );
}
