use std::fmt::Debug;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::collect_snapshot;
use crate::finalize_plan;
use crate::prepare_plan;
use crate::request_execution_grants;

static NONCE: AtomicU64 = AtomicU64::new(1);

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-planner-execution-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("create execution test root");
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn requests() -> GrantRequestSetV1 {
    let objective = digest("objective");
    let generation = must(Generation::new(7));
    let configuration = digest("configuration");
    let frontier = digest("revocation-frontier");
    let owner = id("planner-owner");
    let snapshot = must(collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: objective,
            body_generation: generation,
            configuration_digest: configuration,
            revocation_frontier_digest: frontier,
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 10,
            expires_at_micros: 500,
            required_owner_ids: vec![owner.clone()],
        },
        vec![OwnerSummaryV1 {
            owner_id: owner.clone(),
            revision: must(Revision::new(1)),
            objective_digest: objective,
            body_generation: generation,
            configuration_digest: configuration,
            observed_at_micros: 100,
            expires_at_micros: 500,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("source-frontier"),
            support_digest: digest("support"),
        }],
    ));
    let resource_axis = id("compute");
    let prepared = must(prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("execution-plan"),
            now_micros: 100,
            deadline_micros: 400,
            evaluation_policy_digest: digest("evaluation-policy"),
            resource_profile_digest: digest("resource-profile"),
            candidates: vec![
                PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("abstain"),
                    plan_digest: digest("abstain-plan"),
                    required_owner_ids: vec![owner.clone()],
                    final_payload_digests: vec![],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: resource_axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                },
                PlanCandidateV1 {
                    candidate_id: id("execute"),
                    operation_id: id("execute-operation"),
                    plan_digest: digest("execute-plan"),
                    required_owner_ids: vec![owner],
                    final_payload_digests: vec![digest("final-payload")],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: resource_axis.clone(),
                        value: q32(1),
                    }],
                },
            ],
            resource_reservations: vec![ResourceReservationV1 {
                axis: resource_axis,
                endowment: q32(2),
                essential_floor: FixedQ32::ZERO,
            }],
        },
    ));
    let evaluation = must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: objective,
        body_generation: generation,
        evaluation_policy_digest: digest("evaluation-policy"),
        evaluation_digest: digest("ndu-evaluation"),
        evaluated_candidate_ids: vec![id("abstain"), id("execute")],
        rejected_candidate_ids: vec![],
        pareto_candidate_ids: vec![id("execute")],
        advisory_candidate_id: Some(id("execute")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    }));
    let receipt = must(finalize_plan(&snapshot, &prepared, &evaluation, 110));
    must(request_execution_grants(&snapshot, &prepared, &receipt, 120))
}

fn context() -> CurrentExecutionContextV1 {
    CurrentExecutionContextV1 {
        observed_at_micros: 150,
        revocation_frontier_digest: digest("revocation-frontier"),
        authority_policy_digest: digest("authority-policy"),
        executor_generation_digest: digest("executor-generation"),
    }
}

struct FakeAuthority {
    disposition: AuthorizationDispositionV1,
    tamper_payload: bool,
    calls: usize,
}

impl IndependentPlannerAuthorityV1 for FakeAuthority {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        current: CurrentExecutionContextV1,
    ) -> Result<IndependentAuthorizationReceiptV1, PlannerExecutionError> {
        self.calls += 1;
        let capability = (self.disposition == AuthorizationDispositionV1::Authorized)
            .then(|| digest("independent-capability"));
        let mut receipt = IndependentAuthorizationReceiptV1::new(
            self.disposition,
            request,
            current,
            capability,
            request.expires_at_micros,
        )?;
        if self.tamper_payload {
            receipt.final_payload_digest = digest("substituted-payload");
        }
        Ok(receipt)
    }
}

struct FakeExecutor {
    disposition: EffectObservationDispositionV1,
    calls: usize,
}

impl PlannerEffectExecutorV1 for FakeExecutor {
    fn execute(
        &mut self,
        _request: &GrantRequestV1,
        dispatch: &EffectDispatchV1,
    ) -> Result<EffectObservationV1, PlannerExecutionError> {
        self.calls += 1;
        EffectObservationV1::new(
            dispatch.dispatch_digest,
            self.disposition,
            digest("observed-outcome"),
        )
    }
}

struct FakeReconciler {
    disposition: ReconciliationDispositionV1,
    calls: usize,
}

impl PlannerEffectReconcilerV1 for FakeReconciler {
    fn reconcile(
        &mut self,
        _request: &GrantRequestV1,
        dispatch: &EffectDispatchV1,
        observation: &EffectObservationV1,
    ) -> Result<ReconciliationReceiptV1, PlannerExecutionError> {
        self.calls += 1;
        let terminal = (self.disposition != ReconciliationDispositionV1::StillIndeterminate)
            .then(|| digest("reconciled-terminal-outcome"));
        ReconciliationReceiptV1::new(
            dispatch.dispatch_digest,
            observation.observation_digest,
            self.disposition,
            terminal,
        )
    }
}

#[test]
fn denied_authorization_never_crosses_the_effect_boundary() {
    let root = TempRoot::new("denied");
    let mut store = must(PlannerStoreV1::open(&root.0));
    let mut authority = FakeAuthority {
        disposition: AuthorizationDispositionV1::Denied,
        tamper_payload: false,
        calls: 0,
    };
    let mut executor = FakeExecutor {
        disposition: EffectObservationDispositionV1::Succeeded,
        calls: 0,
    };
    let mut reconciler = FakeReconciler {
        disposition: ReconciliationDispositionV1::StillIndeterminate,
        calls: 0,
    };
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        &mut authority,
        &mut executor,
        &mut reconciler,
    );
    let receipt = must(coordinator.execute_request_set(&requests(), context()));
    assert_eq!(receipt.grants.len(), 1);
    assert_eq!(receipt.grants[0].disposition, ExecutedGrantDispositionV1::Denied);
    assert_eq!(authority.calls, 1);
    assert_eq!(executor.calls, 0);
    assert_eq!(reconciler.calls, 0);
    assert_eq!(must(store.entries()).len(), 2);
}

#[test]
fn authorized_success_persists_dispatch_and_terminal_receipt() {
    let root = TempRoot::new("success");
    let mut store = must(PlannerStoreV1::open(&root.0));
    let mut authority = FakeAuthority {
        disposition: AuthorizationDispositionV1::Authorized,
        tamper_payload: false,
        calls: 0,
    };
    let mut executor = FakeExecutor {
        disposition: EffectObservationDispositionV1::Succeeded,
        calls: 0,
    };
    let mut reconciler = FakeReconciler {
        disposition: ReconciliationDispositionV1::StillIndeterminate,
        calls: 0,
    };
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        &mut authority,
        &mut executor,
        &mut reconciler,
    );
    let receipt = must(coordinator.execute_request_set(&requests(), context()));
    assert_eq!(
        receipt.grants[0].disposition,
        ExecutedGrantDispositionV1::Succeeded
    );
    assert_eq!(executor.calls, 1);
    assert_eq!(reconciler.calls, 0);
    assert_eq!(must(store.entries()).len(), 4);
    drop(store);
    let reopened = must(PlannerStoreV1::open(&root.0));
    assert_eq!(must(reopened.entries()).len(), 4);
}

#[test]
fn payload_drift_in_authority_receipt_fails_before_effect_execution() {
    let root = TempRoot::new("payload-drift");
    let mut store = must(PlannerStoreV1::open(&root.0));
    let mut authority = FakeAuthority {
        disposition: AuthorizationDispositionV1::Authorized,
        tamper_payload: true,
        calls: 0,
    };
    let mut executor = FakeExecutor {
        disposition: EffectObservationDispositionV1::Succeeded,
        calls: 0,
    };
    let mut reconciler = FakeReconciler {
        disposition: ReconciliationDispositionV1::StillIndeterminate,
        calls: 0,
    };
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        &mut authority,
        &mut executor,
        &mut reconciler,
    );
    assert_eq!(
        coordinator
            .execute_request_set(&requests(), context())
            .expect_err("authorization payload drift must reject"),
        PlannerExecutionError::AuthorizationMismatch
    );
    assert_eq!(executor.calls, 0);
    assert_eq!(must(store.entries()).len(), 1);
}

#[test]
fn indeterminate_effect_requires_explicit_reconciliation() {
    let root = TempRoot::new("reconcile");
    let mut store = must(PlannerStoreV1::open(&root.0));
    let mut authority = FakeAuthority {
        disposition: AuthorizationDispositionV1::Authorized,
        tamper_payload: false,
        calls: 0,
    };
    let mut executor = FakeExecutor {
        disposition: EffectObservationDispositionV1::Indeterminate,
        calls: 0,
    };
    let mut reconciler = FakeReconciler {
        disposition: ReconciliationDispositionV1::Succeeded,
        calls: 0,
    };
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        &mut authority,
        &mut executor,
        &mut reconciler,
    );
    let receipt = must(coordinator.execute_request_set(&requests(), context()));
    assert_eq!(reconciler.calls, 1);
    assert_eq!(
        receipt.grants[0].disposition,
        ExecutedGrantDispositionV1::Succeeded
    );
    assert_eq!(must(store.entries()).len(), 5);
}

#[test]
fn changed_revocation_frontier_blocks_authority_and_executor() {
    let root = TempRoot::new("revocation-drift");
    let mut store = must(PlannerStoreV1::open(&root.0));
    let mut authority = FakeAuthority {
        disposition: AuthorizationDispositionV1::Authorized,
        tamper_payload: false,
        calls: 0,
    };
    let mut executor = FakeExecutor {
        disposition: EffectObservationDispositionV1::Succeeded,
        calls: 0,
    };
    let mut reconciler = FakeReconciler {
        disposition: ReconciliationDispositionV1::StillIndeterminate,
        calls: 0,
    };
    let mut changed = context();
    changed.revocation_frontier_digest = digest("new-revocation-frontier");
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        &mut authority,
        &mut executor,
        &mut reconciler,
    );
    assert_eq!(
        coordinator
            .execute_request_set(&requests(), changed)
            .expect_err("revocation drift must fail before authorization"),
        PlannerExecutionError::AuthorizationMismatch
    );
    assert_eq!(authority.calls, 0);
    assert_eq!(executor.calls, 0);
}
