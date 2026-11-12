//! Same original A -> Material -> native NoUpdate -> retained C fixture.
//! Outcome, keys, enrollment and FinalUse are explicit test custody. The
//! terminal value is fixed before training and is never derived from output.
use super::*;
use std::thread::JoinHandle;
use std::time::Duration;

use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialEvidenceRoleV1 as Role;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24MaterialReceiptFilesV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::OriginalCellQ24TrainingBootstrapConfigV1;
use crate::OriginalCellQ24TrainingBootstrapCustodyV1;
use crate::OriginalCellQ24TrainingBootstrapErrorV1;
use crate::OriginalCellQ24TrainingBootstrapOwnerV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCellQ24TrainingReadbackConnectionV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadContextV1;
use crate::OriginalCircuitLearningReadErrorV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::OriginalCircuitNextUseReceiptConfigV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCircuitSelectionCommandOwnerV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;
use crate::OriginalCircuitSelectionReadbackConnectionV1;
use crate::OriginalCircuitSelectionReceiptConfigV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::circuit_feature_current::original_learning_read_fixture as publication;
use crate::learning_iteration_evidence_client::material_bootstrap_test_ports as material_ports;
use crate::learning_iteration_evidence_client::original_bootstrap_test_ports as trainer_ports;
use crate::learning_iteration_evidence_client::original_readback_test_ports as selector_ports;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_types::FixedQ32;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

pub(super) type Trainer =
    OriginalCellQ24TrainingBootstrapOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
pub(super) type TrainerThread = JoinHandle<Result<u64, OriginalCellQ24TrainingBootstrapErrorV1>>;
pub(super) type PublishedThread = JoinHandle<Result<u64, OriginalCircuitLearningReadErrorV1>>;
pub(super) type Selector = OriginalCircuitSelectionCommandOwnerV1<FileAnchorWitnessStore>;

pub(super) struct InitialTrainer {
    pub(super) connection: OriginalCellQ24TrainingReadbackConnectionV1,
    pub(super) server: TrainerThread,
}

pub(super) struct InitialSelector {
    pub(super) connection: OriginalCircuitSelectionReadbackConnectionV1,
    pub(super) channel: HostAuthorityPeerChannel,
}

pub(super) struct DeepFixture {
    pub(super) root: PathBuf,
    pub(super) material: OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) dataset: OriginalCellQ24MaterialCommandReceiptV1,
    pub(super) training: OriginalCellQ24TrainingCommandReceiptV1,
    pub(super) training_cut: LearningIterationSnapshotV1,
    pub(super) selector_config: OriginalCircuitSelectionReceiptConfigV1,
    pub(super) session: support::Session,
    pub(super) definition: CellDefinitionV1,
    pub(super) previous: CircuitTaskSourcePublicationV1,
    pub(super) trainer: Arc<Trainer>,
    pub(super) trainer_for_s: Option<InitialTrainer>,
    pub(super) trainer_for_c: Option<InitialTrainer>,
    pub(super) trainer_for_cold_c: Option<InitialTrainer>,
    pub(super) trainer_fault: Option<(
        OriginalCellQ24TrainingReadbackConnectionV1,
        HostAuthorityPeerChannel,
    )>,
    pub(super) selector_for_c: Option<InitialSelector>,
    pub(super) selector_for_cold_c: Option<InitialSelector>,
    pub(super) material_peers: [material_ports::Peer; 4],
    credentials: material::Credentials,
    source_paths: [PathBuf; 2],
    _version: VersionFixture,
    _source_home: tempfile::TempDir,
    _directory: tempfile::TempDir,
}

impl DeepFixture {
    pub(super) async fn ready() -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let (baseline, bundle, definition) = support::model(&root)?;
        let mut a = support::admission("deep-readonly-original-A").await?;
        let preview = support::source(&a, [Q, Q / 4])?;
        let (mut ledger, credentials) = material::ledger_at(
            &root,
            preview.objective_digest,
            now()?,
            d("deep-readonly-original-ledger"),
        )?;
        let run = crate::circuit_credit::circuit_learning_run_id_v1(
            &ledger,
            &a.runtime.identity.agent_id,
            &id("positive-original-episode"),
        )?;
        a.request.body.run_id = run.to_string();
        let source_a = support::source(&a, [Q, Q / 4])?;
        assert_eq!(source_a.scope.run_id, run);
        let config_a = support::configuration(
            &baseline,
            &bundle,
            &definition,
            &source_a,
            /*generation*/ 1,
        )?;
        let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
        let published = support::publish_initial(&version, definition.clone(), source_a.clone())?;
        let mut a = support::start(a, published, Arc::clone(&baseline), bundle.clone()).await?;
        let previous = execute(&a, /*request_id*/ 1).await?;
        material::decision(&mut ledger, &credentials, &previous)?;
        // This label is an explicit independent test outcome. No observed
        // prediction is copied into it to force NoUpdate.
        material::terminal_outcome_with_value(
            &mut ledger,
            &credentials,
            &previous,
            FixedQ32::from_raw(1_i64 << 32),
        )?;
        let (config, optimizer) = material::unstarted_material_with_profile(
            &root,
            &mut ledger,
            &credentials,
            a.source.as_ref(),
            &a.runtime.identity,
            &baseline,
            &bundle,
            &previous,
            d("deep-readonly-fixed-profile"),
            credentials.observer.principal.principal_id.clone(),
        )?;
        let objective = config.initial.request.envelope.objective_digest;
        let pair = OriginalCellQ24MaterialReceiptOwnersV1::create(
            OriginalCellQ24MaterialReceiptFilesV1 {
                experience: opened(&root, "deep-experience", /*create*/ true)?,
                experience_witness: original_witness(
                    &root,
                    "deep-experience-witness",
                    &config.scope,
                    objective,
                    /*create*/ true,
                )?,
                dataset: opened(&root, "deep-dataset", /*create*/ true)?,
                dataset_witness: original_witness(
                    &root,
                    "deep-dataset-witness",
                    &config.scope,
                    objective,
                    /*create*/ true,
                )?,
            },
            config.clone(),
            SigningKey::from_bytes(&[44; 32]),
            SigningKey::from_bytes(&[45; 32]),
        )?;
        let material_host = Arc::new(pair.into_command_owner(
            a.source.as_ref().clone(),
            a.runtime.identity.clone(),
            Arc::new(Mutex::new(ledger)),
            Arc::clone(&baseline),
        )?);
        // All four upstream connections precede Material completion. They
        // remain the same physical sessions throughout T, S, C and cold C.
        let (dataset_client, dataset_peer) = material_ports::commands_for_original(
            Arc::clone(&material_host),
            config.clone(),
            Role::Dataset,
        )?;
        let dataset_readback = dataset_client.into_original_dataset_readback(&config)?;
        let (source, source_peer) = material_ports::source_for_original(
            Arc::clone(&material_host),
            &config,
            Arc::clone(&baseline),
            Duration::from_secs(300),
        )?;
        let (experience, experience_peer) = material_ports::evidence_for_original(
            Arc::clone(&material_host),
            &config,
            Role::Experience,
        )?;
        let (dataset_evidence, evidence_peer) = material_ports::evidence_for_original(
            Arc::clone(&material_host),
            &config,
            Role::Dataset,
        )?;
        let trainer = Arc::new(Trainer::from_original_custody(
            OriginalCellQ24TrainingBootstrapCustodyV1 {
                native_file: opened(&root, "deep-native-training", /*create*/ true)?,
                native_witness: original_witness(
                    &root,
                    "deep-native-witness",
                    &config.scope,
                    objective,
                    /*create*/ true,
                )?,
                receipt_file: opened(&root, "deep-training-receipt", /*create*/ true)?,
                receipt_witness: original_witness(
                    &root,
                    "deep-training-witness",
                    &config.scope,
                    objective,
                    /*create*/ true,
                )?,
                generator_key: SigningKey::from_bytes(&[41; 32]),
                baseline: Arc::clone(&baseline),
                material_source: source,
                experience,
                dataset: dataset_evidence,
            },
            OriginalCellQ24TrainingBootstrapConfigV1 {
                material: config.clone(),
                optimizer,
                generator: credentials.generator.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            dataset_readback,
            Arc::new(AtomicBool::new(/*v*/ false)),
        )?);
        let (training_connection, training_server) =
            trainer_ports::command(Arc::clone(&trainer), config.clone())?;
        let initial_trainer = || -> anyhow::Result<InitialTrainer> {
            let (connection, server) =
                trainer_ports::readonly(Arc::clone(&trainer), config.clone())?;
            Ok(InitialTrainer { connection, server })
        };
        let trainer_for_s = initial_trainer()?;
        let trainer_for_c = initial_trainer()?;
        let trainer_for_cold_c = initial_trainer()?;
        let trainer_fault = trainer_ports::readonly_channel(config.clone())?;
        let initial_selector = || -> anyhow::Result<InitialSelector> {
            let (connection, channel) = selector_ports::connection(config.clone())?;
            Ok(InitialSelector {
                connection,
                channel,
            })
        };
        let selector_for_c = initial_selector()?;
        let selector_for_cold_c = initial_selector()?;

        let (experience_client, experience_command) = material_ports::commands_for_original(
            Arc::clone(&material_host),
            config.clone(),
            Role::Experience,
        )?;
        let original_experience = experience_client.execute().await?;
        drop(experience_client);
        assert_eq!(material_ports::finish(experience_command)?, 1);
        let (dataset_client, dataset_command) = material_ports::commands_for_original(
            Arc::clone(&material_host),
            config.clone(),
            Role::Dataset,
        )?;
        let dataset = dataset_client.execute().await?;
        assert_eq!(
            dataset.snapshot().receipts[0],
            *original_experience.receipt()
        );
        assert_eq!(
            dataset.attestations()[0],
            *original_experience.attestation()
        );
        drop(dataset_client);
        assert_eq!(material_ports::finish(dataset_command)?, 1);
        drop(material_host);
        let client = training_connection.bind_original_dataset(dataset.clone())?;
        let before_heads = fs::read(root.join("heads"))?;
        let training = client
            .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
            .await?;
        assert!(matches!(
            training.receipt().observation,
            LearningIterationObservationV1::TrainingNoUpdateV2(_)
        ));
        assert_eq!(fs::read(root.join("heads"))?, before_heads);
        drop(client);
        assert_eq!(
            training_server
                .join()
                .map_err(|_| anyhow::anyhow!("actual Trainer command"))??,
            1
        );
        let mut decision =
            LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        decision.record(
            training.receipt().clone(),
            training.receipt().observed_unix_seconds,
        )?;
        let training_cut = decision.snapshot().clone();
        assert_eq!(
            decision.next_stage(),
            Some(LearningIterationStageV1::Selection)
        );
        let completion =
            a.retirement
                .drain_completed_task(&a.cell, a.source.as_ref(), &a.runtime.identity)?;
        a.stop().await?;
        let source_paths = [
            a.runtime.identity.home_root.join("q24-source.journal"),
            a.runtime.identity.home_root.join("q24-source.witness"),
        ];
        let source_home = std::mem::replace(&mut a.runtime._temp, tempfile::tempdir()?);
        drop(a);

        let c = support::admission("deep-readonly-original-C").await?;
        let source_c = support::source(&c, [Q / 4, Q])?;
        assert_ne!(source_a.scope.run_id, source_c.scope.run_id);
        assert_ne!(source_a.observation, source_c.observation);
        let config_c = support::configuration(
            &baseline,
            &bundle,
            &definition,
            &source_c,
            /*generation*/ 2,
        )?;
        let operation = crate::learning_retained_task_operation_id_v1(&decision)?;
        // The test's already enrolled version/FinalUse owner supplies the
        // ordinary retained-task publication. No learning receipt is a grant.
        let prepared = crate::prepare_agentd_generation_cold_same_model_task_v1(
            version.reopen_current()?,
            version.authorities()?,
            AgentdGenerationUpdatePredecessorFilesV1 {
                file: version.file("target-journal")?,
                witness: version.witness("target-witness", &config_a)?,
                config: config_a,
                max_records: RECORDS,
            },
            version.selection()?,
            version.named_target_create("deep-C-journal", "deep-C-witness", config_c)?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: operation.to_string(),
            },
        )?;
        let final_use = version.sign(prepared.final_use_binding())?;
        let published = prepared.publish(&final_use)?.into_circuit_feature_task(
            definition.clone(),
            source_c,
            completion,
        )?;
        let session = support::start(c, published, baseline, bundle).await?;
        let selector_config = OriginalCircuitSelectionReceiptConfigV1 {
            decision: training_cut.clone(),
            scope: config.scope.clone(),
            signer: credentials.selector.clone(),
            verifier: config.verifier.clone(),
            training_evidence: training.attestation().clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        Ok(Self {
            root,
            material: config,
            dataset,
            training,
            training_cut,
            selector_config,
            session,
            definition,
            previous,
            trainer,
            trainer_for_s: Some(trainer_for_s),
            trainer_for_c: Some(trainer_for_c),
            trainer_for_cold_c: Some(trainer_for_cold_c),
            trainer_fault: Some(trainer_fault),
            selector_for_c: Some(selector_for_c),
            selector_for_cold_c: Some(selector_for_cold_c),
            material_peers: [dataset_peer, source_peer, experience_peer, evidence_peer],
            credentials,
            source_paths,
            _version: version,
            _source_home: source_home,
            _directory: directory,
        })
    }

    pub(super) fn selector(
        &self,
    ) -> anyhow::Result<OriginalCircuitSelectionReceiptOwnerV1<FileAnchorWitnessStore>> {
        Ok(OriginalCircuitSelectionReceiptOwnerV1::create(
            opened(&self.root, "deep-selector", /*create*/ true)?,
            original_witness(
                &self.root,
                "deep-selector-witness",
                &self.material.scope,
                self.material.initial.request.envelope.objective_digest,
                /*create*/ true,
            )?,
            self.selector_config.clone(),
            SigningKey::from_bytes(&[46; 32]),
        )?)
    }

    pub(super) fn published(
        &self,
        prefix: LearningIterationSnapshotV1,
        selection: Option<SignedLearningEvidenceV1>,
    ) -> anyhow::Result<(OriginalCircuitLearningReadClientV1, PublishedThread)> {
        let context = OriginalCircuitLearningReadContextV1 {
            prefix,
            scope: self.material.scope.clone(),
            verifier: self.material.verifier.clone(),
            training_evidence: self.training.attestation().clone(),
            selection_evidence: selection,
        };
        let owner = Arc::new(OriginalCircuitLearningReadOwnerV1::from_original_owners(
            self.session.cell.clone(),
            self.session.source.as_ref().clone(),
            self.session.runtime.identity.clone(),
            context.clone(),
        )?);
        let (client, channel) = publication::client(context)?;
        Ok((client, publication::serve(owner, channel)))
    }

    pub(super) fn observer_config(
        &self,
        selection: &OriginalCircuitSelectionCommandReceiptV1,
    ) -> OriginalCircuitNextUseReceiptConfigV1 {
        OriginalCircuitNextUseReceiptConfigV1 {
            selection: selection.snapshot().clone(),
            scope: self.material.scope.clone(),
            signer: self.credentials.observer.clone(),
            verifier: self.material.verifier.clone(),
            training_evidence: self.training.attestation().clone(),
            selection_evidence: selection.attestation().clone(),
            maximum_signature_lifetime_seconds: 300,
        }
    }

    pub(super) fn observer(
        &self,
        config: &OriginalCircuitNextUseReceiptConfigV1,
        create: bool,
    ) -> anyhow::Result<OriginalCircuitNextUseReceiptOwnerV1<FileAnchorWitnessStore>> {
        let file = opened(&self.root, "deep-observer", create)?;
        let witness = original_witness(
            &self.root,
            "deep-observer-witness",
            &self.material.scope,
            self.material.initial.request.envelope.objective_digest,
            create,
        )?;
        Ok(if create {
            OriginalCircuitNextUseReceiptOwnerV1::create(
                file,
                witness,
                config.clone(),
                SigningKey::from_bytes(&[43; 32]),
            )?
        } else {
            OriginalCircuitNextUseReceiptOwnerV1::recover(
                file,
                witness,
                config.clone(),
                SigningKey::from_bytes(&[43; 32]),
            )?
        })
    }

    pub(super) fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut paths = [
            "positive-ledger",
            "positive-ledger-witness",
            "deep-experience",
            "deep-experience-witness",
            "deep-dataset",
            "deep-dataset-witness",
            "deep-native-training",
            "deep-native-witness",
            "deep-training-receipt",
            "deep-training-witness",
            "heads",
        ]
        .into_iter()
        .map(|name| self.root.join(name))
        .collect::<Vec<_>>();
        paths.extend(self.source_paths.iter().cloned());
        paths
            .into_iter()
            .map(|path| fs::read(path).map_err(anyhow::Error::from))
            .collect()
    }

    pub(super) fn receipt_bytes(&self, role: &str) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            fs::read(self.root.join(format!("deep-{role}")))?,
            fs::read(self.root.join(format!("deep-{role}-witness")))?,
        ])
    }

    pub(super) async fn finish(mut self) -> anyhow::Result<[u64; 4]> {
        self.session.stop().await?;
        let Self {
            trainer,
            trainer_for_s,
            trainer_for_c,
            trainer_for_cold_c,
            trainer_fault,
            selector_for_c,
            selector_for_cold_c,
            material_peers,
            _directory,
            _source_home,
            _version,
            session,
            ..
        } = self;
        for retained in [trainer_for_s, trainer_for_c, trainer_for_cold_c]
            .into_iter()
            .flatten()
        {
            drop(retained.connection);
            assert_eq!(
                retained
                    .server
                    .join()
                    .map_err(|_| anyhow::anyhow!("unused original Trainer"))??,
                0
            );
        }
        drop(selector_for_c);
        drop(selector_for_cold_c);
        drop(trainer_fault);
        drop(trainer);
        let [dataset, source, experience, evidence] = material_peers;
        let counts = [
            material_ports::finish(dataset)?,
            material_ports::finish(source)?,
            material_ports::finish(experience)?,
            material_ports::finish(evidence)?,
        ];
        eprintln!(
            "HEPTA_DEEP_S_C_MATERIAL_COUNTS dataset={} source={} experience={} dataset_evidence={}",
            counts[0], counts[1], counts[2], counts[3]
        );
        assert!(counts.iter().all(|count| *count < 128));
        drop(session);
        Ok(counts)
    }
}
