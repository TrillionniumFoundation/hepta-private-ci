//! Original reserved preparation can finish without inventing a model request
//! or candidate. Only the actual independent E's Root-retained whole output
//! enters this path; quota and the original clock remain consumed.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
#[cfg(target_os = "linux")]
use codex_hepta_agent_components::learning_ledger::read_root_review_input;
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdSelfIterationPreparationTerminalV1 {
    source_path: PathBuf,
    source_digest: Digest32,
    facts: PreparationFactsV1,
    evaluator: SignedLearningEvidenceV1,
}
#[derive(Clone, Debug, Eq, PartialEq)]
enum PreparationFactsV1 {
    Evaluated(SelfIterationPreparationFactsV1),
    ServingScope(SelfIterationServingScopeIncompatibleFactsV1),
}
impl PreparationFactsV1 {
    fn payload(&self) -> Result<Vec<u8>, AgentdError> {
        match self {
            Self::Evaluated(f) => self_iteration_preparation_terminal_signing_payload_v1(f),
            Self::ServingScope(f) => self_iteration_serving_scope_signing_payload_v1(f),
        }
        .map_err(|e| invalid(e.to_string()))
    }
    fn bound_round(&self) -> (Digest32, Digest32, Digest32, Digest32, u64, u64, u64) {
        match self {
            Self::Evaluated(f) => (
                f.round_identity_digest,
                f.round_payload_digest,
                f.canonical_policy_digest,
                f.execution_envelope_digest,
                f.admitted_at_ms,
                f.deadline_ms,
                f.observed_at_ms,
            ),
            Self::ServingScope(f) => (
                f.round_identity_digest,
                f.round_payload_digest,
                f.canonical_policy_digest,
                f.execution_envelope_digest,
                f.admitted_at_ms,
                f.deadline_ms,
                f.observed_at_ms,
            ),
        }
    }
}
impl AgentdSelfIterationPreparationTerminalV1 {
    /// This checks the original Root file custody and complete portable packet.
    /// The original runtime still authenticates E and matches its actual round.
    #[cfg(target_os = "linux")]
    pub fn from_root_source(path: PathBuf, pin: Digest32) -> Result<Self, AgentdError> {
        if !path.is_absolute() || pin.is_zero() {
            return Err(invalid("preparation terminal Root source identity"));
        }
        let bytes = read_root_review_input(
            &path,
            MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1 as u64,
        )
        .map_err(|e| invalid(format!("original preparation Root source: {e}")))?;
        if Digest32::of_bytes(&bytes) != pin {
            return Err(invalid("original preparation Root source pin differs"));
        }
        let (facts, evaluator) = if bytes.starts_with(b"HPTSSI01") {
            let (f, e) = decode_self_iteration_serving_scope_terminal_v1(&bytes)
                .map_err(|e| invalid(format!("whole actual Serving scope terminal: {e}")))?;
            (PreparationFactsV1::ServingScope(f), e)
        } else {
            let (f, e) = decode_self_iteration_preparation_terminal_v1(&bytes)
                .map_err(|e| invalid(format!("whole original preparation terminal: {e}")))?;
            (PreparationFactsV1::Evaluated(f), e)
        };
        Ok(Self {
            source_path: path,
            source_digest: pin,
            facts,
            evaluator,
        })
    }
    #[cfg(not(target_os = "linux"))]
    pub fn from_root_source(_path: PathBuf, _pin: Digest32) -> Result<Self, AgentdError> {
        Err(invalid("Root preparation custody requires the Linux host"))
    }
    fn revalidate(&self) -> Result<(), AgentdError> {
        let current = Self::from_root_source(self.source_path.clone(), self.source_digest)?;
        if current != *self {
            return Err(invalid("original preparation terminal source changed"));
        }
        Ok(())
    }
}

/// Compact original journal facts. This read-only value cannot be submitted as
/// a terminal receipt; it preserves the exact whole E output source and pins.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationPreparationStatusV1 {
    pub facts_hex: String,
    /// Present only for the distinct pre-G/O actual Serving incompatibility purpose.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub serving_scope_facts_hex: Option<String>,
    pub source_path: PathBuf,
    #[serde(with = "super::super::codec::digest")]
    pub source_digest: Digest32,
    #[serde(with = "super::super::codec::digest")]
    pub evaluator_evidence_digest: Digest32,
}
impl AgentdSelfIterationPreparationStatusV1 {
    pub fn facts(&self) -> Result<SelfIterationPreparationFactsV1, AgentdError> {
        if self.serving_scope_facts_hex.is_some()
            || self.facts_hex.is_empty()
            || self.facts_hex.len() > 2 * MAX_SELF_ITERATION_PREPARATION_FACTS_BYTES_V1
            || !self
                .facts_hex
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(invalid("original preparation facts encoding"));
        }
        let bytes = codex_hepta_agent_components::learning_ledger::decode_review_payload_hex(
            &self.facts_hex,
        )
        .map_err(|e| invalid(e.to_string()))?;
        decode_self_iteration_preparation_facts_v1(&bytes).map_err(|e| invalid(e.to_string()))
    }
    pub fn serving_scope_facts(
        &self,
    ) -> Result<SelfIterationServingScopeIncompatibleFactsV1, AgentdError> {
        let hex = self
            .serving_scope_facts_hex
            .as_ref()
            .ok_or_else(|| invalid("no actual Serving scope preparation facts"))?;
        if !self.facts_hex.is_empty()
            || hex.is_empty()
            || hex.len() > 2 * MAX_SELF_ITERATION_SERVING_SCOPE_FACTS_BYTES_V1
            || !hex
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(invalid("actual Serving scope preparation facts encoding"));
        }
        let bytes = codex_hepta_agent_components::learning_ledger::decode_review_payload_hex(hex)
            .map_err(|e| invalid(e.to_string()))?;
        decode_self_iteration_serving_scope_facts_v1(&bytes).map_err(|e| invalid(e.to_string()))
    }
    fn original_facts(&self) -> Result<PreparationFactsV1, AgentdError> {
        match self.serving_scope_facts_hex {
            Some(_) => self
                .serving_scope_facts()
                .map(PreparationFactsV1::ServingScope),
            None => self.facts().map(PreparationFactsV1::Evaluated),
        }
    }
    pub(super) fn validate_round(
        &self,
        round: &AgentdSelfIterationRoundV1,
        watermark: u64,
    ) -> Result<(), AgentdError> {
        let (identity, payload, canonical, execution, admitted, deadline, observed) =
            self.original_facts()?.bound_round();
        if !self.source_path.is_absolute()
            || self.source_digest.is_zero()
            || self.evaluator_evidence_digest.is_zero()
            || identity != round.identity_digest()
            || payload != Digest32::of_bytes(&round.canonical_bytes()?)
            || canonical != round.canonical_policy_digest()
            || execution != round.execution_envelope_digest()
            || admitted != round.admitted_at_ms()
            || deadline != round.deadline_ms()
            || observed > watermark
        {
            return Err(invalid(
                "preparation terminal differs from original reserved round",
            ));
        }
        Ok(())
    }
    fn from_terminal(
        value: &AgentdSelfIterationPreparationTerminalV1,
    ) -> Result<Self, AgentdError> {
        let bytes = value.facts.payload()?;
        let hex = bytes.iter().map(|b| format!("{b:02x}")).collect();
        let (facts_hex, serving_scope_facts_hex) = match &value.facts {
            PreparationFactsV1::Evaluated(_) => (hex, None),
            PreparationFactsV1::ServingScope(_) => (String::new(), Some(hex)),
        };
        let mut signed = value.evaluator.signing_bytes();
        signed.extend_from_slice(&value.evaluator.signature);
        Ok(Self {
            facts_hex,
            serving_scope_facts_hex,
            source_path: value.source_path.clone(),
            source_digest: value.source_digest,
            evaluator_evidence_digest: Digest32::of_bytes(&signed),
        })
    }
    pub(super) fn validate_state(
        &self,
        current: &RoundState,
        watermark: u64,
    ) -> Result<(), AgentdError> {
        self.validate_round(&current.permit, watermark)?;
        if !current.terminal
            || current.frozen.is_some()
            || current.rejected_proposal.is_some()
            || current.candidate_effects != Some(AgentdSelfIterationCandidateEffectsV1::NotStarted)
            || !current.stages.is_empty()
        {
            return Err(invalid(
                "preparation cannot retire an admitted model or candidate effect",
            ));
        }
        Ok(())
    }
}

pub(in crate::self_iteration) fn complete(
    owner: &mut SelfIterationOwner,
    round: &AgentdSelfIterationRoundV1,
    terminal: &AgentdSelfIterationPreparationTerminalV1,
    now: u64,
) -> Result<(), AgentdError> {
    if owner.journal.pending() {
        return Err(invalid(
            "actual candidate remains pending during preparation",
        ));
    }
    terminal.revalidate()?;
    let status = AgentdSelfIterationPreparationStatusV1::from_terminal(terminal)?;
    status.validate_round(round, now)?;
    // Actual timely E facts may arrive late. Authentication uses their original
    // signed observation; this records a fact and grants no new result authority.
    if let PreparationFactsV1::ServingScope(facts) = &terminal.facts
        && (facts.expected_training_scope_digest != owner.trust.verifier().scope_digest()
            || facts.expected_training_objective_digest
                != owner.trust.verifier().objective_digest())
    {
        return Err(invalid(
            "incompatible contract differs from original training trust",
        ));
    }
    let evidence = &terminal.evaluator;
    let observed_at = terminal.facts.bound_round().6;
    if evidence.issued_at > observed_at || evidence.issued_at < round.admitted_at_ms() {
        return Err(invalid("original preparation E observation clock"));
    }
    let payload = terminal.facts.payload()?;
    owner
        .trust
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            evidence,
            &payload,
            observed_at,
        )
        .map_err(|e| invalid(format!("original independent preparation E: {e}")))?;
    let mut rounds = owner
        .journal
        .rounds
        .clone()
        .ok_or_else(|| invalid("round not reserved"))?;
    rounds.retain_terminal_clock(now);
    rounds.complete_preparation(round, status)?;
    terminal.revalidate()?;
    owner.journal.persist_rounds(rounds)
}

impl RoundJournal {
    pub(in crate::self_iteration) fn complete_preparation(
        &mut self,
        round: &AgentdSelfIterationRoundV1,
        status: AgentdSelfIterationPreparationStatusV1,
    ) -> Result<(), AgentdError> {
        status.validate_round(round, self.watermark_ms)?;
        let current = self.current_mut(round)?;
        if current.frozen.is_some()
            || current.rejected_proposal.is_some()
            || current.candidate_effects != Some(AgentdSelfIterationCandidateEffectsV1::NotStarted)
            || !current.stages.is_empty()
            || current
                .preparation
                .as_ref()
                .is_some_and(|old| old != &status)
            || current.terminal && current.preparation.is_none()
        {
            return Err(invalid(
                "original preparation remains pending or has candidate effects",
            ));
        }
        current.preparation = Some(status);
        current.terminal = true;
        Ok(())
    }
}
