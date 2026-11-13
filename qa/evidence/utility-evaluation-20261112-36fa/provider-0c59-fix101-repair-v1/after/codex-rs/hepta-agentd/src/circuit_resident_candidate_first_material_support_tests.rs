//! First test-control admission from pre-held Root policy and complete original
//! evidence. Pending authenticates the report; only the original E/D commands
//! can bind its completion claim to the still-live original Source. No new
//! writer, Source publication, Root intent, lease or Training capability exists here.
use super::*;
use codex_hepta_contracts::{FinalUseBinding, SignedFinalUseGrant};
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::ProbabilityQ32;
use crate::OriginalCellQ24MaterialReceiptConfigV1 as Material;
use crate::learning_iteration_checkpoint::{decode_original_owner_snapshot_v1, encode_original_owner_snapshot_v1};

#[path = "circuit_resident_candidate_first_material_wire_tests.rs"]
mod wire;
use wire::encode_original_report;

/// Complete host-selected request policy, deliberately without a fabricated
/// completed_task_receipt. That one claimed field remains Pending until E/D.
#[derive(Clone)]
pub(super) struct PreheldTask {
    pub(super) operation_id: StableId,
    pub(super) principal_id: StableId,
    pub(super) agent_id: StableId,
    pub(super) cell_id: StableId,
    pub(super) source_run_id: StableId,
    pub(super) selected_artifact_digest: Digest32,
    pub(super) selected_bundle: CellCompatibilityBundleV1,
    pub(super) envelope: IterationEnvelopeV1,
    pub(super) budget: LearningIterationBudgetV1,
}

/// These are typed inputs chosen by the trusted parent before the untrusted
/// report. The wire has no trust, signers, optimizer, policy or model selector.
#[derive(Clone)]
pub(super) struct PreheldMaterialInputs {
    pub(super) task: PreheldTask,
    pub(super) owners: LearningIterationOwnersV1,
    pub(super) protocol: crate::OriginalCellEvaluationPanelRegistrationV1,
    pub(super) trust: LearningEvidenceTrustV1,
    pub(super) generator: TrustedLearningSignerV1,
    pub(super) observer: TrustedLearningSignerV1,
    pub(super) evaluator: TrustedLearningSignerV1,
    pub(super) experience: TrustedLearningSignerV1,
    pub(super) dataset: TrustedLearningSignerV1,
    pub(super) baseline: Arc<LoadedCellQ24ModelV1>,
    pub(super) source_input: Vec<i64>,
    pub(super) decision_snapshot: Digest32,
    pub(super) episode_id: StableId,
    pub(super) rule: crate::CellQ24DatasetRuleV1,
    pub(super) optimizer: crate::CellQ24SgdRuleV1,
    pub(super) update_scope: LearningUpdateScopeV2,
    pub(super) freeze_snapshot_id: StableId,
    pub(super) maximum_signature_lifetime_seconds: u64,
}

pub(super) struct RootMaterialContract {
    held: PreheldMaterialInputs,
    verifier: LearningEvidenceVerifierV1,
}

impl RootMaterialContract {
    pub(super) fn from_preheld(held: PreheldMaterialInputs) -> anyhow::Result<Self> {
        let verifier = LearningEvidenceVerifierV1::new(held.trust.clone())?;
        let result = Self { held, verifier };
        result.require_current(now()?)?;
        Ok(result)
    }

    fn require_current(&self, at: u64) -> anyhow::Result<()> {
        let held = &self.held;
        anyhow::ensure!(at < held.task.envelope.expiry_unix_seconds
            && held.trust.objective_digest == held.task.envelope.objective_digest
            && held.owners.evidence_trust_digest == self.verifier.trust_digest()
            && held.baseline.components() == &held.task.selected_bundle.components
            && held.baseline.input_width() == held.source_input.len()
            && !held.decision_snapshot.is_zero(), "current complete pre-held task, model and trust");
        for (role, signer, actor) in [
            (LearningEvidenceRoleV1::Generator, &held.generator, &held.owners.trainer),
            (LearningEvidenceRoleV1::Evaluator, &held.evaluator, &held.owners.evaluator),
            (LearningEvidenceRoleV1::Observer, &held.experience, &held.owners.experience),
            (LearningEvidenceRoleV1::Observer, &held.dataset, &held.owners.dataset),
        ] {
            self.verifier.require_signer_binding(role, signer, at)?;
            anyhow::ensure!(&signer.principal.principal_id == actor, "complete pre-held original role");
        }
        self.verifier.require_signer_binding(LearningEvidenceRoleV1::Observer, &held.observer, at)?;
        Ok(())
    }

    pub(super) fn verify_report(self, bytes: &[u8]) -> anyhow::Result<PendingOriginalMaterial> {
        let report = wire::decode_report(bytes)?;
        let material = self.verify_complete_report(&report)?;
        Ok(PendingOriginalMaterial { contract: self, report, material })
    }

    fn verify_complete_report(&self, report: &wire::DecodedReport) -> anyhow::Result<Material> {
        let started_at = now()?;
        self.require_current(started_at)?;
        let h = &self.held;
        let expected = LearningIterationCoordinatorV1::new(LearningIterationRequestV1 {
            operation_id: h.task.operation_id.clone(), principal_id: h.task.principal_id.clone(),
            agent_id: h.task.agent_id.clone(), cell_id: h.task.cell_id.clone(), source_run_id: h.task.source_run_id.clone(),
            // This is a Pending claim, not an authenticated Source publication.
            completed_task_receipt: report.initial.request.completed_task_receipt,
            selected_artifact_digest: h.task.selected_artifact_digest, selected_bundle: h.task.selected_bundle.clone(),
            evaluation_profile: h.protocol.evaluation_profile(), envelope: h.task.envelope.clone(), budget: h.task.budget.clone(),
        }, h.owners.clone())?;
        anyhow::ensure!(expected.snapshot() == &report.initial && report.initial.receipts.is_empty(),
            "complete original empty cut; no budget, owner, task, profile or envelope substitution");
        let records = report.ledger.records();
        anyhow::ensure!(records.len() == 2, "the complete two-event original A fixture history");
        let (LedgerEvent::AuthenticatedDecisionV2(decision_row), LedgerEvent::AuthenticatedOutcomeV2(outcome_row)) =
            (&records[0].event, &records[1].event) else {
                anyhow::bail!("original authenticated Decision followed by original terminal Outcome");
            };
        let decision = ProductionDecisionV2 {
            record_id: decision_row.record_id.clone(), episode_id: decision_row.episode_id.clone(),
            run_snapshot_digest: decision_row.run_snapshot_digest, objective_digest: decision_row.objective_digest,
            policy_digest: decision_row.policy_digest, candidate_ids: decision_row.candidate_ids.clone(),
            selected_candidate_id: decision_row.selected_candidate_id.clone(), selected_propensity: decision_row.selected_propensity,
            completeness: report.completeness.clone(), support_digest: decision_row.support_digest,
        };
        anyhow::ensure!(decision.record_id == h.task.source_run_id && decision.episode_id == h.episode_id
            && decision.run_snapshot_digest == h.decision_snapshot
            && decision.objective_digest == h.task.envelope.objective_digest
            && decision.selected_propensity == ProbabilityQ32::ONE
            && decision.completeness.generator_id == h.generator.principal.principal_id,
            "same pre-held original A and authenticated generator-relative complete decision");
        let decision_payload = decision_signing_payload_v2(&decision)?;
        anyhow::ensure!(report.decision_admitted_at == report.decision.issued_at
            && report.decision_admitted_at <= started_at, "same original fixture signing/append time");
        self.verifier.verify(LearningEvidenceRoleV1::Generator, &report.decision, &decision_payload, report.decision_admitted_at)?;
        let generator = self.verifier.verify(LearningEvidenceRoleV1::Generator, &report.decision, &decision_payload, started_at)?;
        anyhow::ensure!(generator.principal() == &h.generator.principal, "pre-held complete Generator principal");
        let p = generator.principal();
        let expected_decision = AuthenticatedDecisionRecordV2 {
            record_id: decision.record_id, episode_id: decision.episode_id, run_snapshot_digest: decision.run_snapshot_digest,
            objective_digest: decision.objective_digest, policy_digest: decision.policy_digest,
            generator_id: p.principal_id.clone(), generator_controller_id: generator.controller_id().clone(),
            generator_credential_chain_digest: p.credential_chain_digest, generator_signing_key_digest: p.signing_key_digest,
            generator_scope_digest: p.scope_digest, generator_authority_epoch: p.authority_epoch,
            candidate_ids: decision.candidate_ids, selected_candidate_id: decision.selected_candidate_id,
            selected_propensity: decision.selected_propensity,
            candidate_completeness_digest: validate_candidate_set_completeness(&decision.completeness)?,
            support_digest: decision.support_digest, authentication_digest: authentication_digest(&report.decision),
        };
        anyhow::ensure!(&expected_decision == decision_row, "every original authenticated Decision field and signature digest");
        anyhow::ensure!(outcome_row.terminality == AuthenticatedOutcomeTerminality::Terminal
            && outcome_row.episode_id == h.episode_id && outcome_row.unit_profile_digest == h.rule.unit_profile_digest
            && outcome_row.censoring_reason.is_none() && outcome_row.correction_predecessor.is_none()
            && outcome_row.support_digest != decision_row.support_digest,
            "the independently observed original terminal outcome, not model output or a partial lineage");
        let outcome = AuthenticatedOutcomeV1 {
            record_id: outcome_row.record_id.clone(), outcome_id: outcome_row.outcome_id.clone(),
            episode_id: outcome_row.episode_id.clone(), observer: h.observer.principal.clone(),
            observed_at: outcome_row.observed_at, value: outcome_row.value,
            unit_profile_digest: outcome_row.unit_profile_digest, support_digest: outcome_row.support_digest,
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: outcome_row.latest_observable_at,
                expected_delay_profile_digest: outcome_row.expected_delay_profile_digest,
                terminality: OutcomeTerminalityV1::Terminal, censoring_reason: outcome_row.censoring_reason.clone(),
                correction_predecessor: outcome_row.correction_predecessor.clone(), finalized_at: outcome_row.finalized_at,
            },
        };
        let outcome_payload = outcome_signing_payload_v2(&outcome);
        anyhow::ensure!(report.outcome_admitted_at == report.outcome.issued_at
            && report.outcome_admitted_at >= report.decision_admitted_at
            && report.outcome_admitted_at <= started_at, "same original fixture Outcome signing/append time");
        self.verifier.verify(LearningEvidenceRoleV1::Observer, &report.outcome, &outcome_payload, report.outcome_admitted_at)?;
        let observer = self.verifier.verify(LearningEvidenceRoleV1::Observer, &report.outcome, &outcome_payload, started_at)?;
        verify_signed_role_separation(&generator, &observer, started_at)?;
        validate_authenticated_outcome(generator.principal(), &outcome, report.outcome_admitted_at)?;
        let p = observer.principal();
        let expected_outcome = AuthenticatedOutcomeRecordV2 {
            record_id: outcome.record_id, outcome_id: outcome.outcome_id, episode_id: outcome.episode_id,
            observer_id: p.principal_id.clone(), observer_controller_id: observer.controller_id().clone(),
            observer_credential_chain_digest: p.credential_chain_digest, observer_signing_key_digest: p.signing_key_digest,
            observer_scope_digest: p.scope_digest, observer_authority_epoch: p.authority_epoch,
            observed_at: outcome.observed_at, value: outcome.value, unit_profile_digest: outcome.unit_profile_digest,
            support_digest: outcome.support_digest, latest_observable_at: outcome.watermark.latest_observable_at,
            expected_delay_profile_digest: outcome.watermark.expected_delay_profile_digest,
            terminality: AuthenticatedOutcomeTerminality::Terminal, censoring_reason: outcome.watermark.censoring_reason,
            correction_predecessor: outcome.watermark.correction_predecessor, finalized_at: outcome.watermark.finalized_at,
            authentication_digest: authentication_digest(&report.outcome),
        };
        anyhow::ensure!(&expected_outcome == outcome_row && observer.principal() == &h.observer.principal,
            "every original authenticated Outcome field and signature digest");
        let plan = DatasetFreezePlanV2 {
            snapshot_id: h.freeze_snapshot_id.clone(), objective_digest: h.task.envelope.objective_digest,
            inclusion_policy_digest: h.rule.inclusion_policy_digest(&report.initial)?,
        };
        let freeze_payload = dataset_freeze_signing_payload_v2(&report.ledger, &plan)?;
        let freeze = self.verifier.verify(LearningEvidenceRoleV1::Evaluator, &report.freeze, &freeze_payload, started_at)?;
        anyhow::ensure!(freeze.principal() == &h.evaluator.principal, "the pre-held original freeze Evaluator");
        let receipt = freeze_dataset_from_ledger(&report.ledger, plan.clone(), freeze.principal().clone(), started_at)?;
        verify_dataset_snapshot_receipt_against_ledger_v3(&receipt, &report.ledger, started_at)?;
        anyhow::ensure!(receipt.snapshot.pending_outcomes == 0 && receipt.snapshot.censored_outcomes == 0,
            "the complete terminal freeze, with no omitted active history");
        let value = outcome_row.value.ok_or_else(|| anyhow::anyhow!("original terminal value absent"))?.raw();
        anyhow::ensure!(value % 256 == 0, "original exact Q32 to Q24 conversion");
        let batch = crate::CellQ24TrainingBatchV1::new(receipt.snapshot.dataset_digest,
            vec![crate::CellQ24TrainingSampleV1 { input: h.source_input.clone(), target: value / 256 }])?;
        anyhow::ensure!(batch.rows() <= h.task.budget.maximum_dataset_rows
            && batch.encoded().len() as u64 <= h.task.budget.maximum_dataset_bytes, "original frozen Dataset budget");
        let update_rule = crate::cell_q24_single_head_update_rule_v1(&h.task.selected_bundle, h.rule.head, h.optimizer.digest(&batch)?)?;
        let scope = FrozenLearningScopeV2::freeze(&report.initial.request, &report.initial.owners, h.update_scope, update_rule)?;
        anyhow::ensure!(scope.binding() == report.scope_binding, "same original rule, full components, scope and freeze");
        let material = Material {
            initial: report.initial.clone(), scope, rule: h.rule, freeze_plan: plan,
            freeze_evidence: report.freeze.clone(), experience_signer: h.experience.clone(), dataset_signer: h.dataset.clone(),
            verifier: self.verifier.clone(), maximum_signature_lifetime_seconds: h.maximum_signature_lifetime_seconds,
        };
        Material::require_original_command_initial(&material)?;
        let finished_at = now()?;
        anyhow::ensure!(finished_at >= started_at, "admission clock did not regress");
        self.require_current(finished_at)?;
        self.verifier.verify(LearningEvidenceRoleV1::Generator, &report.decision, &decision_payload, finished_at)?;
        self.verifier.verify(LearningEvidenceRoleV1::Observer, &report.outcome, &outcome_payload, finished_at)?;
        self.verifier.verify(LearningEvidenceRoleV1::Evaluator, &report.freeze, &freeze_payload, finished_at)?;
        Ok(material)
    }
}

fn authentication_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut original = evidence.signing_bytes();
    original.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&original)
}

/// No Clone and no Material/Source/Training getter. Its only effectful exit
/// consumes an original registered Root and all original connected roles.
pub(super) struct PendingOriginalMaterial {
    contract: RootMaterialContract,
    report: wire::DecodedReport,
    material: Material,
}

impl PendingOriginalMaterial {
    pub(super) fn admission_binding(&self) -> anyhow::Result<FinalUseBinding> {
        let material = self.contract.verify_complete_report(&self.report)?;
        Ok(crate::RootResidentLearningProfileV3::admission_binding(&material.initial, &material.scope, &material.verifier)?)
    }

    /// The caller must obtain both artifacts from its original Root. This
    /// constructor neither signs them nor installs their Registry entry.
    pub(super) fn profile_with_original_authorization(&self, intent: SignedFinalUseGrant, lease: AuthorityLease)
        -> anyhow::Result<crate::RootResidentLearningProfileV3> {
        let material = self.contract.verify_complete_report(&self.report)?;
        Ok(crate::RootResidentLearningProfileV3::new(material.initial, material.scope, &material.verifier, intent, lease)?)
    }

    pub(super) fn into_original_root_service(
        self,
        registration: crate::RootResidentLearningRegistrationV3,
        handoff: crate::RootCandidateStageHandoffV1,
        consumer: crate::RootResidentLearningConsumerV3,
    ) -> anyhow::Result<crate::RootResidentCandidateServiceV1> {
        let material = self.contract.verify_complete_report(&self.report)?;
        anyhow::ensure!(Material::require_original_command_initial(&material)?.0
            == Material::require_original_command_initial(&self.material)?.0, "same once-received Pending Material binding");
        // Registration performs the original Root checks. Runtime's fresh CAS
        // installs the original effect gate; E authenticates Source and D
        // rereads it before the original coordinator may ever dispatch T.
        Ok(crate::RootResidentLearningRegistrationV3::into_candidate_service(registration,
            crate::RootResidentCandidateInputsV1 {
                material, protocol: self.contract.held.protocol,
                baseline: self.contract.held.baseline, verifier: self.contract.verifier,
            }, handoff, consumer)?)
    }
}

#[path = "circuit_resident_candidate_first_material_tests.rs"]
mod tests;
