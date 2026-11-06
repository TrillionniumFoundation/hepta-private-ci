//! Opt-in stateful backend at Agentd's Neuron ownership boundary. The existing
//! host supplies its admitted control port, exclusive journal and witness.
//! Construction does not register a default daemon provider or publish output.

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationProposalV2;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::CellTaskCostV2;

pub struct AgentdNeuronGenerationOwnerV2<W: AnchorWitnessStore, P: CellGenerationControlPortV2> {
    journal: CellGenerationJournalV2<W>,
    inference_control: P,
}

impl<W: AnchorWitnessStore, P: CellGenerationControlPortV2> AgentdNeuronGenerationOwnerV2<W, P> {
    pub fn new(journal: CellGenerationJournalV2<W>, inference_control: P) -> Self {
        Self {
            journal,
            inference_control,
        }
    }

    pub fn journal(&self) -> &CellGenerationJournalV2<W> {
        &self.journal
    }

    pub fn journal_mut(&mut self) -> &mut CellGenerationJournalV2<W> {
        &mut self.journal
    }

    /// Exact retries return a receipt or inspect the original computation.
    /// Persisted admission, live pre-contact time and final settlement time are
    /// separate boundaries; unknown worker errors never reopen fresh dispatch.
    pub fn step(
        &mut self,
        request: CellGenerationRequestV2,
        mut clock: impl FnMut() -> u64,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        if let Some(receipt) = self.journal.lookup(&request)? {
            return Ok(receipt);
        }
        if let Some(pending) = self.journal.pending_request()? {
            if pending != &request {
                return Err(CellGenerationErrorV2::Conflict);
            }
            return self.reconcile(clock);
        }
        let admitted = clock();
        if let Some(receipt) = self.journal.admit(request.clone(), admitted)? {
            return Ok(receipt);
        }
        let before_contact = clock();
        if before_contact < admitted {
            return Err(CellGenerationErrorV2::Deadline);
        }
        if before_contact >= request.deadline_micros {
            // This stack frame knows no model entry occurred. A fresh process
            // cannot infer that fact from a missing readback and takes no such path.
            let manifest = self.journal.manifest();
            let cost = CellTaskCostV2::new(CellTaskCostIdentityV2 {
                task_digest: request.task_digest,
                source_digest: manifest.source_digest,
            })
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            return self.journal.commit(
                CellGenerationProposalV2 {
                    request_digest: request.digest()?,
                    bundle_digest: manifest.bundle_digest,
                    runtime_digest: manifest.runtime_digest,
                    device_digest: manifest.device_digest,
                    successor_state: request.predecessor.state.clone(),
                    output_delta: Vec::new(),
                    disposition: CellGenerationDispositionV2::DeadlineExceeded,
                    cost,
                },
                before_contact,
            );
        }
        self.journal
            .observe_dispatch_time(request.digest()?, before_contact)?;
        let proposal = self
            .inference_control
            .execute_generation(self.journal.manifest(), &request)?;
        let after_contact = clock();
        if after_contact < before_contact {
            return Err(CellGenerationErrorV2::Deadline);
        }
        self.journal.commit(proposal, after_contact)
    }

    pub fn reconcile(
        &mut self,
        mut clock: impl FnMut() -> u64,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        let request = self
            .journal
            .pending_request()?
            .cloned()
            .ok_or(CellGenerationErrorV2::Conflict)?;
        let proposal = self
            .inference_control
            .read_generation(&request)?
            .ok_or(CellGenerationErrorV2::Pending)?;
        self.journal.commit(proposal, clock())
    }

    pub fn cancel_pending(&mut self) -> Result<(), CellGenerationErrorV2> {
        let request = self
            .journal
            .pending_request()?
            .cloned()
            .ok_or(CellGenerationErrorV2::Conflict)?;
        self.journal.cancel(request.digest()?)?;
        self.inference_control.cancel_generation(&request)
    }

    pub fn drain(&mut self) -> Result<bool, CellGenerationErrorV2> {
        self.journal.drain()?;
        self.journal.is_drained()
    }
}

#[cfg(test)]
#[path = "neuron_generation_tests.rs"]
mod tests;
