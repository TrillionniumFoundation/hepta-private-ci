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

use super::AuthenticatedOwnerInputV1;
use super::AuthorityRequestSetVerifierV1;
use super::GlobalPlanHostError;
use super::OwnerSummaryVerifierV1;
use super::execute_authenticated_global_plan_v1;
use crate::NduPlanningInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::canonical_ndu_planning_policy_digest;
use crate::canonical_resource_profile_digest;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

struct ExactProofVerifier;

impl OwnerSummaryVerifierV1<Digest32> for ExactProofVerifier {
    fn verify(&self, summary: &OwnerSummaryV1, proof: &Digest32) -> Result<(), String> {
        if *proof == summary.support_digest {
            Ok(())
        } else {
            Err("owner proof mismatch".to_string())
        }
    }
}

#[derive(Default)]
struct AuthorityVerifier {
    calls: usize,
}

impl AuthorityRequestSetVerifierV1 for AuthorityVerifier {
    fn admit(&mut self, requests: &crate::GrantRequestSetV1) -> Result<Digest32, String> {
        self.calls += 1;
        Ok(Digest32::of_bytes(requests.request_set_digest().as_array()))
    }
}

fn fixture() -> (
    SnapshotRequestV1,
    Vec<AuthenticatedOwnerInputV1<Digest32>>,
    PlanningRequestV1,
    NduPlanningInputV1,
) {
    let generation = Generation::new(1).expect("generation");
    let owner_id = id("fleet-owner");
    let objective = digest("objective");
    let configuration = digest("configuration");
    let support = digest("owner-proof");
    let snapshot_request = SnapshotRequestV1 {
        objective_digest: objective,
        body_generation: generation,
        configuration_digest: configuration,
        revocation_frontier_digest: digest("revocations"),
        snapshot_policy_digest: digest("snapshot-policy"),
        collected_at_micros: 100,
        maximum_owner_age_micros: 20,
        expires_at_micros: 200,
        required_owner_ids: vec![owner_id.clone()],
    };
    let owners = vec![AuthenticatedOwnerInputV1 {
        summary: OwnerSummaryV1 {
            owner_id: owner_id.clone(),
            revision: Revision::new(1).expect("revision"),
            objective_digest: objective,
            body_generation: generation,
            configuration_digest: configuration,
            observed_at_micros: 99,
            expires_at_micros: 200,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("fleet-frontier"),
            support_digest: support,
        },
        proof: support,
    }];
    let profile = UtilityProfile {
        profile_id: id("global-plan-profile"),
        dimensions: vec![(id("value"), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: vec![owner_id.clone()],
        },
    };
    let ndu_input = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).expect("policy"),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest: objective,
            generation,
            contributions: ["abstain", "work"]
                .into_iter()
                .map(|name| UtilityContribution {
                    candidate_id: id(name),
                    organ_id: owner_id.clone(),
                    objective_digest: objective,
                    generation,
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: id("value"),
                        value: if name == "work" {
                            FixedQ32::ONE
                        } else {
                            FixedQ32::ZERO
                        },
                    }],
                    risk: vec![],
                    resource: vec![],
                    uncertainty: vec![AxisValue {
                        axis: id("value"),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: support,
                })
                .collect(),
        },
    };
    let reservations = vec![ResourceReservationV1 {
        axis: id("compute"),
        endowment: q32(10),
        essential_floor: q32(2),
    }];
    let planning_request = PlanningRequestV1 {
        plan_id: id("global-plan"),
        now_micros: 100,
        deadline_micros: 190,
        evaluation_policy_digest: canonical_ndu_planning_policy_digest(&ndu_input)
            .expect("ndu policy digest"),
        resource_profile_digest: canonical_resource_profile_digest(&reservations)
            .expect("resource digest"),
        candidates: ["abstain", "work"]
            .into_iter()
            .map(|name| PlanCandidateV1 {
                candidate_id: id(name),
                operation_id: id(&format!("operation-{name}")),
                plan_digest: digest(&format!("plan-{name}")),
                required_owner_ids: vec![owner_id.clone()],
                final_payload_digests: if name == "work" {
                    vec![digest("final-payload")]
                } else {
                    vec![]
                },
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: id("compute"),
                    value: if name == "work" {
                        q32(1)
                    } else {
                        FixedQ32::ZERO
                    },
                }],
            })
            .collect(),
        resource_reservations: reservations,
    };
    (snapshot_request, owners, planning_request, ndu_input)
}

#[test]
fn authenticated_global_plan_reaches_independent_authority_seam() {
    let (snapshot, owners, request, ndu) = fixture();
    let mut authority = AuthorityVerifier::default();
    let execution = execute_authenticated_global_plan_v1(
        snapshot,
        owners,
        request,
        ndu,
        110,
        &ExactProofVerifier,
        &mut authority,
    )
    .expect("global plan");
    assert_eq!(execution.grant_requests.requests().len(), 1);
    assert_eq!(authority.calls, 1);
    assert!(execution.authority_admission_receipt_digest.is_some());
    assert!(!execution.grant_requests.authority().grants_any());
}

#[test]
fn owner_authentication_fails_before_planning_or_authority() {
    let (snapshot, mut owners, request, ndu) = fixture();
    owners[0].proof = digest("wrong-proof");
    let mut authority = AuthorityVerifier::default();
    let error = execute_authenticated_global_plan_v1(
        snapshot,
        owners,
        request,
        ndu,
        110,
        &ExactProofVerifier,
        &mut authority,
    )
    .expect_err("proof mismatch must reject");
    assert!(matches!(
        error,
        GlobalPlanHostError::OwnerAuthentication { .. }
    ));
    assert_eq!(authority.calls, 0);
}
