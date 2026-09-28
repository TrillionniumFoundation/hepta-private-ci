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
    executed: bool,
    disposition: PlannerEffectDispositionV1,
}

impl PlannerEffectExecutorV1 for Executor {
    fn execute(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        self.executed = true;
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

#[test]
fn current_authority_executes_and_durably_records_terminal_receipt() {
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
        executed: false,
        disposition: PlannerEffectDispositionV1::Succeeded,
    };
    let receipt = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut store,
    ));

    assert!(executor.executed);
    assert!(!receipt.authority.grants_any());
    assert_eq!(store.records().len(), 1);
    assert_eq!(
        store.records()[0].kind,
        PlannerStoreRecordKindV1::TerminalReceipt
    );
}

#[test]
fn revocation_after_authorization_stops_before_executor() {
    let request = request();
    let mut authority = Authority {
        payload_digest: request.final_payload_digest,
        revalidation: PlannerAuthorityRevalidationV1::Revoked,
    };
    let mut executor = Executor {
        executed: false,
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
    assert!(!executor.executed);
    assert!(sink.receipts.is_empty());
}

#[test]
fn final_payload_drift_is_rejected_before_revalidation_and_dispatch() {
    let request = request();
    let mut authority = Authority {
        payload_digest: digest("changed-payload"),
        revalidation: PlannerAuthorityRevalidationV1::Current,
    };
    let mut executor = Executor {
        executed: false,
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
    assert!(!executor.executed);
    assert!(sink.receipts.is_empty());
}

#[test]
fn indeterminate_effect_is_reconciled_without_replaying_dispatch() {
    let request = request();
    let mut executor = Executor {
        executed: false,
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
    assert!(!executor.executed);
    assert_eq!(sink.receipts, vec![receipt]);
}
