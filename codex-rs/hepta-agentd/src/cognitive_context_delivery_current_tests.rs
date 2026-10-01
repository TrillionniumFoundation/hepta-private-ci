//! A real signed CURRENT withdrawal between preparation and ledger publication.

use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

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
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;

use crate::CurrentCognitiveRegistry;
use crate::PinnedCognitiveRanker;
use crate::cognitive_context::CognitiveContextError;
use crate::cognitive_context::read_with_retrieval_context_and_learning;
use crate::cognitive_context_delivery::PendingContextDelivery;
use crate::cognitive_context_issuer::ContextPlanIssuer;
use crate::cognitive_sensor_id;

use super::digest;
use super::id;
use super::observation;
use super::owner;
use super::sink;

struct Current(Mutex<(PathBuf, RegistrySnapshotReceipt, Digest32)>);

impl CurrentCognitiveRegistry for Current {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let (path, receipt, predecessor) = &*self.0.lock().map_err(|error| error.to_string())?;
        crate::cognitive_ranker::verified_fixture_current_view(
            File::open(path).map_err(|error| error.to_string())?,
            *receipt,
            *predecessor,
        )
    }
}

#[tokio::test]
async fn current_withdrawal_after_draft_rejects_publication_without_ledger_append() {
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(fleet)
        .unwrap()
        .layout()
        .agent(&owner());
    let store = CognitiveStore::open(&layout).await.unwrap();
    let sensor = cognitive_sensor_id("lemon").unwrap();
    let action = id("empty-context-action");
    let model = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id("publication-ranker"),
        producer_id: id("fixture-trainer"),
        generation: Generation::new(/*value*/ 1).unwrap(),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        sensor_core_digest: digest("exact-query-v1"),
        training_profile_digest: digest("strict-table-v1"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![sensor.clone()],
        action_ids: vec![action.clone()],
        samples: (0..2)
            .map(|index| TabularOperatorSampleV1 {
                sample_id: id(&format!("sample-{index}")),
                sensor_id: sensor.clone(),
                action_id: action.clone(),
                target: FixedQ32::ZERO,
                evidence_digest: digest(&format!("evidence-{index}")),
            })
            .collect(),
    })
    .unwrap();
    let bytes = encode_tabular_payload_v1(&model).unwrap();
    let pin = TabularPayloadPinV1 {
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
        content_digest: pin.payload_digest,
        objective_digest: pin.objective_digest,
        support_digest: pin.dataset_digest,
        producer_id: model.producer_id,
        compatibility_digest: digest("ranker-consumer-v1"),
        encoded_size_bytes: bytes.len() as u64,
    };
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register"),
            manifest: manifest.clone(),
        })
        .unwrap();
    let payload_path = directory.path().join("payload");
    write_candidate_payload(
        CreateOnlyArtifactFile::create(&payload_path).unwrap(),
        &registry,
        &manifest.artifact_id,
        &bytes,
    )
    .unwrap();
    let path = directory.path().join("current");
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&path).unwrap(),
        &registry,
        digest("host-binding"),
    )
    .unwrap();
    let current = Arc::new(Current(Mutex::new((path.clone(), receipt, Digest32::ZERO))));
    let ranker = Arc::new(
        PinnedCognitiveRanker::load(
            owner(),
            /*body_generation*/ 1,
            File::open(path).unwrap(),
            File::open(payload_path).unwrap(),
            PinnedCandidateSpec {
                registry_receipt: receipt,
                manifest,
            },
            pin,
            current.clone(),
        )
        .unwrap(),
    );
    let mut read = read_with_retrieval_context_and_learning(
        &store,
        &owner(),
        /*body_generation*/ 1,
        "lemon",
        /*limit*/ 4,
        Some(&ranker),
        /*current_retrieval*/ None,
        /*learning_sink*/ None,
        /*request_id*/ None,
    )
    .await
    .unwrap();
    let (_ledger_directory, sink) = sink();
    let sink = Arc::new(sink);
    read.delivery = Some(PendingContextDelivery {
        sink: Arc::clone(&sink),
        owner: owner(),
        body_generation: 1,
        request_id: 88,
        assignment: observation("withdrawn-before-publication"),
        delivered_candidates: Vec::new(),
        context_exposed: false,
        published_context_digest: None,
        downstream_policy_digest: None,
        delivery_propensity: ProbabilityQ32::ONE,
    });
    let predecessor = registry.snapshot().head_digest;
    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("withdraw"),
            artifact_id: id("publication-ranker"),
            evaluator_id: id("independent-evaluator"),
            reason_digest: digest("withdrawn-support"),
        }))
        .unwrap();
    let revoked_path = directory.path().join("revoked");
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&revoked_path).unwrap(),
        &registry,
        digest("host-binding"),
    )
    .unwrap();
    *current.0.lock().unwrap() = (revoked_path, receipt, predecessor);
    let snapshot = read.planned.snapshot.clone();
    let issuer = ContextPlanIssuer::default();
    assert!(matches!(
        read.publish(
            &store,
            &owner(),
            /*body_generation*/ 1,
            &issuer,
            Some(&ranker),
            /*current_retrieval*/ None,
        )
        .await,
        Err(CognitiveContextError::RankerUnavailable)
    ));
    assert!(
        sink.writer
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .is_empty()
    );
    assert!(
        issuer
            .validate(owner().as_str(), /*body_generation*/ 1, &snapshot)
            .is_err()
    );
}
