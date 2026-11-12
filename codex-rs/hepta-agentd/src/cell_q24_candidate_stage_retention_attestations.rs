//! One original read transaction returns the complete evaluated signature set.
//! Root still checks every role at its own fresh clock after this future. This
//! removes repeated whole-prefix I/O within one checkpoint, not CURRENT reads
//! between calls. No public trait, cache-return API or caller callback is added.

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::Action;
use super::Error;
use super::Owners;
use super::Predecessors;
use super::common_auth;

impl Owners {
    pub(crate) async fn read_original_evaluated_attestations(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Vec<SignedLearningEvidenceV1>, Error> {
        tokio::time::timeout_at(self.end.into(), async {
            let started = common_auth::now()?;
            self.require_live_deadline()?;
            self.evaluated_retention_prefix(snapshot)?;
            match snapshot.receipts.len() {
                4 => {
                    let evaluation = self.read_original_evaluation(snapshot).await?;
                    let current = {
                        let mut common_lease = self.common.continuation.try_take()?;
                        let common = common_lease.state_mut()?;
                        Predecessors {
                            dataset: common
                                .original_dataset
                                .as_ref()
                                .ok_or(Error::CommitUncertain)?
                                .clone(),
                            training: common
                                .original_training
                                .as_ref()
                                .ok_or(Error::CommitUncertain)?
                                .clone(),
                            evaluation,
                        }
                    };
                    let fresh = common_auth::require_material(
                        &self.common.material,
                        self.common.initial_binding,
                    )?;
                    common_auth::require_clock(started, fresh)?;
                    let signatures =
                        self.evaluated_predecessor_signatures(snapshot, &current, fresh)?;
                    self.require_live_deadline()?;
                    Ok(signatures)
                }
                5 => {
                    let selection = self
                        .original_evaluated_selection(snapshot, Action::Readback)
                        .await?;
                    let mut lane_lease = self.retention.try_take()?;
                    let lane = lane_lease.state_mut()?;
                    if lane.failed || selection.snapshot() != snapshot {
                        return Err(Error::CommitUncertain);
                    }
                    let current = lane.predecessors.as_ref().ok_or(Error::CommitUncertain)?;
                    let fresh = common_auth::require_material(
                        &self.common.material,
                        self.common.initial_binding,
                    )?;
                    common_auth::require_clock(started, fresh)?;
                    let mut signatures =
                        self.evaluated_predecessor_signatures(snapshot, current, fresh)?;
                    self.verify_evaluated_selection(snapshot, current, &selection, fresh)?;
                    signatures.push(selection.attestation().clone());
                    self.require_live_deadline()?;
                    Ok(signatures)
                }
                6 => {
                    let completion = self
                        .original_evaluated_next_use(snapshot, Action::Readback)
                        .await?;
                    let mut lane_lease = self.retention.try_take()?;
                    let lane = lane_lease.state_mut()?;
                    if lane.failed || completion.snapshot() != snapshot {
                        return Err(Error::CommitUncertain);
                    }
                    let current = lane.predecessors.as_ref().ok_or(Error::CommitUncertain)?;
                    let fresh = common_auth::require_material(
                        &self.common.material,
                        self.common.initial_binding,
                    )?;
                    common_auth::require_clock(started, fresh)?;
                    let mut signatures =
                        self.evaluated_predecessor_signatures(snapshot, current, fresh)?;
                    let selection = completion.original_selection();
                    self.verify_evaluated_next_use(
                        snapshot,
                        current,
                        selection,
                        &completion,
                        fresh,
                    )?;
                    signatures.push(selection.attestation().clone());
                    signatures.push(completion.attestation().clone());
                    self.require_live_deadline()?;
                    Ok(signatures)
                }
                _ => Err(Error::WrongScope),
            }
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    // This synchronous tail is reached only after the actual original read in
    // this same invocation. It cannot be called by Root or a generic stage port.
    fn evaluated_predecessor_signatures(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        current: &Predecessors,
        fresh: u64,
    ) -> Result<Vec<SignedLearningEvidenceV1>, Error> {
        let training_cut = self.training_prefix(snapshot)?;
        let mut common_lease = self.common.continuation.try_take()?;
        let common = common_lease.state_mut()?;
        if common.original_dataset.as_ref() != Some(&current.dataset)
            || common.original_training.as_ref() != Some(&current.training)
            || current.dataset.attestations().len() != 2
            || current.dataset.snapshot().receipts != training_cut.receipts[..2]
            || current.training.receipt() != &training_cut.receipts[2]
        {
            return Err(Error::CommitUncertain);
        }
        common_auth::verify_prefix(&self.common.material, &training_cut, common, fresh)?;
        self.verify_original_evaluation(
            snapshot,
            &training_cut,
            &current.training,
            &current.evaluation,
            fresh,
        )?;
        let mut signatures = Vec::with_capacity(snapshot.receipts.len());
        for (index, signature) in current.dataset.attestations().iter().enumerate() {
            if common.records.get(index).map(|record| &record.1) != Some(signature) {
                return Err(Error::WrongScope);
            }
            signatures.push(signature.clone());
        }
        signatures.push(current.training.attestation().clone());
        signatures.push(current.evaluation.attestation().clone());
        Ok(signatures)
    }
}
