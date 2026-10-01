use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tempfile::tempdir;

use super::PlannerAuthorityConsumerV1;
use super::PlannerAuthorityRevalidationV1;
use super::PlannerAuthorizationDecisionV1;
use super::PlannerEffectDispositionV1;
use super::PlannerEffectExecutorV1;
use super::PlannerEffectObservationV1;
use super::PlannerExecutionError;
use super::PlannerExecutionGrantV1;
use super::PlannerTerminalReceiptSinkV1;
use super::PlannerTerminalReceiptV1;
use crate::GrantRequestV1;
use crate::PlannerDispatchClaimOutcomeV1;
use crate::PlannerDispatchClaimSinkV1;
use crate::PlannerStoreConfigV1;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;
use crate::execute_planner_request_v1;
use crate::reconcile_planner_request_v1;

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
    grant_digest: Digest32,
    payload_digest: Digest32,
    revalidation: PlannerAuthorityRevalidationV1,
    authorizations: usize,
    revalidations: usize,
}

impl PlannerAuthorityConsumerV1 for Authority {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorizationDecisionV1, PlannerExecutionError> {
        self.authorizations += 1;
        Ok(PlannerAuthorizationDecisionV1::Granted(
            PlannerExecutionGrantV1 {
                grant_digest: self.grant_digest,
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
        self.revalidations += 1;
        Ok(self.revalidation)
    }
}

struct Executor {
    executions: usize,
    reconciliations: usize,
    fail_next_execute: bool,
    execution_disposition: PlannerEffectDispositionV1,
    reconciliation_disposition: PlannerEffectDispositionV1,
}

impl PlannerEffectExecutorV1 for Executor {
    fn execute(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        self.executions += 1;
        if self.fail_next_execute {
            self.fail_next_execute = false;
            return Err(PlannerExecutionError::Store(
                "injected transport outcome unknown".to_string(),
            ));
        }
        Ok(PlannerEffectObservationV1 {
            disposition: self.execution_disposition,
            outcome_digest: digest("outcome"),
            observed_at_micros: 1_200,
        })
    }

    fn reconcile(
        &mut self,
        _operation_identity_digest: Digest32,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        self.reconciliations += 1;
        Ok(PlannerEffectObservationV1 {
            disposition: self.reconciliation_disposition,
            outcome_digest: digest("reconciled-outcome"),
            observed_at_micros: 1_500,
        })
    }
}

#[derive(Default)]
struct CollectSink {
    claimed_operations: Vec<(Digest32, Digest32, Digest32, Digest32)>,
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
    fn inspect_dispatch(
        &self,
        operation_identity_digest: Digest32,
        request_digest: Digest32,
        final_payload_digest: Digest32,
    ) -> Result<Option<PlannerDispatchClaimOutcomeV1>, PlannerExecutionError> {
        if let Some(receipt) = self
            .receipts
            .iter()
            .rev()
            .find(|receipt| receipt.operation_identity_digest == operation_identity_digest)
        {
            if receipt.request_digest != request_digest
                || receipt.final_payload_digest != final_payload_digest
            {
                return Err(PlannerExecutionError::Store(
                    "test sink operation identity conflict".to_string(),
                ));
            }
            return match receipt.disposition {
                PlannerEffectDispositionV1::Succeeded | PlannerEffectDispositionV1::Failed => {
                    Ok(Some(PlannerDispatchClaimOutcomeV1::ExistingTerminal {
                        receipt: Box::new(receipt.clone()),
                    }))
                }
                PlannerEffectDispositionV1::Indeterminate => {
                    Ok(Some(PlannerDispatchClaimOutcomeV1::ExistingClaim {
                        original_grant_digest: receipt.grant_digest,
                    }))
                }
            };
        }
        if let Some((_, stored_request, original_grant, stored_payload)) = self
            .claimed_operations
            .iter()
            .find(|(operation, _, _, _)| *operation == operation_identity_digest)
        {
            if *stored_request != request_digest || *stored_payload != final_payload_digest {
                return Err(PlannerExecutionError::Store(
                    "test sink operation identity conflict".to_string(),
                ));
            }
            return Ok(Some(PlannerDispatchClaimOutcomeV1::ExistingClaim {
                original_grant_digest: *original_grant,
            }));
        }
        Ok(None)
    }

    fn claim_dispatch(
        &mut self,
        operation_identity_digest: Digest32,
        request_digest: Digest32,
        grant_digest: Digest32,
        final_payload_digest: Digest32,
        _claimed_at_micros: u64,
    ) -> Result<PlannerDispatchClaimOutcomeV1, PlannerExecutionError> {
        if let Some(existing) = self.inspect_dispatch(
            operation_identity_digest,
            request_digest,
            final_payload_digest,
        )? {
            return Ok(existing);
        }
        self.claimed_operations.push((
            operation_identity_digest,
            request_digest,
            grant_digest,
            final_payload_digest,
        ));
        Ok(PlannerDispatchClaimOutcomeV1::Acquired)
    }
}

fn authority(request: &GrantRequestV1) -> Authority {
    Authority {
        grant_digest: digest("grant"),
        payload_digest: request.final_payload_digest,
        revalidation: PlannerAuthorityRevalidationV1::Current,
        authorizations: 0,
        revalidations: 0,
    }
}

fn executor(disposition: PlannerEffectDispositionV1) -> Executor {
    Executor {
        executions: 0,
        reconciliations: 0,
        fail_next_execute: false,
        execution_disposition: disposition,
        reconciliation_disposition: disposition,
    }
}

#[path = "planner_execution_recovery_tests.rs"]
mod recovery_tests;
