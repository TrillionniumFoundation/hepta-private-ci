//! Staged, mechanism-only B/retention over an actual Fresh Bootstrap T.
//! Registration precedes T. Neither constructor runs PositiveFixture's
//! auxiliary Evaluation/Model path. The two real Trainer servers remain owned
//! by OriginalTrainingPeers outside this fixture and are explicitly joined.
pub(in super::super) use super::source::BorrowedOriginalObjective;
use super::*;
use crate::OriginalCellEvaluationHostV1;
use crate::OriginalCellEvaluationPanelOwnerV1;
use crate::OriginalCellEvaluationReceiptConfigV1;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::OriginalCellQ24CandidateMaterialV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::neuron_cell_evaluation::tests::original_provider::panel_members::PanelMemberFixture;
use material::evaluation_provider::DecisionBinding;

type Panel = OriginalCellEvaluationPanelOwnerV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

/// A borrowed view of original completed inputs, not another owner or signer.
/// Candidate is opaque production readback material; both manifests are built
/// from its actual model and the original loaded baseline, without prior E.
pub(in super::super) struct CompletedTrainingInputs<'a> {
    material: &'a OriginalCellQ24MaterialReceiptConfigV1,
    objective: BorrowedOriginalObjective<'a>,
    training: LearningIterationSnapshotV1,
    training_evidence: &'a SignedLearningEvidenceV1,
    baseline: Digest32,
    candidate: Digest32,
    manifests: [CellBackendManifestV2; 2],
    credentials: &'a material::Credentials,
}

impl<'a> CompletedTrainingInputs<'a> {
    pub(in super::super) fn from_original_completion(
        material: &'a OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &'a OriginalCellQ24TrainingCommandReceiptV1,
        candidate: &OriginalCellQ24CandidateMaterialV1,
        baseline: &LoadedCellQ24ModelV1,
        previous: &'a CircuitTaskSourcePublicationV1,
        source_a: &crate::CircuitTaskSourceInputV1,
        config_a: &codex_hepta_neuron::CellGenerationConfigV2,
        credentials: &'a material::Credentials,
    ) -> anyhow::Result<Self> {
        OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        )?;
        anyhow::ensure!(
            material.initial.receipts.is_empty() && dataset.snapshot().receipts.len() == 2
        );
        anyhow::ensure!(candidate.receipt() == training.receipt());
        anyhow::ensure!(candidate.attestation() == training.attestation());
        anyhow::ensure!(candidate.authority() == AuthorityPosture::DENY_ALL);
        anyhow::ensure!(
            baseline.components() == &material.initial.request.selected_bundle.components
        );
        // Match the original Source input projection, retaining the operation
        // identity already authenticated by the opaque publication.
        let expected_input = codex_hepta_neuron::CellStepInputV1 {
            operation_id: previous.input().operation_id.clone(),
            scope: source_a.scope.clone(),
            source_frontier: source_a.source_frontier,
            objective_digest: source_a.objective_digest,
            ndu_snapshot_digest: source_a.ndu_snapshot_digest,
            monotonic_micros: source_a.monotonic_micros,
            deadline_micros: source_a.deadline_micros,
            observation: source_a.observation.clone(),
            candidates: source_a.candidates.clone(),
        };
        anyhow::ensure!(previous.input() == &expected_input);
        anyhow::ensure!(source_a.scope.run_id == material.initial.request.source_run_id);
        anyhow::ensure!(
            source_a.objective_digest == material.initial.request.envelope.objective_digest
        );
        anyhow::ensure!(
            previous.history_digest().as_str().parse::<Digest32>()?
                == material.initial.request.completed_task_receipt
        );
        anyhow::ensure!(
            credentials.generator.principal.principal_id == material.initial.owners.trainer
        );
        anyhow::ensure!(
            credentials.evaluator.principal.principal_id == material.initial.owners.evaluator
        );
        let mut cut = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        cut.record(
            training.receipt().clone(),
            training.receipt().observed_unix_seconds,
        )?;
        anyhow::ensure!(cut.next_stage() == Some(LearningIterationStageV1::Evaluation));
        anyhow::ensure!(cut.snapshot().receipts.len() == 3);
        let baseline_bundle = &material.initial.request.selected_bundle;
        let baseline_definition = support::definition(baseline, baseline_bundle)?;
        let baseline_manifest =
            support::configuration(baseline, baseline_bundle, &baseline_definition, source_a, 1)?
                .manifest;
        anyhow::ensure!(baseline_manifest == config_a.manifest);
        let candidate_definition = support::definition(candidate.model(), candidate.bundle())?;
        let candidate_manifest = support::configuration(
            candidate.model(),
            candidate.bundle(),
            &candidate_definition,
            source_a,
            2,
        )?
        .manifest;
        Ok(Self {
            material,
            objective: BorrowedOriginalObjective::from_original_record(previous.original_record()),
            training: cut.snapshot().clone(),
            training_evidence: training.attestation(),
            baseline: baseline_bundle.digest()?,
            candidate: candidate.bundle().digest()?,
            manifests: [candidate_manifest, baseline_manifest],
            credentials,
        })
    }

    /// Receive a complete pre-held comparison objective separately from A's
    /// Source owner. The original opaque D/T/Candidate checks still execute;
    /// expected A history is compared to authenticated D, never to itself in
    /// initial. This test-only view grants neither Root nor Training authority.
    pub(in super::super) fn from_preheld_objective_and_original_completion(
        material: &'a OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &'a OriginalCellQ24TrainingCommandReceiptV1,
        candidate: &OriginalCellQ24CandidateMaterialV1,
        baseline: &LoadedCellQ24ModelV1,
        objective: BorrowedOriginalObjective<'a>,
        source_a: &crate::CircuitTaskSourceInputV1,
        expected_completed_a: Digest32,
        config_a: &codex_hepta_neuron::CellGenerationConfigV2,
        credentials: &'a material::Credentials,
    ) -> anyhow::Result<Self> {
        OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        )?;
        anyhow::ensure!(
            material.initial.receipts.is_empty() && dataset.snapshot().receipts.len() == 2
        );
        anyhow::ensure!(candidate.receipt() == training.receipt());
        anyhow::ensure!(candidate.attestation() == training.attestation());
        anyhow::ensure!(candidate.authority() == AuthorityPosture::DENY_ALL);
        anyhow::ensure!(
            baseline.components() == &material.initial.request.selected_bundle.components
        );
        // The source input and expected history are trusted host inputs,
        // not fields chosen by an unauthenticated child report. The actual D
        // is the original owner attestation that checked the live Source.
        anyhow::ensure!(objective.objective_digest == source_a.objective_digest);
        anyhow::ensure!(
            source_a.scope.agent_id == material.initial.request.agent_id
                && source_a.scope.cell_id == material.initial.request.cell_id
                && source_a.scope.principal_digest.to_string()
                    == material.initial.request.principal_id.as_str(),
            "complete pre-held A source identity matches original Material"
        );
        anyhow::ensure!(source_a.scope.run_id == material.initial.request.source_run_id);
        anyhow::ensure!(
            source_a.objective_digest == material.initial.request.envelope.objective_digest
        );
        anyhow::ensure!(
            !expected_completed_a.is_zero()
                && dataset.snapshot().request.completed_task_receipt == expected_completed_a,
            "pre-held A history is certified by the actual original D prefix"
        );
        anyhow::ensure!(
            credentials.generator.principal.principal_id == material.initial.owners.trainer
        );
        anyhow::ensure!(
            credentials.evaluator.principal.principal_id == material.initial.owners.evaluator
        );
        let mut cut = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        cut.record(
            training.receipt().clone(),
            training.receipt().observed_unix_seconds,
        )?;
        anyhow::ensure!(cut.next_stage() == Some(LearningIterationStageV1::Evaluation));
        anyhow::ensure!(cut.snapshot().receipts.len() == 3);
        let baseline_bundle = &material.initial.request.selected_bundle;
        let baseline_definition = support::definition(baseline, baseline_bundle)?;
        let baseline_config =
            support::configuration(baseline, baseline_bundle, &baseline_definition, source_a, 1)?;
        anyhow::ensure!(
            baseline_config.task_digest == config_a.task_digest
                && baseline_config.source_frontier == config_a.source_frontier
                && baseline_config.initial.scope == config_a.initial.scope,
            "complete pre-held A input remains bound to its original task config"
        );
        let baseline_manifest = baseline_config.manifest;
        anyhow::ensure!(baseline_manifest == config_a.manifest);
        let candidate_definition = support::definition(candidate.model(), candidate.bundle())?;
        let candidate_manifest = support::configuration(
            candidate.model(),
            candidate.bundle(),
            &candidate_definition,
            source_a,
            2,
        )?
        .manifest;
        Ok(Self {
            material,
            objective,
            training: cut.snapshot().clone(),
            training_evidence: training.attestation(),
            baseline: baseline_bundle.digest()?,
            candidate: candidate.bundle().digest()?,
            manifests: [candidate_manifest, baseline_manifest],
            credentials,
        })
    }
}

/// Created before Material/T; its frozen registration is supplied to the
/// original initial request. No later receipt or profile is rewritten.
pub(in super::super) struct PreparedBPanel {
    primary: BFixture,
    retention: BFixture,
    registration: crate::OriginalCellEvaluationPanelRegistrationV1,
}

impl PreparedBPanel {
    pub(in super::super) fn new(objective: Digest32, trust_time: u64) -> anyhow::Result<Self> {
        let primary = BFixture::new("original-B", objective, trust_time)?;
        let retention = BFixture::new("original-retention", objective, trust_time)?;
        let registration = crate::OriginalCellEvaluationPanelRegistrationV1::new(
            primary.task()?,
            vec![retention.task()?],
        )?;
        Ok(Self {
            primary,
            retention,
            registration,
        })
    }

    pub(in super::super) fn registration(
        &self,
    ) -> &crate::OriginalCellEvaluationPanelRegistrationV1 {
        &self.registration
    }

    pub(in super::super) fn complete<'a>(
        self,
        input: &'a CompletedTrainingInputs<'a>,
        primary_trainer: LearningIterationEvidenceClientV1,
        retention_trainer: LearningIterationEvidenceClientV1,
    ) -> impl std::future::Future<Output = anyhow::Result<CompletedBPanel>> + 'a {
        self.complete_with_trainers(
            input,
            Arc::new(primary_trainer),
            Arc::new(retention_trainer),
        )
    }

    /// Existing production PanelMemberOwners already takes Arc evidence-only
    /// clients. Sequential B reads share one original channel and its limits.
    pub(in super::super) fn complete_with_shared_original_trainer<'a>(
        self,
        input: &'a CompletedTrainingInputs<'a>,
        trainer: Arc<LearningIterationEvidenceClientV1>,
    ) -> impl std::future::Future<Output = anyhow::Result<CompletedBPanel>> + 'a {
        self.complete_with_trainers(input, Arc::clone(&trainer), trainer)
    }

    fn complete_with_trainers<'a>(
        self,
        input: &'a CompletedTrainingInputs<'a>,
        primary_trainer: Arc<LearningIterationEvidenceClientV1>,
        retention_trainer: Arc<LearningIterationEvidenceClientV1>,
    ) -> impl std::future::Future<Output = anyhow::Result<CompletedBPanel>> + 'a {
        Box::pin(async move {
            let Self {
                mut primary,
                mut retention,
                registration,
            } = self;
            anyhow::ensure!(
                input.material.initial.request.evaluation_profile
                    == registration.evaluation_profile()
            );
            anyhow::ensure!(
                primary.rule.objective_digest
                    == input.material.initial.request.envelope.objective_digest
            );
            anyhow::ensure!(primary.at == retention.at);
            let at = primary.at;
            // The original retention result is completed first and enters the
            // primary's signed declaration. Equal supported policies continue
            // to produce the original honest Ineligible result.
            let mut retention_member = complete_member(
                &mut retention,
                input,
                &registration,
                Vec::new(),
                retention_trainer,
            )
            .await?;
            let digests = vec![retention_member.qualification.product().evidence_digest];
            let mut primary_member =
                complete_member(&mut primary, input, &registration, digests, primary_trainer)
                    .await?;
            let config = &primary_member.config;
            let receipt_config = OriginalCellEvaluationReceiptConfigV1 {
                training: config.training.clone(),
                scope: config.scope.clone(),
                plan: config.plan.clone(),
                signing: OriginalCellEvaluationSigningConfigV1 {
                    plan: config.plan.product_plan().clone(),
                    execution_namespace: config.execution_namespace,
                    signer: input.credentials.evaluator.clone(),
                    verifier: config.verifier.clone(),
                    maximum_signature_lifetime_seconds: 600,
                },
            };
            let panel = Panel::from_original_owners(
                registration,
                primary_member.take_original_member(),
                vec![retention_member.take_original_member()],
            )?;
            let directory = tempfile::tempdir_in(std::env::temp_dir().canonicalize()?)?;
            let mut result = CompletedBPanel {
                host: None,
                config: receipt_config,
                at,
                primary,
                retention,
                primary_member,
                retention_member,
                directory,
            };
            let (file, witness) = result.files(true)?;
            let evaluator = OriginalCellEvaluationReceiptOwnerV1::create(
                file,
                witness,
                result.config.clone(),
                SigningKey::from_bytes(&[42; 32]),
            )?;
            let mut host = evaluator.into_original_evaluation_host(panel)?;
            // This remains the existing explicit B clock fixture. It is not a
            // claim of deployed task timing or independently obtained data.
            host.fixture_original_clock(at)?;
            result.host = Some(Arc::new(host));
            Ok(result)
        })
    }
}

async fn complete_member(
    b: &mut BFixture,
    input: &CompletedTrainingInputs<'_>,
    registration: &crate::OriginalCellEvaluationPanelRegistrationV1,
    retention_receipt_digests: Vec<Digest32>,
    trainer: Arc<LearningIterationEvidenceClientV1>,
) -> anyhow::Result<PanelMemberFixture> {
    b.populate_from_preheld_objective(
        input.objective,
        input.baseline,
        input.candidate,
        ObservationMode::Complete,
        false,
        DecisionBinding::ExactSource,
    )
    .await?;
    let config = b.config_from_original_training(
        input.training.clone(),
        &input.material.scope,
        input.training_evidence,
        &input.material.verifier,
        registration,
    )?;
    let cohort = CohortAt::read(b.owners(), config, b.at)?;
    let runner = ProviderPlanFixture::for_panel(
        &cohort.original,
        &b.rule,
        &input.training,
        input.manifests.clone(),
    )?;
    let provider = cohort.consume(runner.plan.clone())?;
    Box::pin(PanelMemberFixture::complete_from_shared_original_trainer(
        runner,
        provider,
        &input.material.initial,
        input.training.clone(),
        input.training_evidence.clone(),
        &input.material.scope,
        &input.credentials.generator,
        &input.credentials.evaluator,
        input.material.verifier.clone(),
        retention_receipt_digests,
        trainer,
    ))
    .await
}

pub(in super::super) struct CompletedBPanel {
    pub(in super::super) host: Option<Arc<OriginalCellEvaluationHostV1>>,
    pub(in super::super) config: OriginalCellEvaluationReceiptConfigV1,
    pub(in super::super) at: u64,
    primary: BFixture,
    retention: BFixture,
    primary_member: PanelMemberFixture,
    retention_member: PanelMemberFixture,
    directory: tempfile::TempDir,
}

impl CompletedBPanel {
    fn files(&self, create: bool) -> anyhow::Result<(File, FileAnchorWitnessStore)> {
        let root = self.directory.path();
        let file = opened(root, "original-evaluation", create)?;
        let witness = original_witness(
            root,
            "original-evaluation-witness",
            &self.config.scope,
            self.config.signing.verifier.objective_digest(),
            create,
        )?;
        Ok((file, witness))
    }

    pub(in super::super) fn original_files(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            fs::read(self.directory.path().join("original-evaluation"))?,
            fs::read(self.directory.path().join("original-evaluation-witness"))?,
        ])
    }

    pub(in super::super) fn upstream_files(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut result = self.primary_member.bytes()?;
        result.extend(self.retention_member.bytes()?);
        result.extend(self.primary.all_source_bytes()?);
        result.extend(self.retention.all_source_bytes()?);
        result.extend(
            self.host
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("original host retained"))?
                .fixture_original_cohort_files()?,
        );
        Ok(result)
    }

    pub(in super::super) fn recover(&mut self) -> anyhow::Result<()> {
        let host = Arc::try_unwrap(
            self.host
                .take()
                .ok_or_else(|| anyhow::anyhow!("original host retained"))?,
        )
        .map_err(|_| {
            anyhow::anyhow!("all original Evaluation services must be joined before recovery")
        })?;
        let panel = host.fixture_take_original_panel()?;
        let (file, witness) = self.files(false)?;
        let evaluator = OriginalCellEvaluationReceiptOwnerV1::recover(
            file,
            witness,
            self.config.clone(),
            SigningKey::from_bytes(&[42; 32]),
        )?;
        let mut host = evaluator.into_original_evaluation_host(panel)?;
        host.fixture_original_clock(self.at)?;
        self.host = Some(Arc::new(host));
        Ok(())
    }

    /// All external service futures must have joined before this point; the
    /// outside OriginalTrainingPeers is finished only after these clients drop.
    pub(in super::super) fn finish(mut self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.host
                .as_ref()
                .is_some_and(|host| Arc::strong_count(host) == 1),
            "all original Evaluation services must be joined"
        );
        drop(self.host.take());
        self.primary_member.finish_with_external_trainer()?;
        self.retention_member.finish_with_external_trainer()?;
        Ok(())
    }
}
