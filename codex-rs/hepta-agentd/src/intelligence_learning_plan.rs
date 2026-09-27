//! Host-owned construction and ownership of canonical learning Decisions.
//!
//! The shared product profile is installed into both the invocation provider
//! and runner. It owns the durable learning host plus bounded per-run Decision
//! plans. A bound runner cannot return `Ready` until the exact Decision intent
//! is durably acknowledged by the canonical learning-ledger writer.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdIntelligenceRuntimeMetricsV1;
use crate::IntelligenceLearningBindingV1;
use crate::IntelligenceLearningErrorV1;
use crate::IntelligenceLearningStateV1;
use crate::IntelligenceLearningStatusV1;
use crate::PreparedAgentdIntelligenceRunV1;

const MAX_PENDING_DECISION_PLANS: usize = 256;

pub trait AgentdIntelligenceDecisionEvidenceProviderV1: Send + Sync {
    fn sign(
        &self,
        decision: &ProductionDecisionV2,
        now: u64,
    ) -> Result<SignedLearningEvidenceV1, IntelligenceLearningErrorV1>;
}

#[derive(Clone)]
pub struct AgentdIntelligenceDecisionPlanV1 {
    expected_predecessor: Digest32,
    episode_id: StableId,
    policy_digest: Digest32,
    canonical_candidate_set_digest: Digest32,
    candidate_ids: Vec<StableId>,
    completeness: CandidateSetCompletenessReceiptV1,
    evidence_provider: Arc<dyn AgentdIntelligenceDecisionEvidenceProviderV1>,
    metrics: Option<Arc<AgentdIntelligenceRuntimeMetricsV1>>,
    acknowledged_binding: Arc<Mutex<Option<IntelligenceLearningBindingV1>>>,
}

impl AgentdIntelligenceDecisionPlanV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        expected_predecessor: Digest32,
        episode_id: StableId,
        policy_digest: Digest32,
        canonical_candidate_set_digest: Digest32,
        mut candidate_ids: Vec<StableId>,
        completeness: CandidateSetCompletenessReceiptV1,
        evidence_provider: Arc<dyn AgentdIntelligenceDecisionEvidenceProviderV1>,
    ) -> Result<Self, IntelligenceLearningErrorV1> {
        candidate_ids.sort();
        let candidates_digest = candidate_ids_digest_v2(&candidate_ids);
        let canonical_order_digest = candidate_order_digest_v2(&candidate_ids);
        if policy_digest.is_zero()
            || canonical_candidate_set_digest.is_zero()
            || candidate_ids.is_empty()
            || candidate_ids.len() > 128
            || candidate_ids.windows(2).any(|pair| pair[0] == pair[1])
            || completeness.candidate_count as usize != candidate_ids.len()
            || completeness.candidates_digest != candidates_digest
            || completeness.canonical_order_digest != canonical_order_digest
            || !completeness.complete_for_generator
        {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "canonical Decision plan",
            ));
        }
        Ok(Self {
            expected_predecessor,
            episode_id,
            policy_digest,
            canonical_candidate_set_digest,
            candidate_ids,
            completeness,
            evidence_provider,
            metrics: None,
            acknowledged_binding: Arc::new(Mutex::new(None)),
        })
    }

    pub(crate) fn attach_runtime_metrics(
        &mut self,
        metrics: Arc<AgentdIntelligenceRuntimeMetricsV1>,
    ) {
        self.metrics = Some(metrics);
    }

    /// Exact run/Decision binding made available only after the canonical
    /// learning owner acknowledges the Decision append. Cloned plans share this
    /// one immutable publication cell, so an outcome observer cannot race a
    /// different binding into the same run.
    pub fn acknowledged_binding(
        &self,
    ) -> Result<Option<IntelligenceLearningBindingV1>, IntelligenceLearningErrorV1> {
        Ok(self
            .acknowledged_binding
            .lock()
            .map_err(|_| IntelligenceLearningErrorV1::Poisoned)?
            .clone())
    }

    fn prepare(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        now: u64,
    ) -> Result<PreparedIntelligenceLearningDecisionV1, IntelligenceLearningErrorV1> {
        let AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } = &prepared.envelope.decision.decision
        else {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "learning Decision requires selected canonical outcome",
            ));
        };
        if now == 0
            || !self.candidate_ids.contains(candidate_id)
            || propensity.raw() == 0
            || self.canonical_candidate_set_digest
                != prepared.envelope.candidate_set_digest
        {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "prepared Decision binding",
            ));
        }
        let run_snapshot = prepared.run_snapshot();
        if run_snapshot.run_id != prepared.envelope.run_id.to_string()
            || run_snapshot.objective_digest != prepared.envelope.objective_digest.to_string()
            || !valid_digest_text(&run_snapshot.request_digest)
            || !valid_digest_text(&run_snapshot.body_digest)
            || !valid_digest_text(&run_snapshot.artifact_set_digest)
            || !valid_digest_text(&run_snapshot.fence_digest)
        {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "prepared run snapshot identity",
            ));
        }
        let run_snapshot_digest = agent_run_snapshot_digest(&run_snapshot)?;
        let binding = IntelligenceLearningBindingV1::new(
            prepared.envelope.run_id.clone(),
            run_snapshot_digest,
            prepared.envelope.objective_digest,
            prepared.envelope.envelope_digest,
            self.completeness.candidates_digest,
            prepared.dispatch_proposal_digest,
            prepared.envelope.run_id.clone(),
            self.episode_id.clone(),
            candidate_id.clone(),
        )?;
        let decision = ProductionDecisionV2 {
            record_id: prepared.envelope.run_id.clone(),
            episode_id: self.episode_id.clone(),
            run_snapshot_digest,
            objective_digest: prepared.envelope.objective_digest,
            policy_digest: self.policy_digest,
            candidate_ids: self.candidate_ids.clone(),
            selected_candidate_id: candidate_id.clone(),
            selected_propensity: *propensity,
            completeness: self.completeness.clone(),
            support_digest: prepared.dispatch_proposal_digest,
        };
        let evidence = self.evidence_provider.sign(&decision, now)?;
        Ok(PreparedIntelligenceLearningDecisionV1 {
            binding,
            expected_predecessor: self.expected_predecessor,
            decision,
            evidence,
        })
    }

    /// Persist and reconcile the exact canonical Decision before a prepared run
    /// may become externally visible as `ContextAttached`/`Ready`.
    ///
    /// The outbox is written before the ledger owner is invoked. Any ambiguous
    /// destination result therefore remains restart-reconcilable and never
    /// authorizes physical dispatch.
    pub(crate) fn append_prepared_decision(
        &self,
        learning_host: &AgentdIntelligenceLearningHostV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        now: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        let decision = self.prepare(prepared, now)?;
        let acknowledged_binding = decision.binding.clone();
        let status = learning_host.enqueue_decision(
            decision.binding,
            decision.expected_predecessor,
            decision.decision,
            decision.evidence,
            now,
        )?;
        if let Some(metrics) = self.metrics.as_ref() {
            metrics.record_learning_state(&status.state);
        }
        if matches!(
            &status.state,
            IntelligenceLearningStateV1::Acknowledged { .. }
        ) {
            let mut slot = self
                .acknowledged_binding
                .lock()
                .map_err(|_| IntelligenceLearningErrorV1::Poisoned)?;
            if slot
                .as_ref()
                .is_some_and(|current| current != &acknowledged_binding)
            {
                return Err(IntelligenceLearningErrorV1::Conflict);
            }
            *slot = Some(acknowledged_binding);
        }
        Ok(status)
    }
}

pub struct AgentdIntelligenceProductProfileV1 {
    profile_digest: Digest32,
    learning_host: Arc<AgentdIntelligenceLearningHostV1>,
    plans: Mutex<BTreeMap<StableId, AgentdIntelligenceDecisionPlanV1>>,
}

impl AgentdIntelligenceProductProfileV1 {
    pub fn new(
        profile_digest: Digest32,
        learning_host: Arc<AgentdIntelligenceLearningHostV1>,
    ) -> Result<Self, IntelligenceLearningErrorV1> {
        if profile_digest.is_zero() {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "product profile digest",
            ));
        }
        Ok(Self {
            profile_digest,
            learning_host,
            plans: Mutex::new(BTreeMap::new()),
        })
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.profile_digest
    }

    pub fn register_plan(
        &self,
        run_id: StableId,
        plan: AgentdIntelligenceDecisionPlanV1,
    ) -> Result<(), IntelligenceLearningErrorV1> {
        let mut plans = self
            .plans
            .lock()
            .map_err(|_| IntelligenceLearningErrorV1::Poisoned)?;
        if plans.contains_key(&run_id) {
            return Err(IntelligenceLearningErrorV1::Conflict);
        }
        if plans.len() >= MAX_PENDING_DECISION_PLANS {
            return Err(IntelligenceLearningErrorV1::Capacity);
        }
        plans.insert(run_id, plan);
        Ok(())
    }

    pub fn remove_plan(
        &self,
        run_id: &StableId,
    ) -> Result<bool, IntelligenceLearningErrorV1> {
        Ok(self
            .plans
            .lock()
            .map_err(|_| IntelligenceLearningErrorV1::Poisoned)?
            .remove(run_id)
            .is_some())
    }

    pub fn pending_plans(&self) -> Result<usize, IntelligenceLearningErrorV1> {
        Ok(self
            .plans
            .lock()
            .map_err(|_| IntelligenceLearningErrorV1::Poisoned)?
            .len())
    }

    pub(crate) fn append_prepared_decision(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        now: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        let run_id = &prepared.envelope.run_id;
        let plan = self
            .plans
            .lock()
            .map_err(|_| IntelligenceLearningErrorV1::Poisoned)?
            .get(run_id)
            .cloned()
            .ok_or(IntelligenceLearningErrorV1::Missing)?;
        let status = plan.append_prepared_decision(&self.learning_host, prepared, now)?;
        if matches!(
            &status.state,
            IntelligenceLearningStateV1::Acknowledged { .. }
        ) {
            self.remove_plan(run_id)?;
        }
        Ok(status)
    }

    pub fn learning_backlog(&self) -> Result<usize, IntelligenceLearningErrorV1> {
        self.learning_host.backlog()
    }

    pub fn learning_host(&self) -> Arc<AgentdIntelligenceLearningHostV1> {
        Arc::clone(&self.learning_host)
    }
}

struct PreparedIntelligenceLearningDecisionV1 {
    binding: IntelligenceLearningBindingV1,
    expected_predecessor: Digest32,
    decision: ProductionDecisionV2,
    evidence: SignedLearningEvidenceV1,
}

fn agent_run_snapshot_digest(
    snapshot: &crate::AgentRunSnapshot,
) -> Result<Digest32, IntelligenceLearningErrorV1> {
    let mut bytes = b"hepta.agentd.intelligence-run-snapshot.v1\0".to_vec();
    for value in [
        snapshot.run_id.as_str(),
        snapshot.request_digest.as_str(),
        snapshot.objective_digest.as_str(),
        snapshot.body_digest.as_str(),
        snapshot.artifact_set_digest.as_str(),
        snapshot.fence_digest.as_str(),
    ] {
        push_string(&mut bytes, value)?;
    }
    bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
    bytes.extend_from_slice(&snapshot.deadline_ms.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn valid_digest_text(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn push_string(
    bytes: &mut Vec<u8>,
    value: &str,
) -> Result<(), IntelligenceLearningErrorV1> {
    let length = u32::try_from(value.len())
        .map_err(|_| IntelligenceLearningErrorV1::Invalid("snapshot field length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}
