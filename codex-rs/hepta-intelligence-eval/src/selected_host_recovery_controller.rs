//! A bounded persistent sweep through the existing selected-host owner APIs.
//!
//! The cursor is scheduling progress only. Every action revalidates the anchored
//! history; prewrite replay uses the native archive verifier, while Pending is
//! read-reconciled without resubmission. No provider or estimator is accepted.
use std::fs::File;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FinalHoldoutCasStoreV1;
use crate::ProductAttemptRecoveryErrorV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::attempt_recovery::validated_history;

#[path = "recovery_cursor.rs"]
mod cursor;
use cursor::RecoveryCursor;

type RecordedError = RecordedProductEvaluationErrorV1;

#[derive(Clone, Copy)]
struct RecoveryTrustFrontierV1 {
    root_digest: Digest32,
    distribution_digest: Digest32,
    generation: u64,
    effective_at: u64,
    authority_epoch: u64,
}

impl RecoveryTrustFrontierV1 {
    fn admit(
        trust: &ActivatedLearningTrustV1,
        now: u64,
        previous: Option<Self>,
    ) -> Result<Self, RecordedError> {
        let current = Self {
            root_digest: trust.root_digest(),
            distribution_digest: trust.distribution_digest(),
            generation: trust.generation(),
            effective_at: trust.effective_at(),
            authority_epoch: trust.verifier().authority_epoch(),
        };
        if current.root_digest.is_zero()
            || current.distribution_digest.is_zero()
            || current.generation == 0
            || current.authority_epoch == 0
            || current.effective_at > now
        {
            return Err(RecordedError::Invariant(
                "selected-host recovery trust is not current",
            ));
        }
        if let Some(previous) = previous
            && (current.root_digest != previous.root_digest
                || current.generation < previous.generation
                || current.effective_at < previous.effective_at
                || current.authority_epoch < previous.authority_epoch
                || (current.generation == previous.generation
                    && current.distribution_digest != previous.distribution_digest))
        {
            return Err(RecordedError::Invariant(
                "selected-host recovery trust regressed",
            ));
        }
        Ok(current)
    }
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    /// Process one page using an exclusively locked, host-provisioned cursor.
    ///
    /// The host supplies a freshly resolved root-authenticated learning-trust
    /// activation and clock sample before every attempt. A page may observe a
    /// monotonic distribution rotation, but it never keeps using a cached bare
    /// verifier after the host has moved to another generation. Root changes,
    /// generation/epoch regression, same-generation distribution substitution
    /// and clock regression fail the page closed. Restarting the page is the
    /// boundary for an independently authorized root-rotation ceremony.
    ///
    /// The host must provide bounded/interruptible storage I/O: the wall budget
    /// is cooperative between owner calls, not a claim to preempt a blocked
    /// filesystem. The returned per-attempt errors retain unresolved work.
    /// Cursor progress survives process exit, advances past rejected evidence,
    /// and wraps only after a complete pass. A journal, cursor or trust-frontier
    /// error aborts the page.
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    pub fn recover_selected_host_pending_page<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        cursor_file: File,
        artifact_root: &Path,
        publication_root: &Path,
        selected_host_binding: Digest32,
        mut current_trust: impl FnMut()
            -> Result<(ActivatedLearningTrustV1, u64), RecordedError>,
        budget: Duration,
        limit: usize,
    ) -> Result<
        Vec<(
            StableId,
            Result<ProductEvaluationAttemptReceiptV1, RecordedError>,
        )>,
        RecordedError,
    > {
        if selected_host_binding.is_zero()
            || !(1..=32).contains(&limit)
            || budget.is_zero()
            || budget > Duration::from_secs(60)
        {
            return Err(RecordedError::Invariant(
                "selected-host recovery page bounds",
            ));
        }
        let started = Instant::now();
        let binding = Digest32::of_parts(&[
            b"hepta.learning-eval.recovery-cursor.v1",
            selected_host_binding.as_array(),
            self.namespace.as_array(),
        ]);
        let mut cursor = RecoveryCursor::open(cursor_file, binding)?;
        let page = journal.pending(cursor.after(), limit)?;
        if page.len() > limit {
            return Err(RecordedError::Invariant(
                "recovery inventory exceeds page",
            ));
        }
        let mut previous = cursor.after().cloned();
        for receipt in &page {
            receipt.validate_integrity()?;
            let id = &receipt.transition.attempt_id;
            if receipt.transition.phase.is_terminal()
                || previous.as_ref().is_some_and(|before| before >= id)
            {
                return Err(RecordedError::Invariant(
                    "invalid recovery inventory order",
                ));
            }
            previous = Some(id.clone());
        }
        let page_len = page.len();
        let mut results = Vec::with_capacity(page_len);
        let mut previous_now = None;
        let mut previous_trust = None;
        for receipt in page {
            if started.elapsed() >= budget {
                break;
            }
            let (trust, now) = current_trust()?;
            if previous_now.is_some_and(|before| now < before) {
                return Err(RecordedError::Invariant(
                    "recovery host clock regressed",
                ));
            }
            previous_now = Some(now);
            previous_trust = Some(RecoveryTrustFrontierV1::admit(
                &trust,
                now,
                previous_trust,
            )?);

            let id = receipt.transition.attempt_id.clone();
            let result = (|| {
                let history = validated_history(journal, &id)
                    .map_err(|error| map_recovery(&id, error))?;
                if history.last() != Some(&receipt)
                    || !history.iter().any(|event| {
                        event.transition.phase
                            == ProductEvaluationAttemptPhaseV1::IntentPersisted
                            && event.transition.holdout_record_digest == self.namespace
                    })
                {
                    return Err(RecordedError::AttemptRequiresRecovery {
                        attempt_id: id.clone(),
                    });
                }
                use ProductEvaluationAttemptPhaseV1 as Phase;
                match receipt.transition.phase {
                    Phase::PublicationPending => Self::reconcile_selected_host_publication(
                        journal,
                        &id,
                        publication_root,
                        selected_host_binding,
                    )
                    .map_err(|error| map_recovery(&id, error)),
                    Phase::QualificationArtifactsPersisted | Phase::QualificationDecided => {
                        if receipt.transition.phase == Phase::QualificationDecided {
                            match Self::reconcile_selected_host_publication(
                                journal,
                                &id,
                                publication_root,
                                selected_host_binding,
                            ) {
                                Ok(published) => return Ok(published),
                                Err(ProductAttemptRecoveryErrorV1::Unresolved) => {}
                                Err(error) => return Err(map_recovery(&id, error)),
                            }
                        }
                        // A wrong-family archive is rejected before any phase
                        // mutation. Only that pre-admission refusal may try the
                        // other registered family; signature errors never fall
                        // back to a weaker path. Both APIs verify V2/V3 internally
                        // against the freshly resolved active trust above.
                        match self.recover_selected_host_qualification(
                            journal,
                            &id,
                            artifact_root,
                            publication_root,
                            selected_host_binding,
                            trust.verifier(),
                            now,
                        ) {
                            Err(RecordedError::AttemptRequiresRecovery { .. }) => self
                                .recover_selected_host_outcome_qualification(
                                    journal,
                                    &id,
                                    artifact_root,
                                    publication_root,
                                    selected_host_binding,
                                    trust.verifier(),
                                    now,
                                ),
                            result => result,
                        }
                    }
                    Phase::IntentPersisted
                    | Phase::HoldoutConsumed
                    | Phase::ComparisonSealed => {
                        // Consumption reconciliation and lost estimator objects
                        // require their existing owner protocols, never reruns.
                        Err(RecordedError::AttemptRequiresRecovery {
                            attempt_id: id.clone(),
                        })
                    }
                    Phase::Failed | Phase::RejectedBeforeHoldout | Phase::Published => {
                        Err(RecordedError::Invariant(
                            "terminal attempt in pending inventory",
                        ))
                    }
                }
            })();
            match result {
                Err(RecordedError::Journal(error)) => {
                    return Err(RecordedError::Journal(error));
                }
                result => {
                    // Persist after each handled identity, including an
                    // unresolved one. Unknown cursor fsync aborts immediately.
                    cursor.save(Some(&id))?;
                    results.push((id, result));
                }
            }
        }
        if results.len() == page_len && page_len < limit {
            cursor.save(None)?;
        }
        Ok(results)
    }
}

fn map_recovery(id: &StableId, error: ProductAttemptRecoveryErrorV1) -> RecordedError {
    match error {
        ProductAttemptRecoveryErrorV1::Journal(error) => RecordedError::Journal(error),
        ProductAttemptRecoveryErrorV1::MissingIntent
        | ProductAttemptRecoveryErrorV1::WrongPhase
        | ProductAttemptRecoveryErrorV1::Unresolved
        | ProductAttemptRecoveryErrorV1::EvidenceMismatch => {
            RecordedError::AttemptRequiresRecovery {
                attempt_id: id.clone(),
            }
        }
    }
}
