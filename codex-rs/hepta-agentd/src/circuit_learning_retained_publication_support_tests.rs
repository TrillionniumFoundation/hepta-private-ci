//! Actual ordinary A, original artifact/Control files and fresh C admission.
//! Only Training observations and credentials are explicit synthetic fixtures;
//! these tests do not assert native optimization or deployed role separation.

use anyhow::Context;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::sync::Arc;

use super::*;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandContextV1;
use crate::OriginalCircuitRetainedPublicationContextV1;
use crate::OriginalCircuitRetainedPublicationInputsV1;
use crate::OriginalCircuitRetainedPublicationRecoveryV1;
use crate::learning_iteration_evidence_client::command_test_support::retained_publication_training_peer;
use crate::learning_iteration_evidence_client::selection_command_test_support::training_fixture_result;

pub(super) struct RetainedPublicationFixture {
    pub(super) version: VersionFixture,
    pub(super) metadata: Metadata,
    pub(super) model: Arc<crate::LoadedCellQ24ModelV1>,
    pub(super) bundle: CellCompatibilityBundleV1,
    pub(super) definition: CellDefinitionV1,
    pub(super) source_a: crate::CircuitTaskSourceInputV1,
    pub(super) source_c: crate::CircuitTaskSourceInputV1,
    pub(super) config_a: codex_hepta_neuron::CellGenerationConfigV2,
    pub(super) config_c: codex_hepta_neuron::CellGenerationConfigV2,
    pub(super) identity_a: crate::AgentdIdentity,
    pub(super) original_source: Arc<crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub(super) c: Option<support::Admission>,
    completed: Option<crate::PublishedCircuitFeatureCompletionV1>,
    _model_root: tempfile::TempDir,
    _source_root: tempfile::TempDir,
}

enum RetainedPublicationFixtureClockV1 {
    OriginalTestClock,
    LiveArtifactClock,
}

impl RetainedPublicationFixture {
    pub(super) async fn ready() -> anyhow::Result<Self> {
        Self::ready_with_clock(RetainedPublicationFixtureClockV1::OriginalTestClock).await
    }

    async fn ready_with_clock(clock: RetainedPublicationFixtureClockV1) -> anyhow::Result<Self> {
        let model_root = tempfile::tempdir()?;
        let (model, bundle, definition) = support::model(model_root.path())?;
        let a = support::admission("retained-publication-original-A").await?;
        let source_a = support::source(&a, [Q, Q / 4])?;
        let config_a = support::configuration(&model, &bundle, &definition, &source_a, 1)?;
        let version = match clock {
            RetainedPublicationFixtureClockV1::OriginalTestClock => {
                VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?
            }
            RetainedPublicationFixtureClockV1::LiveArtifactClock => {
                VersionFixture::new_initial_with_live_artifacts(
                    config_a.clone(),
                    "ordinary-q24-initial",
                )?
            }
        };
        let task = support::publish_initial(&version, definition.clone(), source_a.clone())?;
        let mut a = support::start(a, task, Arc::clone(&model), bundle.clone()).await?;
        a.runtime
            .state
            .attach_circuit_learning_source(source_a.scope.run_id.clone())?;
        let publication = execute(&a, 1).await?;
        let intent = a
            .runtime
            .state
            .circuit_task_store()?
            .circuit_learning_delivery(source_a.scope.run_id.as_str())
            .await
            .map_err(|error| anyhow::anyhow!("actual A delivery: {error:?}"))?
            .context("actual completed A delivery")?
            .intent;
        assert_eq!(publication.history_digest(), &intent.completed_task_receipt);
        let request = LearningIterationRequestV1 {
            operation_id: StableId::new(intent.operation_id)?,
            principal_id: StableId::new(source_a.scope.principal_digest.to_string())?,
            agent_id: source_a.scope.agent_id.clone(),
            cell_id: source_a.scope.cell_id.clone(),
            source_run_id: source_a.scope.run_id.clone(),
            completed_task_receipt: intent.completed_task_receipt.as_str().parse()?,
            selected_artifact_digest: bundle.components.base,
            evaluation_profile: d("retained-publication-evaluation-fixture"),
            selected_bundle: bundle.clone(),
            envelope: IterationEnvelopeV1 {
                envelope_id: StableId::new("retained-publication-envelope")?,
                base_commit: d("retained-publication-source-commit-fixture"),
                base_tree: d("retained-publication-source-tree-fixture"),
                objective_digest: intent.objective_digest.as_str().parse()?,
                grammar_digest: d("retained-publication-grammar-fixture"),
                maximum_files: 1,
                maximum_diff_bytes: 128,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: now()? + 900,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 1,
                maximum_dataset_bytes: 128,
                maximum_training_steps: 1,
                maximum_training_milliseconds: 1,
                maximum_artifact_bytes: 128,
            },
        };
        a.runtime
            .state
            .require_circuit_learning_source(&request)
            .await?;
        let metadata = Metadata::new(request)?;
        let completed =
            a.retirement
                .drain_completed_task(&a.cell, a.source.as_ref(), &a.runtime.identity)?;
        let identity_a = a.runtime.identity.clone();
        let original_source = Arc::clone(&a.source);
        let source_root = std::mem::replace(&mut a.runtime._temp, tempfile::tempdir()?);
        a.stop().await?;
        drop(a);

        let c = support::admission("retained-publication-original-C").await?;
        let source_c = support::source(&c, [Q / 4, Q])?;
        let config_c = support::configuration(&model, &bundle, &definition, &source_c, 2)?;
        Ok(Self {
            version,
            metadata,
            model,
            bundle,
            definition,
            source_a,
            source_c,
            config_a,
            config_c,
            identity_a,
            original_source,
            c: Some(c),
            completed: Some(completed),
            _model_root: model_root,
            _source_root: source_root,
        })
    }

    pub(super) fn dataset(&self) -> LearningIterationSnapshotV1 {
        let mut dataset = self.metadata.decision.snapshot().clone();
        let training = dataset.receipts.pop().expect("explicit Training fixture");
        dataset.head_digest = training.predecessor;
        dataset
    }

    pub(super) async fn context(
        &self,
    ) -> anyhow::Result<OriginalCircuitRetainedPublicationContextV1> {
        let (dataset, original) = training_fixture_result(
            self.metadata.decision.snapshot().clone(),
            self.metadata.scope.clone(),
            self.metadata.verifier.clone(),
            self.metadata.training_signature.clone(),
        )
        .await?;
        Ok(
            OriginalCircuitRetainedPublicationContextV1::from_original_training(
                dataset,
                self.metadata.scope.clone(),
                self.metadata.verifier.clone(),
                &original,
            )?,
        )
    }

    pub(super) fn trainer(
        &self,
        signature: SignedLearningEvidenceV1,
    ) -> anyhow::Result<(
        OriginalCellQ24TrainingCommandClientV1,
        std::thread::JoinHandle<anyhow::Result<usize>>,
    )> {
        retained_publication_training_peer(
            OriginalCellQ24TrainingCommandContextV1 {
                dataset: self.dataset(),
                scope: self.metadata.scope.clone(),
                verifier: self.metadata.verifier.clone(),
            },
            self.metadata.training.clone(),
            signature,
        )
    }

    pub(super) fn inputs(
        &mut self,
    ) -> anyhow::Result<
        OriginalCircuitRetainedPublicationInputsV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    > {
        Ok(OriginalCircuitRetainedPublicationInputsV1 {
            current: self.version.reopen_current()?,
            authorities: self.version.authorities()?,
            selection: self.version.retained_publication_selection()?,
            predecessor: AgentdGenerationUpdatePredecessorFilesV1 {
                file: self.version.file("target-journal")?,
                witness: self.version.witness("target-witness", &self.config_a)?,
                config: self.config_a.clone(),
                max_records: RECORDS,
            },
            target: self.version.named_target_create(
                "retained-C-journal",
                "retained-C-witness",
                self.config_c.clone(),
            )?,
            definition: self.definition.clone(),
            source: self.source_c.clone(),
            completed: self
                .completed
                .take()
                .context("one original completed A token")?,
        })
    }

    pub(super) fn recovery(
        &self,
        intent: Digest32,
    ) -> anyhow::Result<
        OriginalCircuitRetainedPublicationRecoveryV1<
            FileAnchorWitnessStore,
            FileAnchorWitnessStore,
            FileAnchorWitnessStore,
        >,
    > {
        let file = |name: &str| -> anyhow::Result<File> {
            Ok(OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.identity_a.home_root.join(name))?)
        };
        let predecessor = crate::CircuitFeaturePredecessorFilesV1 {
            file: file("q24-cell.journal")?,
            witness: FileAnchorWitnessStore::open(
                file("q24-cell.witness")?,
                JournalScope {
                    scope_digest: cell::d("original-cell-owner"),
                    objective_digest: self.source_a.objective_digest,
                },
                Generation::new(1)?,
                64,
            )?,
            definition: self.definition.clone(),
            source: self.source_a.clone(),
            manifest: self.config_a.manifest.clone(),
            maximum_records: 16,
        };
        Ok(OriginalCircuitRetainedPublicationRecoveryV1 {
            training: self.metadata.decision.snapshot().clone(),
            scope: self.metadata.scope.clone(),
            verifier: self.metadata.verifier.clone(),
            training_evidence: self.metadata.training_signature.clone(),
            intent_digest: intent,
            current: self.version.reopen_current()?,
            authorities: self.version.authorities()?,
            selection: self.version.retained_publication_selection()?,
            target: crate::AgentdGenerationUpdateTargetV1 {
                file: self.version.file("retained-C-journal")?,
                witness: self.version.witness("retained-C-witness", &self.config_c)?,
                config: self.config_c.clone(),
                max_records: RECORDS,
            },
            definition: self.definition.clone(),
            source: self.source_c.clone(),
            predecessor,
            original_source: Arc::clone(&self.original_source),
            original_identity: self.identity_a.clone(),
        })
    }

    pub(super) fn publication_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        ["current.json", "retained-C-journal", "retained-C-witness"]
            .into_iter()
            .map(|name| self.version.bytes(name))
            .collect()
    }

    pub(super) async fn start_c(
        &mut self,
        task: crate::PublishedCircuitFeatureTaskV1,
    ) -> anyhow::Result<support::Session> {
        support::start(
            self.c.take().context("one original C admission")?,
            task,
            Arc::clone(&self.model),
            self.bundle.clone(),
        )
        .await
    }
}

pub(super) fn finish_trainer(
    peer: std::thread::JoinHandle<anyhow::Result<usize>>,
) -> anyhow::Result<usize> {
    peer.join()
        .map_err(|_| anyhow::anyhow!("original Trainer fixture thread"))?
}

#[path = "circuit_retained_version_issuer_support_tests.rs"]
mod version_issuer;
