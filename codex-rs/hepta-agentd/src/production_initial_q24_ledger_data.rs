//! First-A Ledger file/profile data from the original sealed deployment.
//! Role identities, keys and trust enrollment are never selected by this data.

use std::path::PathBuf;

use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::AgentdError;
use crate::OriginalCellQ24TaskLedgerConfigV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LedgerDeploymentData {
    schema: String,
    mode: InitialLedgerMode,
    pub(super) ledger: PathBuf,
    pub(super) ledger_witness: PathBuf,
    pub(super) binding: [u8; 32],
    pub(super) maximum_records: usize,
    pub(super) generator_key: PathBuf,
    pub(super) signature_journal: PathBuf,
    pub(super) signature_witness: SignatureWitnessData,
    contract: OutcomeContractData,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum InitialLedgerMode {
    Create,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignatureWitnessData {
    pub(super) path: PathBuf,
    pub(super) scope: [u8; 32],
    pub(super) generation: u64,
    pub(super) maximum_records: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OutcomeContractData {
    episode_id: String,
    candidate_set_id: String,
    generator_code_digest: [u8; 32],
    grammar_digest: [u8; 32],
    hard_filter_digest: [u8; 32],
    truncation_digest: [u8; 32],
    outcome_record_id: String,
    outcome_id: String,
    unit_profile_digest: [u8; 32],
    expected_delay_profile_digest: [u8; 32],
    claim_deadline_unix_seconds: u64,
    maximum_signature_lifetime_seconds: u64,
}

impl LedgerDeploymentData {
    pub(super) fn configuration(
        &self,
        generator: TrustedLearningSignerV1,
        observer: TrustedLearningSignerV1,
        now: u64,
    ) -> Result<OriginalCellQ24TaskLedgerConfigV1, AgentdError> {
        let InitialLedgerMode::Create = &self.mode;
        let contract = &self.contract;
        if self.schema != "hepta.agentd.original_initial_q24_ledger.v1"
            || !(4..=8192).contains(&self.maximum_records)
            || !(5..=4096).contains(&self.signature_witness.maximum_records)
            || self.signature_witness.generation == 0
            || now >= contract.claim_deadline_unix_seconds
            || !(1..=86_400).contains(&contract.maximum_signature_lifetime_seconds)
        {
            return Err(invalid("explicit first-A Ledger profile or bounds differ"));
        }
        for bytes in [
            self.binding,
            self.signature_witness.scope,
            contract.generator_code_digest,
            contract.grammar_digest,
            contract.hard_filter_digest,
            contract.truncation_digest,
            contract.unit_profile_digest,
            contract.expected_delay_profile_digest,
        ] {
            if Digest32::from_array(bytes).is_zero() {
                return Err(invalid("original Ledger profile requires nonzero digests"));
            }
        }
        let id = |raw: &str| {
            if !(1..=128).contains(&raw.len()) {
                return Err(invalid("original Ledger identity bound"));
            }
            StableId::new(raw).map_err(invalid)
        };
        Ok(OriginalCellQ24TaskLedgerConfigV1 {
            episode_id: id(&contract.episode_id)?,
            candidate_set_id: id(&contract.candidate_set_id)?,
            generator_code_digest: Digest32::from_array(contract.generator_code_digest),
            grammar_digest: Digest32::from_array(contract.grammar_digest),
            hard_filter_digest: Digest32::from_array(contract.hard_filter_digest),
            truncation_digest: Digest32::from_array(contract.truncation_digest),
            generator,
            observer,
            outcome_record_id: id(&contract.outcome_record_id)?,
            outcome_id: id(&contract.outcome_id)?,
            unit_profile_digest: Digest32::from_array(contract.unit_profile_digest),
            expected_delay_profile_digest: Digest32::from_array(
                contract.expected_delay_profile_digest,
            ),
            claim_deadline_unix_seconds: contract.claim_deadline_unix_seconds,
            maximum_signature_lifetime_seconds: contract.maximum_signature_lifetime_seconds,
        })
    }
}

pub(super) fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original Initial Ledger: {error}"))
}
