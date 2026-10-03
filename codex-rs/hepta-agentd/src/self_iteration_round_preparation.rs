//! Original reserved preparation can finish without inventing a model request
//! or candidate. Only the actual independent E's Root-retained whole output
//! enters this path; quota and the original clock remain consumed.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::read_root_review_input;
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdSelfIterationPreparationTerminalV1 {
    source_path: PathBuf,
    source_digest: Digest32,
    facts: SelfIterationPreparationFactsV1,
    evaluator: SignedLearningEvidenceV1,
}
impl AgentdSelfIterationPreparationTerminalV1 {
    /// This checks the original Root file custody and complete portable packet.
    /// The original runtime still authenticates E and matches its actual round.
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
        let (facts, evaluator) = decode_self_iteration_preparation_terminal_v1(&bytes)
            .map_err(|e| invalid(format!("whole original preparation terminal: {e}")))?;
        Ok(Self {
            source_path: path,
            source_digest: pin,
            facts,
            evaluator,
        })
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
    pub source_path: PathBuf,
    #[serde(with = "super::super::codec::digest")]
    pub source_digest: Digest32,
    #[serde(with = "super::super::codec::digest")]
    pub evaluator_evidence_digest: Digest32,
}
impl AgentdSelfIterationPreparationStatusV1 {
    pub fn facts(&self) -> Result<SelfIterationPreparationFactsV1, AgentdError> {
        if self.facts_hex.is_empty()
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
    pub(super) fn validate_round(
        &self,
        round: &AgentdSelfIterationRoundV1,
        watermark: u64,
    ) -> Result<(), AgentdError> {
        let facts = self.facts()?;
        if !self.source_path.is_absolute()
            || self.source_digest.is_zero()
            || self.evaluator_evidence_digest.is_zero()
            || facts.round_identity_digest != round.identity_digest()
            || facts.round_payload_digest != Digest32::of_bytes(&round.canonical_bytes()?)
            || facts.canonical_policy_digest != round.canonical_policy_digest()
            || facts.execution_envelope_digest != round.execution_envelope_digest()
            || facts.admitted_at_ms != round.admitted_at_ms()
            || facts.deadline_ms != round.deadline_ms()
            || facts.observed_at_ms > watermark
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
        let bytes = self_iteration_preparation_terminal_signing_payload_v1(&value.facts)
            .map_err(|e| invalid(e.to_string()))?;
        let mut signed = value.evaluator.signing_bytes();
        signed.extend_from_slice(&value.evaluator.signature);
        Ok(Self {
            facts_hex: bytes.iter().map(|b| format!("{b:02x}")).collect(),
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
    let evidence = &terminal.evaluator;
    if evidence.issued_at > terminal.facts.observed_at_ms
        || evidence.issued_at < round.admitted_at_ms()
    {
        return Err(invalid("original preparation E observation clock"));
    }
    let payload = self_iteration_preparation_terminal_signing_payload_v1(&terminal.facts)
        .map_err(|e| invalid(e.to_string()))?;
    owner
        .trust
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            evidence,
            &payload,
            terminal.facts.observed_at_ms,
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
