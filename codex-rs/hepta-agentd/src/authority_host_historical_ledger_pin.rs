//! Independently retained original Ledger custody. This module supplies data
//! capture only; historical Dataset admission requires a new Root recipient.

use super::super::data_refusal::RootDataKind;
use super::*;
use crate::cell_q24_task_ledger::history::OriginalTaskLedgerHistoryContextV1;
use crate::root_historical_ledger_data::RootHistoricalLedgerCutDataV1 as CapturedLedgerCut;
use crate::root_initial_learning_trust_data::LearningTrustPinV1;

#[path = "authority_host_historical_ledger_files.rs"]
mod files;
pub(crate) use files::OriginalLedgerFiles;
use files::OriginalLedgerObservation;
use files::OriginalLedgerReadGuard;
use files::OriginalLedgerReadModeV1;

#[path = "authority_host_historical_ledger_history.rs"]
mod history;
#[path = "authority_host_historical_ledger_registration.rs"]
mod registration;
pub(crate) use history::PendingOriginalLedgerHistoryV1;
pub(crate) use history::RootOriginalHistoricalLedgerObservationV1;

const LEDGER_PURPOSE: &str = "runtime.circuit.original-ledger-retention.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case", deny_unknown_fields)]
enum LedgerPhase {
    Enrolled,
    Captured { cut: Box<CapturedLedgerCut> },
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct LedgerRecord {
    schema: u8,
    purpose: String,
    initial_profile: String,
    identity: String,
    registered_identity: String,
    writer: String,
    publisher_epoch: u64,
    publisher: CognitiveCheckpointPeerLifetime,
    peer_gid: u32,
    target: CellGenerationOwnerBindingV1,
    files: [FilePin; 4],
    metadata: String,
    registered_at: u64,
    trust: LearningTrustPinV1,
    phase: LedgerPhase,
}

pub(crate) struct RegisteredOriginalLedgerCaptureV1 {
    files: OriginalLedgerFiles,
    store: HostAuthorityFrontierStore<LedgerRecord>,
    owner: String,
    baseline: LedgerRecord,
    config: crate::OriginalCellQ24TaskLedgerConfigV1,
    refusal: RootDataRefusalV1,
    end: std::time::Instant,
}

pub(crate) struct PendingOriginalLedgerCaptureV1<'a> {
    original: &'a RegisteredOriginalLedgerCaptureV1,
    captured: Option<(
        LedgerRecord,
        OriginalLedgerObservation,
        OriginalLedgerReadGuard,
    )>,
}

pub(super) struct OriginalLedgerCaptureDataV1<'a> {
    pub(super) identity: &'a crate::AgentdIdentity,
    pub(super) inputs: &'a RootHistoricalSourceInputsV1,
    pub(super) source: &'a crate::HistoricalCircuitTaskSourceObservationV1,
    pub(super) cell: &'a codex_hepta_neuron::CellDecisionReceiptV1,
    pub(super) retained: &'a RetainedSourcePinRecordV1,
}

impl RegisteredOriginalLedgerCaptureV1 {
    pub(crate) fn with_original_ledger_capture<T>(
        original: Option<Self>,
        action: impl FnOnce(Option<&mut PendingOriginalLedgerCaptureV1<'_>>) -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        let Some(original) = original else {
            return action(None);
        };
        original.refusal.inspect(|| {
            if std::time::Instant::now() >= original.end
                || original.baseline.phase != LedgerPhase::Enrolled
                || original
                    .store
                    .load(&original.owner)
                    .map_err(io::Error::other)?
                    != original.baseline
            {
                return Err(io::Error::other(
                    "original Ledger enrollment changed or expired",
                ));
            }
            original.files.require_original_files()?;
            let mut pending = PendingOriginalLedgerCaptureV1 {
                original: &original,
                captured: None,
            };
            // The actual writer/Artifact/FinalUse/pidfd context, including all
            // its postchecks, executes before this independent arm may clear.
            let result = action(Some(&mut pending))?;
            let (captured, observation, mut held) = pending
                .captured
                .ok_or_else(|| io::Error::other("original Ledger capture was not observed"))?;
            held.require_unchanged(&observation)?;
            original.files.require_original_files()?;
            if original
                .store
                .load(&original.owner)
                .map_err(io::Error::other)?
                != captured
                || std::time::Instant::now() >= original.end
            {
                return Err(io::Error::other(
                    "original Ledger capture changed after Root context",
                ));
            }
            Ok(result)
        })
    }
}

impl PendingOriginalLedgerCaptureV1<'_> {
    pub(super) fn observe_and_retain_original_ledger(
        &mut self,
        slot: &RegisteredGenerationInitial,
        data: OriginalLedgerCaptureDataV1<'_>,
        now_millis: u64,
    ) -> io::Result<()> {
        original_root()?;
        let OriginalLedgerCaptureDataV1 {
            identity,
            inputs,
            source,
            cell,
            retained,
        } = data;
        let original = self.original;
        let baseline = &original.baseline;
        if self.captured.is_some()
            || baseline.initial_profile != slot.profile.binding
            || baseline.identity != slot.profile.identity
            || baseline.writer != slot.profile.writer
            || baseline.target != slot.profile.deployment.target
            || baseline.files != *original.files.file_pins()
            || baseline.metadata != original.files.deployment.metadata_digest().to_string()
            || Some(&baseline.trust) != slot.profile.learning_trust.as_ref()
            || retained.expected.pin.initial_profile != baseline.initial_profile
            || retained.expected.pin.publisher != baseline.publisher
            || retained.expected.pin.publisher_epoch != baseline.publisher_epoch
            || retained.expected.pin.target != baseline.target
            || retained.expected.pin.publication
                != source.publication().publication_digest().to_string()
            || source.original_identity() != identity
        {
            return Err(io::Error::other(
                "original Ledger capture differs from enrolled publisher",
            ));
        }
        for ledger in &baseline.files {
            if retained
                .expected
                .pin
                .source_files
                .iter()
                .any(|source| (ledger.device, ledger.inode) == (source.device, source.inode))
            {
                return Err(io::Error::other("original Source and Ledger files alias"));
            }
        }
        let trust = slot
            .learning_trust
            .as_ref()
            .ok_or_else(|| io::Error::other("original enrolled Ledger trust missing"))?;
        let (activated, generator, observer) = trust
            .read_original_payload(now_millis)?
            .activate_pinned_genesis(now_millis / 1_000)?;
        if generator != original.config.generator || observer != original.config.observer {
            return Err(io::Error::other("original Ledger role enrollment differs"));
        }
        let context = OriginalTaskLedgerHistoryContextV1 {
            identity,
            definition: &inputs.definition,
            source: &inputs.source,
            config: &original.config,
            ledger_binding: Digest32::from_array(original.files.deployment.ledger.binding),
            verifier: activated.verifier(),
        };
        let mut held = original
            .files
            .open_original_terminal(&context, OriginalLedgerReadModeV1::Capture)?;
        let observed = held.observe_original_terminal(
            &context,
            source.publication(),
            cell,
            now_millis / 1_000,
        )?;
        let source_pin = Digest32::of_parts(&[
            b"hepta.root.historical-source-pin.v1\0",
            &serde_json::to_vec(&retained.expected).map_err(io::Error::other)?,
        ]);
        let cut =
            CapturedLedgerCut::from_original(&observed, source.publication(), cell, source_pin)?;
        let mut next = baseline.clone();
        next.phase = LedgerPhase::Captured { cut: Box::new(cut) };
        original
            .store
            .compare_and_set(&original.owner, baseline, &next)
            .map_err(io::Error::other)?;
        held.require_unchanged(&observed)?;
        original.files.require_original_files()?;
        if original
            .store
            .load(&original.owner)
            .map_err(io::Error::other)?
            != next
        {
            return Err(io::Error::other(
                "original Ledger capture acknowledgement differs",
            ));
        }
        self.captured = Some((next, observed, held));
        Ok(())
    }
}

impl CapturedLedgerCut {
    fn from_original(
        observed: &OriginalLedgerObservation,
        publication: &crate::CircuitTaskSourcePublicationV1,
        cell: &codex_hepta_neuron::CellDecisionReceiptV1,
        source_pin: Digest32,
    ) -> io::Result<Self> {
        Ok(Self {
            source_pin: source_pin.to_string(),
            source_publication: publication.publication_digest().to_string(),
            cell_decision: Digest32::of_parts(&[
                b"hepta.root.original-ledger-cell-decision.v1\0",
                &crate::circuit_cell_output::encode_receipt(cell).map_err(io::Error::other)?,
                &serde_json::to_vec(&(
                    &cell.representation.drive_q24,
                    &cell.representation.prediction_q24,
                ))
                .map_err(io::Error::other)?,
            ])
            .to_string(),
            ledger_binding: observed.cut.binding.to_string(),
            ledger_sequence: observed.cut.frontier.anchor.sequence,
            ledger_chain: observed.cut.frontier.anchor.chain_digest.to_string(),
            ledger_length: observed.cut.ledger_length,
            ledger_image: observed.cut.ledger_digest.to_string(),
            witness_length: observed.cut.witness_length,
            witness_image: observed.cut.witness_digest.to_string(),
            signature_binding: observed.facts.signature_binding.to_string(),
            signature_sequence: observed.signature_anchor.sequence,
            signature_checkpoint: observed.signature_anchor.checkpoint_digest.to_string(),
            signature_length: observed.signature_images[0].0,
            signature_image: observed.signature_images[0].1.to_string(),
            signature_witness_length: observed.signature_images[1].0,
            signature_witness_image: observed.signature_images[1].1.to_string(),
            decision_chain: observed.facts.decision.chain_digest.to_string(),
            outcome_chain: observed.facts.outcome.chain_digest.to_string(),
        })
    }
}

fn ledger_owner(target: &CellGenerationOwnerBindingV1) -> io::Result<String> {
    target.digest().map_err(io::Error::other)?;
    Ok(format!(
        "historical-ledger/{}",
        crate::neuron_generation_current::types::scope_digest(target.scope())
            .map_err(io::Error::other)?
    ))
}
