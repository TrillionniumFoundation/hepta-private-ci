//! Fail-closed product append for retrieval lifecycle projections.
//!
//! Projection and durable append remain separate operations so recovery can
//! inspect the immutable evidence before attempting storage. Product code must
//! use this checked boundary rather than call the raw port operation directly.

use codex_hepta_memory_retrieval::DurableDecisionAppendErrorV1;
use codex_hepta_memory_retrieval::DurableDecisionPortV1;
use codex_hepta_memory_retrieval::append_durable_decision_checked_v1;

use crate::retrieval_delivery::RetrievalLifecycleProjectionV1;

pub fn append_retrieval_lifecycle_projection_checked_v1<P: DurableDecisionPortV1>(
    port: &mut P,
    expected_frontier: u64,
    projection: &RetrievalLifecycleProjectionV1,
) -> Result<u64, DurableDecisionAppendErrorV1<P::Error>> {
    append_durable_decision_checked_v1(
        port,
        expected_frontier,
        &projection.record,
        projection.quarantine.as_ref(),
    )
}

#[cfg(test)]
mod tests {
    use std::io;

    use codex_hepta_memory_retrieval::DurableDecisionRecordV1;
    use codex_hepta_memory_retrieval::QuarantinedUnknownOutcomeV1;
    use codex_hepta_memory_retrieval::RetrievalExecutionIdentityPartsV1;
    use codex_hepta_memory_retrieval::RetrievalExecutionIdentityV1;
    use codex_hepta_memory_retrieval::RetrievalLifecyclePhaseV1;

    use super::*;

    fn identity() -> RetrievalExecutionIdentityV1 {
        RetrievalExecutionIdentityV1::new(RetrievalExecutionIdentityPartsV1 {
            tenant: "tenant".to_string(),
            principal: "principal".to_string(),
            request: "request".to_string(),
            query_digest: "query".to_string(),
            policy_generation: "policy".to_string(),
            encoder_identity: "encoder".to_string(),
            snapshot_identity: "snapshot".to_string(),
            decision_identity: "decision".to_string(),
        })
        .expect("identity")
    }

    #[derive(Default)]
    struct Port {
        frontier: u64,
        latest: Option<DurableDecisionRecordV1>,
    }

    impl DurableDecisionPortV1 for Port {
        type Error = io::Error;

        fn acquire_writer_fence(&mut self, _writer_identity: &str) -> Result<u64, Self::Error> {
            Ok(1)
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
            self.latest = Some(record.clone());
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
            self.compare_and_append(
                expected_frontier,
                &DurableDecisionRecordV1 {
                    identity: outcome.identity().clone(),
                    phase: RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
                    writer_fence,
                    frontier: expected_frontier
                        .checked_add(1)
                        .ok_or_else(|| io::Error::other("frontier exhausted"))?,
                    payload_digest: payload_digest.to_string(),
                },
            )
        }

        fn verify_replay_integrity(&self) -> Result<(), Self::Error> {
            Ok(())
        }

        fn retire_before_frontier(
            &mut self,
            _exclusive_frontier: u64,
        ) -> Result<u64, Self::Error> {
            Ok(0)
        }
    }

    #[test]
    fn product_wrapper_uses_checked_append() {
        let projection = RetrievalLifecycleProjectionV1 {
            record: DurableDecisionRecordV1 {
                identity: identity(),
                phase: RetrievalLifecyclePhaseV1::QualifiedDecision,
                writer_fence: 1,
                frontier: 1,
                payload_digest: "prepared".to_string(),
            },
            quarantine: None,
        };
        let mut port = Port::default();
        assert_eq!(
            append_retrieval_lifecycle_projection_checked_v1(&mut port, 0, &projection)
                .expect("checked append"),
            1
        );
    }
}
