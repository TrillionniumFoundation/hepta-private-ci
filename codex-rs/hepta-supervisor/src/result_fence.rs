//! Generation- and authority-bound result admission for writer handoffs.
//!
//! Work admitted before a handoff may complete after routing changes.  The
//! result must therefore carry the writer generation and authority epoch that
//! admitted it, and the supervisor must re-check that fence at commit time.
//! This module deliberately separates "process finished" from "result may
//! mutate authoritative state".

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WriterHandoffCheckpointV1;
use crate::WriterHandoffPhaseV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WriterResultFenceV1 {
    pub domain_id: StableId,
    pub writer_id: StableId,
    pub generation: Generation,
    pub authority_epoch: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WriterResultFenceErrorV1 {
    DomainMismatch,
    StaleAuthorityEpoch,
    StaleWriterOrGeneration,
    AdmissionClosed,
}

impl std::fmt::Display for WriterResultFenceErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for WriterResultFenceErrorV1 {}

impl WriterHandoffCheckpointV1 {
    /// Issue an old-generation fence only while new work may still be admitted.
    /// The token remains usable while the predecessor is draining, but becomes
    /// invalid as soon as `Drained` is durably recorded.
    #[must_use]
    pub fn issue_old_result_fence(&self) -> Option<WriterResultFenceV1> {
        self.old_writer_admission_open()
            .then(|| WriterResultFenceV1 {
                domain_id: self.plan.domain_id.clone(),
                writer_id: self.plan.source_writer.clone(),
                generation: self.plan.old_generation,
                authority_epoch: self.plan.authority_epoch,
            })
    }

    /// Issue a successor fence only after the new route is published.
    #[must_use]
    pub fn issue_new_result_fence(&self) -> Option<WriterResultFenceV1> {
        self.new_writer_admission_open()
            .then(|| WriterResultFenceV1 {
                domain_id: self.plan.domain_id.clone(),
                writer_id: self.plan.target_writer.clone(),
                generation: self.plan.new_generation,
                authority_epoch: self.plan.authority_epoch,
            })
    }

    /// Re-check a work fence immediately before authoritative result commit.
    ///
    /// Old-generation in-flight results remain acceptable only through the
    /// drain phase. Once the durable checkpoint says `Drained`, any later old
    /// result contradicts the drain proof and is rejected. Successor results
    /// are rejected until route publication even if the process is already
    /// started and fenced.
    pub fn validate_result_fence(
        &self,
        fence: &WriterResultFenceV1,
    ) -> Result<(), WriterResultFenceErrorV1> {
        if fence.domain_id != self.plan.domain_id {
            return Err(WriterResultFenceErrorV1::DomainMismatch);
        }
        if fence.authority_epoch != self.plan.authority_epoch {
            return Err(WriterResultFenceErrorV1::StaleAuthorityEpoch);
        }

        let old_identity = fence.writer_id == self.plan.source_writer
            && fence.generation == self.plan.old_generation;
        if old_identity {
            return if matches!(
                self.phase,
                WriterHandoffPhaseV1::Prepared | WriterHandoffPhaseV1::AdmissionStopped
            ) {
                Ok(())
            } else {
                Err(WriterResultFenceErrorV1::AdmissionClosed)
            };
        }

        let new_identity = fence.writer_id == self.plan.target_writer
            && fence.generation == self.plan.new_generation;
        if new_identity {
            return if matches!(
                self.phase,
                WriterHandoffPhaseV1::RoutePublished | WriterHandoffPhaseV1::Retired
            ) {
                Ok(())
            } else {
                Err(WriterResultFenceErrorV1::AdmissionClosed)
            };
        }

        Err(WriterResultFenceErrorV1::StaleWriterOrGeneration)
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;

    use super::*;
    use crate::WriterHandoffPlanV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn checkpoint(phase: WriterHandoffPhaseV1) -> WriterHandoffCheckpointV1 {
        WriterHandoffCheckpointV1 {
            plan: WriterHandoffPlanV1 {
                operation_id: id("handoff.test"),
                domain_id: id("memory.test"),
                source_writer: id("writer.old"),
                target_writer: id("writer.new"),
                old_generation: Generation::new(1).expect("generation"),
                new_generation: Generation::new(2).expect("generation"),
                authority_epoch: 7,
                migration_plan_digest: Digest32::of_bytes(b"migration"),
                schema_digest: Digest32::of_bytes(b"schema"),
                rollback_predecessor_digest: Digest32::of_bytes(b"rollback"),
            },
            revision: 1,
            phase,
            outbox_watermark: None,
            unknown_effect_count: 0,
            evidence_digest: Digest32::of_bytes(b"evidence"),
            previous_receipt_digest: Digest32::ZERO,
            receipt_digest: Digest32::of_bytes(b"receipt"),
        }
    }

    #[test]
    fn old_generation_result_is_rejected_once_drain_is_durable() {
        let prepared = checkpoint(WriterHandoffPhaseV1::Prepared);
        let fence = prepared
            .issue_old_result_fence()
            .expect("old route accepts work before handoff");

        checkpoint(WriterHandoffPhaseV1::AdmissionStopped)
            .validate_result_fence(&fence)
            .expect("already admitted work may finish while draining");
        assert_eq!(
            checkpoint(WriterHandoffPhaseV1::Drained).validate_result_fence(&fence),
            Err(WriterResultFenceErrorV1::AdmissionClosed)
        );
        assert_eq!(
            checkpoint(WriterHandoffPhaseV1::RoutePublished).validate_result_fence(&fence),
            Err(WriterResultFenceErrorV1::AdmissionClosed)
        );
    }

    #[test]
    fn successor_result_cannot_commit_before_route_publication() {
        let published = checkpoint(WriterHandoffPhaseV1::RoutePublished);
        let fence = published
            .issue_new_result_fence()
            .expect("published route accepts successor work");

        assert_eq!(
            checkpoint(WriterHandoffPhaseV1::NewWriterFenced).validate_result_fence(&fence),
            Err(WriterResultFenceErrorV1::AdmissionClosed)
        );
        published
            .validate_result_fence(&fence)
            .expect("current successor result accepted");
        checkpoint(WriterHandoffPhaseV1::Retired)
            .validate_result_fence(&fence)
            .expect("successor remains current after predecessor retirement");
    }

    #[test]
    fn authority_epoch_and_generation_must_match_exactly() {
        let current = checkpoint(WriterHandoffPhaseV1::RoutePublished);
        let mut fence = current.issue_new_result_fence().expect("new fence");
        fence.authority_epoch += 1;
        assert_eq!(
            current.validate_result_fence(&fence),
            Err(WriterResultFenceErrorV1::StaleAuthorityEpoch)
        );

        let mut fence = current.issue_new_result_fence().expect("new fence");
        fence.generation = Generation::new(3).expect("generation");
        assert_eq!(
            current.validate_result_fence(&fence),
            Err(WriterResultFenceErrorV1::StaleWriterOrGeneration)
        );
    }
}
