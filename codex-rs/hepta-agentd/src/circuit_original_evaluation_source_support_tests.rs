//! Real B Source/Cell/ledger files and original signed Outcomes. The clock,
//! keys, model responses and measurements are explicit mechanism fixtures.
//! The provider receives no caller-built OPE rows or cached publications.
use super::*;
use crate::circuit_original_evaluation_provider::*;
use crate::circuit_task::cell_q24_dataset_source_test_support as source_fixture;
use crate::circuit_task::source_test_support as source_support;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use material::evaluation_provider::DecisionBinding;
use pretty_assertions::assert_eq;

pub(super) enum ObservationMode {
    Complete,
    NonCanonicalOrder,
    MissingLast,
    WrongUnitLast,
}

pub(super) struct BFixture {
    pub(super) rule: OriginalCircuitEvaluationCohortRuleV1,
    pub(super) at: u64,
    pub(super) root: PathBuf,
    pub(super) writer: Option<LedgerWriter>,
    credentials: material::Credentials,
    sources: Vec<(
        crate::AgentdIdentity,
        source_fixture::Source,
        StableId,
        PathBuf,
    )>,
    _directory: tempfile::TempDir,
}

impl BFixture {
    pub(super) fn new(label: &str, objective: Digest32, trust_time: u64) -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let (writer, credentials) = material::ledger_at(
            &root,
            objective,
            trust_time,
            d(&format!("explicit-independent-{label}-ledger")),
        )?;
        let identity = source_support::identity(&root)?;
        let episode = |name: &str| -> anyhow::Result<OriginalCircuitEvaluationEpisodeV1> {
            let episode_id = id(&format!("{label}-{name}"));
            let behavior_run_id =
                crate::circuit_learning_run_id_v1(&writer, &identity.agent_id, &episode_id)?;
            Ok(OriginalCircuitEvaluationEpisodeV1 {
                episode_id,
                behavior_run_id,
            })
        };
        let history = (0..3)
            .map(|index| episode(&format!("history-{index}")))
            .collect::<anyhow::Result<Vec<_>>>()?;
        let targets = (0..2)
            .map(|index| -> anyhow::Result<_> {
                let episode = episode(&format!("target-{index}"))?;
                Ok(OriginalCircuitEvaluationTargetV1 {
                    baseline_run_id: episode.behavior_run_id.clone(),
                    candidate_run_id: id(&format!("{label}-candidate-{index}")),
                    episode,
                })
            })
            .collect::<anyhow::Result<Vec<_>>>()?;
        let fold = TemporalFoldPlan {
            plan_digest: d(&format!("{label}-temporal-fold")),
            fold_id: id(&format!("{label}-original-fold")),
            training_watermark: trust_time - 10,
            evaluation_start: trust_time + 120,
            minimum_per_action: 1,
        };
        let temporal = |arm: &str| -> anyhow::Result<TemporalEvaluationPlan> {
            let mut plan = TemporalEvaluationPlan {
                plan_digest: Digest32::ZERO,
                evaluation_id: id(&format!("{label}-{arm}")),
                objective_digest: objective,
                fold: fold.clone(),
                ope: OpePlan {
                    plan_digest: d(&format!("{label}-{arm}-ope")),
                    outcome_watermark: trust_time + 123,
                    minimum_rows: 2,
                    minimum_ess: FixedQ32::ONE,
                    maximum_weight: FixedQ32::from_raw(4_i64 << 32),
                },
                confidence: ClusterConfidencePlan {
                    plan_digest: d(&format!("{label}-{arm}-confidence")),
                    assumptions_digest: d("explicit-independent-test-principals"),
                    family_alpha_ppm: 50_000,
                    simultaneous_comparisons: 1,
                    minimum_clusters: 2,
                },
            };
            plan.plan_digest = plan.canonical_digest()?;
            Ok(plan)
        };
        let rule = OriginalCircuitEvaluationCohortRuleV1 {
            plan_id: id(&format!("{label}-plan")),
            task_digest: d(&format!("{label}-original-task")),
            objective_digest: objective,
            snapshot_id: id(&format!("{label}-original-dataset")),
            unit_profile_digest: d("explicit-original-B-success-unit"),
            expected_delay_profile_digest: d("explicit-original-B-outcome-delay"),
            history_start_unix_seconds: trust_time - 30,
            evaluation_end_unix_seconds: trust_time + 123,
            history_window_id: id(&format!("{label}-history-window")),
            holdout_window_id: id(&format!("{label}-heldout-window")),
            candidate_plan: temporal("candidate")?,
            baseline_plan: temporal("baseline")?,
            history,
            targets,
        };
        rule.canonical_digest()?;
        Ok(Self {
            rule,
            at: trust_time + 124,
            root,
            writer: Some(writer),
            credentials,
            sources: Vec::new(),
            _directory: directory,
        })
    }

    pub(super) fn task(&self) -> anyhow::Result<crate::OriginalCellEvaluationPanelTaskV1> {
        Ok(crate::OriginalCellEvaluationPanelTaskV1 {
            plan_id: self.rule.plan_id.clone(),
            task_digest: self.rule.task_digest,
            cohort_rule_digest: self.rule.canonical_digest()?,
        })
    }

    pub(super) async fn populate(
        &mut self,
        original: &PositiveFixture,
        mode: ObservationMode,
        changed_candidate_action: bool,
    ) -> anyhow::Result<()> {
        Box::pin(self.populate_with_decision_binding(
            original,
            mode,
            changed_candidate_action,
            DecisionBinding::ExactSource,
        ))
        .await
    }

    pub(super) async fn populate_with_decision_binding(
        &mut self,
        original: &PositiveFixture,
        mode: ObservationMode,
        changed_candidate_action: bool,
        decision_binding: DecisionBinding,
    ) -> anyhow::Result<()> {
        let baseline = original.config.decision.request.selected_bundle.digest()?;
        let candidate = original.candidate.digest()?;
        let rule = self.rule.clone();
        let history_at = rule.history_start_unix_seconds + 10;
        for (index, episode) in rule.history.iter().enumerate() {
            let principal = d(&format!("{}-history-principal-{index}", rule.plan_id));
            let mut input = self.input(&episode.behavior_run_id, principal, index);
            if matches!(mode, ObservationMode::NonCanonicalOrder) {
                input
                    .candidates
                    .sort_by(|left, right| right.candidate_id.cmp(&left.candidate_id));
                assert!(
                    input
                        .candidates
                        .windows(2)
                        .any(|pair| pair[0].candidate_id > pair[1].candidate_id)
                );
            }
            let publication = self
                .execute(original, input, baseline, index, history_at)
                .await?;
            material::evaluation_provider::decision(
                self.writer.as_mut().expect("original B ledger"),
                &self.credentials,
                &episode.episode_id,
                &publication,
                history_at,
                decision_binding,
            )?;
            let value = [
                FixedQ32::ONE,
                FixedQ32::ZERO,
                FixedQ32::from_raw(1_i64 << 31),
            ][index];
            material::evaluation_provider::outcome(
                self.writer.as_mut().expect("original B ledger"),
                &self.credentials,
                &episode.episode_id,
                history_at + 1,
                value,
                rule.unit_profile_digest,
                rule.expected_delay_profile_digest,
            )?;
        }
        for (index, target) in rule.targets.iter().enumerate() {
            let principal = d(&format!("{}-heldout-principal-{index}", rule.plan_id));
            let mut input = self.input(&target.episode.behavior_run_id, principal, index + 10);
            if matches!(mode, ObservationMode::NonCanonicalOrder) {
                input
                    .candidates
                    .sort_by(|left, right| right.candidate_id.cmp(&left.candidate_id));
                assert!(
                    input
                        .candidates
                        .windows(2)
                        .any(|pair| pair[0].candidate_id > pair[1].candidate_id)
                );
            }
            let publication = self
                .execute(
                    original,
                    input.clone(),
                    baseline,
                    /*selected_index*/ 0,
                    rule.candidate_plan.fold.evaluation_start,
                )
                .await?;
            material::evaluation_provider::decision(
                self.writer.as_mut().expect("original B ledger"),
                &self.credentials,
                &target.episode.episode_id,
                &publication,
                rule.candidate_plan.fold.evaluation_start,
                decision_binding,
            )?;
            let mut candidate_input = input;
            candidate_input.scope.run_id = target.candidate_run_id.clone();
            self.execute(
                original,
                candidate_input,
                candidate,
                usize::from(changed_candidate_action),
                rule.candidate_plan.fold.evaluation_start,
            )
            .await?;
            if index == 1 && matches!(mode, ObservationMode::MissingLast) {
                continue;
            }
            let unit = if index == 1 && matches!(mode, ObservationMode::WrongUnitLast) {
                d("another-real-but-wrong-unit")
            } else {
                rule.unit_profile_digest
            };
            let value = [FixedQ32::ONE, FixedQ32::from_raw(1_i64 << 31)][index];
            material::evaluation_provider::outcome(
                self.writer.as_mut().expect("original B ledger"),
                &self.credentials,
                &target.episode.episode_id,
                rule.evaluation_end_unix_seconds,
                value,
                unit,
                rule.expected_delay_profile_digest,
            )?;
        }
        assert_eq!(self.sources.len(), 7);
        Ok(())
    }

    fn input(
        &self,
        run: &StableId,
        principal: Digest32,
        index: usize,
    ) -> crate::CircuitTaskSourceInputV1 {
        let mut input = source_support::source(
            run.as_str(),
            format!("independent-input-{index}").as_bytes(),
        );
        input.scope.principal_digest = principal;
        input.objective_digest = self.rule.objective_digest;
        input
    }

    async fn execute(
        &mut self,
        original: &PositiveFixture,
        input: crate::CircuitTaskSourceInputV1,
        bundle: Digest32,
        selected_index: usize,
        at: u64,
    ) -> anyhow::Result<crate::CircuitTaskSourcePublicationV1> {
        let run = input.scope.run_id.clone();
        let root = self
            .root
            .join(format!("original-source-{}", self.sources.len()));
        fs::create_dir(&root)?;
        let mut record = source_support::record(run.as_str());
        // A shared digest cannot replace the original compiled objective.
        // B keeps its distinct admission/run/time, with the complete objective
        // and function bytes used by the preregistered comparison.
        let objective = original.previous.original_record();
        assert_eq!(
            objective.snapshot.objective_digest,
            self.rule.objective_digest
        );
        record.snapshot.objective_digest = self.rule.objective_digest;
        record.objective_semantic_bytes = objective.objective_semantic_bytes.clone();
        record.objective_function_v1_digest = objective.objective_function_v1_digest;
        record.objective_function_v1_bytes = objective.objective_function_v1_bytes.clone();
        record.admission.observed_at_unix_micros = at * 1_000_000;
        record.admission.deadline_unix_micros = (at + 1) * 1_000_000;
        record.authentication.expires_at_ms = (at + 1) * 1_000;
        let (identity, source, publication) = source_fixture::original_evaluation_source(
            &root,
            bundle,
            input,
            record,
            selected_index,
        )
        .await?;
        assert_eq!(publication.original_record().snapshot.run_id, run);
        self.sources.push((identity, source, run, root));
        Ok(publication)
    }

    pub(super) fn training(
        original: &PositiveFixture,
    ) -> anyhow::Result<LearningIterationSnapshotV1> {
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(original.initial.clone())?;
        for receipt in &original.config.decision.receipts[..3] {
            coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        }
        Ok(coordinator.snapshot().clone())
    }

    pub(super) fn config(
        &self,
        original: &PositiveFixture,
        registration: &crate::OriginalCellEvaluationPanelRegistrationV1,
    ) -> anyhow::Result<OriginalCircuitEvaluationCohortConfigV1> {
        let freeze_plan = DatasetFreezePlanV2 {
            snapshot_id: self.rule.snapshot_id.clone(),
            objective_digest: self.rule.objective_digest,
            inclusion_policy_digest: self.rule.canonical_digest()?,
        };
        let writer = self
            .writer
            .as_ref()
            .expect("original B ledger before transfer");
        assert_eq!(
            writer.verifier().trust_digest(),
            original.config.verifier.trust_digest()
        );
        let freeze_evidence = material::evaluation_provider::freeze(
            writer,
            &self.credentials,
            &freeze_plan,
            self.at,
        )?;
        Ok(OriginalCircuitEvaluationCohortConfigV1 {
            registration: registration.clone(),
            rule: self.rule.clone(),
            training: Self::training(original)?,
            scope: original.config.scope.clone(),
            training_evidence: original.config.training_evidence.clone(),
            verifier: original.config.verifier.clone(),
            freeze_plan,
            freeze_evidence,
        })
    }

    pub(super) fn owners(&mut self) -> OriginalCircuitEvaluationSourceOwnersV1 {
        OriginalCircuitEvaluationSourceOwnersV1 {
            ledger: self
                .writer
                .take()
                .expect("unique original B ledger transfer"),
            sources: self
                .sources
                .iter()
                .map(
                    |(identity, source, run, _)| OriginalCircuitEvaluationSourceV1 {
                        source: source.readback(),
                        identity: identity.clone(),
                        run_id: run.clone(),
                    },
                )
                .collect(),
        }
    }

    pub(super) fn withdraw_target(&self) -> anyhow::Result<()> {
        let (_, source, run, _) = &self.sources[3];
        source.withdraw_source(run)?;
        Ok(())
    }

    pub(super) fn source_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        self.sources
            .iter()
            .map(|(_, _, _, root)| Ok(fs::read(root.join("source-journal"))?))
            .collect()
    }

    pub(super) fn all_source_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = Vec::new();
        for (_, _, _, root) in &self.sources {
            for name in [
                "source-journal",
                "source-witness",
                "cell-journal",
                "cell-witness",
            ] {
                bytes.push(fs::read(root.join(name))?);
            }
        }
        Ok(bytes)
    }

    pub(super) fn corrupt_source(&self) -> anyhow::Result<(PathBuf, Vec<u8>)> {
        use std::io::Write;
        let path = self.sources[3].3.join("source-journal");
        let bytes = fs::read(&path)?;
        let mut changed = bytes.clone();
        changed[0] ^= 1;
        let mut file = OpenOptions::new().write(true).open(&path)?;
        file.write_all(&changed)?;
        file.sync_all()?;
        Ok((path, bytes))
    }

    pub(super) fn original_manifests(original: &PositiveFixture) -> [CellBackendManifestV2; 2] {
        let plan = original.evaluation.receipt.plan().record();
        [
            plan.candidate.manifest.clone(),
            plan.fixed_expert.manifest.clone(),
        ]
    }
}
