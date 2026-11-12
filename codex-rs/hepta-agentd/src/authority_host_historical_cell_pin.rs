//! Root retention of the actual Cell cut independently of the Source pin.
//! Registration observes an empty original Cell before Initial enrollment is
//! acknowledged. Capture cannot initialize a missing baseline or clear a
//! refused read. Retained data alone never authorizes a historical recipient.

use super::super::data_refusal::RootDataKind;
use super::*;
use codex_hepta_neuron::CellGenerationCurrentV1;

#[path = "authority_host_historical_cell_files.rs"]
mod files;
pub(crate) use files::OriginalCellFiles;
use files::OriginalCellObservation;
pub(crate) use files::RootHistoricalCellInputsV1;
#[path = "authority_host_historical_cell_registration.rs"]
mod registration;

const CELL_PURPOSE: &str = "runtime.circuit.original-cell-retention.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case", deny_unknown_fields)]
enum CellPhase {
    Enrolled,
    Captured {
        source_pin: String,
        source_publication: String,
        sequence: u64,
        checkpoint: String,
        decision: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellRecord {
    schema: u8,
    purpose: String,
    initial_profile: String,
    identity: String,
    writer: String,
    publisher_epoch: u64,
    publisher: CognitiveCheckpointPeerLifetime,
    target: CellGenerationOwnerBindingV1,
    files: [FilePin; 2],
    context: String,
    phase: CellPhase,
}

/// Consumed once by the actual post-drain Source worker. Its independent arm
/// contains the caller's entire original Root context, including postchecks.
pub(crate) struct RegisteredOriginalCellCaptureV1 {
    files: OriginalCellFiles,
    root: Arc<RootAuthorityDirectory>,
    store: HostAuthorityFrontierStore<CellRecord>,
    owner: String,
    baseline: CellRecord,
    refusal: RootDataRefusalV1,
}

pub(crate) struct PendingOriginalCellCaptureV1<'a> {
    original: &'a RegisteredOriginalCellCaptureV1,
    captured: Option<CellRecord>,
}

impl RegisteredOriginalCellCaptureV1 {
    pub(crate) fn with_original_cell_capture<T>(
        original: Option<Self>,
        action: impl FnOnce(Option<&mut PendingOriginalCellCaptureV1<'_>>) -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        let Some(original) = original else {
            return action(None);
        };
        original.refusal.inspect(|| {
            if original
                .store
                .load(&original.owner)
                .map_err(io::Error::other)?
                != original.baseline
                || original.baseline.phase != CellPhase::Enrolled
            {
                return Err(io::Error::other("original Cell capture baseline changed"));
            }
            let mut pending = PendingOriginalCellCaptureV1 {
                original: &original,
                captured: None,
            };
            let result = action(Some(&mut pending))?;
            let captured = pending
                .captured
                .ok_or_else(|| io::Error::other("original Cell capture was not observed"))?;
            if original
                .store
                .load(&original.owner)
                .map_err(io::Error::other)?
                != captured
            {
                return Err(io::Error::other(
                    "original Cell capture changed after Root context",
                ));
            }
            Ok(result)
        })
    }
}

impl PendingOriginalCellCaptureV1<'_> {
    pub(super) fn observe_and_retain_original_cell(
        &mut self,
        slot: &RegisteredGenerationInitial,
        inputs: &RootHistoricalSourceInputsV1,
        source: &crate::HistoricalCircuitTaskSourceObservationV1,
        retained: &RetainedSourcePinRecordV1,
    ) -> io::Result<()> {
        original_root()?;
        let original = self.original;
        let baseline = &original.baseline;
        if self.captured.is_some()
            || baseline.initial_profile != slot.profile.binding
            || baseline.identity != slot.profile.identity
            || baseline.writer != slot.profile.writer
            || baseline.target != slot.profile.deployment.target
            || baseline.files != *original.files.file_pins()
            || baseline.context != original.files.context_digest().to_string()
            || retained.expected.pin.initial_profile != baseline.initial_profile
            || retained.expected.pin.publisher != baseline.publisher
            || retained.expected.pin.publisher_epoch != baseline.publisher_epoch
            || retained.expected.pin.target != baseline.target
            || retained.expected.pin.publication
                != source.publication().publication_digest().to_string()
        {
            return Err(io::Error::other(
                "original Cell capture differs from its enrolled publisher",
            ));
        }
        // This is the actual protected CURRENT owner for the still-live A.
        // It is used only by the no-writer Cell reader inside the original
        // artifact/FinalUse/writer context; it is never a retired-task guard.
        let current: Arc<dyn CellGenerationCurrentV1> = Arc::new(
            NeuronGenerationCurrentOwnerV1::open(
                Arc::clone(&original.root),
                baseline.target.scope(),
            )
            .map_err(io::Error::other)?,
        );
        let observed = original.files.observe_original_cell(
            &inputs.definition,
            &inputs.source,
            source.publication(),
            &baseline.target,
            current,
        )?;
        let mut next = baseline.clone();
        next.phase = CellPhase::Captured {
            source_pin: Digest32::of_parts(&[
                b"hepta.root.historical-source-pin.v1\0",
                &serde_json::to_vec(&retained.expected).map_err(io::Error::other)?,
            ])
            .to_string(),
            source_publication: source.publication().publication_digest().to_string(),
            sequence: observed.anchor.sequence,
            checkpoint: observed.anchor.checkpoint_digest.to_string(),
            decision: original_decision_digest(&observed)?.to_string(),
        };
        original
            .store
            .compare_and_set(&original.owner, baseline, &next)
            .map_err(io::Error::other)?;
        if original
            .store
            .load(&original.owner)
            .map_err(io::Error::other)?
            != next
        {
            return Err(io::Error::other(
                "original Cell capture acknowledgement differs",
            ));
        }
        self.captured = Some(next);
        Ok(())
    }
}

fn original_decision_digest(observed: &OriginalCellObservation) -> io::Result<Digest32> {
    let decision = &observed.decision;
    decision
        .representation
        .validate()
        .map_err(io::Error::other)?;
    Ok(Digest32::of_parts(&[
        b"hepta.root.original-cell-decision.v1\0",
        &crate::circuit_cell_output::encode_receipt(decision).map_err(io::Error::other)?,
        &serde_json::to_vec(&(
            &decision.representation.drive_q24,
            &decision.representation.prediction_q24,
        ))
        .map_err(io::Error::other)?,
    ]))
}

fn cell_owner(target: &CellGenerationOwnerBindingV1) -> io::Result<String> {
    target.digest().map_err(io::Error::other)?;
    Ok(format!(
        "historical-cell/{}",
        crate::neuron_generation_current::types::scope_digest(target.scope())
            .map_err(io::Error::other)?
    ))
}
