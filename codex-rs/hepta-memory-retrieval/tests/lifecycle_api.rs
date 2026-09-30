use std::io;

use codex_hepta_memory_retrieval::DurableDecisionPortV1;
use codex_hepta_memory_retrieval::DurableDecisionRecordV1;
use codex_hepta_memory_retrieval::LifecycleErrorV1;
use codex_hepta_memory_retrieval::QuarantinedUnknownOutcomeV1;
use codex_hepta_memory_retrieval::RetrievalExecutionIdentityPartsV1;
use codex_hepta_memory_retrieval::RetrievalExecutionIdentityV1;
use codex_hepta_memory_retrieval::RetrievalLifecyclePhaseV1;
use codex_hepta_memory_retrieval::ValidatedRequestV1;

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

#[derive(Default)]
struct MemoryDecisionPort {
    frontier: u64,
    writer_fence: u64,
    latest: Option<DurableDecisionRecordV1>,
}

impl DurableDecisionPortV1 for MemoryDecisionPort {
    type Error = io::Error;

    fn acquire_writer_fence(&mut self, _writer_identity: &str) -> Result<u64, Self::Error> {
        self.writer_fence = self.writer_fence.saturating_add(1);
        Ok(self.writer_fence)
    }

    fn compare_and_append(
        &mut self,
        expected_frontier: u64,
        record: &DurableDecisionRecordV1,
    ) -> Result<u64, Self::Error> {
        record
            .validate()
            .map_err(|error| io::Error::other(error.to_string()))?;
        if expected_frontier != self.frontier {
            return Err(io::Error::other("frontier mismatch"));
        }
        self.frontier = self.frontier.saturating_add(1);
        let mut committed = record.clone();
        committed.frontier = self.frontier;
        self.latest = Some(committed);
        Ok(self.frontier)
    }

    fn load_latest(
        &self,
        identity: &RetrievalExecutionIdentityV1,
    ) -> Result<Option<DurableDecisionRecordV1>, Self::Error> {
        Ok(self
            .latest
            .as_ref()
            .filter(|record| &record.identity == identity)
            .cloned())
    }

    fn quarantine_unknown_outcome(
        &mut self,
        expected_frontier: u64,
        outcome: &QuarantinedUnknownOutcomeV1,
        writer_fence: u64,
        payload_digest: &str,
    ) -> Result<u64, Self::Error> {
        let record = DurableDecisionRecordV1 {
            identity: outcome.identity().clone(),
            phase: RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
            writer_fence,
            frontier: expected_frontier,
            payload_digest: payload_digest.to_string(),
        };
        self.compare_and_append(expected_frontier, &record)
    }

    fn verify_replay_integrity(&self) -> Result<(), Self::Error> {
        if let Some(record) = &self.latest {
            record
                .validate()
                .map_err(|error| io::Error::other(error.to_string()))?;
        }
        Ok(())
    }

    fn retire_before_frontier(&mut self, exclusive_frontier: u64) -> Result<u64, Self::Error> {
        let retired = u64::from(
            self.latest
                .as_ref()
                .is_some_and(|record| record.frontier < exclusive_frontier),
        );
        if retired == 1 {
            self.latest = None;
        }
        Ok(retired)
    }
}

#[test]
fn external_api_preserves_identity_through_acknowledgement() {
    let expected = identity();
    let acknowledged = ValidatedRequestV1::new(expected.clone())
        .bind_tenant()
        .seal_snapshot("snapshot-11")
        .expect("snapshot must match")
        .qualify_decision("decision-19")
        .expect("decision must match")
        .publish("publication-23".to_string())
        .expect("publication digest")
        .consume("publication-23", "effect-29".to_string())
        .expect("publication identity")
        .acknowledge("effect-29", "ack-31".to_string())
        .expect("effect identity");

    assert_eq!(acknowledged.identity(), &expected);
    assert_eq!(acknowledged.publication_digest(), "publication-23");
    assert_eq!(acknowledged.downstream_effect_digest(), "effect-29");
    assert_eq!(acknowledged.acknowledgement_digest(), "ack-31");
}

#[test]
fn external_api_rejects_cross_identity_transition() {
    let error = ValidatedRequestV1::new(identity())
        .bind_tenant()
        .seal_snapshot("snapshot-from-another-request")
        .expect_err("cross-request snapshot must fail");
    assert_eq!(
        error,
        LifecycleErrorV1::IdentityMismatch("snapshot_identity")
    );
}

#[test]
fn durable_port_contract_compiles_and_fences_replay() {
    let identity = identity();
    let mut port = MemoryDecisionPort::default();
    let writer_fence = port.acquire_writer_fence("writer-a").expect("writer fence");
    let record = DurableDecisionRecordV1 {
        identity: identity.clone(),
        phase: RetrievalLifecyclePhaseV1::PublishedRetrieval,
        writer_fence,
        frontier: 0,
        payload_digest: "payload-37".to_string(),
    };
    let frontier = port.compare_and_append(0, &record).expect("first append");
    assert_eq!(frontier, 1);
    assert!(port.compare_and_append(0, &record).is_err());
    assert_eq!(
        port.load_latest(&identity)
            .expect("load")
            .expect("latest")
            .frontier,
        1
    );
    port.verify_replay_integrity().expect("integrity");

    let unknown = QuarantinedUnknownOutcomeV1::new(
        identity.clone(),
        "consumer acknowledgement was not observed".to_string(),
    )
    .expect("bounded reason");
    assert_eq!(
        port.quarantine_unknown_outcome(1, &unknown, writer_fence, "unknown-41")
            .expect("quarantine"),
        2
    );
    assert_eq!(port.retire_before_frontier(3).expect("retire"), 1);
    assert!(
        port.load_latest(&identity)
            .expect("load after retire")
            .is_none()
    );
}
