use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::AuthenticatedOwnerPortV1;
use super::GlobalPlanningErrorV1;
use super::GlobalPlanningRequestV1;
use super::NduPlanningPortV1;
use super::OwnerPortErrorV1;
use super::plan_global_and_record_v1;
use super::plan_global_v1;
use crate::PlannerJournalStoreV1;
use crate::EvaluatedPlanV1;
use crate::GlobalStateSnapshotV1;
use crate::NduPlanningError;
use crate::NduPlanningInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::canonical_ndu_planning_policy_digest;
use crate::canonical_resource_profile_digest;
use crate::evaluate_prepared_plan_with_ndu;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation() -> Generation {
    Generation::new(7).expect("generation")
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

#[derive(Clone)]
struct FixedOwnerPort {
    summary: OwnerSummaryV1,
}

impl AuthenticatedOwnerPortV1 for FixedOwnerPort {
    fn owner_id(&self) -> &StableId {
        &self.summary.owner_id
    }

    fn snapshot_summary(
        &self,
        _request: &SnapshotRequestV1,
    ) -> Result<OwnerSummaryV1, OwnerPortErrorV1> {
        Ok(self.summary.clone())
    }
}

struct RealNduPort {
    input: NduPlanningInputV1,
}

impl NduPlanningPortV1 for RealNduPort {
    fn evaluate(
        &self,
        snapshot: &GlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        now_micros: u64,
    ) -> Result<EvaluatedPlanV1, NduPlanningError> {
        evaluate_prepared_plan_with_ndu(snapshot, prepared, self.input.clone(), now_micros)
    }
}

fn owner(owner: &str, revision: u64) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id(owner),
        revision: Revision::new(revision).expect("revision"),
        objective_digest: digest("objective"),
        body_generation: generation(),
        configuration_digest: digest("configuration"),
        observed_at_micros: 990,
        expires_at_micros: 2_000,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest(&format!("frontier:{owner}")),
        support_digest: digest(&format!("support:{owner}")),
    }
}

fn fixture() -> (
    FixedOwnerPort,
    FixedOwnerPort,
    RealNduPort,
    GlobalPlanningRequestV1,
) {
    let owner_a = id("fleet-owner");
    let owner_b = id("evidence-owner");
    let utility_axis = id("utility");
    let resource_axis = id("compute");
    let profile = UtilityProfile {
        profile_id: id("global-control"),
        dimensions: vec![(utility_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: vec![owner_a.clone(), owner_b.clone()],
        },
    };
    let mut ndu_input = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).expect("policy"),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest: digest("objective"),
            generation: generation(),
            contributions: Vec::new(),
        },
    };
    for candidate in ["abstain", "work"] {
        for organ in [owner_a.clone(), owner_b.clone()] {
            ndu_input.contributions.contributions.push(UtilityContribution {
                candidate_id: id(candidate),
                organ_id: organ.clone(),
                objective_digest: digest("objective"),
                generation: generation(),
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: utility_axis.clone(),
                    value: if candidate == "work" {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                }],
                risk: vec![],
                resource: vec![],
                uncertainty: vec![AxisValue {
                    axis: utility_axis.clone(),
                    value: FixedQ32::ZERO,
                }],
                support_digest: digest(&format!("{candidate}:{}", organ.as_str())),
            });
        }
    }
    let reservations = vec![ResourceReservationV1 {
        axis: resource_axis.clone(),
        endowment: q32(10),
        essential_floor: q32(2),
    }];
    let candidates = ["abstain", "work"]
        .into_iter()
        .map(|candidate| PlanCandidateV1 {
            candidate_id: id(candidate),
            operation_id: id(&format!("operation-{candidate}")),
            plan_digest: digest(&format!("plan:{candidate}")),
            required_owner_ids: vec![owner_a.clone(), owner_b.clone()],
            final_payload_digests: if candidate == "work" {
                vec![digest("payload:work")]
            } else {
                vec![]
            },
            resource_costs: vec![PlannerAxisValueV1 {
                axis: resource_axis.clone(),
                value: if candidate == "work" {
                    q32(1)
                } else {
                    FixedQ32::ZERO
                },
            }],
        })
        .collect();
    let request = GlobalPlanningRequestV1 {
        snapshot_request: SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: generation(),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocation-frontier"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 2_000,
            required_owner_ids: vec![owner_a, owner_b],
        },
        planning_request: PlanningRequestV1 {
            plan_id: id("global-plan"),
            now_micros: 1_000,
            deadline_micros: 1_900,
            evaluation_policy_digest: canonical_ndu_planning_policy_digest(&ndu_input)
                .expect("ndu policy digest"),
            resource_profile_digest: canonical_resource_profile_digest(&reservations)
                .expect("resource profile"),
            candidates,
            resource_reservations: reservations,
        },
        now_micros: 1_000,
    };
    (
        FixedOwnerPort {
            summary: owner("fleet-owner", 4),
        },
        FixedOwnerPort {
            summary: owner("evidence-owner", 9),
        },
        RealNduPort { input: ndu_input },
        request,
    )
}

#[test]
fn multi_owner_global_plan_runs_real_ndu_and_emits_grant_request() {
    let (fleet, evidence, ndu, request) = fixture();
    let receipt = plan_global_v1(&[&fleet, &evidence], &ndu, request).expect("global plan");
    assert_eq!(
        receipt.evaluation.plan.chosen_candidate_id(),
        Some(&id("work"))
    );
    assert_eq!(receipt.grant_requests.requests().len(), 1);
    assert_eq!(
        receipt.grant_requests.requests()[0].final_payload_digest,
        digest("payload:work")
    );
    assert!(!receipt.grant_requests.authority().grants_any());
}

#[test]
fn durable_global_plan_commits_selection_before_returning() {
    let (fleet, evidence, ndu, request) = fixture();
    let temp = tempfile::tempdir().expect("tempdir");
    let (store, empty) = PlannerJournalStoreV1::open(temp.path()).expect("open store");
    assert!(empty.entries().is_empty());
    let operation = digest("durable-global-operation");

    let receipt = plan_global_and_record_v1(
        &[&fleet, &evidence],
        &ndu,
        &store,
        operation,
        request.clone(),
    )
    .expect("durable global plan");
    let journal = store.reopen().expect("reopen committed journal");
    assert_eq!(
        journal.selected_plan_digest(),
        Some(receipt.evaluation.plan.receipt_digest())
    );

    let retry = plan_global_and_record_v1(
        &[&fleet, &evidence],
        &ndu,
        &store,
        operation,
        request,
    )
    .expect("idempotent retry");
    assert_eq!(
        retry.evaluation.plan.receipt_digest(),
        receipt.evaluation.plan.receipt_digest()
    );
    assert_eq!(store.reopen().expect("reopen retry").entries().len(), 3);
}

#[test]
fn missing_required_owner_port_fails_closed() {
    let (fleet, _evidence, ndu, request) = fixture();
    assert_eq!(
        plan_global_v1(&[&fleet], &ndu, request).expect_err("missing owner must reject"),
        GlobalPlanningErrorV1::MissingOwnerPort(id("evidence-owner"))
    );
}

#[test]
fn mixed_clock_binding_is_rejected_before_owner_reads() {
    let (fleet, evidence, ndu, mut request) = fixture();
    request.now_micros += 1;
    assert_eq!(
        plan_global_v1(&[&fleet, &evidence], &ndu, request)
            .expect_err("mixed monotonic time must reject"),
        GlobalPlanningErrorV1::TimeBindingMismatch
    );
}
