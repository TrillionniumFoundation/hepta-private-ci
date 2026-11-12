//! Fixed panel membership, exact original predecessor pins and final sealing.
use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCellEvaluationPanelMemberOwnersV1;
use super::OriginalCellEvaluationPanelMemberReadbackV1;
use super::OriginalCellEvaluationPanelOwnerV1;
use super::OriginalCellEvaluationPanelReadbackV1;
use super::OriginalCellEvaluationPanelRegistrationV1;
use super::original;
use crate::OriginalCircuitEvaluationCohortReadbackV1;

impl<C: AnchorWitnessStore, F: AnchorWitnessStore, X: AnchorWitnessStore, Q: AnchorWitnessStore>
    OriginalCellEvaluationPanelOwnerV1<C, F, X, Q>
{
    pub(super) fn validate_original_members(
        registration: &OriginalCellEvaluationPanelRegistrationV1,
        primary: &OriginalCellEvaluationPanelMemberOwnersV1<C, F, X, Q>,
        retention: &[OriginalCellEvaluationPanelMemberOwnersV1<C, F, X, Q>],
    ) -> Result<Vec<Digest32>, Error> {
        if retention.is_empty()
            || retention.len() != registration.retention().len()
            || retention.len() > super::contract::MAX_RETENTION_TASKS
        {
            return Err(Error::Binding("all original registered retention members"));
        }
        let first = &primary.qualification.config;
        if first.training.request.evaluation_profile != registration.evaluation_profile()
            || first.context.retention_receipt_digests.len() != retention.len()
            || first
                .context
                .retention_receipt_digests
                .iter()
                .any(|digest| digest.is_zero())
        {
            return Err(Error::Binding("originally frozen complete panel profile"));
        }
        let mut namespaces = BTreeSet::new();
        let mut bindings = Vec::with_capacity(retention.len() + 1);
        let members = std::iter::once(primary).chain(retention);
        let tasks = std::iter::once(registration.primary()).chain(registration.retention());
        for (index, (member, task)) in members.zip(tasks).enumerate() {
            let config = &member.qualification.config;
            OriginalCircuitEvaluationCohortReadbackV1::require_original_member(
                &member.cohort,
                registration,
                task,
                &config.training,
                &config.scope,
                &config.plan,
                &config.training_evidence,
                &config.verifier,
            )?;
            let saved = original::validate_config(config)?;
            let record = config.plan.record();
            if member.qualification.saved != saved
                || config.training != first.training
                || config.scope != first.scope
                || config.training_evidence != first.training_evidence
                || config.context.generator != first.context.generator
                || config.context.evaluator != first.context.evaluator
                || config.verifier.trust_digest() != first.verifier.trust_digest()
                || config.verifier.scope_digest() != first.verifier.scope_digest()
                || config.verifier.objective_digest() != first.verifier.objective_digest()
                || config.plan.product_plan().frozen_plan.plan_id != task.plan_id
                || record.candidate.cost.identity().task_digest != task.task_digest.into_array()
                || record.fixed_expert.cost.identity().task_digest != task.task_digest.into_array()
                || !namespaces.insert(config.execution_namespace)
                || !namespaces.insert(config.qualification_namespace)
                || !config.context.unlearning_receipt_digest.is_zero()
                || (index > 0 && !config.context.retention_receipt_digests.is_empty())
            {
                return Err(Error::Binding(
                    "same original candidate, baseline and member custody",
                ));
            }
            bindings.push(saved.binding_digest);
        }
        Ok(bindings)
    }

    pub(super) fn require_observed_panel(
        &self,
        observed: &[OriginalCellEvaluationPanelMemberReadbackV1],
    ) -> Result<(), Error> {
        if observed.len() != self.registration.retention().len() + 1
            || observed.is_empty()
            || observed[0].task != *self.registration.primary()
        {
            return Err(Error::Binding("complete actual original panel"));
        }
        let mut runs = BTreeSet::new();
        let mut retained_digests = Vec::with_capacity(self.retention.len());
        for (index, member) in observed.iter().enumerate() {
            if member.qualification.product().decision.decision.disposition
                == IndependentEvaluationDispositionV1::InsufficientEvidence
            {
                return Err(Error::Binding(
                    "original panel member has unknown evaluation",
                ));
            }
            // Both arms may share one task run, but another panel member may
            // never reuse either actual run. The physical Cells supplied them.
            let member_runs: BTreeSet<_> = member
                .scopes
                .iter()
                .map(|scope| scope.run_id.clone())
                .collect();
            if member_runs.iter().any(|run| runs.contains(run)) {
                return Err(Error::Binding("distinct actual B and retention runs"));
            }
            runs.extend(member_runs);
            if index > 0 {
                if member.task != self.registration.retention()[index - 1] {
                    return Err(Error::Binding("same registered retention task"));
                }
                retained_digests.push(member.qualification.product().evidence_digest);
            }
        }
        retained_digests.sort_unstable();
        if retained_digests.is_empty()
            || retained_digests.windows(2).any(|pair| pair[0] == pair[1])
            || self
                .primary
                .qualification
                .config
                .context
                .retention_receipt_digests
                != retained_digests
            || observed[0].prepared.bundle.retention_receipt_digests != retained_digests
        {
            return Err(Error::Binding(
                "original B signed the complete actual retention panel",
            ));
        }
        // A complete negative retention result cannot authorize a positive B
        // decision. It is not rewritten as NoUpdate: the original signed
        // primary decision and every frozen member contract remain unchanged.
        if observed[0].qualification.product().decision.decision.disposition
            == IndependentEvaluationDispositionV1::EligibleForIndependentSelection
            && observed.iter().skip(1).any(|member| {
                member.qualification.product().decision.decision.disposition
                    != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
            })
        {
            return Err(Error::Binding(
                "qualified original B requires eligible retention",
            ));
        }
        Ok(())
    }

    pub(super) fn seal_observed_panel(
        &self,
        mut observed: Vec<OriginalCellEvaluationPanelMemberReadbackV1>,
    ) -> Result<OriginalCellEvaluationPanelReadbackV1, Error> {
        if observed.len() != self.bindings.len() || observed.is_empty() {
            return Err(Error::CommitUncertain);
        }
        let config = &self.primary.qualification.config;
        let mut bytes = b"hepta.agentd.original-cell-evaluation-panel-current.v1\0".to_vec();
        bytes.extend_from_slice(self.registration.evaluation_profile().as_array());
        bytes.extend_from_slice(config.training.head_digest.as_array());
        bytes.extend_from_slice(config.scope.binding().as_array());
        bytes.extend_from_slice(&(observed.len() as u64).to_be_bytes());
        for (binding, member) in self.bindings.iter().zip(&observed) {
            let product = member.qualification.product();
            for digest in [
                *binding,
                member.cohort.binding(),
                member.cells[0],
                member.cells[1],
                product.temporal_execution_digest,
                product.publication_digest,
                product.evidence_digest,
                product.decision.authentication_digest,
            ] {
                bytes.extend_from_slice(digest.as_array());
            }
        }
        let primary = observed.remove(0);
        Ok(OriginalCellEvaluationPanelReadbackV1 {
            binding: Digest32::of_bytes(&bytes),
            registration: self.registration.clone(),
            training: config.training.clone(),
            training_evidence: config.training_evidence.clone(),
            primary,
            retention: observed,
        })
    }
}
