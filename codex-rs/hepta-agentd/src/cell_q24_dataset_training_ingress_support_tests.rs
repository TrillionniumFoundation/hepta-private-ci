//! Actual ordinary Q24/source/ledger/trainer I/O. Issuers, root CURRENT custody,
//! terminal scores and stage credential enrollment remain explicit test data.

use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

use super::super as ingress;
use super::*;
use crate::cell_q24_dataset::test_support as signed;

pub(super) type NativeSource = crate::DurableCircuitTaskSourceV1<FileAnchorWitnessStore>;

pub(super) struct OriginalQ24DatasetIngressFixture {
    _models: tempfile::TempDir,
    _ledger_files: tempfile::TempDir,
    _source_files: tempfile::TempDir,
    _version: VersionFixture,
    pub model: Arc<crate::LoadedCellQ24ModelV1>,
    pub bundle: CellCompatibilityBundleV1,
    pub publication: CircuitTaskSourcePublicationV1,
    pub original: NativeSource,
    pub identity: AgentdIdentity,
    pub ledger: Arc<Mutex<LedgerWriter>>,
    pub material: Arc<crate::OriginalCellQ24DatasetV1>,
    pub at: u64,
}

impl OriginalQ24DatasetIngressFixture {
    pub(super) async fn new(target_q32: i64) -> anyhow::Result<Self> {
        Self::with_additional_signers(target_q32, Vec::new()).await
    }

    pub(super) async fn with_additional_signers(
        target_q32: i64,
        additional: Vec<TrustedLearningSignerV1>,
    ) -> anyhow::Result<Self> {
        let models = tempfile::tempdir()?;
        let ledger_files = tempfile::tempdir()?;
        let (model, bundle, definition) = ingress::support::model(models.path())?;
        // This request is only a semantic-objective preview, never dispatched.
        // The real signed ingress below uses the run derived from the real ledger.
        let mut admission = ingress::support::admission("dataset-semantic-request-A").await?;
        let objective = ingress::support::source(&admission, [Q, Q / 2])?.objective_digest;
        let at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs();
        let mut ledger = if additional.is_empty() {
            signed::ledger(ledger_files.path(), at, objective)?
        } else {
            signed::ledger_with_additional_signers(ledger_files.path(), at, objective, &additional)?
        };
        let run = crate::circuit_learning_run_id_v1(
            &ledger,
            &admission.runtime.identity.agent_id,
            &cell::id("dataset-native-A"),
        )?;
        // Keep the semantic source request fixed: its requestId contributes
        // to the objective digest, while RunStart.run_id is a separate signed
        // execution binding. Changing both would make the run hash circular.
        // support::start re-signs the complete final body before normal ingress.
        admission.request.body.run_id = run.to_string();
        let input = ingress::support::source(&admission, [Q, Q / 2])?;
        pretty_assertions::assert_eq!(input.objective_digest, objective);
        let config = ingress::support::configuration(&model, &bundle, &definition, &input, 1)?;
        let version = VersionFixture::new_initial(config, "ordinary-q24-initial")?;
        let task = ingress::support::publish_initial(&version, definition.clone(), input.clone())?;
        let mut session =
            ingress::support::start(admission, task, Arc::clone(&model), bundle.clone()).await?;
        let publication = ingress::execute(&session, 1).await?;
        let decision = ingress::read_receipt(&session, &definition, &publication)?;
        let material = freeze(
            &mut ledger,
            &publication,
            &decision.selected_candidate,
            &session.runtime.identity,
            session.source.as_ref(),
            at,
            target_q32,
        )?;
        let identity = session.runtime.identity.clone();
        let source_files = std::mem::replace(&mut session.runtime._temp, tempfile::tempdir()?);
        session.stop().await?;
        drop(session);
        // No retained source handle remains. This reopens its original files,
        // witness and immutable input; it neither republishes nor recomputes A.
        let original =
            ingress::cold_recovery::reopen::original_source(&identity, &definition, &input)?;
        material.revalidate(&ledger, &original.readback(), &identity)?;
        Ok(Self {
            _models: models,
            _ledger_files: ledger_files,
            _source_files: source_files,
            _version: version,
            model,
            bundle,
            publication,
            original,
            identity,
            ledger: Arc::new(Mutex::new(ledger)),
            material: Arc::new(material),
            at,
        })
    }

    pub(super) fn context(&self) -> OriginalCellQ24TrainingSourceV1<FileAnchorWitnessStore> {
        OriginalCellQ24TrainingSourceV1 {
            material: Arc::clone(&self.material),
            ledger: Arc::clone(&self.ledger),
            source: Arc::new(self.original.readback()),
            identity: self.identity.clone(),
        }
    }

    pub(super) fn source_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "q24-source.journal",
            "q24-source.witness",
            "q24-cell.journal",
            "q24-cell.witness",
            "q24-control.journal",
            "objective-run-start-v1/journal.bin",
        ]
        .iter()
        .map(|name| Ok(fs::read(self.identity.home_root.join(name))?))
        .collect()
    }
}

fn freeze(
    ledger: &mut LedgerWriter,
    publication: &CircuitTaskSourcePublicationV1,
    selected: &StableId,
    identity: &AgentdIdentity,
    source: &crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    at: u64,
    target: i64,
) -> anyhow::Result<crate::OriginalCellQ24DatasetV1> {
    let observed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs();
    let episode = cell::id("dataset-native-A");
    let run_snapshot_digest = cell::d("explicit-fixture-Generator-snapshot");
    let decision_support_digest = cell::d("explicit-fixture-Generator-support");
    let candidates: Vec<_> = publication
        .input()
        .candidates
        .iter()
        .filter(|c| c.allowed)
        .map(|c| c.candidate_id.clone())
        .collect();
    let request = ProductionDecisionV2 {
        record_id: publication.input().scope.run_id.clone(),
        episode_id: episode.clone(),
        run_snapshot_digest,
        objective_digest: publication.input().objective_digest,
        policy_digest: publication.bundle_digest(),
        candidate_ids: candidates.clone(),
        selected_candidate_id: selected.clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: cell::id("native-fixture-set"),
            state_digest: cell::d("fixture-state"),
            generator_id: cell::id("generator"),
            generator_code_digest: cell::d("fixture-generator"),
            grammar_digest: cell::d("fixture-grammar"),
            hard_filter_digest: cell::d("fixture-filter"),
            truncation_digest: cell::d("fixture-truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: decision_support_digest,
    };
    let evidence = signed::sign(
        ledger,
        LearningEvidenceRoleV1::Generator,
        at,
        &decision_signing_payload_v2(&request)?,
    );
    ledger.append_decision(Digest32::ZERO, request, &evidence, observed)?;
    let outcome = AuthenticatedOutcomeV1 {
        record_id: cell::id("native-terminal-record"),
        outcome_id: cell::id("native-terminal"),
        episode_id: episode.clone(),
        observer: signed::signer(LearningEvidenceRoleV1::Observer, at).principal,
        observed_at: Some(observed),
        value: Some(FixedQ32::from_raw(target)),
        unit_profile_digest: cell::d("explicit-fixture-terminal-score"),
        support_digest: publication.publication_digest(),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: observed,
            expected_delay_profile_digest: cell::d("fixture-delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(observed),
        },
    };
    let evidence = signed::sign(
        ledger,
        LearningEvidenceRoleV1::Observer,
        at,
        &outcome_signing_payload_v2(&outcome),
    );
    ledger.append_outcome(ledger.snapshot()?.head_digest, outcome, &evidence, observed)?;
    let input = publication.input();
    let profile = crate::CellQ24DatasetProfileV1 {
        principal_id: cell::id("explicit-learning-principal"),
        agent_id: identity.agent_id.clone(),
        cell_id: input.scope.cell_id.clone(),
        principal_digest: input.scope.principal_digest,
        ledger_binding: ledger.binding_digest(),
        evidence_trust_digest: ledger.verifier().trust_digest(),
        objective_digest: input.objective_digest,
        selected_bundle: publication.bundle_digest(),
        outcome_unit_profile: cell::d("explicit-fixture-terminal-score"),
        input_width: 2,
        training_episodes: vec![crate::CellQ24DatasetEpisodeV1 {
            episode_id: episode,
            run_snapshot_digest,
            decision_support_digest,
        }],
        excluded_episodes: vec![cell::id("independent-B-never-read")],
    };
    let plan = DatasetFreezePlanV2 {
        snapshot_id: cell::id("original-native-dataset"),
        objective_digest: input.objective_digest,
        inclusion_policy_digest: profile.digest()?,
    };
    let payload = dataset_freeze_signing_payload_v2(&ledger.snapshot()?, &plan)?;
    let evidence = signed::sign(ledger, LearningEvidenceRoleV1::Evaluator, at, &payload);
    Ok(crate::OriginalCellQ24DatasetV1::freeze(
        ledger, source, identity, profile, plan, evidence,
    )?)
}

pub(super) struct Training {
    pub root: tempfile::TempDir,
    model: Arc<crate::LoadedCellQ24ModelV1>,
    data: crate::CellQ24TrainingBatchV1,
    rule: crate::CellQ24SgdRuleV1,
    pub config: crate::OriginalCellQ24TrainingSigningConfigV1,
}

impl Training {
    pub(super) fn new(
        native: &OriginalQ24DatasetIngressFixture,
        principal: StableId,
        data: crate::CellQ24TrainingBatchV1,
    ) -> anyhow::Result<Self> {
        let prefix = ingress::trained::training_prefix(
            &native.publication,
            native.bundle.clone(),
            &data,
            native.material.dataset().snapshot.dataset_digest,
            native.material.dataset().revocation_cut_digest,
            principal,
        )?;
        let ledger = native
            .ledger
            .lock()
            .map_err(|_| anyhow::anyhow!("fixture ledger poisoned"))?;
        let signer = signed::signer(LearningEvidenceRoleV1::Generator, native.at);
        let mut owners = prefix.owners.clone();
        owners.evidence_trust_digest = ledger.verifier().trust_digest();
        owners.trainer = signer.principal.principal_id.clone();
        let mut coordinator = LearningIterationCoordinatorV1::new(prefix.request.clone(), owners)?;
        // These two stage prefix records remain explicit engineering fixtures;
        // Dataset identity/rows/bytes come from the authenticated original material.
        for mut receipt in prefix.receipts {
            receipt.predecessor = coordinator.snapshot().head_digest;
            let observed = receipt.observed_unix_seconds;
            coordinator.record(receipt, observed)?;
        }
        let dataset = coordinator.snapshot().clone();
        let rule = crate::CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        };
        let scope = FrozenLearningScopeV2::freeze(
            &dataset.request,
            &dataset.owners,
            LearningUpdateScopeV2::Cell,
            crate::cell_q24_single_head_update_rule_v1(
                &native.bundle,
                crate::CellQ24PrivateHeadV1::Drive { index: 0 },
                rule.digest(&data)?,
            )?,
        )?;
        let config = crate::OriginalCellQ24TrainingSigningConfigV1 {
            dataset,
            scope,
            signer,
            verifier: ledger.verifier().clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        Ok(Self {
            root: tempfile::tempdir()?,
            model: Arc::clone(&native.model),
            data,
            rule,
            config,
        })
    }

    pub(super) fn with_trigger(
        mut self,
        source_run_id: StableId,
        completed_task_receipt: Digest32,
    ) -> anyhow::Result<Self> {
        let mut request = self.config.dataset.request.clone();
        request.source_run_id = source_run_id;
        request.completed_task_receipt = completed_task_receipt;
        let mut coordinator =
            LearningIterationCoordinatorV1::new(request, self.config.dataset.owners.clone())?;
        // Rebuild a structurally valid fixture prefix and frozen owner scope.
        // Only the original-source gate can reject these alternate trigger claims.
        for retained in &self.config.dataset.receipts {
            let mut observation = retained.observation.clone();
            if let LearningIterationObservationV1::Experience {
                completed_task_receipt: claimed,
                ..
            } = &mut observation
            {
                *claimed = completed_task_receipt;
            }
            let receipt = crate::neuron_generation_update_bootstrap::learning_test_receipt(
                &coordinator,
                observation,
            );
            coordinator.record(receipt, retained.observed_unix_seconds)?;
        }
        self.config.dataset = coordinator.snapshot().clone();
        self.config.scope = FrozenLearningScopeV2::freeze(
            &self.config.dataset.request,
            &self.config.dataset.owners,
            LearningUpdateScopeV2::Cell,
            crate::cell_q24_single_head_update_rule_v1(
                &self.config.dataset.request.selected_bundle,
                crate::CellQ24PrivateHeadV1::Drive { index: 0 },
                self.rule.digest(&self.data)?,
            )?,
        )?;
        Ok(self)
    }

    pub(super) fn witness(&self) -> anyhow::Result<FileAnchorWitnessStore> {
        ingress::trained::witness(self.root.path(), &self.config.dataset)
    }

    pub(super) fn training<W: AnchorWitnessStore>(
        &self,
        witness: W,
        recover: bool,
    ) -> anyhow::Result<crate::CellQ24TrainingOwnerV1<W>> {
        let file = ingress::trained::file(self.root.path(), "training.journal")?;
        let plan = ingress::trained::plan(
            Arc::clone(&self.model),
            &self.config.dataset,
            &self.data,
            self.rule,
        )?;
        Ok(if recover {
            crate::CellQ24TrainingOwnerV1::recover(
                file,
                witness,
                plan,
                self.data.clone(),
                self.rule,
            )?
        } else {
            crate::CellQ24TrainingOwnerV1::create(
                file,
                witness,
                plan,
                self.data.clone(),
                self.rule,
            )?
        })
    }

    pub(super) fn receipts(
        &self,
        recover: bool,
    ) -> anyhow::Result<crate::OriginalCellQ24TrainingReceiptOwnerV1<FileAnchorWitnessStore>> {
        let witness = FileAnchorWitnessStore::open(
            ingress::trained::file(self.root.path(), "receipt.witness")?,
            JournalScope {
                scope_digest: self.config.scope.binding(),
                objective_digest: self.config.dataset.request.envelope.objective_digest,
            },
            Generation::new(1)?,
            16,
        )?;
        let file = ingress::trained::file(self.root.path(), "receipts.journal")?;
        let key = SigningKey::from_bytes(&[1; 32]);
        Ok(if recover {
            crate::OriginalCellQ24TrainingReceiptOwnerV1::recover(
                file,
                witness,
                self.config.clone(),
                key,
            )?
        } else {
            crate::OriginalCellQ24TrainingReceiptOwnerV1::create(
                file,
                witness,
                self.config.clone(),
                key,
            )?
        })
    }

    pub(super) async fn stage(
        &self,
        recover: bool,
    ) -> anyhow::Result<Stage<FileAnchorWitnessStore, FileAnchorWitnessStore>> {
        Ok(Stage::from_original_owners(
            self.training(self.witness()?, recover)?,
            self.receipts(recover)?,
        )
        .await?)
    }

    pub(super) fn retained(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "training.journal",
            "training.witness",
            "receipts.journal",
            "receipt.witness",
        ]
        .iter()
        .map(|name| Ok(fs::read(self.root.path().join(name))?))
        .collect()
    }

    pub(super) fn signature_bytes(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            fs::read(self.root.path().join("receipts.journal"))?,
            fs::read(self.root.path().join("receipt.witness"))?,
        ])
    }
}
