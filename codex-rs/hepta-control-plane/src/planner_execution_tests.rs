use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tempfile::tempdir;

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

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn request_set(select_work: bool) -> GrantRequestSetV1 {
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: Generation::new(7).expect("generation"),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 2_000,
            required_owner_ids: vec![id("planner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("planner"),
            revision: Revision::new(3).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: Generation::new(7).expect("generation"),
            configuration_digest: digest("configuration"),
            observed_at_micros: 950,
            expires_at_micros: 1_800,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }],
    )
    .expect("snapshot");
    let abstain = PlanCandidateV1 {
        candidate_id: id("abstain"),
        operation_id: id("abstain"),
        plan_digest: digest("abstain-plan"),
        required_owner_ids: vec![id("planner")],
        final_payload_digests: Vec::new(),
        resource_costs: vec![PlannerAxisValueV1 {
            axis: id("compute"),
            value: FixedQ32::ZERO,
        }],
    };
    let work = PlanCandidateV1 {
        candidate_id: id("work"),
        operation_id: id("write-output"),
        plan_digest: digest("work-plan"),
        required_owner_ids: vec![id("planner")],
        final_payload_digests: vec![digest("final-payload")],
        resource_costs: vec![PlannerAxisValueV1 {
            axis: id("compute"),
            value: q32(1),
        }],
    };
    let prepared = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("execution-test"),
            now_micros: 1_000,
            deadline_micros: 1_700,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resources"),
            candidates: vec![abstain, work],
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("compute"),
                endowment: q32(2),
                essential_floor: FixedQ32::ZERO,
            }],
        },
    )
    .expect("prepared plan");
    let selected = if select_work { id("work") } else { id("abstain") };
    let disposition = if select_work {
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation
    } else {
        PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain
    };
    let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: digest("objective"),
        body_generation: Generation::new(7).expect("generation"),
        evaluation_policy_digest: digest("policy"),
        evaluation_digest: digest("evaluation"),
        evaluated_candidate_ids: vec![id("abstain"), id("work")],
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: vec![selected.clone()],
        advisory_candidate_id: Some(selected),
        uncertainty_digest: digest("uncertainty"),
        disposition,
    })
    .expect("NDU binding");
    let receipt = finalize_plan(&snapshot, &prepared, &evaluation, 1_100).expect("final plan");
    let requests = request_execution_grants(&snapshot, &prepared, &receipt, 1_150)
        .expect("grant requests");
    assert_eq!(requests.authority(), &AuthorityPosture::DENY_ALL);
    requests
}

#[derive(Default)]
struct TestAuthority {
    reject_revalidation: bool,
}

impl IndependentAuthorityPortV1 for TestAuthority {
    fn authorize(
        &mut self,
        request_set_digest: Digest32,
        request: &GrantRequestV1,
        request_digest: Digest32,
        _now_micros: u64,
    ) -> Result<AuthorityGrantV1, PlannerExecutionError> {
        AuthorityGrantV1::admit_external(
            request_set_digest,
            request_digest,
            9,
            request.revocation_frontier_digest,
            request.final_payload_digest,
            request.expires_at_micros,
            b"externally-issued-capability".to_vec(),
        )
    }

    fn revalidate_immediately_before_dispatch(
        &mut self,
        _grant: &AuthorityGrantV1,
        _request: &GrantRequestV1,
        _now_micros: u64,
    ) -> Result<(), PlannerExecutionError> {
        if self.reject_revalidation {
            Err(PlannerExecutionError::AuthorityRejected)
        } else {
            Ok(())
        }
    }
}

#[derive(Default)]
struct TestExecutor {
    calls: usize,
}

impl EffectExecutorPortV1 for TestExecutor {
    fn execute(
        &mut self,
        operation_identity_digest: Digest32,
        grant: &AuthorityGrantV1,
    ) -> Result<EffectTerminalReceiptV1, PlannerExecutionError> {
        self.calls += 1;
        Ok(EffectTerminalReceiptV1 {
            operation_identity_digest,
            grant_digest: grant.grant_digest(),
            final_payload_digest: grant.final_payload_digest(),
            status: EffectTerminalStatusV1::Succeeded,
            observed_outcome_digest: digest("observed-outcome"),
            terminal_at_micros: 1_200,
        })
    }
}

#[derive(Default)]
struct TestReconciler {
    calls: usize,
}

impl EffectReconcilerPortV1 for TestReconciler {
    fn reconcile(
        &mut self,
        terminal: &EffectTerminalReceiptV1,
    ) -> Result<ReconciliationReceiptV1, PlannerExecutionError> {
        self.calls += 1;
        let terminal_digest = Digest32::of_bytes(&encode_terminal_receipt(terminal)?);
        Ok(ReconciliationReceiptV1 {
            operation_identity_digest: terminal.operation_identity_digest,
            terminal_receipt_digest: terminal_digest,
            reconciled_state_digest: digest("reconciled-state"),
            reconciled_at_micros: 1_300,
        })
    }
}

#[test]
fn named_coordinator_persists_decision_authority_terminal_and_reconciliation() {
    let root = tempdir().expect("store root");
    let store_path = root.path().join("planner.store");
    let mut store = PlannerStoreV1::open(&store_path, Default::default()).expect("store");
    let requests = request_set(true);
    let mut authority = TestAuthority::default();
    let mut executor = TestExecutor::default();
    let mut reconciler = TestReconciler::default();
    let receipt = DurablePlannerExecutionCoordinatorV1::new(&mut store)
        .execute(
            digest("decision-identity"),
            b"complete canonical decision envelope",
            &requests,
            &mut authority,
            &mut executor,
            &mut reconciler,
            1_160,
        )
        .expect("durable execution");
    assert_eq!(executor.calls, 1);
    assert_eq!(reconciler.calls, 1);
    assert_eq!(receipt.terminal_receipt_digests.len(), 1);
    assert_eq!(receipt.reconciliation_receipt_digests.len(), 1);
    assert!(!receipt.batch_digest.is_zero());
    assert_eq!(
        store
            .records()
            .iter()
            .map(PlannerStoreRecordV1::kind)
            .collect::<Vec<_>>(),
        vec![
            PlannerStoreRecordKindV1::DecisionEnvelope,
            PlannerStoreRecordKindV1::GrantRequestEnvelope,
            PlannerStoreRecordKindV1::AuthorityDecisionEnvelope,
            PlannerStoreRecordKindV1::EffectTerminalEnvelope,
            PlannerStoreRecordKindV1::ReconciliationEnvelope,
        ]
    );
}

#[test]
fn revocation_between_authorization_and_dispatch_closes_before_effect() {
    let root = tempdir().expect("store root");
    let store_path = root.path().join("planner.store");
    let mut store = PlannerStoreV1::open(&store_path, Default::default()).expect("store");
    let requests = request_set(true);
    let mut authority = TestAuthority {
        reject_revalidation: true,
    };
    let mut executor = TestExecutor::default();
    let mut reconciler = TestReconciler::default();
    assert!(matches!(
        DurablePlannerExecutionCoordinatorV1::new(&mut store).execute(
            digest("decision-identity"),
            b"complete canonical decision envelope",
            &requests,
            &mut authority,
            &mut executor,
            &mut reconciler,
            1_160,
        ),
        Err(PlannerExecutionError::AuthorityRejected)
    ));
    assert_eq!(executor.calls, 0);
    assert_eq!(reconciler.calls, 0);
    assert_eq!(store.records().len(), 3);
}

#[test]
fn abstain_decision_is_durable_without_fabricating_a_capability() {
    let root = tempdir().expect("store root");
    let store_path = root.path().join("planner.store");
    let mut store = PlannerStoreV1::open(&store_path, Default::default()).expect("store");
    let requests = request_set(false);
    let mut authority = TestAuthority::default();
    let mut executor = TestExecutor::default();
    let mut reconciler = TestReconciler::default();
    let receipt = DurablePlannerExecutionCoordinatorV1::new(&mut store)
        .execute(
            digest("abstain-decision"),
            b"complete abstain decision envelope",
            &requests,
            &mut authority,
            &mut executor,
            &mut reconciler,
            1_160,
        )
        .expect("durable abstention");
    assert!(requests.requests().is_empty());
    assert_eq!(executor.calls, 0);
    assert_eq!(reconciler.calls, 0);
    assert!(receipt.terminal_receipt_digests.is_empty());
    assert_eq!(store.records().len(), 1);
}
