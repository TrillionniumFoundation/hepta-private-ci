use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tempfile::tempdir;

use super::PlannerAuthorizationDecisionV1;
use super::PlannerAuthorityConsumerV1;
use super::PlannerAuthorityRevalidationV1;
use super::PlannerEffectDispositionV1;
use super::PlannerEffectExecutorV1;
use super::PlannerEffectObservationV1;
use super::PlannerExecutionError;
use super::PlannerExecutionGrantV1;
use super::PlannerTerminalReceiptSinkV1;
use super::PlannerTerminalReceiptV1;
use super::execute_planner_request_v1;
use super::reconcile_planner_request_v1;
use crate::GrantRequestV1;
use crate::PlannerDispatchClaimSinkV1;
use crate::PlannerStoreConfigV1;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T, E: Debug>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(_) => panic!("expected error"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn request() -> GrantRequestV1 {
    GrantRequestV1 {
        operation_id: id("send-message"),
        candidate_id: id("candidate-one"),
        plan_digest: digest("plan"),
        final_payload_digest: digest("payload"),
        objective_digest: digest("objective"),
        snapshot_digest: digest("snapshot"),
        revocation_frontier_digest: digest("revocations"),
        expires_at_micros: 2_000,
    }
}

struct Authority {
    payload_digest: Digest32,
    revalidation: PlannerAuthorityRevalidationV1,
}

impl PlannerAuthorityConsumerV1 for Authority {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorizationDecisionV1, PlannerExecutionError> {
        Ok(PlannerAuthorizationDecisionV1::Granted(
            PlannerExecutionGrantV1 {
                grant_digest: digest("grant"),
                final_payload_digest: self.payload_digest,
                revocation_frontier_digest: request.revocation_frontier_digest,
                expires_at_micros: request.expires_at_micros,
            },
        ))
    }

    fn revalidate(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorityRevalidationV1, PlannerExecutionError> {
        Ok(self.revalidation)
    }
}

struct Executor {
    executions: usize,
    disposition: PlannerEffectDispositionV1,
}

impl PlannerEffectExecutorV1 for Executor {
    fn execute(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        self.executions += 1;
        Ok(PlannerEffectObservationV1 {
            disposition: self.disposition,
            outcome_digest: digest("outcome"),
            observed_at_micros: 1_200,
        })
    }

    fn reconcile(
        &mut self,
        _operation_identity_digest: Digest32,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        Ok(PlannerEffectObservationV1 {
            disposition: self.disposition,
            outcome_digest: digest("reconciled-outcome"),
            observed_at_micros: 1_500,
        })
    }
}

#[derive(Default)]
struct CollectSink {
    claimed_operations: Vec<Digest32>,
    receipts: Vec<PlannerTerminalReceiptV1>,
}

impl PlannerTerminalReceiptSinkV1 for CollectSink {
    fn append_terminal_receipt(
        &mut self,
        receipt: &PlannerTerminalReceiptV1,
    ) -> Result<(), PlannerExecutionError> {
        self.receipts.push(receipt.clone());
        Ok(())
    }
}

impl PlannerDispatchClaimSinkV1 for CollectSink {
    fn claim_dispatch(
        &mut self,
        operation_identity_digest: Digest32,
        _request_digest: Digest32,
        _grant_digest: Digest32,
        _final_payload_digest: Digest32,
        _claimed_at_micros: u64,
    ) -> Result<bool, PlannerExecutionError> {
        if self.claimed_operations.contains(&operation_identity_digest) {
            return Ok(false);
        }
        self.claimed_operations.push(operation_identity_digest);
        Ok(true)
    }
}

#[test]
fn current_authority_claims_before_execution_and_records_terminal_receipt() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let request = request();
    let mut authority = Authority {
        payload_digest: request.final_payload_digest,
        revalidation: PlannerAuthorityRevalidationV1::Current,
    };
    let mut executor = Executor {
        executions: 0,
        disposition: PlannerEffectDispositionV1::Succeeded,
    };
    let receipt = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut store,
    ));

    assert_eq!(executor.executions, 1);
    assert!(!receipt.authority.grants_any());
    assert_eq!(store.records().len(), 2);
    assert_eq!(store.records()[0].kind, PlannerStoreRecordKindV1::Selection);
    assert_eq!(
        store.records()[1].kind,
        PlannerStoreRecordKindV1::TerminalReceipt
    );
}

#[test]
fn repeated_request_never_replays_after_a_durable_claim() {
    let request = request();
    let mut authority = Authority {
        payload_digest: request.final_payload_digest,
        revalidation: PlannerAuthorityRevalidationV1::Current,
    };
    let mut executor = Executor {
        executions: 0,
        disposition: PlannerEffectDispositionV1::Succeeded,
    };
    let mut sink = CollectSink::default();
    must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    let error = must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));

    assert!(matches!(
        error,
        PlannerExecutionError::Store(message) if message.contains("reconcile without replay")
    ));
    assert_eq!(executor.executions, 1);
}

#[test]
fn revocation_after_claim_stops_before_executor() {
    let request = request();
    let mut authority = Authority {
        payload_digest: request.final_payload_digest,
        revalidation: PlannerAuthorityRevalidationV1::Revoked,
    };
    let mut executor = Executor {
        executions: 0,
        disposition: PlannerEffectDispositionV1::Succeeded,
    };
    let mut sink = CollectSink::default();
    let error = must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));

    assert_eq!(error, PlannerExecutionError::AuthorityRevoked);
    assert_eq!(executor.executions, 0);
    assert_eq!(sink.claimed_operations.len(), 1);
    assert!(sink.receipts.is_empty());
}

#[test]
fn final_payload_drift_is_rejected_before_claim_and_dispatch() {
    let request = request();
    let mut authority = Authority {
        payload_digest: digest("changed-payload"),
        revalidation: PlannerAuthorityRevalidationV1::Current,
    };
    let mut executor = Executor {
        executions: 0,
        disposition: PlannerEffectDispositionV1::Succeeded,
    };
    let mut sink = CollectSink::default();
    let error = must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));

    assert_eq!(error, PlannerExecutionError::GrantMismatch);
    assert_eq!(executor.executions, 0);
    assert!(sink.claimed_operations.is_empty());
    assert!(sink.receipts.is_empty());
}

#[test]
fn indeterminate_effect_is_reconciled_without_replaying_dispatch() {
    let request = request();
    let mut executor = Executor {
        executions: 0,
        disposition: PlannerEffectDispositionV1::Indeterminate,
    };
    let mut sink = CollectSink::default();
    let receipt = must(reconcile_planner_request_v1(
        &request,
        digest("grant"),
        &mut executor,
        &mut sink,
    ));

    assert_eq!(
        receipt.disposition,
        PlannerEffectDispositionV1::Indeterminate
    );
    assert_eq!(executor.executions, 0);
    assert_eq!(sink.receipts, vec![receipt]);
}
