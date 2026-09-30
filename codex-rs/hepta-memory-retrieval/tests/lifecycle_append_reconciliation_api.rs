use std::cell::Cell;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_memory_retrieval::DurableDecisionAppendErrorV1;
use codex_hepta_memory_retrieval::DurableDecisionPortV1;
use codex_hepta_memory_retrieval::DurableDecisionRecordV1;
use codex_hepta_memory_retrieval::QuarantinedUnknownOutcomeV1;
use codex_hepta_memory_retrieval::RetrievalExecutionIdentityPartsV1;
use codex_hepta_memory_retrieval::RetrievalExecutionIdentityV1;
use codex_hepta_memory_retrieval::RetrievalLifecyclePhaseV1;
use codex_hepta_memory_retrieval::append_durable_decision_checked_v1;

fn identity() -> RetrievalExecutionIdentityV1 {
    RetrievalExecutionIdentityV1::new(RetrievalExecutionIdentityPartsV1 {
        tenant: "tenant-a".to_string(),
        principal: "principal-a".to_string(),
        request: "request-a".to_string(),
        query_digest: "query-a".to_string(),
        policy_generation: "policy-7".to_string(),
        encoder_identity: "encoder-3".to_string(),
        snapshot_identity: "snapshot-11".to_string(),
        decision_identity: "decision-19".to_string(),
    })
    .expect("valid lifecycle identity")
}

fn candidate(payload: &str) -> DurableDecisionRecordV1 {
    DurableDecisionRecordV1 {
        identity: identity(),
        phase: RetrievalLifecyclePhaseV1::QualifiedDecision,
        writer_fence: 7,
        frontier: 1,
        payload_digest: payload.to_string(),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PortError {
    CompareAndAppend,
    LostAcknowledgement,
    Load,
}

impl fmt::Display for PortError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PortError {}

#[derive(Default)]
struct Port {
    frontier: u64,
    latest: Option<DurableDecisionRecordV1>,
    writes: usize,
    fail_before_commit_once: bool,
    fail_after_commit_once: bool,
    fail_confirmation_once: Cell<bool>,
    replacement: Option<DurableDecisionRecordV1>,
}

impl DurableDecisionPortV1 for Port {
    type Error = PortError;

    fn acquire_writer_fence(&mut self, _writer_identity: &str) -> Result<u64, Self::Error> {
        Ok(7)
    }

    fn compare_and_append(
        &mut self,
        expected_frontier: u64,
        record: &DurableDecisionRecordV1,
    ) -> Result<u64, Self::Error> {
        if expected_frontier != self.frontier || self.fail_before_commit_once {
            self.fail_before_commit_once = false;
            return Err(PortError::CompareAndAppend);
        }
        self.frontier = self
            .frontier
            .checked_add(1)
            .expect("test frontier capacity");
        self.writes = self.writes.checked_add(1).expect("test write capacity");
        self.latest = Some(self.replacement.take().unwrap_or_else(|| record.clone()));
        if self.fail_after_commit_once {
            self.fail_after_commit_once = false;
            return Err(PortError::LostAcknowledgement);
        }
        Ok(self.frontier)
    }

    fn load_latest(
        &self,
        execution: &RetrievalExecutionIdentityV1,
    ) -> Result<Option<DurableDecisionRecordV1>, Self::Error> {
        if self.writes > 0 && self.fail_confirmation_once.replace(false) {
            return Err(PortError::Load);
        }
        Ok(self
            .latest
            .as_ref()
            .filter(|record| &record.identity == execution)
            .cloned())
    }

    fn quarantine_unknown_outcome(
        &mut self,
        expected_frontier: u64,
        outcome: &QuarantinedUnknownOutcomeV1,
        writer_fence: u64,
        payload_digest: &str,
    ) -> Result<u64, Self::Error> {
        self.compare_and_append(
            expected_frontier,
            &DurableDecisionRecordV1 {
                identity: outcome.identity().clone(),
                phase: RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
                writer_fence,
                frontier: expected_frontier
                    .checked_add(1)
                    .expect("test frontier capacity"),
                payload_digest: payload_digest.to_string(),
            },
        )
    }

    fn verify_replay_integrity(&self) -> Result<(), Self::Error> {
        Ok(())
    }

    fn retire_before_frontier(&mut self, exclusive_frontier: u64) -> Result<u64, Self::Error> {
        let retired = self
            .latest
            .as_ref()
            .is_some_and(|record| record.frontier < exclusive_frontier);
        if retired {
            self.latest = None;
        }
        Ok(if retired { 1 } else { 0 })
    }
}

#[test]
fn lost_acknowledgement_is_reconciled_without_a_second_write() {
    let next = candidate("prepared");
    let mut port = Port {
        fail_after_commit_once: true,
        ..Port::default()
    };

    assert_eq!(
        append_durable_decision_checked_v1(&mut port, 0, &next, None)
            .expect("exact committed record reconciles"),
        1
    );
    assert_eq!(port.writes, 1);

    append_durable_decision_checked_v1(&mut port, 0, &next, None)
        .expect("exact replay is idempotent");
    assert_eq!(port.writes, 1);
}

#[test]
fn failed_append_without_exact_readback_is_typed_unknown() {
    let next = candidate("prepared");
    let mut port = Port {
        fail_before_commit_once: true,
        ..Port::default()
    };

    let error = append_durable_decision_checked_v1(&mut port, 0, &next, None)
        .expect_err("unproven mutating error must be outcome unknown");
    assert!(matches!(
        error,
        DurableDecisionAppendErrorV1::CommitOutcomeUnknown {
            append_error: Some(PortError::CompareAndAppend),
            reconciliation_error: None,
            observed_frontier: None,
            observed_phase: None,
        }
    ));
    assert_eq!(port.writes, 0);
}

#[test]
fn successful_append_with_failed_confirmation_is_typed_unknown() {
    let next = candidate("prepared");
    let mut port = Port {
        fail_confirmation_once: Cell::new(true),
        ..Port::default()
    };

    let error = append_durable_decision_checked_v1(&mut port, 0, &next, None)
        .expect_err("success without exact confirmation must be outcome unknown");
    assert!(matches!(
        error,
        DurableDecisionAppendErrorV1::CommitOutcomeUnknown {
            append_error: None,
            reconciliation_error: Some(PortError::Load),
            observed_frontier: None,
            observed_phase: None,
        }
    ));
    assert_eq!(port.writes, 1);

    append_durable_decision_checked_v1(&mut port, 0, &next, None)
        .expect("later exact reload recognizes the committed record");
    assert_eq!(port.writes, 1);
}

#[test]
fn successful_port_return_requires_the_exact_committed_record() {
    let next = candidate("prepared");
    let replacement = DurableDecisionRecordV1 {
        phase: RetrievalLifecyclePhaseV1::PublishedRetrieval,
        payload_digest: "different-publication".to_string(),
        ..next.clone()
    };
    let mut port = Port {
        replacement: Some(replacement),
        ..Port::default()
    };

    let error = append_durable_decision_checked_v1(&mut port, 0, &next, None)
        .expect_err("wrong committed record must fail");
    assert!(matches!(
        error,
        DurableDecisionAppendErrorV1::CommittedRecordMismatch {
            expected_frontier: 1,
            actual_frontier: Some(1),
            actual_phase: Some(RetrievalLifecyclePhaseV1::PublishedRetrieval),
        }
    ));
    assert_eq!(port.writes, 1);
}
