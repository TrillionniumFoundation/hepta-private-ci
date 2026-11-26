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
use crate::product::SelectedHostClockErrorV1;
use crate::product::SelectedHostClockV1;

#[path = "recovery_cursor.rs"]
mod cursor;
use cursor::RecoveryCursor;

type RecordedError = RecordedProductEvaluationErrorV1;

#[derive(Clone, Copy)]
struct RecoveryTrustFrontierV1 {
    clock_binding: Digest32,
    root_digest: Digest32,
    distribution_digest: Digest32,
    generation: u64,
    effective_at: u64,
    expires_at: u64,
    authority_epoch: u64,
}

impl RecoveryTrustFrontierV1 {
    fn admit(
        trust: &ActivatedLearningTrustV1,
        now: u64,
        clock_binding: Digest32,
        previous: Option<Self>,
    ) -> Result<Self, RecordedError> {
        if !trust.is_current_at(now) {
            return Err(RecordedError::Invariant(
                "selected-host recovery trust is not current",
            ));
        }
        Self {
            clock_binding,
            root_digest: trust.root_digest(),
            distribution_digest: trust.distribution_digest(),
            generation: trust.generation(),
            effective_at: trust.effective_at(),
            expires_at: trust.expires_at(),
            authority_epoch: trust.verifier().authority_epoch(),
        }
        .validate(now, previous)
    }

    fn validate(self, now: u64, previous: Option<Self>) -> Result<Self, RecordedError> {
        if self.clock_binding.is_zero()
            || self.root_digest.is_zero()
            || self.distribution_digest.is_zero()
            || self.generation == 0
            || self.authority_epoch == 0
            || self.effective_at > now
            || now > self.expires_at
        {
            return Err(RecordedError::Invariant(
                "selected-host recovery trust is not current",
            ));
        }
        if let Some(previous) = previous
            && (self.clock_binding != previous.clock_binding
                || self.root_digest != previous.root_digest
                || self.generation < previous.generation
                || self.effective_at < previous.effective_at
                || self.authority_epoch < previous.authority_epoch
                || (self.generation == previous.generation
                    && self.distribution_digest != previous.distribution_digest))
        {
            return Err(RecordedError::Invariant(
                "selected-host recovery trust regressed",
            ));
        }
        Ok(self)
    }
}

fn map_clock(error: SelectedHostClockErrorV1) -> RecordedError {
    match error {
        SelectedHostClockErrorV1::Unavailable => {
            RecordedError::Invariant("selected-host recovery clock unavailable")
        }
        SelectedHostClockErrorV1::Indeterminate => {
            RecordedError::Invariant("selected-host recovery clock indeterminate")
        }
    }
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    /// Process one page using an exclusively locked, host-provisioned cursor.
    ///
    /// The host supplies a freshly resolved root-authenticated learning-trust
    /// activation before every attempt. The runner samples the host-owned clock
    /// immediately before verification/publication final use. Clock identity,
    /// sampled time, root, generation and epoch may not regress within a page.
    /// Restarting the page is the boundary for an independently authorized root
    /// rotation ceremony.
    ///
    /// The host must provide bounded/interruptible storage I/O: the wall budget
    /// is cooperative between owner calls, not a claim to preempt a blocked
    /// filesystem. Cursor progress survives process exit and advances past a
    /// handled unresolved identity. A journal, cursor, clock or trust-frontier
    /// error aborts the page.
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    pub fn recover_selected_host_pending_page<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        cursor_file: File,
        artifact_root: &Path,
        publication_root: &Path,
        selected_host_binding: Digest32,
        clock: &mut dyn SelectedHostClockV1,
        mut current_trust: impl FnMut() -> Result<ActivatedLearningTrustV1, RecordedError>,
        budget: Duration,
        limit: usize,
    ) -> Result<
        Vec<(
            StableId,
            Result<ProductEvaluationAttemptReceiptV1, RecordedError>,
        )>,
        RecordedError,
    > {
        let clock_binding = clock.binding();
        if selected_host_binding.is_zero()
            || clock_binding.is_zero()
            || !(1..=32).contains(&limit)
            || budget.is_zero()
            || budget > Duration::from_secs(60)
        {
            return Err(RecordedError::Invariant(
                "selected-host recovery page bounds",
            ));
        }
        let started = Instant::now();
        // Preserve the existing cursor binding/format. Clock identity is a
        // selected-topology fact and is checked on every use within this page.
        let binding = Digest32::of_parts(&[
            b"hepta.learning-eval.recovery-cursor.v1",
            selected_host_binding.as_array(),
            self.namespace.as_array(),
        ]);
        let mut cursor = RecoveryCursor::open(cursor_file, binding)?;
        let page = journal.pending(cursor.after(), limit)?;
        if page.len() > limit {
            return Err(RecordedError::Invariant("recovery inventory exceeds page"));
        }
        let mut previous = cursor.after().cloned();
        for receipt in &page {
            receipt.validate_integrity()?;
            let id = &receipt.transition.attempt_id;
            if receipt.transition.phase.is_terminal()
                || previous.as_ref().is_some_and(|before| before >= id)
            {
                return Err(RecordedError::Invariant("invalid recovery inventory order"));
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
            let trust = current_trust()?;
            if clock.binding() != clock_binding {
                return Err(RecordedError::Invariant(
                    "selected-host recovery clock binding changed",
                ));
            }
            let mut now = clock.sample_current_time().map_err(map_clock)?;
            if clock.binding() != clock_binding {
                return Err(RecordedError::Invariant(
                    "selected-host recovery clock binding changed",
                ));
            }
            if previous_now.is_some_and(|before| now < before) {
                return Err(RecordedError::Invariant("recovery host clock regressed"));
            }
            previous_trust = Some(RecoveryTrustFrontierV1::admit(
                &trust,
                now,
                clock_binding,
                previous_trust,
            )?);

            let id = receipt.transition.attempt_id.clone();
            let result = (|| {
                let history =
                    validated_history(journal, &id).map_err(|error| map_recovery(&id, error))?;
                if history.last() != Some(&receipt)
                    || !history.iter().any(|event| {
                        event.transition.phase == ProductEvaluationAttemptPhaseV1::IntentPersisted
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
                        // A wrong-family archive is rejected before phase
                        // mutation. Only that pre-admission refusal may try the
                        // other registered family; signature errors never fall
                        // back to a weaker path. Both paths resample time and
                        // reverify after write-ahead I/O at first publication.
                        match self.recover_selected_host_qualification_at_current_time(
                            journal,
                            &id,
                            artifact_root,
                            publication_root,
                            selected_host_binding,
                            &trust,
                            clock,
                            clock_binding,
                            &mut now,
                        ) {
                            Err(RecordedError::AttemptRequiresRecovery { .. }) => self
                                .recover_selected_host_outcome_qualification_at_current_time(
                                    journal,
                                    &id,
                                    artifact_root,
                                    publication_root,
                                    selected_host_binding,
                                    &trust,
                                    clock,
                                    clock_binding,
                                    &mut now,
                                ),
                            result => result,
                        }
                    }
                    Phase::IntentPersisted | Phase::HoldoutConsumed | Phase::ComparisonSealed => {
                        // Consumption reconciliation and lost estimator objects
                        // require their existing owner protocols, never reruns.
                        Err(RecordedError::AttemptRequiresRecovery {
                            attempt_id: id.clone(),
                        })
                    }
                    Phase::Failed | Phase::RejectedBeforeHoldout | Phase::Published => Err(
                        RecordedError::Invariant("terminal attempt in pending inventory"),
                    ),
                }
            })();
            // Preserve the final-use sample for the next identity's monotonic
            // comparison, including a per-attempt signature rejection.
            previous_now = Some(now);
            match result {
                Err(RecordedError::Journal(error)) => {
                    return Err(RecordedError::Journal(error));
                }
                Err(error @ RecordedError::Invariant(_)) => return Err(error),
                result => {
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

#[cfg(test)]
mod trust_frontier_tests {
    use super::*;

    fn frontier(label: &str) -> RecoveryTrustFrontierV1 {
        RecoveryTrustFrontierV1 {
            clock_binding: Digest32::of_bytes(b"clock"),
            root_digest: Digest32::of_bytes(format!("root:{label}").as_bytes()),
            distribution_digest: Digest32::of_bytes(format!("distribution:{label}").as_bytes()),
            generation: 7,
            effective_at: 70,
            expires_at: 130,
            authority_epoch: 11,
        }
    }

    fn assert_not_current(value: RecoveryTrustFrontierV1, now: u64) {
        assert!(matches!(
            value.validate(now, None),
            Err(RecordedError::Invariant(
                "selected-host recovery trust is not current"
            ))
        ));
    }

    fn assert_regressed(value: RecoveryTrustFrontierV1, previous: RecoveryTrustFrontierV1) {
        assert!(matches!(
            value.validate(100, Some(previous)),
            Err(RecordedError::Invariant(
                "selected-host recovery trust regressed"
            ))
        ));
    }

    #[test]
    fn recovery_trust_rejects_zero_future_and_expired_frontiers() {
        let valid = frontier("valid");
        assert_not_current(
            RecoveryTrustFrontierV1 {
                clock_binding: Digest32::ZERO,
                ..valid
            },
            100,
        );
        assert_not_current(
            RecoveryTrustFrontierV1 {
                root_digest: Digest32::ZERO,
                ..valid
            },
            100,
        );
        assert_not_current(
            RecoveryTrustFrontierV1 {
                distribution_digest: Digest32::ZERO,
                ..valid
            },
            100,
        );
        assert_not_current(
            RecoveryTrustFrontierV1 {
                generation: 0,
                ..valid
            },
            100,
        );
        assert_not_current(
            RecoveryTrustFrontierV1 {
                authority_epoch: 0,
                ..valid
            },
            100,
        );
        assert_not_current(
            RecoveryTrustFrontierV1 {
                effective_at: 101,
                ..valid
            },
            100,
        );
        assert_not_current(
            RecoveryTrustFrontierV1 {
                expires_at: 99,
                ..valid
            },
            100,
        );
    }

    #[test]
    fn recovery_trust_rejects_every_in_page_regression_class() {
        let previous = frontier("previous");
        assert_regressed(
            RecoveryTrustFrontierV1 {
                clock_binding: Digest32::of_bytes(b"different-clock"),
                ..previous
            },
            previous,
        );
        assert_regressed(frontier("different-root"), previous);
        assert_regressed(
            RecoveryTrustFrontierV1 {
                generation: previous.generation - 1,
                ..previous
            },
            previous,
        );
        assert_regressed(
            RecoveryTrustFrontierV1 {
                effective_at: previous.effective_at - 1,
                ..previous
            },
            previous,
        );
        assert_regressed(
            RecoveryTrustFrontierV1 {
                authority_epoch: previous.authority_epoch - 1,
                ..previous
            },
            previous,
        );
        assert_regressed(
            RecoveryTrustFrontierV1 {
                distribution_digest: Digest32::of_bytes(b"same-generation-substitution"),
                ..previous
            },
            previous,
        );
    }

    #[test]
    fn recovery_trust_accepts_same_frontier_and_monotonic_rotation() {
        let previous = frontier("previous");
        assert!(previous.validate(100, Some(previous)).is_ok());
        let rotated = RecoveryTrustFrontierV1 {
            distribution_digest: Digest32::of_bytes(b"rotated-distribution"),
            generation: previous.generation + 1,
            effective_at: previous.effective_at + 1,
            authority_epoch: previous.authority_epoch + 1,
            ..previous
        };
        assert!(matches!(
            rotated.validate(100, Some(previous)),
            Ok(value) if value.generation == rotated.generation
        ));
    }
}
