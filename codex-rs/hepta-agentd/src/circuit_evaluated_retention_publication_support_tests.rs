//! One original A produces the native Candidate and the actual independent
//! Ineligible B/retention panel. That same A supplies the drained baseline
//! publication. All role credentials, clocks and measurements are fixtures;
//! this is neither ordinary qualification nor daemon/Root cold recovery.
//! Existing B member evidence peers retain fixture original signatures.
//! Auxiliary positive Eval/Model records are not this Ineligible B's evidence.

use anyhow::Context as _;
use std::fs::File;
use std::fs::OpenOptions;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;

use super::*;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandContextV1;
use crate::OriginalCellQ24TrainingCommandErrorV1;
use crate::OriginalCellQ24TrainingCommandOwnerV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitEvaluatedRetentionRecoveryV1;
use crate::OriginalCircuitRetainedPublicationInputsV1;
use crate::learning_iteration_evidence_client::command_test_support as commands;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

type Trainer =
    OriginalCellQ24TrainingCommandOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
type TrainerPeer = std::thread::JoinHandle<Result<u64, OriginalCellQ24TrainingCommandErrorV1>>;

pub(super) struct Peers {
    trainer: TrainerPeer,
    evaluator: super::super::fixture::Peer,
}

impl Peers {
    pub(super) fn finish(self) -> anyhow::Result<[u64; 2]> {
        Ok([
            self.trainer.join().expect("same original Trainer peer")?,
            self.evaluator
                .join()
                .expect("same original Evaluator peer")?,
        ])
    }
}

pub(super) struct PublicationFixture {
    pub(super) host: HostFixture,
    trainer: Arc<Trainer>,
    trainer_context: OriginalCellQ24TrainingCommandContextV1,
    pub(super) training: OriginalCellQ24TrainingCommandReceiptV1,
    pub(super) evaluation: OriginalCellEvaluationCommandReceiptV1,
    pub(super) bundle: CellCompatibilityBundleV1,
    pub(super) definition: CellDefinitionV1,
    pub(super) source_a: crate::CircuitTaskSourceInputV1,
    pub(super) source_c: crate::CircuitTaskSourceInputV1,
    config_a: codex_hepta_neuron::CellGenerationConfigV2,
    config_c: codex_hepta_neuron::CellGenerationConfigV2,
    identity_a: crate::AgentdIdentity,
    original_source: Arc<crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    completed: Option<crate::PublishedCircuitFeatureCompletionV1>,
    c: Option<support::Admission>,
}

impl PublicationFixture {
    pub(super) async fn ready() -> anyhow::Result<Self> {
        let mut host = Box::pin(HostFixture::before_adoption()).await?;
        let mut dataset = host.config.training.clone();
        let completed_training = dataset.receipts.pop().context("original native Training")?;
        dataset.head_digest = completed_training.predecessor;
        let trainer_context = OriginalCellQ24TrainingCommandContextV1 {
            dataset,
            scope: host.config.scope.clone(),
            verifier: host.config.signing.verifier.clone(),
        };
        // The publication's external Trainer commands read the same actual
        // SourceBound lane, without a static response, substituted batch,
        // reopened writer or renewed signature. B's member peers remain fixtures.
        let trainer = Arc::new(
            Trainer::recover_original_stage(
                Arc::clone(&host.original.stage),
                trainer_context.clone(),
                Arc::new(AtomicBool::new(/*v*/ false)),
            )
            .await?,
        );
        let (client, channel) = commands::client(
            trainer_context.clone(),
            /*readback_only*/ true,
            /*retained*/ None,
        )?;
        let trainer_peer = commands::serve(Arc::clone(&trainer), channel);
        let training = client.readback().await?;
        assert_eq!(training.receipt(), &completed_training);
        assert_eq!(
            training.attestation(),
            &host.original.config.training_evidence
        );
        drop(client);
        assert_eq!(trainer_peer.join().expect("original Trainer")?, 1);

        let (client, peer) = host.commands(
            /*readback_only*/ false, /*expected*/ None, "original",
        )?;
        let evaluation = client.execute_evaluation().await?;
        assert_eq!(evaluation.training_attestation(), training.attestation());
        assert!(matches!(
            evaluation.receipt().observation,
            LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::NoUpdate,
                ..
            }
        ));
        assert_eq!(finish(client, peer)?, 1);

        let bundle = evaluation.snapshot().request.selected_bundle.clone();
        let definition = support::definition(&host.original.baseline, &bundle)?;
        let config_a = host.original.version.target_config.clone();
        let mut a = host.original.session.0.take().context("same original A")?;
        let source_a = a.retirement.source().clone();
        assert_eq!(
            source_a.scope.run_id,
            evaluation.snapshot().request.source_run_id
        );
        assert_eq!(source_a.scope, host.original.previous.input().scope);
        assert_eq!(
            source_a.observation,
            host.original.previous.input().observation
        );
        let completed =
            a.retirement
                .drain_completed_task(&a.cell, a.source.as_ref(), &a.runtime.identity)?;
        let identity_a = a.runtime.identity.clone();
        let original_source = Arc::clone(&a.source);
        a.stop().await?;
        host.original._source_home = std::mem::replace(&mut a.runtime._temp, tempfile::tempdir()?);
        drop(a);

        let c = support::admission("evaluated-retention-original-C").await?;
        let source_c = support::source(&c, [Q / 4, Q])?;
        let config_c = support::configuration(
            &host.original.baseline,
            &bundle,
            &definition,
            &source_c,
            /*generation*/ 2,
        )?;
        assert_eq!(config_c.manifest, config_a.manifest);
        assert_ne!(bundle.digest()?, host.original.candidate.digest()?);
        Ok(Self {
            host,
            trainer,
            trainer_context,
            training,
            evaluation,
            bundle,
            definition,
            source_a,
            source_c,
            config_a,
            config_c,
            identity_a,
            original_source,
            completed: Some(completed),
            c: Some(c),
        })
    }

    pub(super) fn context(&self) -> anyhow::Result<OriginalCircuitEvaluatedRetentionContextV1> {
        Ok(
            OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
                self.host.config.scope.clone(),
                self.host.config.signing.verifier.clone(),
                &self.training,
                &self.evaluation,
            )?,
        )
    }

    pub(super) fn readback_context(
        &self,
    ) -> anyhow::Result<OriginalCircuitEvaluatedRetentionContextV1> {
        Ok(
            OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(
                self.host.config.scope.clone(),
                self.host.config.signing.verifier.clone(),
                &self.training,
                &self.evaluation,
            )?,
        )
    }

    pub(super) fn clients(
        &self,
    ) -> anyhow::Result<(
        OriginalCellQ24TrainingCommandClientV1,
        OriginalCellEvaluationCommandClientV1,
        Peers,
    )> {
        let (trainer, channel) = commands::client(
            self.trainer_context.clone(),
            /*readback_only*/ true,
            Some(self.training.clone()),
        )?;
        let trainer_peer = commands::serve(Arc::clone(&self.trainer), channel);
        let (evaluator, evaluator_peer) = self.host.commands(
            /*readback_only*/ true,
            Some(self.evaluation.clone()),
            "original",
        )?;
        Ok((
            trainer,
            evaluator,
            Peers {
                trainer: trainer_peer,
                evaluator: evaluator_peer,
            },
        ))
    }

    pub(super) fn inputs(
        &mut self,
    ) -> anyhow::Result<
        OriginalCircuitRetainedPublicationInputsV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    > {
        let version = &self.host.original.version;
        Ok(OriginalCircuitRetainedPublicationInputsV1 {
            current: version.reopen_current()?,
            authorities: version.authorities()?,
            selection: version.retained_publication_selection()?,
            predecessor: AgentdGenerationUpdatePredecessorFilesV1 {
                file: version.file("target-journal")?,
                witness: version.witness("target-witness", &self.config_a)?,
                config: self.config_a.clone(),
                max_records: RECORDS,
            },
            target: version.named_target_create(
                "evaluated-retained-C-journal",
                "evaluated-retained-C-witness",
                self.config_c.clone(),
            )?,
            definition: self.definition.clone(),
            source: self.source_c.clone(),
            completed: self.completed.take().context("one original drained A")?,
        })
    }

    pub(super) fn recovery(
        &self,
        intent: Digest32,
    ) -> anyhow::Result<
        OriginalCircuitEvaluatedRetentionRecoveryV1<
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
        let version = &self.host.original.version;
        Ok(OriginalCircuitEvaluatedRetentionRecoveryV1 {
            context: self.readback_context()?,
            intent_digest: intent,
            current: version.reopen_current()?,
            authorities: version.authorities()?,
            selection: version.retained_publication_selection()?,
            target: crate::AgentdGenerationUpdateTargetV1 {
                file: version.file("evaluated-retained-C-journal")?,
                witness: version.witness("evaluated-retained-C-witness", &self.config_c)?,
                config: self.config_c.clone(),
                max_records: RECORDS,
            },
            definition: self.definition.clone(),
            source: self.source_c.clone(),
            predecessor: crate::CircuitFeaturePredecessorFilesV1 {
                file: file("q24-cell.journal")?,
                witness: FileAnchorWitnessStore::open(
                    file("q24-cell.witness")?,
                    JournalScope {
                        scope_digest: cell::d("original-cell-owner"),
                        objective_digest: self.source_a.objective_digest,
                    },
                    Generation::new(/*value*/ 1)?,
                    /*max_records*/ 64,
                )?,
                definition: self.definition.clone(),
                source: self.source_a.clone(),
                manifest: self.config_a.manifest.clone(),
                maximum_records: 16,
            },
            original_source: Arc::clone(&self.original_source),
            original_identity: self.identity_a.clone(),
        })
    }

    pub(super) fn publication_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "current.json",
            "evaluated-retained-C-journal",
            "evaluated-retained-C-witness",
        ]
        .into_iter()
        .map(|name| self.host.original.version.bytes(name))
        .collect()
    }

    pub(super) async fn start_c(
        &mut self,
        task: crate::PublishedCircuitFeatureTaskV1,
    ) -> anyhow::Result<support::Session> {
        support::start(
            self.c.take().context("one original C admission")?,
            task,
            Arc::clone(&self.host.original.baseline),
            self.bundle.clone(),
        )
        .await
    }

    pub(super) async fn finish(self) -> anyhow::Result<()> {
        drop(self.trainer);
        self.host.finish().await?;
        Ok(())
    }
}

#[path = "circuit_evaluated_retention_receipt_tests.rs"]
mod receipt_tests;
