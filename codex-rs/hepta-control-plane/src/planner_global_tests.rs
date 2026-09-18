use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

use super::*;

use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::ResourceReservationV1;
use crate::canonical_ndu_planning_policy_digest;
use crate::canonical_resource_profile_digest;

struct Authenticator {
    salt: &'static str,
    reject: Option<StableId>,
}

impl OwnerSummaryAuthenticatorV1 for Authenticator {
    fn authenticate_owner(&self, summary: &OwnerSummaryV1) -> Option<Digest32> {
        if self.reject.as_ref() == Some(&summary.owner_id) {
            return None;
        }
        Some(Digest32::of_bytes(
            format!("{}:{}", self.salt, summary.owner_id.as_str()).as_bytes(),
        ))
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn input() -> GlobalPlanningInputV1 {
    let generation = Generation::new(7).expect("generation");
    let objective_digest = digest("objective");
    let configuration_digest = digest("configuration");
    let owners = ["owner-a", "owner-b"];
    let owner_summaries = owners
        .into_iter()
        .map(|owner| OwnerSummaryV1 {
            owner_id: id(owner),
            revision: Revision::new(3).expect("revision"),
            objective_digest,
            body_generation: generation,
            configuration_digest,
            observed_at_micros: 990,
            expires_at_micros: 2_000,
            readiness: crate::OwnerReadinessV1::Ready,
            source_frontier_digest: digest(&format!("frontier:{owner}")),
            support_digest: digest(&format!("support:{owner}")),
        })
        .collect::<Vec<_>>();

    let profile = UtilityProfile {
        profile_id: id("global-plan-utility"),
        dimensions: vec![(id("utility"), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: owners.into_iter().map(id).collect(),
        },
    };
    let ndu_input = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).expect("policy"),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest,
            generation,
            contributions: ["abstain", "work"]
                .into_iter()
                .flat_map(|candidate| {
                    owners.into_iter().map(move |owner| UtilityContribution {
                        candidate_id: id(candidate),
                        organ_id: id(owner),
                        objective_digest,
                        generation,
                        feasibility: FeasibilityPosture::Feasible,
                        utility: vec![AxisValue {
                            axis: id("utility"),
                            value: if candidate == "work" {
                                FixedQ32::ONE
                            } else {
                                FixedQ32::ZERO
                            },
                        }],
                        risk: vec![],
                        resource: vec![],
                        uncertainty: vec![AxisValue {
                            axis: id("utility"),
                            value: FixedQ32::ZERO,
                        }],
                        support_digest: digest(&format!("{candidate}:{owner}")),
                    })
                })
                .collect(),
        },
    };
    let reservations = vec![ResourceReservationV1 {
        axis: id("compute"),
        endowment: q32(2),
        essential_floor: q32(1),
    }];
    let candidates = ["abstain", "work"]
        .into_iter()
        .map(|candidate| PlanCandidateV1 {
            candidate_id: id(candidate),
            operation_id: id(&format!("operation-{candidate}")),
            plan_digest: digest(&format!("plan:{candidate}")),
            required_owner_ids: owners.into_iter().map(id).collect(),
            final_payload_digests: if candidate == "work" {
                vec![digest("payload:work")]
            } else {
                vec![]
            },
            resource_costs: vec![PlannerAxisValueV1 {
                axis: id("compute"),
                value: if candidate == "work" {
                    q32(1)
                } else {
                    FixedQ32::ZERO
                },
            }],
        })
        .collect();

    GlobalPlanningInputV1 {
        snapshot_request: SnapshotRequestV1 {
            objective_digest,
            body_generation: generation,
            configuration_digest,
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 2_000,
            required_owner_ids: owners.into_iter().map(id).collect(),
        },
        owner_summaries,
        planning_request: PlanningRequestV1 {
            plan_id: id("global-plan"),
            now_micros: 1_000,
            deadline_micros: 1_900,
            evaluation_policy_digest: canonical_ndu_planning_policy_digest(&ndu_input)
                .expect("NDU binding"),
            resource_profile_digest: canonical_resource_profile_digest(&reservations)
                .expect("resource binding"),
            candidates,
            resource_reservations: reservations,
        },
        ndu_input,
        now_micros: 1_000,
    }
}

#[test]
fn authenticated_multi_owner_flow_reaches_deny_all_grant_requests() {
    let output = evaluate_global_plan_v1(
        &Authenticator {
            salt: "auth-v1",
            reject: None,
        },
        input(),
    )
    .expect("global plan");
    assert_eq!(
        output.evaluation.plan.chosen_candidate_id(),
        Some(&id("work"))
    );
    assert_eq!(output.grant_requests.requests().len(), 1);
    assert!(!output.grant_requests.authority().grants_any());
    assert!(!output.owner_authentication_set_digest.is_zero());
}

#[test]
fn authentication_rejection_and_drift_are_bound_into_planning() {
    let rejected = evaluate_global_plan_v1(
        &Authenticator {
            salt: "auth-v1",
            reject: Some(id("owner-b")),
        },
        input(),
    );
    assert_eq!(
        rejected,
        Err(GlobalPlanningErrorV1::OwnerAuthenticationRejected(id(
            "owner-b"
        )))
    );

    let first = evaluate_global_plan_v1(
        &Authenticator {
            salt: "auth-v1",
            reject: None,
        },
        input(),
    )
    .expect("first plan");
    let changed = evaluate_global_plan_v1(
        &Authenticator {
            salt: "auth-v2",
            reject: None,
        },
        input(),
    )
    .expect("changed plan");
    assert_ne!(first.snapshot.snapshot_digest(), changed.snapshot.snapshot_digest());
    assert_ne!(
        first.evaluation.plan.receipt_digest(),
        changed.evaluation.plan.receipt_digest()
    );
}

#[test]
fn global_coordinator_rejects_mixed_clock_inputs() {
    let mut request = input();
    request.now_micros += 1;
    assert_eq!(
        evaluate_global_plan_v1(
            &Authenticator {
                salt: "auth-v1",
                reject: None,
            },
            request,
        ),
        Err(GlobalPlanningErrorV1::ClockMismatch)
    );
}
