//! Immutable pre-B declarations for the explicitly versioned paired route.
//!
//! This is public metadata, not proof that a factory ran before A and not a B
//! execution capability. The original T signature must already commit its
//! complete V2 panel profile; old V1 rules and signatures are never upgraded.

use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::OnPolicyArmBindingV1;
use codex_hepta_intelligence_eval::OnPolicyPairContractV1;
use codex_hepta_intelligence_eval::OnPolicyPairingContractV1;
use codex_hepta_intelligence_eval::ProductEvaluationPolicyV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::Error;
use super::OriginalCircuitOnPolicyCohortRuleV1;

#[path = "circuit_on_policy_evaluation_policy_codec.rs"]
mod codec;
#[path = "circuit_on_policy_evaluation_policy_comparison.rs"]
mod comparison;
#[path = "circuit_on_policy_evaluation_policy_encoding.rs"]
mod encoding;
#[path = "circuit_on_policy_evaluation_policy_panel.rs"]
mod panel;

pub use comparison::OriginalCircuitOnPolicyComparisonPolicyV2;
pub use panel::OriginalCircuitOnPolicyPanelPolicyV2;

const DOMAIN: &[u8] = b"hepta.circuit.original-on-policy-evaluation-policy.v2\0";

/// All values are declarations. Only the unique original T candidate and the
/// actual Dataset/Cell observations are absent from this immutable policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyEvaluationPolicyInputV2 {
    pub product: ProductEvaluationPolicyV2,
    pub comparison: OriginalCircuitOnPolicyComparisonPolicyV2,
    pub baseline_bundle_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Arm {
    decision: StableId,
    principal: StableId,
    episode: StableId,
    run: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Pair {
    id: StableId,
    input: Digest32,
    protocol: Digest32,
    candidate: Arm,
    baseline: Arm,
}

/// Private immutable fields and purpose-fixed strict decoding expose only
/// declarations. There is no Deserialize, owner, signer, or CURRENT brand.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyEvaluationPolicyV2 {
    legacy_rule: Digest32,
    task: Digest32,
    snapshot: StableId,
    ledger: Digest32,
    product: ProductEvaluationPolicyV2,
    comparison: OriginalCircuitOnPolicyComparisonPolicyV2,
    baseline: Digest32,
    pairs: Vec<Pair>,
}

impl OriginalCircuitOnPolicyEvaluationPolicyV2 {
    /// Borrow only the original ledger's immutable identity. No journal is
    /// read, signed, initialized, or treated as an execution grant.
    pub fn freeze(
        rule: &OriginalCircuitOnPolicyCohortRuleV1,
        ledger: &LedgerWriter,
        input: OriginalCircuitOnPolicyEvaluationPolicyInputV2,
    ) -> Result<Self, Error> {
        let context = input.product.context();
        if context.plan_id != rule.plan_id
            || context.objective_digest != rule.objective_digest
            || context.final_holdout_window_id != rule.holdout_window_id
            || context.candidate_temporal != rule.candidate_plan
            || context.baseline_temporal != rule.baseline_plan
        {
            return Err(Error::Binding("complete fixed Product policy and original cohort rule"));
        }
        let protocol = rule.protocol.canonical_digest()?;
        let mut pairs = Vec::with_capacity(rule.pairs.len());
        for pair in &rule.pairs {
            let principal = StableId::new(format!("principal:{}", pair.input.scope.principal_digest))
                .map_err(|_| Error::Binding("actual original principal declaration"))?;
            let arm = |value: &crate::OriginalCircuitEvaluationEpisodeV1| -> Result<Arm, Error> {
                Ok(Arm {
                    decision: value.behavior_run_id.clone(),
                    principal: principal.clone(),
                    episode: super::binding::episode_lineage(ledger, &value.episode_id)?,
                    run: value.behavior_run_id.clone(),
                })
            };
            pairs.push(Pair {
                id: pair.pair_id.clone(),
                input: super::contract::input_digest(&pair.input)?,
                protocol,
                candidate: arm(&pair.candidate)?,
                baseline: arm(&pair.baseline)?,
            });
        }
        pairs.sort_by(|left, right| left.id.cmp(&right.id));
        let mut policy = Self {
            legacy_rule: rule.canonical_digest()?,
            task: rule.task_digest,
            snapshot: rule.snapshot_id.clone(),
            ledger: ledger.binding_digest(),
            product: input.product,
            comparison: input.comparison,
            baseline: input.baseline_bundle_digest,
            pairs,
        };
        policy.validate()?;
        OriginalCircuitOnPolicyEvaluationPolicyV2::canonical_commitment_bytes(&policy)?;
        Ok(policy)
    }

    pub fn canonical_commitment_bytes(&self) -> Result<Vec<u8>, Error> {
        encoding::encode(self)
    }

    pub fn digest(&self) -> Result<Digest32, Error> {
        Ok(Digest32::of_bytes(&self.canonical_commitment_bytes()?))
    }

    /// A separate domain binds the unchanged legacy rule and the full policy.
    pub fn cohort_rule_digest(&self) -> Result<Digest32, Error> {
        Ok(Digest32::of_parts(&[
            b"hepta.circuit.original-on-policy-cohort-rule.v2\0",
            self.legacy_rule.as_array(),
            self.digest()?.as_array(),
        ]))
    }

    pub fn product(&self) -> &ProductEvaluationPolicyV2 {
        &self.product
    }

    pub fn task_digest(&self) -> Digest32 {
        self.task
    }

    pub(crate) fn snapshot_id(&self) -> &StableId {
        &self.snapshot
    }

    pub(crate) fn ledger_binding(&self) -> Digest32 {
        self.ledger
    }

    pub(crate) fn from_canonical_commitment_bytes(bytes: &[u8]) -> Result<Self, Error> {
        let mut policy = encoding::decode(bytes)?;
        policy.validate()?;
        if OriginalCircuitOnPolicyEvaluationPolicyV2::canonical_commitment_bytes(&policy)? != bytes {
            return Err(Error::Binding("canonical complete V2 policy preimage"));
        }
        Ok(policy)
    }

    pub(crate) fn require_original_rule(
        &self,
        rule: &OriginalCircuitOnPolicyCohortRuleV1,
        ledger: &LedgerWriter,
    ) -> Result<(), Error> {
        let reconstructed = OriginalCircuitOnPolicyEvaluationPolicyV2::freeze(rule, ledger, OriginalCircuitOnPolicyEvaluationPolicyInputV2 {
            product: self.product.clone(),
            comparison: self.comparison.clone(),
            baseline_bundle_digest: self.baseline,
        })?;
        if &reconstructed != self {
            return Err(Error::Binding("whole original rule, policy and ledger identity"));
        }
        Ok(())
    }

    pub(crate) fn require_original_policy_training(&self, training: &LearningIterationSnapshotV1) -> Result<(), Error> {
        LearningIterationCoordinatorV1::from_snapshot(training.clone())?;
        if training.request.selected_bundle.artifact_id != self.product.input().baseline_id
            || codex_hepta_learning_artifacts::CellCompatibilityBundleV1::digest(&training.request.selected_bundle)
                .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)? != self.baseline
            || training.request.envelope.objective_digest != self.product.context().objective_digest
        {
            return Err(Error::Binding("original T request preserves fixed baseline and objective"));
        }
        Ok(())
    }

    pub(crate) fn pairing(
        &self,
        training: &LearningIterationSnapshotV1,
    ) -> Result<OnPolicyPairingContractV1, Error> {
        self.require_original_policy_training(training)?;
        let original = LearningIterationCoordinatorV1::from_snapshot(training.clone())?;
        let candidate = codex_hepta_learning_artifacts::CellCompatibilityBundleV1::digest(
            original.candidate()
                .ok_or(Error::Binding("unique original signed T candidate"))?,
        ).map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        if candidate == self.baseline {
            return Err(Error::Binding("paired candidate differs from retained baseline"));
        }
        let arm = |value: &Arm, model_digest| OnPolicyArmBindingV1 {
            decision_id: value.decision.clone(),
            principal_lineage: value.principal.clone(),
            episode_lineage: value.episode.clone(),
            behavior_run_id: value.run.clone(),
            model_digest,
        };
        let pairing = OnPolicyPairingContractV1 {
            pairs: self.pairs.iter().map(|pair| OnPolicyPairContractV1 {
                pair_id: pair.id.clone(),
                input_digest: pair.input,
                protocol_digest: pair.protocol,
                candidate: arm(&pair.candidate, candidate),
                baseline: arm(&pair.baseline, self.baseline),
            }).collect(),
        };
        codex_hepta_intelligence_eval::OnPolicyPairingContractV1::digest(&pairing).map_err(|_| Error::Binding("complete fixed actual paired identities"))?;
        Ok(pairing)
    }

    pub(crate) fn comparison(
        &self,
        training: &LearningIterationSnapshotV1,
        candidate_structure: [u8; 32],
        baseline_structure: [u8; 32],
    ) -> Result<crate::CellComparisonContractV1, Error> {
        self.require_original_policy_training(training)?;
        self.comparison.observed(training, candidate_structure, baseline_structure)
    }

    fn validate(&mut self) -> Result<(), Error> {
        self.comparison.normalize()?;
        if [self.legacy_rule, self.task, self.ledger, self.baseline]
            .iter().any(|digest| digest.is_zero())
            || self.pairs.is_empty()
            || self.pairs.len() > 31
            || self.pairs.windows(2).any(|rows| rows[0].id >= rows[1].id)
        {
            return Err(Error::Binding("complete bounded preregistered policy identity"));
        }
        let mut decisions = BTreeSet::new();
        let mut episodes = BTreeSet::new();
        let mut runs = BTreeSet::new();
        for pair in &self.pairs {
            if pair.input.is_zero() || pair.protocol.is_zero()
                || pair.candidate.principal != pair.baseline.principal
            {
                return Err(Error::Binding("same actual pair principal and fixed input/protocol"));
            }
            for arm in [&pair.candidate, &pair.baseline] {
                if arm.decision != arm.run
                    || !decisions.insert(&arm.decision)
                    || !episodes.insert(&arm.episode)
                    || !runs.insert(&arm.run)
                {
                    return Err(Error::Binding("distinct original runs and episode identities"));
                }
            }
        }
        Ok(())
    }
}


#[cfg(test)]
#[path = "circuit_on_policy_evaluation_policy_tests.rs"]
mod tests;
