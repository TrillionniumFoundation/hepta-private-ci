//! Complete mechanism fixture with actual ordinary A/C and original native
//! Material, SourceBound Training, Evaluation, Model and Selection owners.
//! Credentials, final authorization and heldout cohorts remain explicit tests.
use std::fs::File;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_learning_artifacts::*;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::UnlearningLineageRequestV1;
use codex_hepta_learning_ledger::unlearning_signing_payload_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::super::*;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::CellQ24TrainingOutcomeV1;
use crate::CellQ24TrainingOwnerV1;
use crate::LearningIterationEvidenceClientV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::OriginalCellQ24TrainingSigningConfigV1;
use crate::OriginalCellQ24TrainingSourceOwnersV1;
use crate::OriginalCellQ24TrainingStageV1;
use crate::OriginalCircuitModelSelectionReceiptConfigV1;
use crate::OriginalCircuitModelSelectionReceiptErrorV1;
use crate::OriginalCircuitModelSelectionReceiptOwnerV1;
use crate::OriginalCircuitModelSelectionReceiptSourcesV1;
use crate::SourceBoundCellQ24TrainingStageV1;
use crate::learning_iteration_evidence_client::fixture_original_receipt_client_until_close;
use crate::neuron_cell_evaluation::tests::original_model_selection::EvaluationFixture;

#[path = "circuit_model_selection_material_support_tests.rs"]
mod material;

type Stage = SourceBoundCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
pub(super) type Owner = OriginalCircuitModelSelectionReceiptOwnerV1<FileAnchorWitnessStore>;
pub(super) type SelectionError = OriginalCircuitModelSelectionReceiptErrorV1;
type PeerThread = std::thread::JoinHandle<anyhow::Result<usize>>;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}
fn id(label: &str) -> StableId {
    StableId::new(label).expect("explicit positive fixture id")
}
fn now() -> anyhow::Result<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}
fn opened(root: &Path, name: &str, create: bool) -> anyhow::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).mode(0o600);
    if create {
        options.create_new(true);
    }
    Ok(options.open(root.join(name))?)
}
fn original_witness(
    root: &Path,
    name: &str,
    scope: &FrozenLearningScopeV2,
    objective: Digest32,
    create: bool,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        opened(root, name, create)?,
        JournalScope {
            scope_digest: scope.binding(),
            objective_digest: objective,
        },
        Generation::new(1)?,
        64,
    )?)
}

pub(super) struct Peers {
    trainer: LearningIterationEvidenceClientV1,
    evaluator: LearningIterationEvidenceClientV1,
    threads: [PeerThread; 2],
}
impl Peers {
    pub(super) fn finish(self) -> anyhow::Result<[usize; 2]> {
        drop(self.trainer);
        drop(self.evaluator);
        let [first, second] = self.threads;
        Ok([
            first.join().expect("original Trainer transport")?,
            second.join().expect("original Evaluator transport")?,
        ])
    }
}

pub(super) struct PositiveFixture {
    root: PathBuf,
    pub(super) config: OriginalCircuitModelSelectionReceiptConfigV1,
    pub(super) session: support::Session,
    pub(super) version: VersionFixture,
    pub(super) definition: CellDefinitionV1,
    pub(super) candidate: CellCompatibilityBundleV1,
    pub(super) previous: CircuitTaskSourcePublicationV1,
    pub(super) evaluation: EvaluationFixture,
    initial: LearningIterationSnapshotV1,
    // Retain the exact original owner signatures for the Root checkpoint
    // mechanism; never re-sign material to make a later cut authenticate.
    material_evidence: [SignedLearningEvidenceV1; 2],
    stage: Stage,
    model: CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore>,
    ledger: Arc<Mutex<LedgerWriter>>,
    frozen: DatasetSnapshotReceiptV3,
    credentials: material::Credentials,
    source_threads: [PeerThread; 2],
    source_paths: [PathBuf; 2],
    // Retain the actual original private directory while SourceBound retains
    // its source handles; dropping the stopped Session must not unlink it.
    _source_home: tempfile::TempDir,
    _directory: tempfile::TempDir,
}

impl PositiveFixture {
    pub(super) async fn ready() -> anyhow::Result<Self> {
        Self::ready_with_profile(
            d("explicit-positive-independent-evaluation-profile"),
            now()?,
        )
        .await
    }

    async fn ready_with_profile(
        evaluation_profile: Digest32,
        trust_time: u64,
    ) -> anyhow::Result<Self> {
        let admission = support::admission("positive-source-envelope-request").await?;
        Self::ready_with_admission(evaluation_profile, trust_time, admission).await
    }

    async fn ready_with_admission(
        evaluation_profile: Digest32,
        trust_time: u64,
        mut a: support::Admission,
    ) -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let (baseline, bundle, definition_a) = support::model(&root)?;
        let preview = support::source(&a, [Q, Q / 4])?;
        let (mut writer, credentials) = material::ledger_at(
            &root,
            preview.objective_digest,
            trust_time,
            d("explicit-positive-ledger"),
        )?;
        let run = crate::circuit_credit::circuit_learning_run_id_v1(
            &writer,
            &a.runtime.identity.agent_id,
            &id("positive-original-episode"),
        )?;
        // The envelope requestId and execution run_id are separate original
        // fields. Bind the actual run before Decision, issuance or execution;
        // support::start signs this final body with the explicit test issuer.
        a.request.body.run_id = run.to_string();
        let source_a = support::source(&a, [Q, Q / 4])?;
        assert_eq!(source_a.objective_digest, preview.objective_digest);
        assert_eq!(source_a.scope.run_id, run);
        material::decision(&mut writer, &credentials, &source_a)?;
        let config_a = support::configuration(&baseline, &bundle, &definition_a, &source_a, 1)?;
        let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
        let published_a =
            support::publish_initial(&version, definition_a.clone(), source_a.clone())?;
        let mut a = support::start(a, published_a, Arc::clone(&baseline), bundle.clone()).await?;
        let previous = execute(&a, 1).await?;
        let before_training = read_receipt(&a, &definition_a, &previous)?;
        assert_eq!(before_training.representation.prediction_q24[0], Q);
        assert_eq!(previous.original_record().snapshot.run_id, run);
        material::terminal_outcome(&mut writer, &credentials)?;
        let material::Material {
            initial,
            config: source_config,
            frozen,
        } = material::material_with_profile(
            &root,
            &mut writer,
            &credentials,
            a.source.as_ref(),
            &a.runtime.identity,
            &baseline,
            &bundle,
            &previous,
            evaluation_profile,
        )?;
        let ledger = Arc::new(Mutex::new(writer));
        let (experience, first) = fixture_original_receipt_client_until_close(
            initial.clone(),
            source_config.dataset.receipts[0].clone(),
            source_config.verifier.clone(),
            source_config.experience_evidence.clone(),
        )?;
        let (dataset, second) = fixture_original_receipt_client_until_close(
            initial.clone(),
            source_config.dataset.receipts[1].clone(),
            source_config.verifier.clone(),
            source_config.dataset_evidence.clone(),
        )?;
        let capture = crate::capture_original_cell_q24_training_source_v1(
            OriginalCellQ24TrainingSourceOwnersV1 {
                source: a.source.as_ref().clone(),
                identity: a.runtime.identity.clone(),
                ledger: Arc::clone(&ledger),
                baseline: Arc::clone(&baseline),
                experience,
                dataset,
            },
            source_config.clone(),
        )
        .await?;
        let training = CellQ24TrainingOwnerV1::create_from_original_source(
            opened(&root, "positive-native-training", true)?,
            original_witness(
                &root,
                "positive-native-witness",
                &source_config.scope,
                initial.request.envelope.objective_digest,
                true,
            )?,
            capture,
        )?;
        let receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
            opened(&root, "positive-training-receipt", true)?,
            original_witness(
                &root,
                "positive-training-receipt-witness",
                &source_config.scope,
                initial.request.envelope.objective_digest,
                true,
            )?,
            OriginalCellQ24TrainingSigningConfigV1 {
                dataset: source_config.dataset.clone(),
                scope: source_config.scope.clone(),
                signer: credentials.generator.clone(),
                verifier: source_config.verifier.clone(),
                maximum_signature_lifetime_seconds: 600,
            },
            SigningKey::from_bytes(&[41; 32]),
        )?;
        let original =
            OriginalCellQ24TrainingStageV1::from_original_owners(training, receipts).await?;
        let stage = SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?;
        let completed = stage
            .execute_training(&source_config.dataset, Arc::new(AtomicBool::new(false)))
            .await?;
        let CellQ24TrainingOutcomeV1::Candidate(trained) = completed.outcome else {
            anyhow::bail!("actual source-bound optimizer did not produce a candidate")
        };
        assert_eq!(trained.metrics.optimizer_steps, 2);
        assert!(trained.metrics.squared_error_after_q48 < trained.metrics.squared_error_before_q48);
        assert_ne!(trained.heads, fs::read(root.join("heads"))?);
        let candidate = trained.bundle;
        let candidate_model = Arc::new(trained.model);
        let definition = support::definition(&candidate_model, &candidate)?;
        let candidate_manifest =
            support::configuration(&candidate_model, &candidate, &definition, &source_a, 2)?
                .manifest;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(source_config.dataset.clone())?;
        coordinator.record(
            completed.receipt.clone(),
            completed.receipt.observed_unix_seconds,
        )?;
        let training_cut = coordinator.snapshot().clone();
        let mut evaluation = EvaluationFixture::new(
            &initial,
            training_cut.clone(),
            completed.attestation.clone(),
            &source_config.scope,
            &credentials.generator,
            &credentials.evaluator,
            source_config.verifier.clone(),
            [candidate_manifest.clone(), config_a.manifest.clone()],
        )
        .await?;
        coordinator.record(
            evaluation.stage_receipt.clone(),
            evaluation.stage_receipt.observed_unix_seconds,
        )?;
        let mut model = tokio::task::block_in_place(|| {
            SourceBoundCellQ24TrainingStageV1::create_model_owner(
                &stage,
                opened(&root, "positive-model-proposal", true)?,
                original_witness(
                    &root,
                    "positive-model-witness",
                    &source_config.scope,
                    initial.request.envelope.objective_digest,
                    true,
                )?,
            )
            .map_err(anyhow::Error::from)
        })?;
        let proposal = tokio::task::block_in_place(|| -> anyhow::Result<_> {
            let request = evaluation.request()?;
            Ok(SourceBoundCellQ24TrainingStageV1::commit_model_or_readback(
                &stage,
                &mut model,
                &CellQ24ModelProposalInputsV1 {
                    training_cut: &training_cut,
                    training_attestation: &completed.attestation,
                    runner: evaluation.runner(),
                    evaluation: &evaluation.receipt,
                    qualification: &evaluation.qualification,
                    request: &request,
                },
            )?)
        })?;
        assert_eq!(proposal.authority(), AuthorityPosture::DENY_ALL);
        assert_eq!(
            proposal.learning_receipt().predecessor,
            coordinator.snapshot().head_digest
        );
        coordinator.record(
            proposal.learning_receipt().clone(),
            proposal.learning_receipt().observed_unix_seconds,
        )?;
        assert_eq!(
            coordinator.next_stage(),
            Some(LearningIterationStageV1::Selection)
        );

        let completion_a =
            a.retirement
                .drain_completed_task(&a.cell, a.source.as_ref(), &a.runtime.identity)?;
        a.stop().await?;
        let source_paths = [
            a.runtime.identity.home_root.join("q24-source.journal"),
            a.runtime.identity.home_root.join("q24-source.witness"),
        ];
        let source_home = std::mem::replace(&mut a.runtime._temp, tempfile::tempdir()?);
        drop(a); // Release only the stopped version/Cell owners; retain source custody.

        let c = support::admission("positive-original-C").await?;
        let source_c = support::source(&c, [Q / 4, Q])?;
        let config_c =
            support::configuration(&candidate_model, &candidate, &definition, &source_c, 2)?;
        assert_eq!(config_c.manifest, candidate_manifest);
        assert_ne!(source_a.scope.run_id, source_c.scope.run_id);
        assert_ne!(source_a.observation, source_c.observation);
        // Explicit test authority admits this actual candidate through the real
        // artifact selection and FinalUse owners. No eligibility/grant conversion
        // is performed by Model or the new Selector receipt owner.
        let selected =
            version.publish_next_selection(&config_c.manifest, "positive-original-candidate")?;
        let operation = crate::learning_updated_task_operation_id_v1(&coordinator)?;
        let prepared = crate::prepare_agentd_generation_cold_drained_update_v1(
            version.reopen_current()?,
            version.authorities()?,
            AgentdGenerationUpdatePredecessorFilesV1 {
                file: version.file("target-journal")?,
                witness: version.witness("target-witness", &config_a)?,
                config: config_a,
                max_records: RECORDS,
            },
            selected,
            version.named_target_create("positive-C-journal", "positive-C-witness", config_c)?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: operation.to_string(),
            },
        )?;
        let final_use = version.sign(prepared.final_use_binding())?;
        let published_c = prepared.publish(&final_use)?.into_circuit_feature_task(
            definition.clone(),
            source_c,
            completion_a,
        )?;
        let session = support::start(c, published_c, candidate_model, candidate.clone()).await?;
        assert!(
            matches!(session.cell.read_learning_selection(&coordinator)?,
            LearningIterationObservationV1::Selection { candidate_bundle, .. }
            if candidate_bundle == candidate.digest()?)
        );
        let config = OriginalCircuitModelSelectionReceiptConfigV1 {
            decision: coordinator.snapshot().clone(),
            scope: source_config.scope,
            signer: credentials.selector.clone(),
            verifier: source_config.verifier,
            training_evidence: completed.attestation,
            evaluation_evidence: evaluation.stage_evidence.clone(),
            evaluation: evaluation.receipt.clone(),
            qualification: evaluation.qualification.clone(),
            product_evidence: evaluation.evidence.clone(),
            execution_evidence: evaluation.execution_evidence.clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        assert_eq!(
            evaluation.original_signature()?,
            *config.execution_evidence.attestation()
        );
        Ok(Self {
            root,
            config,
            session,
            version,
            definition,
            candidate,
            previous,
            evaluation,
            initial,
            material_evidence: [
                source_config.experience_evidence,
                source_config.dataset_evidence,
            ],
            stage,
            model,
            ledger,
            frozen,
            credentials,
            source_threads: [first, second],
            source_paths,
            _source_home: source_home,
            _directory: directory,
        })
    }

    pub(super) fn peers(&self, training: SignedLearningEvidenceV1) -> anyhow::Result<Peers> {
        let (trainer, first) = fixture_original_receipt_client_until_close(
            self.initial.clone(),
            self.config.decision.receipts[2].clone(),
            self.config.verifier.clone(),
            training,
        )?;
        let (evaluator, second) = fixture_original_receipt_client_until_close(
            self.initial.clone(),
            self.config.decision.receipts[3].clone(),
            self.config.verifier.clone(),
            self.config.evaluation_evidence.clone(),
        )?;
        Ok(Peers {
            trainer,
            evaluator,
            threads: [first, second],
        })
    }

    pub(super) fn selector_witness(&self, create: bool) -> anyhow::Result<FileAnchorWitnessStore> {
        original_witness(
            &self.root,
            "positive-selector-witness",
            &self.config.scope,
            self.config.decision.request.envelope.objective_digest,
            create,
        )
    }

    pub(super) fn create_with_witness<W: AnchorWitnessStore>(
        &self,
        witness: W,
    ) -> anyhow::Result<OriginalCircuitModelSelectionReceiptOwnerV1<W>> {
        Ok(OriginalCircuitModelSelectionReceiptOwnerV1::create(
            opened(&self.root, "positive-selector", true)?,
            witness,
            self.config.clone(),
            SigningKey::from_bytes(&[46; 32]),
        )?)
    }

    pub(super) fn create_owner(&self) -> anyhow::Result<Owner> {
        self.create_with_witness(self.selector_witness(true)?)
    }

    pub(super) fn recover_config(
        &self,
        config: OriginalCircuitModelSelectionReceiptConfigV1,
    ) -> anyhow::Result<Owner> {
        Ok(OriginalCircuitModelSelectionReceiptOwnerV1::recover(
            opened(&self.root, "positive-selector", false)?,
            self.selector_witness(false)?,
            config,
            SigningKey::from_bytes(&[46; 32]),
        )?)
    }

    fn sources<'a>(
        &'a mut self,
        snapshot: &'a LearningIterationSnapshotV1,
        peers: &'a Peers,
    ) -> OriginalCircuitModelSelectionReceiptSourcesV1<
        'a,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        LockedFileFinalHoldoutCasStoreV1,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
    > {
        OriginalCircuitModelSelectionReceiptSourcesV1 {
            snapshot,
            cell: &self.session.cell,
            training_stage: &self.stage,
            model: &mut self.model,
            evaluation: self.evaluation.sources(),
            trainer: &peers.trainer,
            evaluator: &peers.evaluator,
        }
    }

    pub(super) fn attest<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut OriginalCircuitModelSelectionReceiptOwnerV1<W>,
        snapshot: &LearningIterationSnapshotV1,
        peers: &Peers,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), SelectionError> {
        tokio::task::block_in_place(|| {
            owner.attest_original_selection(self.sources(snapshot, peers))
        })
    }

    pub(super) fn readback<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut OriginalCircuitModelSelectionReceiptOwnerV1<W>,
        snapshot: &LearningIterationSnapshotV1,
        peers: &Peers,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), SelectionError> {
        tokio::task::block_in_place(|| owner.readback(self.sources(snapshot, peers)))
    }

    pub(super) fn selector_bytes(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            fs::read(self.root.join("positive-selector"))?,
            fs::read(self.root.join("positive-selector-witness"))?,
        ])
    }

    pub(super) fn predecessor_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = self.evaluation.durable_bytes()?;
        for name in [
            "positive-ledger",
            "positive-ledger-witness",
            "positive-experience",
            "positive-experience-witness",
            "positive-dataset",
            "positive-dataset-witness",
            "positive-native-training",
            "positive-native-witness",
            "positive-training-receipt",
            "positive-training-receipt-witness",
            "positive-model-proposal",
            "positive-model-witness",
            "heads",
        ] {
            bytes.push(fs::read(self.root.join(name))?);
        }
        for path in &self.source_paths {
            bytes.push(fs::read(path)?);
        }
        Ok(bytes)
    }

    pub(super) fn withdraw_original_dataset(&self) -> anyhow::Result<()> {
        let mut ledger = self.ledger.lock().expect("original Ledger owner");
        let request = UnlearningLineageRequestV1 {
            record_id: id("positive-original-source-withdrawal"),
            lineage_id: id("positive-original-unlearning"),
            source_record_id: self.initial.request.source_run_id.clone(),
            dataset_snapshot_id: self.frozen.snapshot.snapshot_id.clone(),
            dataset_digest: self.frozen.snapshot.dataset_digest,
            artifact_id: self.candidate.artifact_id.clone(),
            reason_digest: d("explicit-positive-withdrawal"),
        };
        let at = now()?;
        let signed = material::sign(
            ledger.verifier(),
            &self.credentials.unlearning,
            48,
            &unlearning_signing_payload_v1(&request),
            at,
        );
        let before = ledger.snapshot()?.head_digest;
        ledger.append_unlearning(before, request, &self.frozen, &signed, at)?;
        assert_ne!(ledger.read_current_durable_snapshot()?.head_digest, before);
        Ok(())
    }

    pub(super) async fn finish(mut self) -> anyhow::Result<()> {
        self.session.stop().await?;
        drop(self.stage);
        let [first, second] = self.source_threads;
        assert!(first.join().expect("original Experience transport")? > 0);
        assert!(second.join().expect("original Dataset transport")? > 0);
        Ok(())
    }
}

#[path = "circuit_original_evaluation_provider_tests.rs"]
mod evaluation_provider;
