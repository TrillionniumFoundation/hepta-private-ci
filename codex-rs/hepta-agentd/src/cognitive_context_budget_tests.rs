//! Real SQLite and stored-model regressions for post-ranking response budgets.
//! Training scores and current-registry witnesses are explicit test fixtures,
//! not independent task-benefit or production-authorization evidence.

use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_strict_v2;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::super::MAX_CONTEXT_JSON_BYTES;
use super::*;
use crate::CognitiveContextItem;
use crate::CurrentCognitiveRegistry;
use crate::PinnedCognitiveRanker;
use crate::cognitive_action_id;
use crate::cognitive_sensor_id;

struct CurrentView {
    path: PathBuf,
    receipt: RegistrySnapshotReceipt,
}

impl CurrentCognitiveRegistry for CurrentView {
    fn current(&self) -> Result<(File, RegistrySnapshotReceipt), String> {
        Ok((
            File::open(&self.path).map_err(|error| error.to_string())?,
            self.receipt,
        ))
    }
}

struct RankerFixture {
    _directory: tempfile::TempDir,
    ranker: Arc<PinnedCognitiveRanker>,
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fitted_ranker(owner: AgentId, items: &[CognitiveContextItem], scores: &[i64]) -> RankerFixture {
    assert_eq!(items.len(), scores.len());
    let directory = tempfile::tempdir().unwrap();
    let sensor = cognitive_sensor_id("lemon").unwrap();
    let actions: Vec<_> = items
        .iter()
        .map(cognitive_action_id)
        .collect::<Result<_, _>>()
        .unwrap();
    let model = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id("budget-ranker"),
        producer_id: id("fixture-trainer"),
        generation: Generation::new(/*value*/ 1).unwrap(),
        objective_digest: hash("budgeted-context"),
        dataset_digest: hash("synthetic-budget-samples"),
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
                    evidence_digest: hash(&format!("fixture-{index}-{replicate}")),
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
            event_id: id("register-budget-ranker"),
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
    let current = Arc::new(CurrentView {
        path: snapshot.clone(),
        receipt: registry_receipt,
    });
    let ranker = Arc::new(
        PinnedCognitiveRanker::load(
            owner,
            /*body_generation*/ 1,
            File::open(snapshot).unwrap(),
            File::open(payload).unwrap(),
            PinnedCandidateSpec {
                registry_receipt,
                manifest,
            },
            model_pin,
            current,
        )
        .unwrap(),
    );
    RankerFixture {
        _directory: directory,
        ranker,
    }
}

async fn stored_candidates(
    contents: Vec<String>,
) -> (
    tempfile::TempDir,
    CognitiveStore,
    AgentId,
    Vec<CognitiveContextItem>,
) {
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "budget-test-source".to_string(),
                content: b"fixture lemon descriptions".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let expected_count = contents.len();
    for (index, content) in contents.into_iter().enumerate() {
        store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: format!("record-{index}"),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content,
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
    let batch = store
        .retrieve_memory_candidates(
            &access,
            &RetrievalRequest::new("lemon", /*now_unix_seconds*/ 100),
        )
        .await
        .unwrap();
    let items: Vec<_> = batch
        .candidates
        .into_iter()
        .map(|candidate| {
            let memory = candidate.memory;
            CognitiveContextItem {
                memory_id: memory.id.memory_id.as_str().to_string(),
                revision: memory.id.revision,
                content: memory.content,
                content_sha256: memory.content_sha256.as_str().to_string(),
            }
        })
        .collect();
    assert_eq!(items.len(), expected_count);
    (directory, store, owner, items)
}

fn escaping_contents() -> Vec<String> {
    (0..4)
        .map(|index| format!("lemon {index} {}", "\\\"".repeat(/*n*/ 1700)))
        .collect()
}

#[tokio::test]
async fn learned_winner_survives_legacy_byte_cut_and_response_stays_bounded() {
    let (_directory, store, owner, items) = stored_candidates(escaping_contents()).await;
    let baseline = read(
        &store,
        &owner,
        /*body_generation*/ 1,
        /*authority_epoch*/ 2,
        "lemon",
        /*limit*/ 4,
        /*ranker*/ None,
    )
    .await
    .unwrap();
    let winner = items.last().unwrap().clone();
    assert!(!baseline.items.contains(&winner));
    let fixture = fitted_ranker(owner.clone(), &items, &[0, 0, 0, 10]);
    let selected = read(
        &store,
        &owner,
        /*body_generation*/ 1,
        /*authority_epoch*/ 2,
        "lemon",
        /*limit*/ 1,
        Some(&fixture.ranker),
    )
    .await
    .unwrap();
    assert_eq!(selected.items, vec![winner.clone()]);
    let budgeted = read(
        &store,
        &owner,
        /*body_generation*/ 1,
        /*authority_epoch*/ 2,
        "lemon",
        /*limit*/ 4,
        Some(&fixture.ranker),
    )
    .await
    .unwrap();
    assert_eq!(
        budgeted.items,
        vec![winner, items[0].clone(), items[1].clone()]
    );
    assert!(serde_json::to_vec(&budgeted).unwrap().len() <= MAX_CONTEXT_JSON_BYTES);
}

#[tokio::test]
async fn oversized_learned_winner_does_not_consume_the_only_result_slot() {
    let mut contents = vec![
        "lemon alpha".to_string(),
        "lemon beta".to_string(),
        "lemon gamma".to_string(),
    ];
    contents.push(format!("lemon oversized {}", "\\\"".repeat(/*n*/ 13000)));
    let (_directory, store, owner, items) = stored_candidates(contents).await;
    let oversized = items
        .iter()
        .position(|item| item.content.contains("oversized"))
        .unwrap();
    let expected = items
        .iter()
        .enumerate()
        .find(|(index, _)| *index != oversized)
        .unwrap()
        .1
        .clone();
    let scores: Vec<_> = (0..items.len())
        .map(|index| if index == oversized { 100 } else { 0 })
        .collect();
    let fixture = fitted_ranker(owner.clone(), &items, &scores);
    let selected = read(
        &store,
        &owner,
        /*body_generation*/ 1,
        /*authority_epoch*/ 2,
        "lemon",
        /*limit*/ 1,
        Some(&fixture.ranker),
    )
    .await
    .unwrap();
    assert_eq!(selected.items, vec![expected]);
    assert!(serde_json::to_vec(&selected).unwrap().len() <= MAX_CONTEXT_JSON_BYTES);
}

#[tokio::test]
async fn byte_cut_cannot_hide_an_unsupported_candidate_from_whole_batch_abstention() {
    let (_directory, store, owner, items) = stored_candidates(escaping_contents()).await;
    let baseline = read(
        &store,
        &owner,
        /*body_generation*/ 1,
        /*authority_epoch*/ 2,
        "lemon",
        /*limit*/ 4,
        /*ranker*/ None,
    )
    .await
    .unwrap();
    assert!(baseline.items.len() > 1 && baseline.items.len() < items.len());
    let scores: Vec<_> = (0..baseline.items.len())
        .map(|index| i64::try_from(index).unwrap())
        .collect();
    let fixture = fitted_ranker(owner.clone(), &baseline.items, &scores);
    let selected = read(
        &store,
        &owner,
        /*body_generation*/ 1,
        /*authority_epoch*/ 2,
        "lemon",
        /*limit*/ 1,
        Some(&fixture.ranker),
    )
    .await
    .unwrap();
    assert_eq!(selected.items, vec![baseline.items[0].clone()]);
}
