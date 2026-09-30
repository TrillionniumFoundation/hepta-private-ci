use codex_hepta_types::StableId;
use tempfile::tempdir;

use super::*;
use crate::PlannerAuthorityConsumerV1;
use crate::PlannerAuthorityRevalidationV1;
use crate::PlannerAuthorizationDecisionV1;
use crate::PlannerEffectDispositionV1;
use crate::PlannerEffectObservationV1;
use crate::PlannerExecutionGrantV1;
use crate::PlannerStoreConfigV1;
use crate::execute_planner_request_v1;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identifier")
}

fn request(name: &str) -> GrantRequestV1 {
    GrantRequestV1 {
        operation_id: id(&format!("operation.{name}")),
        candidate_id: id(&format!("candidate.{name}")),
        plan_digest: digest(&format!("plan.{name}")),
        final_payload_digest: digest(&format!("payload.{name}")),
        objective_digest: digest(&format!("objective.{name}")),
        snapshot_digest: digest(&format!("snapshot.{name}")),
        revocation_frontier_digest: digest(&format!("frontier.{name}")),
        expires_at_micros: 10_000,
    }
}

struct FixtureAuthority {
    grant: PlannerExecutionGrantV1,
}

impl PlannerAuthorityConsumerV1 for FixtureAuthority {
    fn authorize(
        &mut self,
        _request: &GrantRequestV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorizationDecisionV1, PlannerExecutionError> {
        Ok(PlannerAuthorizationDecisionV1::Granted(self.grant.clone()))
    }

    fn revalidate(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorityRevalidationV1, PlannerExecutionError> {
        Ok(PlannerAuthorityRevalidationV1::Current)
    }
}

struct FixtureExecutor {
    execute_calls: usize,
    reconcile_calls: usize,
    reconcile_disposition: PlannerEffectDispositionV1,
}

impl PlannerEffectExecutorV1 for FixtureExecutor {
    fn execute(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        self.execute_calls += 1;
        Ok(PlannerEffectObservationV1 {
            disposition: PlannerEffectDispositionV1::Indeterminate,
            outcome_digest: digest("initial-indeterminate"),
            observed_at_micros: 101,
        })
    }

    fn reconcile(
        &mut self,
        _operation_identity_digest: Digest32,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        self.reconcile_calls += 1;
        Ok(PlannerEffectObservationV1 {
            disposition: self.reconcile_disposition,
            outcome_digest: digest("reconciled-outcome"),
            observed_at_micros: 202,
        })
    }
}

struct FixtureResolver {
    request: GrantRequestV1,
    calls: usize,
}

impl PlannerPendingRequestResolverV1 for FixtureResolver {
    fn resolve_request(
        &mut self,
        _pending: &PlannerPendingDispatchV1,
    ) -> Result<PlannerPendingRequestResolutionV1, PlannerExecutionError> {
        self.calls += 1;
        Ok(PlannerPendingRequestResolutionV1::Resolved(
            self.request.clone(),
        ))
    }
}

fn seed_indeterminate(
    store: &mut PlannerStoreV1,
    request: &GrantRequestV1,
    executor: &mut FixtureExecutor,
) {
    let mut authority = FixtureAuthority {
        grant: PlannerExecutionGrantV1 {
            grant_digest: digest("grant"),
            final_payload_digest: request.final_payload_digest,
            revocation_frontier_digest: request.revocation_frontier_digest,
            expires_at_micros: 9_000,
        },
    };
    let receipt = execute_planner_request_v1(request, 100, &mut authority, executor, store)
        .expect("seed unresolved durable claim");
    assert_eq!(
        receipt.disposition,
        PlannerEffectDispositionV1::Indeterminate
    );
    assert_eq!(
        receipt.operation_identity_digest,
        planner_operation_identity_digest_v1(request)
    );
    assert_eq!(receipt.request_digest, planner_request_digest_v1(request));
}

#[test]
fn pending_reconciliation_controller_never_redispatches_and_closes_exact_claim() {
    let directory = tempdir().expect("temporary planner store");
    let mut store = PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default())
        .expect("open planner store");
    let request = request("exact");
    let mut executor = FixtureExecutor {
        execute_calls: 0,
        reconcile_calls: 0,
        reconcile_disposition: PlannerEffectDispositionV1::Succeeded,
    };
    seed_indeterminate(&mut store, &request, &mut executor);
    assert_eq!(executor.execute_calls, 1);

    let mut resolver = FixtureResolver {
        request: request.clone(),
        calls: 0,
    };
    let batch = reconcile_pending_dispatches_v1(&mut store, None, 1, &mut resolver, &mut executor)
        .expect("bounded reconciliation pass");

    assert_eq!(resolver.calls, 1);
    assert_eq!(executor.execute_calls, 1);
    assert_eq!(executor.reconcile_calls, 1);
    assert_eq!(batch.items.len(), 1);
    assert!(!batch.authority.grants_any());
    assert!(!batch.items[0].authority.grants_any());
    assert!(matches!(
        &batch.items[0].disposition,
        PlannerPendingReconciliationDispositionV1::Reconciled { receipt }
            if receipt.disposition == PlannerEffectDispositionV1::Succeeded
                && receipt.operation_identity_digest
                    == planner_operation_identity_digest_v1(&request)
    ));

    let empty = reconcile_pending_dispatches_v1(
        &mut store,
        batch.next_after_sequence,
        1,
        &mut resolver,
        &mut executor,
    )
    .expect("conclusive operation is no longer pending");
    assert!(empty.items.is_empty());
    assert_eq!(executor.execute_calls, 1);
    assert_eq!(executor.reconcile_calls, 1);
}

#[test]
fn pending_reconciliation_controller_rejects_resolver_identity_drift_before_effect_owner() {
    let directory = tempdir().expect("temporary planner store");
    let mut store = PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default())
        .expect("open planner store");
    let original = request("original");
    let mut executor = FixtureExecutor {
        execute_calls: 0,
        reconcile_calls: 0,
        reconcile_disposition: PlannerEffectDispositionV1::Succeeded,
    };
    seed_indeterminate(&mut store, &original, &mut executor);

    let mut resolver = FixtureResolver {
        request: request("drifted"),
        calls: 0,
    };
    let batch = reconcile_pending_dispatches_v1(&mut store, None, 1, &mut resolver, &mut executor)
        .expect("binding mismatch is item evidence");

    assert_eq!(executor.execute_calls, 1);
    assert_eq!(executor.reconcile_calls, 0);
    assert!(matches!(
        &batch.items[0].disposition,
        PlannerPendingReconciliationDispositionV1::RequestBindingMismatch { .. }
    ));
    assert_eq!(
        store
            .pending_dispatches_page(None, 1)
            .expect("claim remains pending")
            .items
            .len(),
        1
    );
}
