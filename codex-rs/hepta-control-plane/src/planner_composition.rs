//! Authenticated owner admission and bounded end-to-end planner composition.
//!
//! This module sequences existing owners without absorbing their authority. An
//! external authenticator must admit every owner summary, NDU remains the value
//! owner, and the resulting grant requests are still DENY_ALL proposals that
//! must be handed to an independent authority owner.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvaluatedPlanV1;
use crate::GlobalStateSnapshotV1;
use crate::GrantRequestSetV1;
use crate::GrantRequestV1;
use crate::NduPlanningError;
use crate::NduPlanningInputV1;
use crate::OwnerSummaryV1;
use crate::PlannerError;
use crate::PlannerHardeningError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::SnapshotRequestV1;
use crate::collect_snapshot;
use crate::evaluate_prepared_plan_with_ndu;
use crate::prepare_plan_hardened;
use crate::request_execution_grants;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerAuthenticationProofV1 {
    pub producer_id: StableId,
    pub proof_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerAdmissionError {
    EmptyProof,
    AuthenticationRejected,
}

impl fmt::Display for OwnerAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyProof => formatter.write_str("owner authentication proof is empty"),
            Self::AuthenticationRejected => formatter.write_str("owner authentication rejected"),
        }
    }
}

impl StdError for OwnerAdmissionError {}

/// A summary whose producer identity/proof was checked by the caller-supplied
/// owner authenticator. The inner value is intentionally not public.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOwnerSummaryV1(OwnerSummaryV1);

impl AuthenticatedOwnerSummaryV1 {
    #[must_use]
    pub fn summary(&self) -> &OwnerSummaryV1 {
        &self.0
    }

    pub(crate) fn from_verified(summary: OwnerSummaryV1) -> Self {
        Self(summary)
    }

    fn into_inner(self) -> OwnerSummaryV1 {
        self.0
    }
}

pub fn authenticate_owner_summary_v1(
    summary: OwnerSummaryV1,
    proof: &OwnerAuthenticationProofV1,
    verifier: impl FnOnce(&OwnerSummaryV1, &OwnerAuthenticationProofV1) -> bool,
) -> Result<AuthenticatedOwnerSummaryV1, OwnerAdmissionError> {
    if proof.proof_digest.is_zero() {
        return Err(OwnerAdmissionError::EmptyProof);
    }
    if !verifier(&summary, proof) {
        return Err(OwnerAdmissionError::AuthenticationRejected);
    }
    Ok(AuthenticatedOwnerSummaryV1(summary))
}

pub struct GlobalPlanCompositionInputV1 {
    pub snapshot_request: SnapshotRequestV1,
    pub authenticated_owners: Vec<AuthenticatedOwnerSummaryV1>,
    pub planning_request: PlanningRequestV1,
    pub ndu_input: NduPlanningInputV1,
    pub now_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlobalPlanCompositionV1 {
    pub snapshot: GlobalStateSnapshotV1,
    pub prepared: PreparedPlanInputV1,
    pub evaluated: EvaluatedPlanV1,
    pub grant_requests: GrantRequestSetV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GlobalPlanCompositionError {
    Planner(PlannerError),
    Hardening(PlannerHardeningError),
    Ndu(NduPlanningError),
}

impl fmt::Display for GlobalPlanCompositionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Planner(error) => write!(formatter, "{error}"),
            Self::Hardening(error) => write!(formatter, "{error}"),
            Self::Ndu(error) => write!(formatter, "{error}"),
        }
    }
}

impl StdError for GlobalPlanCompositionError {}

/// Complete authority-free planning chain over already-authenticated owner
/// observations. This function never grants or executes an effect.
pub fn compose_global_plan_v1(
    input: GlobalPlanCompositionInputV1,
) -> Result<GlobalPlanCompositionV1, GlobalPlanCompositionError> {
    if input.planning_request.now_micros != input.now_micros {
        return Err(GlobalPlanCompositionError::Planner(
            PlannerError::InvalidTime("global composition time"),
        ));
    }
    let owners = input
        .authenticated_owners
        .into_iter()
        .map(AuthenticatedOwnerSummaryV1::into_inner)
        .collect();
    let snapshot = collect_snapshot(input.snapshot_request, owners)
        .map_err(GlobalPlanCompositionError::Planner)?;
    let prepared = prepare_plan_hardened(&snapshot, input.planning_request)
        .map_err(GlobalPlanCompositionError::Hardening)?;
    let evaluated =
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, input.ndu_input, input.now_micros)
            .map_err(GlobalPlanCompositionError::Ndu)?;
    let grant_requests =
        request_execution_grants(&snapshot, &prepared, &evaluated.plan, input.now_micros)
            .map_err(GlobalPlanCompositionError::Planner)?;
    Ok(GlobalPlanCompositionV1 {
        snapshot,
        prepared,
        evaluated,
        grant_requests,
    })
}

/// Explicit handoff seam to the independently owned authority implementation.
/// Control runtime does not interpret, cache, or convert the returned values.
pub fn handoff_grant_requests_v1<R, E>(
    requests: &GrantRequestSetV1,
    mut authority: impl FnMut(&GrantRequestV1) -> Result<R, E>,
) -> Result<Vec<R>, E> {
    requests.requests().iter().map(&mut authority).collect()
}

#[cfg(test)]
mod tests {
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
    use crate::OwnerReadinessV1;
    use crate::PlanCandidateV1;
    use crate::PlannerAxisValueV1;
    use crate::ResourceReservationV1;
    use crate::canonical_ndu_planning_policy_digest;
    use crate::canonical_resource_profile_digest;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn authenticated_owner_ndu_and_grant_handoff_compose_without_authority_leak() {
        let generation = Generation::new(1).expect("generation");
        let summary = OwnerSummaryV1 {
            owner_id: id("state-reader"),
            revision: Revision::new(1).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 99,
            expires_at_micros: 200,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        };
        let proof = OwnerAuthenticationProofV1 {
            producer_id: id("state-reader"),
            proof_digest: digest("signed-owner-proof"),
        };
        let owner = authenticate_owner_summary_v1(summary, &proof, |summary, proof| {
            summary.owner_id == proof.producer_id
        })
        .expect("authenticated owner");

        let profile = UtilityProfile {
            profile_id: id("context-delivery"),
            dimensions: vec![(id("utility"), AxisDirection::Maximize)],
            risk_ceilings: vec![],
            resource_ceilings: vec![],
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("state-reader")],
            },
        };
        let ndu_input = NduPlanningInputV1 {
            policy: legacy_evaluation_policy(&profile).expect("policy"),
            profile,
            scalarization: None,
            contributions: ContributionSet {
                objective_digest: digest("objective"),
                generation,
                contributions: ["abstain", "work"]
                    .into_iter()
                    .map(|candidate| UtilityContribution {
                        candidate_id: id(candidate),
                        organ_id: id("state-reader"),
                        objective_digest: digest("objective"),
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
                        support_digest: digest(candidate),
                    })
                    .collect(),
            },
        };
        let reservations = vec![ResourceReservationV1 {
            axis: id("compute"),
            endowment: FixedQ32::ONE,
            essential_floor: FixedQ32::ZERO,
        }];
        let resource_profile_digest =
            canonical_resource_profile_digest(&reservations).expect("resource profile");
        let evaluation_policy_digest =
            canonical_ndu_planning_policy_digest(&ndu_input).expect("evaluation policy");
        let candidates = ["abstain", "work"]
            .into_iter()
            .map(|candidate| PlanCandidateV1 {
                candidate_id: id(candidate),
                operation_id: id(&format!("operation-{candidate}")),
                plan_digest: digest(&format!("plan-{candidate}")),
                required_owner_ids: vec![id("state-reader")],
                final_payload_digests: if candidate == "work" {
                    vec![digest("effect-payload")]
                } else {
                    vec![]
                },
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: id("compute"),
                    value: if candidate == "work" {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                }],
            })
            .collect();

        let result = compose_global_plan_v1(GlobalPlanCompositionInputV1 {
            snapshot_request: SnapshotRequestV1 {
                objective_digest: digest("objective"),
                body_generation: generation,
                configuration_digest: digest("configuration"),
                revocation_frontier_digest: digest("revocations"),
                snapshot_policy_digest: digest("snapshot-policy"),
                collected_at_micros: 100,
                maximum_owner_age_micros: 10,
                expires_at_micros: 200,
                required_owner_ids: vec![id("state-reader")],
            },
            authenticated_owners: vec![owner],
            planning_request: PlanningRequestV1 {
                plan_id: id("global-plan"),
                now_micros: 100,
                deadline_micros: 190,
                evaluation_policy_digest,
                resource_profile_digest,
                candidates,
                resource_reservations: reservations,
            },
            ndu_input,
            now_micros: 100,
        })
        .expect("global composition");
        assert_eq!(
            result.evaluated.plan.chosen_candidate_id(),
            Some(&id("work"))
        );
        assert_eq!(result.grant_requests.requests().len(), 1);
        assert!(!result.grant_requests.authority().grants_any());

        let forwarded = handoff_grant_requests_v1(&result.grant_requests, |request| {
            Ok::<_, ()>(request.final_payload_digest)
        })
        .expect("authority handoff");
        assert_eq!(forwarded, vec![digest("effect-payload")]);
    }

    #[test]
    fn owner_summary_cannot_be_wrapped_without_authenticator_acceptance() {
        let generation = Generation::new(1).expect("generation");
        let summary = OwnerSummaryV1 {
            owner_id: id("owner"),
            revision: Revision::new(1).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 1,
            expires_at_micros: 2,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        };
        let proof = OwnerAuthenticationProofV1 {
            producer_id: id("owner"),
            proof_digest: digest("proof"),
        };
        assert_eq!(
            authenticate_owner_summary_v1(summary, &proof, |_, _| false),
            Err(OwnerAdmissionError::AuthenticationRejected)
        );
    }
}
