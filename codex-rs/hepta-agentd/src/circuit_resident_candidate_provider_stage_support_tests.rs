//! Preserve original Fresh custody while advancing actual Material -> T -> B.
//! Every response is produced by the original owner. This local fixture uses
//! existing same-process adapters, not public different-UID admission.
use super::super::evaluation_provider::fresh_training::CompletedBPanel;
use super::super::evaluation_provider::fresh_training::CompletedTrainingInputs;
use super::super::evaluation_provider::fresh_training::PreparedBPanel;
use super::original_material::ProviderAdmission;
use super::original_material::UnstartedProvider;
use super::*;
use crate::OriginalCellEvaluationCommandClientV1 as EvaluationClient;
use crate::OriginalCellEvaluationCommandConnectionV1 as EvaluationConnection;
use crate::OriginalCellEvaluationCommandReceiptV1 as EvaluationReceipt;
use crate::OriginalCellQ24CandidateMaterialV1 as Candidate;
use crate::OriginalCellQ24CandidateReadbackClientV1 as CandidateClient;
use crate::OriginalCellQ24DatasetCommandReadbackV1 as DatasetReadback;
use crate::OriginalCellQ24MaterialCommandClientV1 as MaterialClient;
use crate::OriginalCellQ24MaterialCommandReceiptV1 as DatasetReceipt;
use crate::OriginalCellQ24MaterialEvidenceRoleV1 as Role;
use crate::OriginalCellQ24TrainingCommandClientV1 as TrainingClient;
use crate::OriginalCellQ24TrainingCommandConnectionV1 as TrainingConnection;
use crate::OriginalCellQ24TrainingCommandReceiptV1 as TrainingReceipt;
use crate::learning_iteration_evidence_client::original_bootstrap_test_ports as training_ports;
use crate::learning_iteration_evidence_client::original_material_bootstrap_test_ports as material_ports;
use anyhow::Context as _;

type TrainerPeer =
    std::thread::JoinHandle<Result<u64, crate::OriginalCellQ24TrainingBootstrapErrorV1>>;
type EvaluationPeer = std::thread::JoinHandle<anyhow::Result<u64>>;

/// Initial typed connections are consumed once. The outer fixture must drop
/// any Version/S/C clones before finish. No field can replace a failed owner.
pub(super) struct FreshStages {
    pub(super) original: Option<Box<UnstartedProvider>>,
    prepared_b: Option<PreparedBPanel>,
    pub(super) panel: Option<CompletedBPanel>,
    experience: Option<MaterialClient>,
    dataset: Option<MaterialClient>,
    root_trainer_initial: Option<TrainingConnection>,
    pub(super) root_trainer: Option<TrainingClient>,
    pub(super) candidate_client: Option<CandidateClient>,
    training_peers: Option<training_ports::OriginalTrainingPeers>,
    pub(super) version_dataset: Option<DatasetReadback>,
    pub(super) version_trainer: Option<TrainingConnection>,
    pub(super) version_evaluator: Option<EvaluationConnection>,
    pub(super) root_evaluator: Option<EvaluationClient>,
    pub(super) dataset_receipt: Option<DatasetReceipt>,
    pub(super) training: Option<TrainingReceipt>,
    pub(super) candidate: Option<Candidate>,
    pub(super) evaluation: Option<EvaluationReceipt>,
    material_servers: Vec<material_ports::Peer>,
    training_servers: Vec<TrainerPeer>,
    evaluation_servers: Vec<EvaluationPeer>,
}

impl FreshStages {
    pub(super) async fn new() -> anyhow::Result<Self> {
        let admission = Box::pin(ProviderAdmission::new()).await?;
        // Freeze B's original declaration before Material signs the operation.
        let prepared_b = PreparedBPanel::new(admission.objective, admission.trust_time)?;
        let profile = prepared_b.registration().evaluation_profile();
        let original = Box::new(Box::pin(UnstartedProvider::new(admission, profile)).await?);
        let mut result = Self {
            original: Some(original),
            prepared_b: Some(prepared_b),
            panel: None,
            experience: None,
            dataset: None,
            root_trainer_initial: None,
            root_trainer: None,
            candidate_client: None,
            training_peers: None,
            version_dataset: None,
            version_trainer: None,
            version_evaluator: None,
            root_evaluator: None,
            dataset_receipt: None,
            training: None,
            candidate: None,
            evaluation: None,
            material_servers: Vec::new(),
            training_servers: Vec::new(),
            evaluation_servers: Vec::new(),
        };
        if let Err(error) = result.connect_originals() {
            let cleanup = result.finish().await;
            return Err(error.context(format!("original connection cleanup: {cleanup:?}")));
        }
        Ok(result)
    }

    pub(super) fn original(&self) -> anyhow::Result<&UnstartedProvider> {
        self.original
            .as_deref()
            .context("same unstarted original custody")
    }

    fn connect_originals(&mut self) -> anyhow::Result<()> {
        let original = self.original()?;
        anyhow::ensure!(original.material.initial.receipts.is_empty());
        let host = Arc::clone(&original.material_owner);
        let trainer = Arc::clone(&original.trainer);
        let material = original.material.clone();
        let (experience, peer) = material_ports::commands_for_original(
            Arc::clone(&host),
            material.clone(),
            Role::Experience,
        )?;
        self.experience = Some(experience);
        self.material_servers.push(peer);
        let (dataset, peer) = material_ports::commands_for_original(
            Arc::clone(&host),
            material.clone(),
            Role::Dataset,
        )?;
        self.dataset = Some(dataset);
        self.material_servers.push(peer);
        let (dataset, peer) =
            material_ports::commands_for_original(host, material.clone(), Role::Dataset)?;
        self.material_servers.push(peer);
        self.version_dataset = Some(dataset.into_original_dataset_readback(&material)?);
        let (root, peer) = training_ports::command(Arc::clone(&trainer), material.clone())?;
        self.root_trainer_initial = Some(root);
        self.training_servers.push(peer);
        let (version, peer) = training_ports::command(Arc::clone(&trainer), material.clone())?;
        self.version_trainer = Some(version);
        self.training_servers.push(peer);
        // Four actual T transports: root command, Candidate, one shared B
        // evidence connection, and Version command (later shared by V/S/C).
        // These are fixture transports, not a public semaphore assertion.
        self.training_peers = Some(training_ports::OriginalTrainingPeers::new_shared(
            trainer, material,
        )?);
        Ok(())
    }

    pub(super) async fn complete_training(&mut self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.training.is_none() && self.dataset_receipt.is_none(),
            "one Fresh original execution sequence"
        );
        let original = self.original()?;
        anyhow::ensure!(
            std::fs::metadata(original.root.join("positive-native-training"))?.len() == 0
        );
        anyhow::ensure!(
            std::fs::metadata(original.root.join("positive-training-receipt"))?.len() == 0
        );
        let experience = self
            .experience
            .as_ref()
            .context("original Experience client")?
            .execute()
            .await?;
        anyhow::ensure!(experience.snapshot().receipts.len() == 1);
        let dataset = self
            .dataset
            .as_ref()
            .context("original Dataset client")?
            .execute()
            .await?;
        anyhow::ensure!(dataset.snapshot().receipts.len() == 2);
        anyhow::ensure!(dataset.snapshot().receipts[0] == *experience.receipt());
        let client = self
            .root_trainer_initial
            .take()
            .context("one original initial T")?
            .bind_original_dataset(dataset.clone())?;
        self.root_trainer = Some(client);
        // Completion is the actual original Execute future's return. A Ready
        // bootstrap observation alone never authorizes Candidate or B work.
        let training = self
            .root_trainer
            .as_ref()
            .context("bound original T")?
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await?;
        let baseline = Arc::clone(&self.original()?.baseline);
        let candidate_initial = self
            .training_peers
            .as_mut()
            .context("held original Candidate")?
            .take_candidate()?;
        let candidate = candidate_initial.bind_original_candidate_material(
            dataset.clone(),
            training.clone(),
            baseline,
        )?;
        self.candidate_client = Some(candidate);
        let candidate = self
            .candidate_client
            .as_ref()
            .context("original Candidate reader")?
            .readback()
            .await?;
        anyhow::ensure!(candidate.receipt() == training.receipt());
        anyhow::ensure!(candidate.attestation() == training.attestation());
        anyhow::ensure!(candidate.authority() == AuthorityPosture::DENY_ALL);
        anyhow::ensure!(candidate.bundle().digest()? != self.original()?.bundle.digest()?);
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        coordinator.record(
            training.receipt().clone(),
            training.receipt().observed_unix_seconds,
        )?;
        anyhow::ensure!(coordinator.snapshot().receipts.len() == 3);
        anyhow::ensure!(coordinator.next_stage() == Some(LearningIterationStageV1::Evaluation));
        self.dataset_receipt = Some(dataset);
        self.training = Some(training);
        self.candidate = Some(candidate);
        Ok(())
    }

    pub(super) async fn complete_b_and_evaluation(&mut self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.panel.is_none() && self.evaluation.is_none(),
            "one pre-registered independent mechanism B panel"
        );
        let dataset = self
            .dataset_receipt
            .as_ref()
            .context("actual D before B")?
            .clone();
        let training = self.training.as_ref().context("actual T before B")?.clone();
        let trainer = self
            .training_peers
            .as_mut()
            .context("held actual B readback")?
            .take_shared_trainer()?
            .bind_original_training(dataset.clone(), training.clone())?;
        let trainer = Arc::new(trainer);
        let prepared = self
            .prepared_b
            .take()
            .context("one original B declaration")?;
        let original = self.original()?;
        let input = CompletedTrainingInputs::from_original_completion(
            &original.material,
            &dataset,
            &training,
            self.candidate
                .as_ref()
                .context("actual original Candidate")?,
            original.baseline.as_ref(),
            &original.previous,
            &original.source_a,
            &original.config_a,
            &original.credentials,
        )?;
        let panel =
            Box::pin(prepared.complete_with_shared_original_trainer(&input, trainer)).await?;
        drop(input);
        self.panel = Some(panel);
        let host = self
            .panel
            .as_ref()
            .context("actual B panel")?
            .host
            .as_ref()
            .context("same original E host")?;
        // This staged fixture constructs E only after actual B exists. It does
        // not claim all ten cross-UID endpoints were delivered before T.
        let (version, peer) = host.fixture_original_readback_connection()?;
        self.version_evaluator = Some(version);
        self.evaluation_servers.push(peer);
        let (client, peer) = host.fixture_commands(false, None, "original")?;
        self.root_evaluator = Some(client);
        self.evaluation_servers.push(peer);
        let evaluation = self
            .root_evaluator
            .as_ref()
            .context("original E client")?
            .execute_evaluation()
            .await?;
        anyhow::ensure!(evaluation.training_attestation() == training.attestation());
        anyhow::ensure!(evaluation.snapshot().receipts.len() == 4);
        anyhow::ensure!(matches!(
            evaluation.receipt().observation,
            LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::NoUpdate,
                ..
            }
        ));
        anyhow::ensure!(evaluation.snapshot().request.selected_bundle == self.original()?.bundle);
        anyhow::ensure!(
            LearningIterationCoordinatorV1::from_snapshot(evaluation.snapshot().clone(),)?
                .next_stage()
                == Some(LearningIterationStageV1::Selection)
        );
        self.evaluation = Some(evaluation);
        Ok(())
    }

    pub(super) fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = self.original()?.original_bytes()?;
        if let Some(panel) = &self.panel {
            bytes.extend(panel.original_files()?);
            bytes.extend(panel.upstream_files()?);
        }
        Ok(bytes)
    }

    pub(super) fn close_evaluation_clients(&mut self) -> anyhow::Result<Vec<u64>> {
        drop(self.root_evaluator.take());
        drop(self.version_evaluator.take());
        let mut counts = Vec::new();
        let mut errors = Vec::new();
        for peer in self.evaluation_servers.drain(..) {
            match peer.join() {
                Ok(Ok(count)) => counts.push(count),
                Ok(Err(error)) => errors.push(error.to_string()),
                Err(_) => errors.push("original E peer panicked".into()),
            }
        }
        anyhow::ensure!(errors.is_empty(), "all original E peers joined: {errors:?}");
        Ok(counts)
    }

    pub(super) async fn finish(mut self) -> anyhow::Result<()> {
        let mut errors = Vec::new();
        if let Err(error) = self.close_evaluation_clients() {
            errors.push(error.to_string());
        }
        if let Some(panel) = self.panel.take() {
            if let Err(error) = panel.finish() {
                errors.push(error.to_string());
            }
        }
        drop(self.candidate_client.take());
        drop(self.root_trainer.take());
        drop(self.root_trainer_initial.take());
        drop(self.version_trainer.take());
        drop(self.version_dataset.take());
        drop(self.experience.take());
        drop(self.dataset.take());
        if let Some(peers) = self.training_peers.take() {
            if let Err(error) = peers.finish_shared() {
                errors.push(error.to_string());
            }
        }
        for peer in self.training_servers.drain(..) {
            match peer.join() {
                Ok(Ok(_)) => {}
                Ok(Err(error)) => errors.push(error.to_string()),
                Err(_) => errors.push("original T peer panicked".into()),
            }
        }
        for peer in self.material_servers.drain(..) {
            if let Err(error) = material_ports::finish(peer) {
                errors.push(error.to_string());
            }
        }
        if let Some(original) = self.original.take() {
            if let Err(error) = (*original).finish().await {
                errors.push(error.to_string());
            }
        }
        anyhow::ensure!(
            errors.is_empty(),
            "all staged original owners joined: {errors:?}"
        );
        Ok(())
    }
}

pub(super) async fn finish_case(
    result: anyhow::Result<()>,
    fixture: FreshStages,
) -> anyhow::Result<()> {
    let cleanup = fixture.finish().await;
    match (result, cleanup) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
        (Err(error), Err(cleanup)) => Err(error.context(format!("original cleanup: {cleanup:#}"))),
    }
}
