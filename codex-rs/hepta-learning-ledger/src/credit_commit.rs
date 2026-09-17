//! Conserved V2 credit committed through the witnessed durable V1 ledger.
//!
//! The compatibility ledger retains individual `CreditAssignment` events, but a
//! product caller no longer needs to append them one-by-one. This adapter binds
//! the batch to the active terminal outcome, validates exact conservation, builds
//! deterministic record identities, atomically appends the complete allocation
//! set and advances the independent ledger witness before returning success.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AcknowledgedLearningJournal;
use crate::AppendReceipt;
use crate::CausalV2Error;
use crate::CreditAllocationBatchV1;
use crate::CreditAllocationReceiptV1;
use crate::CreditAssignment;
use crate::DurableLedgerError;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LearningLedger;
use crate::OutcomeFinality;
use crate::finalize_credit_batch;

const RECORD_ID_DOMAIN: &[u8] = b"hepta.learning-ledger.credit-record-id.v1";
const CREDIT_ID_DOMAIN: &[u8] = b"hepta.learning-ledger.credit-id.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCreditBatchReceiptV1 {
    pub conservation: CreditAllocationReceiptV1,
    pub appends: Vec<AppendReceipt>,
    pub terminal_chain_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableCreditBatchError {
    Causal(CausalV2Error),
    Ledger(DurableLedgerError),
    Snapshot(LedgerError),
    ActiveTerminalOutcomeMissing,
    TerminalOutcomeMismatch,
    DerivedIdentity,
}

impl fmt::Display for DurableCreditBatchError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableCreditBatchError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Causal(error) => Some(error),
            Self::Ledger(error) => Some(error),
            Self::Snapshot(error) => Some(error),
            Self::ActiveTerminalOutcomeMissing
            | Self::TerminalOutcomeMismatch
            | Self::DerivedIdentity => None,
        }
    }
}

impl From<CausalV2Error> for DurableCreditBatchError {
    fn from(value: CausalV2Error) -> Self {
        Self::Causal(value)
    }
}

impl From<DurableLedgerError> for DurableCreditBatchError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Ledger(value)
    }
}

impl From<LedgerError> for DurableCreditBatchError {
    fn from(value: LedgerError) -> Self {
        Self::Snapshot(value)
    }
}

/// Validate and durably commit one complete causal-credit publication unit.
///
/// The terminal outcome value is derived from the acknowledged ledger snapshot,
/// not trusted from the submitted batch. Every emitted V1 credit event binds the
/// V2 batch digest in `support_digest`. The durable batch append and independent
/// witness advance complete before this function returns success.
pub fn append_conserved_credit_batch_v1(
    ledger: &mut dyn AcknowledgedLearningJournal,
    expected_predecessor: Digest32,
    mut batch: CreditAllocationBatchV1,
    now: u64,
) -> Result<DurableCreditBatchReceiptV1, DurableCreditBatchError> {
    let snapshot = ledger.snapshot()?;
    let replayed = LearningLedger::from_snapshot(snapshot)?;
    let terminal = replayed.active_records().into_iter().find_map(|record| {
        let LedgerEvent::Outcome(outcome) = &record.event else {
            return None;
        };
        (outcome.episode_id == batch.episode_id
            && outcome.outcome_id == batch.outcome_id
            && outcome.finality == OutcomeFinality::Terminal)
            .then_some(outcome.value)
    });
    let terminal = terminal.ok_or(DurableCreditBatchError::ActiveTerminalOutcomeMissing)?;
    if terminal != batch.terminal_outcome {
        return Err(DurableCreditBatchError::TerminalOutcomeMismatch);
    }

    let conservation = finalize_credit_batch(batch.clone(), now)?;
    batch
        .allocations
        .sort_by(|left, right| left.target_id.cmp(&right.target_id));
    let mut events = Vec::with_capacity(batch.allocations.len());
    for allocation in &batch.allocations {
        let record_id = derived_id(
            "credit-record",
            RECORD_ID_DOMAIN,
            conservation.batch_digest,
            &allocation.target_id,
        )?;
        let credit_id = derived_id(
            "credit",
            CREDIT_ID_DOMAIN,
            conservation.batch_digest,
            &allocation.target_id,
        )?;
        events.push(LedgerEvent::Credit(CreditAssignment {
            record_id,
            credit_id,
            episode_id: batch.episode_id.clone(),
            outcome_id: batch.outcome_id.clone(),
            target_artifact_id: allocation.target_id.clone(),
            allocator_id: batch.allocator.principal_id.clone(),
            credit: allocation.credit,
            support_digest: conservation.batch_digest,
        }));
    }

    let appends = ledger.append_batch(expected_predecessor, events)?;
    let terminal_chain_digest = appends
        .last()
        .map(|receipt| receipt.chain_digest)
        .ok_or(DurableCreditBatchError::DerivedIdentity)?;
    Ok(DurableCreditBatchReceiptV1 {
        conservation,
        appends,
        terminal_chain_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn derived_id(
    prefix: &str,
    domain: &[u8],
    batch_digest: Digest32,
    target: &StableId,
) -> Result<StableId, DurableCreditBatchError> {
    let mut bytes = Vec::with_capacity(domain.len() + 32 + target.as_str().len() + 4);
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(batch_digest.as_array());
    let target_bytes = target.as_str().as_bytes();
    let target_len = u32::try_from(target_bytes.len())
        .map_err(|_| DurableCreditBatchError::DerivedIdentity)?;
    bytes.extend_from_slice(&target_len.to_be_bytes());
    bytes.extend_from_slice(target_bytes);
    let digest = Digest32::of_bytes(&bytes);
    StableId::new(format!("{prefix}:{digest}"))
        .map_err(|_| DurableCreditBatchError::DerivedIdentity)
}

#[cfg(test)]
mod tests {
    use std::fs::File;
    use std::fs::OpenOptions;
    use std::path::Path;
    use std::path::PathBuf;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;

    use super::*;
    use crate::AuthenticatedPrincipalV1;
    use crate::CandidateSetCompleteness;
    use crate::CreditAllocationV1;
    use crate::DurableLedger;
    use crate::EpisodeDecision;
    use crate::LedgerWitnessStore;
    use crate::OutcomeObservation;
    use crate::WitnessedLearningLedger;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn file(root: &Path, name: &str, create_new: bool) -> File {
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        if create_new {
            options.create_new(true);
        }
        options.open(root.join(name)).expect("open test file")
    }

    fn temp_root(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-credit-batch-{label}-{}-{nanos}",
            std::process::id()
        ));
        std::fs::create_dir(&root).expect("create test root");
        root
    }

    fn allocator() -> AuthenticatedPrincipalV1 {
        AuthenticatedPrincipalV1 {
            principal_id: id("allocator"),
            credential_chain_digest: digest("allocator-credential"),
            signing_key_digest: digest("allocator-key"),
            scope_digest: digest("scope"),
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 100,
        }
    }

    fn batch(terminal_outcome: FixedQ32) -> CreditAllocationBatchV1 {
        let half = FixedQ32::from_raw(FixedQ32::ONE.raw() / 2);
        CreditAllocationBatchV1 {
            batch_id: id("batch"),
            episode_id: id("episode"),
            outcome_id: id("outcome"),
            allocator: allocator(),
            terminal_outcome,
            allocations: vec![
                CreditAllocationV1 {
                    target_id: id("artifact-b"),
                    credit: half,
                },
                CreditAllocationV1 {
                    target_id: id("artifact-a"),
                    credit: half,
                },
            ],
            conservation_residual: FixedQ32::ZERO,
            support_digest: digest("batch-support"),
            finalized: true,
        }
    }

    fn writer(root: &Path) -> WitnessedLearningLedger<DurableLedger> {
        let ledger = DurableLedger::create(
            file(root, "ledger", true),
            digest("ledger-binding"),
            16,
        )
        .expect("create ledger");
        let witness = LedgerWitnessStore::create(
            file(root, "witness", true),
            digest("witness-binding"),
        )
        .expect("create witness");
        WitnessedLearningLedger::attach(ledger, witness).expect("attach witness")
    }

    fn seed_terminal_outcome(
        writer: &mut WitnessedLearningLedger<DurableLedger>,
    ) -> Digest32 {
        let decision = writer
            .append(
                Digest32::ZERO,
                LedgerEvent::Decision(EpisodeDecision {
                    record_id: id("decision-record"),
                    episode_id: id("episode"),
                    objective_digest: digest("objective"),
                    policy_id: id("policy"),
                    candidate_ids: vec![id("abstain"), id("action")],
                    selected_candidate_id: id("action"),
                    selected_propensity: ProbabilityQ32::ONE,
                    completeness: CandidateSetCompleteness::Complete,
                    support_digest: digest("decision-support"),
                }),
            )
            .expect("append decision");
        writer
            .append(
                decision.chain_digest,
                LedgerEvent::Outcome(OutcomeObservation {
                    record_id: id("outcome-record"),
                    outcome_id: id("outcome"),
                    episode_id: id("episode"),
                    observer_id: id("observer"),
                    value: FixedQ32::ONE,
                    finality: OutcomeFinality::Terminal,
                    support_digest: digest("outcome-support"),
                }),
            )
            .expect("append outcome")
            .chain_digest
    }

    #[test]
    fn conserved_credit_is_atomic_and_witnessed() {
        let root = temp_root("success");
        let mut writer = writer(&root);
        let predecessor = seed_terminal_outcome(&mut writer);
        let receipt = append_conserved_credit_batch_v1(
            &mut writer,
            predecessor,
            batch(FixedQ32::ONE),
            50,
        )
        .expect("append conserved credit");
        assert_eq!(receipt.appends.len(), 2);
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
        assert_eq!(writer.witness_anchor().sequence, 4);
        assert_eq!(writer.witness_anchor().chain_digest, receipt.terminal_chain_digest);
        let snapshot = writer.snapshot().expect("snapshot");
        for record in &snapshot.records()[2..] {
            let LedgerEvent::Credit(credit) = &record.event else {
                panic!("credit record expected")
            };
            assert_eq!(credit.support_digest, receipt.conservation.batch_digest);
        }
        drop(writer);
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn submitted_terminal_value_cannot_drift_from_ledger() {
        let root = temp_root("terminal-mismatch");
        let mut writer = writer(&root);
        let predecessor = seed_terminal_outcome(&mut writer);
        assert_eq!(
            append_conserved_credit_batch_v1(
                &mut writer,
                predecessor,
                batch(FixedQ32::ZERO),
                50,
            ),
            Err(DurableCreditBatchError::TerminalOutcomeMismatch)
        );
        assert_eq!(writer.snapshot().expect("snapshot").records().len(), 2);
        drop(writer);
        std::fs::remove_dir_all(root).expect("remove test root");
    }
}
