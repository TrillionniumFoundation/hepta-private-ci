//! Actual journal/ACK/Control files with explicitly synthetic mechanism costs.
//! An Advanced proposal here is a file-protocol fixture, not model execution.

use std::fs::OpenOptions;
use std::io::Write;

use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::CellGenerationProposalV2;
use codex_hepta_types::Digest32;

use super::super::Fixture;
use super::super::Journal;
use super::super::RECORDS;
use super::super::config;
use super::super::cost;
use super::super::request;
use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_current::NeuronGenerationUpdatePublicationV1;
use crate::neuron_generation_current::PreparedNeuronGenerationUpdateV1;
use crate::neuron_generation_current::PublishedNeuronGenerationUpdateV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

pub(super) struct Case {
    pub(super) fixture: Fixture,
    pub(super) old: Journal,
    pub(super) new: Journal,
    pub(super) selected: AgentdSelectedGenerationV1,
    pub(super) prepared: PreparedNeuronGenerationUpdateV1,
    pub(super) signed: SignedFinalUseGrant,
}

impl Case {
    pub(super) fn new(
        stopped: bool,
        completion: NeuronGenerationPredecessorCompletionV1,
    ) -> anyhow::Result<Self> {
        let fixture = Fixture::new(config()?)?;
        let old = if stopped {
            fixture.stopped_old()?
        } else {
            let mut old = fixture.old_journal()?;
            append_advanced(&fixture, &mut old)?;
            deliver(&fixture, &mut old)?;
            old.drain()?;
            old
        };
        let selected = fixture.selection()?;
        let binding = CellGenerationOwnerBindingV1::new(&fixture.target_config, RECORDS)?;
        let prepared = match completion {
            NeuronGenerationPredecessorCompletionV1::ModelStopped => {
                fixture
                    .current
                    .prepare(&old, "replace-completion".into(), binding, &selected)?
            }
            NeuronGenerationPredecessorCompletionV1::OwnerDrained => {
                fixture.current.prepare_drained_retirement(
                    &old,
                    "replace-completion".into(),
                    binding,
                    &selected,
                )?
            }
            NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel => {
                anyhow::bail!("replacement fixture requires a changed manifest")
            }
        };
        let target = fixture.target_create()?;
        let new = CellGenerationJournalV2::open_guarded(
            target.file,
            target.witness,
            target.config,
            target.max_records,
            fixture.current.clone(),
        )?;
        let signed = fixture.sign(prepared.final_use_binding())?;
        Ok(Self {
            fixture,
            old,
            new,
            selected,
            prepared,
            signed,
        })
    }

    pub(super) fn publish(&mut self) -> Result<PublishedNeuronGenerationUpdateV1, AgentdError> {
        let mut artifacts = self
            .fixture
            .artifacts
            .lock()
            .map_err(|_| AgentdError::Invalid("artifact lock poisoned".into()))?;
        self.fixture.current.publish(
            &self.prepared,
            &self.old,
            &self.new,
            &mut self.selected,
            NeuronGenerationUpdatePublicationV1 {
                artifacts: &mut artifacts,
                authority: &self.fixture.authority,
                signed: &self.signed,
                clock: self.fixture.clock.as_ref(),
            },
        )
    }
}

pub(super) fn append_advanced(fixture: &Fixture, old: &mut Journal) -> anyhow::Result<()> {
    let request = request(old, &fixture.old_config, "synthetic-advanced")?;
    old.admit(request.clone(), /*now_micros*/ 10)?;
    old.commit(
        CellGenerationProposalV2 {
            request_digest: request.digest()?,
            bundle_digest: fixture.old_config.manifest.bundle_digest,
            runtime_digest: fixture.old_config.manifest.runtime_digest,
            device_digest: fixture.old_config.manifest.device_digest,
            successor_state: request.predecessor.state,
            output_delta: vec![42],
            disposition: CellGenerationDispositionV2::Advanced,
            cost: cost(&fixture.old_config, "advanced", CellCostStageV2::Inference)?,
        },
        /*now_micros*/ 11,
    )?;
    Ok(())
}

pub(super) fn deliver(fixture: &Fixture, old: &mut Journal) -> anyhow::Result<()> {
    let chunk = old
        .pending_output()?
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("missing actual unacknowledged output"))?;
    let mut receiver = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(fixture.directory.path().join("advanced-delivery"))?;
    receiver.write_all(&chunk.bytes)?;
    receiver.sync_all()?;
    old.acknowledge(
        chunk,
        Digest32::of_bytes(b"advanced-receiver-ack").into_array(),
        cost(
            &fixture.old_config,
            "advanced-ack",
            CellCostStageV2::Communication,
        )?,
    )?;
    Ok(())
}
