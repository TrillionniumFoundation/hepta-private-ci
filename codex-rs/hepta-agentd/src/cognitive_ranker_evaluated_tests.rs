//! Virtual-clock, fixture-key protocol E2E. These are not longitudinal product
//! efficacy observations. No opaque admission value is fabricated in this test.

use super::*;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::TabularPayloadPinV2;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_verified_v3;
use codex_hepta_bellman_operator::tabular_training_signing_payload_v2;
use codex_hepta_bellman_operator::verify_tabular_operator_plan_v3;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::OpenOptions;
use std::path::PathBuf;

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
struct View(Mutex<Option<(PathBuf, RegistrySnapshotReceipt, Digest32)>>);
impl CurrentCognitiveRegistry for View {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let view = self.0.lock().unwrap();
        let (path, receipt, predecessor) = view.as_ref().ok_or("missing current witness")?;
        verified_fixture_current_view(
            File::open(path).map_err(|error| error.to_string())?,
            *receipt,
            *predecessor,
        )
    }
}

use crate::learning_operator_test_support::LearningFixture;

impl LearningFixture {
    fn fit(&self, items: &[CognitiveContextItem], generation: u64) -> TabularOperatorArtifactV1 {
        let sensor = cognitive_sensor_id("lemon").unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(self.receipt.snapshot.source_record_digests.len(), 2);
        let actions: Vec<_> = items
            .iter()
            .map(|item| cognitive_action_id(item).unwrap())
            .collect();
        let plan = TabularOperatorPlanV1 {
            artifact_id: id(&format!("evaluated-ranker-{generation}")),
            producer_id: id("generator"),
            generation: Generation::new(generation).unwrap(),
            objective_digest: self.trust.objective_digest,
            dataset_digest: self.receipt.snapshot.dataset_digest,
            sensor_core_digest: hash("exact-query-revision-v1"),
            training_profile_digest: hash("signed-tabular-v3"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![sensor.clone()],
            action_ids: actions.clone(),
            samples: self
                .receipt
                .snapshot
                .source_record_digests
                .iter()
                .enumerate()
                .map(|(index, evidence)| TabularOperatorSampleV1 {
                    sample_id: id(&format!("row-{index}")),
                    sensor_id: sensor.clone(),
                    action_id: actions[index].clone(),
                    target: FixedQ32::from_raw(if index as u64 == generation - 1 {
                        20
                    } else {
                        0
                    }),
                    evidence_digest: *evidence,
                })
                .collect(),
        };
        let payload =
            tabular_training_signing_payload_v2(&plan, &self.receipt, &self.owner).unwrap();
        let rows = Self::sign(self.owner.verifier(), 1, &payload, 6);
        let verified = verify_tabular_operator_plan_v3(
            plan,
            &self.receipt,
            &self.owner,
            &self.freeze,
            &rows,
            6,
        )
        .unwrap();
        fit_tabular_operator_verified_v3(verified, 6).unwrap()
    }
}

struct Admission(Mutex<RankerAdmissionSnapshotV2>);
impl CurrentRankerAdmission for Admission {
    fn current(&self) -> Result<RankerAdmissionSnapshotV2, String> {
        Ok(self.0.lock().unwrap().clone())
    }
}

struct EvaluatedFixture {
    directory: tempfile::TempDir,
    learning: LearningFixture,
    registry: ArtifactRegistry,
    view: Arc<View>,
    admission: Arc<Admission>,
    selection: VerifiedSelfEvolutionSelectionV1,
    specs: [PinnedCandidateSpec; 2],
    pins: [TabularPayloadPinV2; 2],
}

impl EvaluatedFixture {
    fn new(items: &[CognitiveContextItem]) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let learning = LearningFixture::new();
        let models = [learning.fit(items, 1), learning.fit(items, 2)];
        let mut registry = ArtifactRegistry::new();
        let runtime = hash("ranker-consumer-v2");
        let manifests: [ArtifactManifest; 2] = std::array::from_fn(|index| {
            let model = &models[index];
            let bytes = encode_tabular_payload_v1(model).unwrap();
            let manifest = ArtifactManifest {
                artifact_id: model.artifact_id.clone(),
                kind: ArtifactKind::Policy,
                generation: model.generation,
                predecessor_id: (index == 1).then(|| models[0].artifact_id.clone()),
                content_digest: Digest32::of_bytes(&bytes),
                objective_digest: model.objective_digest,
                support_digest: model.dataset_digest,
                producer_id: model.producer_id.clone(),
                compatibility_digest: runtime,
                encoded_size_bytes: bytes.len() as u64,
            };
            registry
                .append(ArtifactEvent::Register {
                    event_id: id(&format!("register-{index}")),
                    manifest: manifest.clone(),
                })
                .unwrap();
            write_candidate_payload(
                CreateOnlyArtifactFile::create(directory.path().join(format!("payload-{index}")))
                    .unwrap(),
                &registry,
                &manifest.artifact_id,
                &bytes,
            )
            .unwrap();
            manifest
        });
        let snapshot = directory.path().join("snapshot");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&snapshot).unwrap(),
            &registry,
            hash("fixture-host-binding"),
        )
        .unwrap();
        let view = Arc::new(View(Mutex::new(Some((snapshot, receipt, Digest32::ZERO)))));
        let admission = Arc::new(Admission(Mutex::new(RankerAdmissionSnapshotV2 {
            learning_verifier: learning.owner.verifier().clone(),
            artifact_trust_digest: view.current().unwrap().trust_digest(),
            runtime_profile_digest: runtime,
            now_unix_micros: 50,
        })));
        let selection = learning.selection(&manifests[0], &manifests[1]);
        let pins = std::array::from_fn(|index| TabularPayloadPinV2 {
            artifact_id: models[index].artifact_id.clone(),
            producer_id: models[index].producer_id.clone(),
            artifact_schema_version: 1,
            payload_schema_version: 1,
            payload_digest: manifests[index].content_digest,
            artifact_digest: models[index].artifact_digest,
            objective_digest: models[index].objective_digest,
            dataset_digest: models[index].dataset_digest,
            sensor_core_digest: models[index].sensor_core_digest,
            training_profile_digest: models[index].training_profile_digest,
            runtime_profile_digest: runtime,
            trust_digest: learning.owner.verifier().trust_digest(),
            registry_head_digest: receipt.head_digest,
            authority_epoch: 7,
            generation: models[index].generation,
        });
        let specs = manifests.map(|manifest| PinnedCandidateSpec {
            registry_receipt: receipt,
            manifest,
        });
        Self {
            directory,
            learning,
            registry,
            view,
            admission,
            selection,
            specs,
            pins,
        }
    }
    fn load(&self) -> Result<PinnedCognitiveRanker, String> {
        self.load_pin(self.pins[1].clone())
    }
    fn load_pin(&self, pin: TabularPayloadPinV2) -> Result<PinnedCognitiveRanker, String> {
        PinnedCognitiveRanker::load_evaluated(
            owner(),
            2,
            File::open(self.directory.path().join("snapshot")).unwrap(),
            File::open(self.directory.path().join("payload-1")).unwrap(),
            self.specs[1].clone(),
            pin,
            self.view.clone(),
            &self.selection,
            self.admission.clone(),
        )
    }
    fn revoke_candidate(&mut self) {
        let predecessor = self.registry.snapshot().head_digest;
        self.registry
            .append(ArtifactEvent::Revoke(StateChange {
                event_id: id("revoke-evaluated-candidate"),
                artifact_id: self.specs[1].manifest.artifact_id.clone(),
                evaluator_id: id("artifact-evaluator"),
                reason_digest: hash("withdrawn"),
            }))
            .unwrap();
        let path = self.directory.path().join("revoked");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).unwrap(),
            &self.registry,
            hash("fixture-host-binding"),
        )
        .unwrap();
        *self.view.0.lock().unwrap() = Some((path, receipt, predecessor));
    }
}

#[test]
fn evaluated_load_uses_real_owner_training_selection_revocation_and_rollback() {
    let original = vec![item("one"), item("two")];
    let mut fixture = EvaluatedFixture::new(&original);
    let ranker = fixture.load().unwrap();
    let mut ranked = original.clone();
    assert!(
        ranker
            .rank(&owner(), 2, "lemon", &mut ranked)
            .unwrap()
            .applied
    );
    assert_eq!(ranked, vec![original[1].clone(), original[0].clone()]);
    assert!(!fixture.selection.receipt().authority.grants_any());
    fixture.revoke_candidate();
    let before = ranked.clone();
    assert!(ranker.rank(&owner(), 2, "lemon", &mut ranked).is_err());
    assert_eq!(ranked, before);
    let regression = hash("independent-regression-observation");
    let payload = rollback_signing_payload_v1(&fixture.selection, regression).unwrap();
    let evidence = LearningFixture::sign(fixture.learning.owner.verifier(), 2, &payload, 50);
    let rollback = admit_self_evolution_rollback_v1(
        &fixture.selection,
        regression,
        &evidence,
        fixture.learning.owner.verifier(),
        50,
    )
    .unwrap();
    let restored = PinnedCognitiveRanker::load_evaluated_rollback(
        owner(),
        3,
        File::open(fixture.directory.path().join("snapshot")).unwrap(),
        File::open(fixture.directory.path().join("payload-0")).unwrap(),
        fixture.specs[0].clone(),
        fixture.pins[0].clone(),
        fixture.view.clone(),
        &rollback,
        fixture.admission.clone(),
    )
    .unwrap();
    let mut items = original.clone();
    restored.rank(&owner(), 3, "lemon", &mut items).unwrap();
    assert_eq!(items, original);
    assert!(restored.rank(&owner(), 1, "lemon", &mut items).is_err());
}

#[test]
fn evaluated_load_rejects_each_full_pin_substitution() {
    let original = vec![item("one"), item("two")];
    let fixture = EvaluatedFixture::new(&original);
    for mutation in 0..8 {
        let mut pin = fixture.pins[1].clone();
        match mutation {
            0 => pin.artifact_id = id("imposter"),
            1 => pin.producer_id = id("imposter"),
            2 => pin.runtime_profile_digest = hash("other-runtime"),
            3 => pin.trust_digest = hash("other-trust"),
            4 => pin.registry_head_digest = hash("other-head"),
            5 => pin.authority_epoch += 1,
            6 => pin.payload_schema_version += 1,
            7 => pin.generation = Generation::new(3).unwrap(),
            _ => unreachable!(),
        }
        assert!(fixture.load_pin(pin).is_err(), "pin mutation {mutation}");
    }
}

#[test]
fn evaluated_rank_rechecks_expiry_epoch_revocation_runtime_and_clock_without_resurrection() {
    for mutation in 0..5 {
        let original = vec![item("one"), item("two")];
        let fixture = EvaluatedFixture::new(&original);
        let ranker = fixture.load().unwrap();
        let saved = fixture.admission.0.lock().unwrap().clone();
        {
            let mut host = fixture.admission.0.lock().unwrap();
            match mutation {
                0 => host.now_unix_micros = 101,
                1 => {
                    let mut trust = fixture.learning.trust.clone();
                    trust.authority_epoch += 1;
                    for signer in &mut trust.signers {
                        signer.principal.authority_epoch += 1;
                    }
                    host.learning_verifier = LearningEvidenceVerifierV1::new(trust).unwrap();
                }
                2 => {
                    let mut trust = fixture.learning.trust.clone();
                    trust.signers[3].revoked_at = Some(50);
                    host.learning_verifier = LearningEvidenceVerifierV1::new(trust).unwrap();
                }
                3 => host.runtime_profile_digest = hash("other-runtime"),
                4 => host.now_unix_micros = 49,
                _ => unreachable!(),
            }
        }
        let mut items = original.clone();
        assert!(ranker.rank(&owner(), 2, "lemon", &mut items).is_err());
        assert_eq!(items, original);
        *fixture.admission.0.lock().unwrap() = saved;
        assert!(ranker.rank(&owner(), 2, "lemon", &mut items).is_err());
    }
}

#[tokio::test]
async fn evaluated_load_reaches_sqlite_read_boundary_before_limit_without_writes() {
    use codex_hepta_memory::*;
    use codex_hepta_paths::HeptaFleetRoot;
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(std::fs::canonicalize(fleet).unwrap())
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
                event_key: "evaluated-ranker-source".to_string(),
                content: b"lemon orchard".to_vec(),
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
                    stable_key: name.to_string(),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content: format!("lemon orchard {name}"),
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
    let baseline = crate::cognitive_context::read(&store, &owner(), 2, "lemon", 4, None)
        .await
        .unwrap();
    let fixture = EvaluatedFixture::new(&baseline.items);
    let ranker = Arc::new(fixture.load().unwrap());
    let ranked = crate::cognitive_context::read(&store, &owner(), 2, "lemon", 1, Some(&ranker))
        .await
        .unwrap();
    assert_eq!(ranked.items, vec![baseline.items[1].clone()]);
    let unchanged = crate::cognitive_context::read(&store, &owner(), 2, "lemon", 4, None)
        .await
        .unwrap();
    assert_eq!(
        unchanged.items, baseline.items,
        "read-only ranking must not mutate stored rows"
    );
}
