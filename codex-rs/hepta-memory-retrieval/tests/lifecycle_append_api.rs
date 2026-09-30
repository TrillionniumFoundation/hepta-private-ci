use std::io;

use codex_hepta_memory_retrieval::DurableDecisionAppendErrorV1;
use codex_hepta_memory_retrieval::DurableDecisionPortV1;
use codex_hepta_memory_retrieval::DurableDecisionRecordV1;
use codex_hepta_memory_retrieval::DurableDecisionTransitionErrorV1;
use codex_hepta_memory_retrieval::QuarantinedUnknownOutcomeV1;
use codex_hepta_memory_retrieval::RetrievalExecutionIdentityPartsV1;
use codex_hepta_memory_retrieval::RetrievalExecutionIdentityV1;
use codex_hepta_memory_retrieval::RetrievalLifecyclePhaseV1;
use codex_hepta_memory_retrieval::append_durable_decision_checked_v1;
use codex_hepta_memory_retrieval::validate_durable_decision_append_v1;

fn identity(request: &str) -> RetrievalExecutionIdentityV1 {
    RetrievalExecutionIdentityV1::new(RetrievalExecutionIdentityPartsV1 {
        tenant: "tenant-a".to_string(),
        principal: "principal-a".to_string(),
        request: request.to_string(),
        query_digest: "query-a".to_string(),
        policy_generation: "policy-7".to_string(),
        encoder_identity: "encoder-3".to_string(),
        snapshot_identity: "snapshot-11".to_string(),
        decision_identity: "decision-19".to_string(),
    })
    .expect("valid lifecycle identity")
}

fn record(
    identity: RetrievalExecutionIdentityV1,
    phase: RetrievalLifecyclePhaseV1,
    writer_fence: u64,
    frontier: u64,
    payload: &str,
) -> DurableDecisionRecordV1 {
    DurableDecisionRecordV1 {
        identity,
        phase,
        writer_fence,
        frontier,
        payload_digest: payload.to_string(),
    }
}

#[derive(Default)]
struct MemoryDecisionPort {
    frontier: u64,
    latest: Vec<DurableDecisionRecordV1>,
    append_count: u64,
    wrong_commit_frontier: bool,
}

impl DurableDecisionPortV1 for MemoryDecisionPort {
    type Error = io::Error;

    fn acquire_writer_fence(&mut self, _writer_identity: &str) -> Result<u64, Self::Error> {
        Ok(7)
    }

    fn compare_and_append(
        &mut self,
        expected_frontier: u64,
        record: &DurableDecisionRecordV1,
    ) -> Result<u64, Self::Error> {
        if expected_frontier != self.frontier {
            return Err(io::Error::other("frontier mismatch"));
        }
        self.frontier = self
            .frontier
            .checked_add(1)
            .ok_or_else(|| io::Error::other("frontier exhausted"))?;
        self.append_count = self.append_count.saturating_add(1);
        self.latest.retain(|value| value.identity != record.identity);
        self.latest.push(record.clone());
        if self.wrong_commit_frontier {
            Ok(self.frontier.saturating_add(1))
        } else {
            Ok(self.frontier)
        }
    }

    fn load_latest(
        &self,
        identity: &RetrievalExecutionIdentityV1,
    ) -> Result<Option<DurableDecisionRecordV1>, Self::Error> {
        Ok(self
            .latest
            .iter()
            .find(|record| &record.identity == identity)
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
            &record(
                outcome.identity().clone(),
                RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
                writer_fence,
                expected_frontier + 1,
                payload_digest,
            ),
        )
    }

    fn verify_replay_integrity(&self) -> Result<(), Self::Error> {
        for value in &self.latest {
            value
                .validate()
                .map_err(|error| io::Error::other(error.to_string()))?;
        }
        Ok(())
    }

    fn retire_before_frontier(&mut self, exclusive_frontier: u64) -> Result<u64, Self::Error> {
        let before = self.latest.len();
        self.latest
            .retain(|value| value.frontier >= exclusive_frontier);
        Ok(u64::try_from(before - self.latest.len()).unwrap_or(u64::MAX))
    }
}

#[test]
fn initial_identity_can_append_after_unrelated_global_history() {
    let next = record(
        identity("request-a"),
        RetrievalLifecyclePhaseV1::QualifiedDecision,
        7,
        42,
        "prepared",
    );
    validate_durable_decision_append_v1(None, 41, &next, None)
        .expect("new identity may follow unrelated journal entries");
}

#[test]
fn quarantine_cannot_regress_to_prepared_or_be_blindly_replayed() {
    let execution = identity("request-a");
    let quarantined = record(
        execution.clone(),
        RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
        7,
        1,
        "dispatch-unknown",
    );
    let quarantine = QuarantinedUnknownOutcomeV1::new(
        execution.clone(),
        "native dispatch outcome unknown".to_string(),
    )
    .expect("bounded quarantine");
    let mut port = MemoryDecisionPort::default();
    append_durable_decision_checked_v1(&mut port, 0, &quarantined, Some(&quarantine))
        .expect("quarantine append");

    let prepared_again = record(
        execution,
        RetrievalLifecyclePhaseV1::QualifiedDecision,
        7,
        2,
        "prepared-again",
    );
    assert!(matches!(
        append_durable_decision_checked_v1(&mut port, 1, &prepared_again, None),
        Err(DurableDecisionAppendErrorV1::Transition(
            DurableDecisionTransitionErrorV1::InvalidPhaseTransition {
                previous: RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
                next: RetrievalLifecyclePhaseV1::QualifiedDecision,
            }
        ))
    ));
}

#[test]
fn exact_committed_replay_is_idempotent_without_second_append() {
    let execution = identity("request-a");
    let next = record(
        execution,
        RetrievalLifecyclePhaseV1::QualifiedDecision,
        7,
        1,
        "prepared",
    );
    let mut port = MemoryDecisionPort::default();
    assert_eq!(
        append_durable_decision_checked_v1(&mut port, 0, &next, None)
            .expect("initial append"),
        1
    );
    assert_eq!(port.append_count, 1);

    assert_eq!(
        append_durable_decision_checked_v1(&mut port, 0, &next, None)
            .expect("exact replay is already committed"),
        1
    );
    assert_eq!(port.append_count, 1);
}

#[test]
fn exact_replay_still_requires_matching_quarantine_evidence() {
    let execution = identity("request-a");
    let quarantined = record(
        execution.clone(),
        RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
        7,
        1,
        "dispatch-unknown",
    );
    let quarantine = QuarantinedUnknownOutcomeV1::new(
        execution,
        "native dispatch outcome unknown".to_string(),
    )
    .expect("bounded quarantine");
    let mut port = MemoryDecisionPort::default();
    append_durable_decision_checked_v1(&mut port, 0, &quarantined, Some(&quarantine))
        .expect("quarantine append");

    assert!(matches!(
        append_durable_decision_checked_v1(&mut port, 0, &quarantined, None),
        Err(DurableDecisionAppendErrorV1::Transition(
            DurableDecisionTransitionErrorV1::MissingQuarantineEvidence
        ))
    ));
    assert_eq!(port.append_count, 1);
}

#[test]
fn exact_reconciliation_may_advance_quarantine_to_consumed() {
    let execution = identity("request-a");
    let quarantined = record(
        execution.clone(),
        RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
        7,
        1,
        "dispatch-unknown",
    );
    let quarantine = QuarantinedUnknownOutcomeV1::new(
        execution.clone(),
        "native dispatch outcome unknown".to_string(),
    )
    .expect("bounded quarantine");
    let mut port = MemoryDecisionPort::default();
    append_durable_decision_checked_v1(&mut port, 0, &quarantined, Some(&quarantine))
        .expect("quarantine append");

    let consumed = record(
        execution,
        RetrievalLifecyclePhaseV1::ConsumedRetrieval,
        8,
        2,
        "exact-turn",
    );
    assert_eq!(
        append_durable_decision_checked_v1(&mut port, 1, &consumed, None)
            .expect("exact reconciliation advances"),
        2
    );
}

#[test]
fn stale_writer_and_terminal_successors_are_rejected() {
    let execution = identity("request-a");
    let latest = record(
        execution.clone(),
        RetrievalLifecyclePhaseV1::ConsumedRetrieval,
        9,
        7,
        "turn",
    );
    let stale = record(
        execution.clone(),
        RetrievalLifecyclePhaseV1::AcknowledgedRetrieval,
        8,
        9,
        "outcome",
    );
    assert_eq!(
        validate_durable_decision_append_v1(Some(&latest), 8, &stale, None),
        Err(DurableDecisionTransitionErrorV1::StaleWriterFence {
            latest: 9,
            next: 8,
        })
    );

    let terminal = record(
        execution.clone(),
        RetrievalLifecyclePhaseV1::AcknowledgedRetrieval,
        9,
        8,
        "outcome",
    );
    let after_terminal = record(
        execution,
        RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
        9,
        9,
        "late-unknown",
    );
    let quarantine = QuarantinedUnknownOutcomeV1::new(
        after_terminal.identity.clone(),
        "late result remained uncertain".to_string(),
    )
    .expect("bounded quarantine");
    assert!(matches!(
        validate_durable_decision_append_v1(
            Some(&terminal),
            8,
            &after_terminal,
            Some(&quarantine),
        ),
        Err(DurableDecisionTransitionErrorV1::InvalidPhaseTransition { .. })
    ));
}

#[test]
fn port_must_return_the_exact_committed_frontier() {
    let mut port = MemoryDecisionPort {
        wrong_commit_frontier: true,
        ..MemoryDecisionPort::default()
    };
    let next = record(
        identity("request-a"),
        RetrievalLifecyclePhaseV1::QualifiedDecision,
        7,
        1,
        "prepared",
    );
    assert!(matches!(
        append_durable_decision_checked_v1(&mut port, 0, &next, None),
        Err(DurableDecisionAppendErrorV1::CommittedFrontierMismatch {
            expected: 1,
            actual: 2,
        })
    ));
}

#[test]
fn identity_and_frontier_mismatch_fail_before_storage() {
    let latest = record(
        identity("request-a"),
        RetrievalLifecyclePhaseV1::QualifiedDecision,
        7,
        4,
        "prepared",
    );
    let wrong_identity = record(
        identity("request-b"),
        RetrievalLifecyclePhaseV1::ConsumedRetrieval,
        7,
        6,
        "turn",
    );
    assert_eq!(
        validate_durable_decision_append_v1(Some(&latest), 5, &wrong_identity, None),
        Err(DurableDecisionTransitionErrorV1::IdentityMismatch)
    );

    let wrong_frontier = record(
        latest.identity.clone(),
        RetrievalLifecyclePhaseV1::ConsumedRetrieval,
        7,
        7,
        "turn",
    );
    assert_eq!(
        validate_durable_decision_append_v1(Some(&latest), 5, &wrong_frontier, None),
        Err(DurableDecisionTransitionErrorV1::FrontierMismatch {
            expected: 6,
            actual: 7,
        })
    );
}

#[test]
fn quarantine_phase_requires_matching_typed_evidence() {
    let execution = identity("request-a");
    let next = record(
        execution.clone(),
        RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
        7,
        1,
        "unknown",
    );
    assert_eq!(
        validate_durable_decision_append_v1(None, 0, &next, None),
        Err(DurableDecisionTransitionErrorV1::MissingQuarantineEvidence)
    );

    let mismatched = QuarantinedUnknownOutcomeV1::new(
        identity("request-b"),
        "another request".to_string(),
    )
    .expect("bounded quarantine");
    assert_eq!(
        validate_durable_decision_append_v1(None, 0, &next, Some(&mismatched)),
        Err(DurableDecisionTransitionErrorV1::QuarantineIdentityMismatch)
    );
}
