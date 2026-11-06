//! Opt-in stateful backend at Agentd's Neuron ownership boundary. The existing
//! host supplies its admitted control port, exclusive journal and witness.
//! Construction does not register a default daemon provider or publish output.

use std::time::Instant;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationProposalV2;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;

pub struct AgentdNeuronGenerationOwnerV2<W: AnchorWitnessStore, P: CellGenerationControlPortV2> {
    journal: CellGenerationJournalV2<W>,
    inference_control: P,
}

pub(crate) enum GenerationOwnerBoundary {
    Admission,
    Dispatch,
    Settlement,
}

enum NoContactReason {
    Draining,
    Deadline,
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
        clock: impl FnMut() -> u64,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        self.step_checked(request, clock, |_| Ok(()))
    }

    pub(crate) fn step_checked(
        &mut self,
        request: CellGenerationRequestV2,
        mut clock: impl FnMut() -> u64,
        mut check: impl FnMut(GenerationOwnerBoundary) -> Result<(), CellGenerationErrorV2>,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        if let Some(receipt) = self.journal.lookup(&request)? {
            return Ok(receipt);
        }
        if let Some(pending) = self.journal.pending_request()? {
            if pending != &request {
                return Err(CellGenerationErrorV2::Conflict);
            }
            return self.reconcile_checked(clock, || check(GenerationOwnerBoundary::Settlement));
        }
        let started = Instant::now();
        let admitted = clock();
        check(GenerationOwnerBoundary::Admission)?;
        if let Some(receipt) = self.journal.admit(request.clone(), admitted)? {
            return Ok(receipt);
        }
        let before_contact = clock();
        if before_contact < admitted {
            return Err(CellGenerationErrorV2::Deadline);
        }
        if before_contact >= request.deadline_micros {
            return self.settle_no_contact(
                &request,
                NoContactReason::Deadline,
                started,
                before_contact,
                || check(GenerationOwnerBoundary::Settlement),
            );
        }
        self.journal
            .observe_dispatch_time(request.digest()?, before_contact)?;
        match check(GenerationOwnerBoundary::Dispatch) {
            Ok(()) => {}
            Err(CellGenerationErrorV2::Draining) => {
                return self.settle_no_contact(
                    &request,
                    NoContactReason::Draining,
                    started,
                    before_contact,
                    || check(GenerationOwnerBoundary::Settlement),
                );
            }
            Err(error) => return Err(error),
        }
        let proposal = self
            .inference_control
            .execute_generation(self.journal.manifest(), &request)?;
        let after_contact = clock();
        if after_contact < before_contact {
            return Err(CellGenerationErrorV2::Deadline);
        }
        check(GenerationOwnerBoundary::Settlement)?;
        self.journal.commit(proposal, after_contact)
    }

    fn settle_no_contact(
        &mut self,
        request: &CellGenerationRequestV2,
        reason: NoContactReason,
        started: Instant,
        observed_at: u64,
        mut check: impl FnMut() -> Result<(), CellGenerationErrorV2>,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        // Only the live stack above proves that control was never contacted.
        // Missing readback after reopen, or a worker error, proves no such fact.
        let (disposition, outcome) = match reason {
            NoContactReason::Draining => (
                CellGenerationDispositionV2::Rejected,
                CellCostOutcomeV2::Rejected,
            ),
            NoContactReason::Deadline => (
                CellGenerationDispositionV2::DeadlineExceeded,
                CellCostOutcomeV2::Failed,
            ),
        };
        let request_digest = request.digest()?;
        let manifest = self.journal.manifest();
        let mut cost = CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        check()?;
        // One undivided host admission/check interval, including admission
        // persistence latency, charged once as Queue. No control actor ran.
        // This excludes proposal construction, the final fence check/Commit,
        // and complete cost-record persistence. Future substage meters must
        // partition this interval or use an envelope rather than add charges.
        let wall_micros = u64::try_from(started.elapsed().as_micros())
            .map_err(|_| CellGenerationErrorV2::Capacity)?;
        cost.record(CellCostEntryV2 {
            event_id: Digest32::of_parts(&[
                b"hepta.agentd.generation.no-contact.v1\0",
                &request_digest,
            ])
            .into_array(),
            identity: cost.identity(),
            stage: CellCostStageV2::Queue,
            outcome,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(wall_micros),
                ..CellCostMetricsV2::default()
            },
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let proposal = CellGenerationProposalV2 {
            request_digest,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: request.predecessor.state.clone(),
            output_delta: Vec::new(),
            disposition,
            cost,
        };
        check()?;
        self.journal.commit(proposal, observed_at)
    }

    pub fn reconcile(
        &mut self,
        clock: impl FnMut() -> u64,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        self.reconcile_checked(clock, || Ok(()))
    }

    pub(crate) fn reconcile_checked(
        &mut self,
        mut clock: impl FnMut() -> u64,
        mut check: impl FnMut() -> Result<(), CellGenerationErrorV2>,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        let request = self
            .journal
            .pending_request()?
            .cloned()
            .ok_or(CellGenerationErrorV2::Conflict)?;
        check()?;
        let proposal = self
            .inference_control
            .read_generation(&request)?
            .ok_or(CellGenerationErrorV2::Pending)?;
        let settled = clock();
        check()?;
        self.journal.commit(proposal, settled)
    }

    pub fn cancel_pending(&mut self) -> Result<(), CellGenerationErrorV2> {
        self.cancel_pending_checked(|| Ok(()))
    }

    pub(crate) fn cancel_pending_checked(
        &mut self,
        mut check: impl FnMut() -> Result<(), CellGenerationErrorV2>,
    ) -> Result<(), CellGenerationErrorV2> {
        let request = self
            .journal
            .pending_request()?
            .cloned()
            .ok_or(CellGenerationErrorV2::Conflict)?;
        check()?;
        self.journal.cancel(request.digest()?)?;
        check()?;
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
