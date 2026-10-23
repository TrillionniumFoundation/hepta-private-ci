//! Planner and router role profiles for a Neural Circuit.
//!
//! These adapters deliberately sit above the existing TaskFlow and CNS
//! owners.  They produce bounded, authority-free proposals; they do not
//! schedule work, publish a route, execute an effect, or create a store.
//! TaskFlow owns plan lifecycle and CNS owns route admission/cutover.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_control_plane::CnsRouteV1;
use codex_hepta_control_plane::cns_route_digest_v1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellAdapterContextV1;
use crate::CellRoleAdapterErrorV1;
use crate::CellRoleStepV1;
use crate::digest_bytes;
use crate::step_receipt;

/// Stable owner binding for the existing TaskFlow circuit seam.
pub const PLANNER_OWNER_MODULE: &str = "hepta-automation::taskflow-circuit";
/// Stable owner binding for the existing CNS route seam.
pub const ROUTER_OWNER_MODULE: &str = "hepta-cns::route-owner";
const CIRCUIT_ROLE_SCHEMA_V1: &str = "hepta.cell-role.circuit-profile.v1";

/// Bounded search and resource cursor shared by planner and router profiles.
/// The cursor is a value passed by the existing owner; it is never persisted
/// by this adapter and never grants permission to advance itself.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CircuitBudgetCursorV1 {
    pub frontier_cursor: u32,
    pub frontier_limit: u32,
    pub budget_cursor_q24: u64,
    pub budget_limit_q24: u64,
}

impl CircuitBudgetCursorV1 {
    pub fn validate(self) -> Result<(), CircuitRoleErrorV1> {
        if self.frontier_limit == 0 {
            return Err(CircuitRoleErrorV1::InvalidBudget("frontier limit"));
        }
        if self.frontier_cursor > u32::MAX.saturating_sub(self.frontier_limit) {
            return Err(CircuitRoleErrorV1::InvalidBudget("frontier cursor"));
        }
        if self.budget_cursor_q24 > self.budget_limit_q24 {
            return Err(CircuitRoleErrorV1::InvalidBudget("budget cursor"));
        }
        Ok(())
    }

    fn frontier_end(self) -> u32 {
        self.frontier_cursor.saturating_add(self.frontier_limit)
    }

    fn remaining_budget(self) -> u64 {
        self.budget_limit_q24.saturating_sub(self.budget_cursor_q24)
    }
}

/// Typed planner candidate.  The candidate is an advisory TaskFlow plan;
/// `required_owner_ids` names deterministic downstream owners and does not
/// authorize this role to call any of them.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanCandidateV1 {
    pub candidate_id: StableId,
    pub operation_id: StableId,
    pub plan_digest: Digest32,
    pub required_owner_ids: Vec<StableId>,
    pub owner_module: StableId,
    pub estimated_cost_q24: u64,
    pub frontier_index: u32,
    pub expiry_micros: u64,
    pub fallback_plan_digest: Digest32,
}

impl PlanCandidateV1 {
    fn validate(&self) -> Result<(), CircuitRoleErrorV1> {
        for (label, id) in [
            ("candidate", &self.candidate_id),
            ("operation", &self.operation_id),
            ("owner module", &self.owner_module),
        ] {
            if id.as_str().is_empty() {
                return Err(CircuitRoleErrorV1::EmptyId(label));
            }
        }
        if self.plan_digest.is_zero() {
            return Err(CircuitRoleErrorV1::EmptyDigest("plan"));
        }
        if self.fallback_plan_digest.is_zero() {
            return Err(CircuitRoleErrorV1::EmptyDigest("fallback plan"));
        }
        if self.expiry_micros == 0 {
            return Err(CircuitRoleErrorV1::InvalidCandidate("expiry"));
        }
        if self.required_owner_ids.is_empty()
            || self
                .required_owner_ids
                .iter()
                .any(|id| id.as_str().is_empty())
        {
            return Err(CircuitRoleErrorV1::InvalidCandidate("required owners"));
        }
        if !self.required_owner_ids.contains(&self.owner_module) {
            return Err(CircuitRoleErrorV1::OwnerBinding);
        }
        Ok(())
    }

    fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::from(CIRCUIT_ROLE_SCHEMA_V1.as_bytes());
        bytes.extend_from_slice(self.candidate_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(self.operation_id.as_str().as_bytes());
        bytes.extend_from_slice(self.plan_digest.as_array());
        bytes.extend_from_slice(self.owner_module.as_str().as_bytes());
        bytes.push(0);
        for owner in &self.required_owner_ids {
            bytes.extend_from_slice(owner.as_str().as_bytes());
            bytes.push(0);
        }
        bytes.extend_from_slice(&self.estimated_cost_q24.to_be_bytes());
        bytes.extend_from_slice(&self.frontier_index.to_be_bytes());
        bytes.extend_from_slice(&self.expiry_micros.to_be_bytes());
        bytes.extend_from_slice(self.fallback_plan_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

/// Planner input supplied by the TaskFlow/Circuit owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerCircuitInputV1 {
    pub candidates: Vec<PlanCandidateV1>,
    pub legal_candidate_ids: Vec<StableId>,
    /// Digest of the already admitted DecisionCell policy/propensity
    /// observation. Planner only applies bounded guards; it cannot replace
    /// or mutate that policy.
    pub policy_digest: Digest32,
    pub budget: CircuitBudgetCursorV1,
    pub now_micros: u64,
    pub deadline_micros: u64,
}

/// Advisory output from the Planner profile.  `selected` is a proposal for
/// TaskFlow; it is not a TaskFlow run and cannot execute any operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerResultV1 {
    pub policy_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub frontier_digest: Digest32,
    pub selected: Option<PlanCandidateV1>,
    pub owner_module: StableId,
    pub considered_count: u32,
    pub rejected_count: u32,
    pub next_budget: CircuitBudgetCursorV1,
    pub frontier_exhausted: bool,
    pub budget_exhausted: bool,
}

/// A durable-owner supplied replay witness for a Planner step.  This is a
/// structural replay receipt: it binds the exact output and successor state
/// observed on the first evaluation to the deterministic re-evaluation.  It
/// does not grant TaskFlow authority or imply that a plan was executed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerReplayReceiptV1 {
    pub step_digest: Digest32,
    pub replay_digest: Digest32,
    pub matched: bool,
}

pub struct PlannerAdapterV1;

impl PlannerAdapterV1 {
    pub const OWNER_MODULE: &'static str = PLANNER_OWNER_MODULE;

    pub fn adapt(
        context: &CellAdapterContextV1,
        input: &PlannerCircuitInputV1,
    ) -> Result<CellRoleStepV1<PlannerResultV1>, CircuitRoleErrorV1> {
        input.validate()?;
        context
            .validate(CellRoleV1::Planner)
            .map_err(CircuitRoleErrorV1::Adapter)?;

        let owner_module = StableId::new(Self::OWNER_MODULE)
            .map_err(|_| CircuitRoleErrorV1::EmptyId("planner owner module"))?;
        let legal = legal_ids(&input.legal_candidate_ids)?;
        let mut all = input.candidates.clone();
        all.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
        let all_ids = all
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if !legal.is_subset(&all_ids) {
            return Err(CircuitRoleErrorV1::UnknownLegalCandidate);
        }
        let candidate_set_digest = digest_ids_and_candidates(&legal, &all);

        let mut feasible = all
            .iter()
            .filter(|candidate| {
                legal.contains(&candidate.candidate_id)
                    && candidate.owner_module == owner_module
                    && candidate.frontier_index >= input.budget.frontier_cursor
                    && candidate.frontier_index < input.budget.frontier_end()
                    && candidate.expiry_micros > input.now_micros
                    && candidate.expiry_micros <= input.deadline_micros
                    && candidate.estimated_cost_q24 <= input.budget.remaining_budget()
            })
            .cloned()
            .collect::<Vec<_>>();
        feasible.sort_by(|left, right| {
            left.frontier_index
                .cmp(&right.frontier_index)
                .then_with(|| left.candidate_id.cmp(&right.candidate_id))
                .then_with(|| left.plan_digest.cmp(&right.plan_digest))
        });
        let selected = feasible.first().cloned();
        let considered_count = u32::try_from(feasible.len()).unwrap_or(u32::MAX);
        let rejected_count = u32::try_from(
            legal
                .iter()
                .filter(|id| {
                    !feasible
                        .iter()
                        .any(|candidate| &candidate.candidate_id == *id)
                })
                .count(),
        )
        .unwrap_or(u32::MAX);
        let mut frontier_bytes = Vec::from(b"hepta.cell-role.planner-frontier.v1".as_slice());
        for candidate in &feasible {
            frontier_bytes.extend_from_slice(candidate.content_digest().as_array());
        }
        let frontier_digest = Digest32::of_bytes(&frontier_bytes);
        let next_budget =
            selected
                .as_ref()
                .map_or(input.budget, |candidate| CircuitBudgetCursorV1 {
                    frontier_cursor: candidate.frontier_index.saturating_add(1),
                    frontier_limit: input.budget.frontier_limit,
                    budget_cursor_q24: input
                        .budget
                        .budget_cursor_q24
                        .saturating_add(candidate.estimated_cost_q24),
                    budget_limit_q24: input.budget.budget_limit_q24,
                });
        let budget_exhausted = selected.is_none()
            && legal.iter().any(|id| {
                all.iter().any(|candidate| {
                    &candidate.candidate_id == id
                        && candidate.owner_module == owner_module
                        && candidate.estimated_cost_q24 > input.budget.remaining_budget()
                })
            });
        let frontier_exhausted = selected.is_none()
            && legal.iter().any(|id| {
                all.iter().any(|candidate| {
                    &candidate.candidate_id == id
                        && candidate.frontier_index >= input.budget.frontier_end()
                })
            });
        let output_digest = digest_bytes(
            b"hepta.cell-role.planner-output.v1",
            &[
                input.policy_digest.as_array(),
                candidate_set_digest.as_array(),
                frontier_digest.as_array(),
                selected
                    .as_ref()
                    .map_or(Digest32::ZERO, PlanCandidateV1::content_digest)
                    .as_array(),
            ],
        );
        let state_successor_digest = digest_bytes(
            b"hepta.cell-role.planner-state.v1",
            &[
                context.state_predecessor_digest.as_array(),
                &next_budget.frontier_cursor.to_be_bytes(),
                &next_budget.budget_cursor_q24.to_be_bytes(),
            ],
        );
        let status = if selected.is_some() {
            CellStepStatusV1::Accepted
        } else if legal.is_empty() {
            CellStepStatusV1::Abstained
        } else {
            CellStepStatusV1::SlowPath
        };
        let receipt = step_receipt(
            context,
            CellRoleV1::Planner,
            state_successor_digest,
            output_digest,
            0,
            0,
            status,
        )
        .map_err(CircuitRoleErrorV1::Adapter)?;
        Ok(CellRoleStepV1 {
            result: PlannerResultV1 {
                policy_digest: input.policy_digest,
                candidate_set_digest,
                frontier_digest,
                selected,
                owner_module,
                considered_count,
                rejected_count,
                next_budget,
                frontier_exhausted,
                budget_exhausted,
            },
            receipt,
        })
    }

    /// Re-evaluate the bounded Planner projection and compare it with a
    /// previously persisted step.  TaskFlow remains the owner of durable
    /// journals and execution; this method only supplies a deterministic
    /// replay witness that callers can append to that journal.
    pub fn replay(
        context: &CellAdapterContextV1,
        input: &PlannerCircuitInputV1,
        expected: &CellRoleStepV1<PlannerResultV1>,
    ) -> Result<PlannerReplayReceiptV1, CircuitRoleErrorV1> {
        let replayed = Self::adapt(context, input)?;
        let step_digest = expected.receipt.content_digest().map_err(|error| {
            CircuitRoleErrorV1::Adapter(CellRoleAdapterErrorV1::Contract(error))
        })?;
        let replay_digest = replayed.receipt.content_digest().map_err(|error| {
            CircuitRoleErrorV1::Adapter(CellRoleAdapterErrorV1::Contract(error))
        })?;
        Ok(PlannerReplayReceiptV1 {
            step_digest,
            replay_digest,
            matched: replayed == *expected,
        })
    }
}

impl PlannerCircuitInputV1 {
    fn validate(&self) -> Result<(), CircuitRoleErrorV1> {
        self.budget.validate()?;
        if self.deadline_micros <= self.now_micros {
            return Err(CircuitRoleErrorV1::InvalidCandidate("deadline"));
        }
        if self.policy_digest.is_zero() {
            return Err(CircuitRoleErrorV1::EmptyDigest("planner policy"));
        }
        if self.candidates.is_empty() {
            return Err(CircuitRoleErrorV1::InvalidCandidate("candidates"));
        }
        let mut ids = BTreeSet::new();
        for candidate in &self.candidates {
            candidate.validate()?;
            if !ids.insert(candidate.candidate_id.clone()) {
                return Err(CircuitRoleErrorV1::DuplicateId("candidate"));
            }
        }
        Ok(())
    }
}

/// A route candidate bound to the concrete route value owned by CNS.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RouteCandidateV1 {
    pub route_id: StableId,
    pub route: CnsRouteV1,
    pub route_predicate_digest: Digest32,
    pub fallback_route_digest: Digest32,
    pub owner_module: StableId,
    pub frontier_index: u32,
    pub estimated_cost_q24: u64,
}

impl RouteCandidateV1 {
    fn validate(&self, expected_generation: Generation) -> Result<(), CircuitRoleErrorV1> {
        if self.route_id.as_str().is_empty() || self.owner_module.as_str().is_empty() {
            return Err(CircuitRoleErrorV1::EmptyId("route"));
        }
        if self.route.generation != expected_generation {
            return Err(CircuitRoleErrorV1::GenerationMismatch);
        }
        if self.route.cns.as_str().is_empty()
            || self.route.hierarchy_digest.is_zero()
            || self.route.source.system.as_str().is_empty()
            || self.route.source.organ.as_str().is_empty()
            || self.route.source.driver.as_str().is_empty()
            || self.route.targets.is_empty()
        {
            return Err(CircuitRoleErrorV1::InvalidRoute);
        }
        if self.route_predicate_digest.is_zero() {
            return Err(CircuitRoleErrorV1::EmptyDigest("route predicate"));
        }
        if self.fallback_route_digest.is_zero() {
            return Err(CircuitRoleErrorV1::EmptyDigest("fallback route"));
        }
        Ok(())
    }

    fn content_digest(&self) -> Digest32 {
        digest_bytes(
            b"hepta.cell-role.router-candidate.v1",
            &[
                self.route_id.as_str().as_bytes(),
                cns_route_digest_v1(&self.route).as_array(),
                self.route_predicate_digest.as_array(),
                self.fallback_route_digest.as_array(),
                self.owner_module.as_str().as_bytes(),
                &self.frontier_index.to_be_bytes(),
                &self.estimated_cost_q24.to_be_bytes(),
            ],
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RouterCircuitInputV1 {
    pub candidates: Vec<RouteCandidateV1>,
    pub legal_route_ids: Vec<StableId>,
    /// Digest of the DecisionCell policy/propensity observation that admitted
    /// this route candidate set. CNS still owns route fencing and dispatch.
    pub policy_digest: Digest32,
    pub expected_generation: Generation,
    pub route_fence_digest: Digest32,
    pub budget: CircuitBudgetCursorV1,
}

/// Advisory route selection. CNS must still verify/admit this route and own
/// the generation fence before dispatch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RouteDecisionV1 {
    pub policy_digest: Digest32,
    pub selected_route_id: Option<StableId>,
    pub selected_route: Option<CnsRouteV1>,
    pub route_digest: Digest32,
    pub route_predicate_digest: Digest32,
    pub fallback_route_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub owner_module: StableId,
    pub next_budget: CircuitBudgetCursorV1,
    pub route_fence_digest: Digest32,
    pub fallback_available: bool,
}

/// A structural route-fence witness emitted by the Router owner before CNS
/// dispatch.  CNS still owns admission, generation fencing, and cutover.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RouterFenceReceiptV1 {
    pub route_digest: Digest32,
    pub route_fence_digest: Digest32,
    pub generation: Generation,
    pub fallback_route_digest: Digest32,
    pub fence_digest: Digest32,
}

/// A deterministic replay witness for one Router projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RouterReplayReceiptV1 {
    pub step_digest: Digest32,
    pub replay_digest: Digest32,
    pub matched: bool,
}

pub struct RouterAdapterV1;

impl RouterAdapterV1 {
    pub const OWNER_MODULE: &'static str = ROUTER_OWNER_MODULE;

    pub fn adapt(
        context: &CellAdapterContextV1,
        input: &RouterCircuitInputV1,
    ) -> Result<CellRoleStepV1<RouteDecisionV1>, CircuitRoleErrorV1> {
        input.validate()?;
        context
            .validate(CellRoleV1::Router)
            .map_err(CircuitRoleErrorV1::Adapter)?;
        let owner_module = StableId::new(Self::OWNER_MODULE)
            .map_err(|_| CircuitRoleErrorV1::EmptyId("router owner module"))?;
        let legal = legal_ids(&input.legal_route_ids)?;
        let mut all = input.candidates.clone();
        all.sort_by(|left, right| left.route_id.cmp(&right.route_id));
        let all_ids = all
            .iter()
            .map(|candidate| candidate.route_id.clone())
            .collect::<BTreeSet<_>>();
        if !legal.is_subset(&all_ids) {
            return Err(CircuitRoleErrorV1::UnknownLegalCandidate);
        }
        let candidate_set_digest = digest_ids_and_routes(&legal, &all);
        let selected = all
            .iter()
            .filter(|candidate| {
                legal.contains(&candidate.route_id)
                    && candidate.owner_module == owner_module
                    && candidate.frontier_index >= input.budget.frontier_cursor
                    && candidate.frontier_index < input.budget.frontier_end()
                    && candidate.estimated_cost_q24 <= input.budget.remaining_budget()
            })
            .min_by(|left, right| {
                left.route_id.cmp(&right.route_id).then_with(|| {
                    cns_route_digest_v1(&left.route).cmp(&cns_route_digest_v1(&right.route))
                })
            })
            .cloned();
        let (
            selected_route_id,
            selected_route,
            route_digest,
            route_predicate_digest,
            fallback_route_digest,
        ) = selected.as_ref().map_or(
            (None, None, Digest32::ZERO, Digest32::ZERO, Digest32::ZERO),
            |candidate| {
                (
                    Some(candidate.route_id.clone()),
                    Some(candidate.route.clone()),
                    cns_route_digest_v1(&candidate.route),
                    candidate.route_predicate_digest,
                    candidate.fallback_route_digest,
                )
            },
        );
        let next_budget =
            selected
                .as_ref()
                .map_or(input.budget, |candidate| CircuitBudgetCursorV1 {
                    frontier_cursor: candidate.frontier_index.saturating_add(1),
                    frontier_limit: input.budget.frontier_limit,
                    budget_cursor_q24: input
                        .budget
                        .budget_cursor_q24
                        .saturating_add(candidate.estimated_cost_q24),
                    budget_limit_q24: input.budget.budget_limit_q24,
                });
        let output_digest = digest_bytes(
            b"hepta.cell-role.router-output.v1",
            &[
                input.policy_digest.as_array(),
                candidate_set_digest.as_array(),
                route_digest.as_array(),
                input.route_fence_digest.as_array(),
            ],
        );
        let state_successor_digest = digest_bytes(
            b"hepta.cell-role.router-state.v1",
            &[
                context.state_predecessor_digest.as_array(),
                input.route_fence_digest.as_array(),
                &next_budget.frontier_cursor.to_be_bytes(),
                &next_budget.budget_cursor_q24.to_be_bytes(),
            ],
        );
        let status = if selected.is_some() {
            CellStepStatusV1::Accepted
        } else if legal.is_empty() {
            CellStepStatusV1::Abstained
        } else {
            CellStepStatusV1::SlowPath
        };
        let receipt = step_receipt(
            context,
            CellRoleV1::Router,
            state_successor_digest,
            output_digest,
            0,
            0,
            status,
        )
        .map_err(CircuitRoleErrorV1::Adapter)?;
        Ok(CellRoleStepV1 {
            result: RouteDecisionV1 {
                policy_digest: input.policy_digest,
                selected_route_id,
                selected_route,
                route_digest,
                route_predicate_digest,
                fallback_route_digest,
                candidate_set_digest,
                owner_module,
                next_budget,
                route_fence_digest: input.route_fence_digest,
                fallback_available: !fallback_route_digest.is_zero(),
            },
            receipt,
        })
    }

    /// Bind a selected route to the caller's current generation fence.  This
    /// is intentionally a read-only owner projection; the returned digest is
    /// passed to CNS, whose route owner performs the actual cutover/fence.
    pub fn fence(
        input: &RouterCircuitInputV1,
        decision: &RouteDecisionV1,
    ) -> Result<RouterFenceReceiptV1, CircuitRoleErrorV1> {
        input.validate()?;
        if decision.policy_digest != input.policy_digest
            || decision.route_fence_digest != input.route_fence_digest
        {
            return Err(CircuitRoleErrorV1::FenceMismatch);
        }
        if decision.owner_module
            != StableId::new(ROUTER_OWNER_MODULE)
                .map_err(|_| CircuitRoleErrorV1::EmptyId("router owner module"))?
        {
            return Err(CircuitRoleErrorV1::OwnerBinding);
        }
        if let Some(route) = &decision.selected_route {
            if route.generation != input.expected_generation {
                return Err(CircuitRoleErrorV1::GenerationMismatch);
            }
            let selected_id = decision
                .selected_route_id
                .as_ref()
                .ok_or(CircuitRoleErrorV1::FenceMismatch)?;
            let candidate = input
                .candidates
                .iter()
                .find(|candidate| &candidate.route_id == selected_id)
                .ok_or(CircuitRoleErrorV1::FenceMismatch)?;
            let owner_module = StableId::new(ROUTER_OWNER_MODULE)
                .map_err(|_| CircuitRoleErrorV1::EmptyId("router owner module"))?;
            if candidate.owner_module != owner_module
                || candidate.route != *route
                || candidate.route_predicate_digest != decision.route_predicate_digest
                || candidate.fallback_route_digest != decision.fallback_route_digest
            {
                return Err(CircuitRoleErrorV1::FenceMismatch);
            }
            if decision.selected_route_id.is_none()
                || cns_route_digest_v1(route) != decision.route_digest
                || decision.route_predicate_digest.is_zero()
                || decision.fallback_route_digest.is_zero()
                || !decision.fallback_available
            {
                return Err(CircuitRoleErrorV1::FenceMismatch);
            }
        } else if !decision.route_digest.is_zero()
            || !decision.route_predicate_digest.is_zero()
            || !decision.fallback_route_digest.is_zero()
            || decision.selected_route_id.is_some()
            || decision.fallback_available
        {
            return Err(CircuitRoleErrorV1::FenceMismatch);
        }
        let fence_digest = digest_bytes(
            b"hepta.cell-role.router-fence.v1",
            &[
                decision.route_digest.as_array(),
                input.route_fence_digest.as_array(),
                decision
                    .selected_route_id
                    .as_ref()
                    .map_or(&[][..], |id| id.as_str().as_bytes()),
                decision.fallback_route_digest.as_array(),
                &input.expected_generation.get().to_be_bytes(),
            ],
        );
        Ok(RouterFenceReceiptV1 {
            route_digest: decision.route_digest,
            route_fence_digest: input.route_fence_digest,
            generation: input.expected_generation,
            fallback_route_digest: decision.fallback_route_digest,
            fence_digest,
        })
    }

    /// Re-evaluate and compare a Router result before handing its fence to
    /// CNS.  This prevents a stale route decision from being replayed under a
    /// different policy or generation.
    pub fn replay(
        context: &CellAdapterContextV1,
        input: &RouterCircuitInputV1,
        expected: &CellRoleStepV1<RouteDecisionV1>,
    ) -> Result<RouterReplayReceiptV1, CircuitRoleErrorV1> {
        let replayed = Self::adapt(context, input)?;
        let step_digest = expected.receipt.content_digest().map_err(|error| {
            CircuitRoleErrorV1::Adapter(CellRoleAdapterErrorV1::Contract(error))
        })?;
        let replay_digest = replayed
            .receipt
            .content_digest()
            .map_err(CellRoleAdapterErrorV1::Contract)
            .map_err(CircuitRoleErrorV1::Adapter)?;
        let expected_fence = Self::fence(input, &expected.result)?;
        let replay_fence = Self::fence(input, &replayed.result)?;
        Ok(RouterReplayReceiptV1 {
            step_digest,
            replay_digest,
            matched: replayed == *expected && expected_fence == replay_fence,
        })
    }
}

impl RouterCircuitInputV1 {
    fn validate(&self) -> Result<(), CircuitRoleErrorV1> {
        self.budget.validate()?;
        if self.route_fence_digest.is_zero() {
            return Err(CircuitRoleErrorV1::EmptyDigest("route fence"));
        }
        if self.policy_digest.is_zero() {
            return Err(CircuitRoleErrorV1::EmptyDigest("router policy"));
        }
        if self.candidates.is_empty() {
            return Err(CircuitRoleErrorV1::InvalidCandidate("routes"));
        }
        let mut ids = BTreeSet::new();
        for candidate in &self.candidates {
            candidate.validate(self.expected_generation)?;
            if !ids.insert(candidate.route_id.clone()) {
                return Err(CircuitRoleErrorV1::DuplicateId("route"));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CircuitRoleErrorV1 {
    Adapter(CellRoleAdapterErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    InvalidBudget(&'static str),
    InvalidCandidate(&'static str),
    InvalidRoute,
    OwnerBinding,
    GenerationMismatch,
    DuplicateId(&'static str),
    UnknownLegalCandidate,
    FenceMismatch,
}

impl fmt::Display for CircuitRoleErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CircuitRoleErrorV1 {}

fn legal_ids(ids: &[StableId]) -> Result<BTreeSet<StableId>, CircuitRoleErrorV1> {
    let mut result = BTreeSet::new();
    for id in ids {
        if id.as_str().is_empty() || !result.insert(id.clone()) {
            return Err(CircuitRoleErrorV1::DuplicateId("legal candidate"));
        }
    }
    Ok(result)
}

fn digest_ids_and_candidates(ids: &BTreeSet<StableId>, candidates: &[PlanCandidateV1]) -> Digest32 {
    let mut bytes = Vec::from(b"hepta.cell-role.planner-candidate-set.v1".as_slice());
    for id in ids {
        bytes.extend_from_slice(id.as_str().as_bytes());
        bytes.push(0);
        if let Some(candidate) = candidates
            .iter()
            .find(|candidate| &candidate.candidate_id == id)
        {
            bytes.extend_from_slice(candidate.content_digest().as_array());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_ids_and_routes(ids: &BTreeSet<StableId>, candidates: &[RouteCandidateV1]) -> Digest32 {
    let mut bytes = Vec::from(b"hepta.cell-role.router-candidate-set.v1".as_slice());
    for id in ids {
        bytes.extend_from_slice(id.as_str().as_bytes());
        bytes.push(0);
        if let Some(candidate) = candidates
            .iter()
            .find(|candidate| &candidate.route_id == id)
        {
            bytes.extend_from_slice(candidate.content_digest().as_array());
        }
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_control_plane::OrganPathV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::of_bytes(&[value])
    }

    fn context(role: CellRoleV1) -> CellAdapterContextV1 {
        CellAdapterContextV1 {
            cell_id: id("circuit.role.1"),
            generation: Generation::new(2).expect("generation"),
            scope_digest: digest(1),
            role,
            capability_digest: digest(2),
            input_frontier_digest: digest(3),
            state_predecessor_digest: digest(4),
            resource_receipt_digest: digest(5),
            evidence_digest: digest(6),
        }
    }

    fn budget() -> CircuitBudgetCursorV1 {
        CircuitBudgetCursorV1 {
            frontier_cursor: 0,
            frontier_limit: 4,
            budget_cursor_q24: 0,
            budget_limit_q24: 10,
        }
    }

    fn plan(id_value: &str, index: u32, cost: u64) -> PlanCandidateV1 {
        let owner = StableId::new(PLANNER_OWNER_MODULE).expect("owner");
        PlanCandidateV1 {
            candidate_id: id(id_value),
            operation_id: id("taskflow.operation"),
            plan_digest: digest(index as u8 + 10),
            required_owner_ids: vec![owner.clone()],
            owner_module: owner,
            estimated_cost_q24: cost,
            frontier_index: index,
            expiry_micros: 100,
            fallback_plan_digest: digest(index as u8 + 40),
        }
    }

    fn route(id_value: &str, route_id: u8) -> RouteCandidateV1 {
        let generation = Generation::new(2).expect("generation");
        let owner = StableId::new(ROUTER_OWNER_MODULE).expect("owner");
        let route = CnsRouteV1 {
            cns: id("cns.main"),
            generation,
            hierarchy_digest: digest(route_id + 30),
            source: OrganPathV1 {
                system: id("system.main"),
                organ: id("organ.source"),
                driver: id("driver.source"),
            },
            output_port: 0,
            targets: vec![OrganPathV1 {
                system: id("system.main"),
                organ: id("organ.target"),
                driver: id("driver.target"),
            }],
        };
        RouteCandidateV1 {
            route_id: id(id_value),
            route,
            route_predicate_digest: digest(route_id + 50),
            fallback_route_digest: digest(route_id + 60),
            owner_module: owner,
            frontier_index: u32::from(route_id),
            estimated_cost_q24: 1,
        }
    }

    #[test]
    fn planner_is_bounded_legal_and_authority_free() {
        let input = PlannerCircuitInputV1 {
            candidates: vec![plan("plan.b", 1, 4), plan("plan.a", 0, 3)],
            legal_candidate_ids: vec![id("plan.b"), id("plan.a")],
            policy_digest: digest(91),
            budget: budget(),
            now_micros: 1,
            deadline_micros: 100,
        };
        let step = PlannerAdapterV1::adapt(&context(CellRoleV1::Planner), &input).expect("step");
        assert_eq!(
            step.result
                .selected
                .as_ref()
                .map(|p| p.candidate_id.as_str()),
            Some("plan.a")
        );
        assert_eq!(step.result.next_budget.budget_cursor_q24, 3);
        assert_eq!(
            step.receipt.authority,
            codex_hepta_types::AuthorityPosture::DENY_ALL
        );
        assert_eq!(step.receipt.status, CellStepStatusV1::Accepted);
    }

    #[test]
    fn planner_rejects_illegal_ids_and_owner_mismatch() {
        let mut input = PlannerCircuitInputV1 {
            candidates: vec![plan("plan.a", 0, 3)],
            legal_candidate_ids: vec![id("unknown")],
            policy_digest: digest(91),
            budget: budget(),
            now_micros: 1,
            deadline_micros: 100,
        };
        assert_eq!(
            PlannerAdapterV1::adapt(&context(CellRoleV1::Planner), &input),
            Err(CircuitRoleErrorV1::UnknownLegalCandidate)
        );
        input.legal_candidate_ids = vec![id("plan.a")];
        input.candidates[0].owner_module = id("rogue.owner");
        input.candidates[0].required_owner_ids = vec![id("rogue.owner")];
        let step = PlannerAdapterV1::adapt(&context(CellRoleV1::Planner), &input).expect("step");
        assert!(step.result.selected.is_none());
        assert_eq!(step.receipt.status, CellStepStatusV1::SlowPath);
    }

    #[test]
    fn router_binds_generation_fence_and_fallback() {
        let input = RouterCircuitInputV1 {
            candidates: vec![route("route.b", 2), route("route.a", 1)],
            legal_route_ids: vec![id("route.b"), id("route.a")],
            policy_digest: digest(92),
            expected_generation: Generation::new(2).expect("generation"),
            route_fence_digest: digest(90),
            budget: budget(),
        };
        let step = RouterAdapterV1::adapt(&context(CellRoleV1::Router), &input).expect("step");
        assert_eq!(
            step.result.selected_route_id.as_ref().map(StableId::as_str),
            Some("route.a")
        );
        assert!(!step.result.route_digest.is_zero());
        assert!(step.result.fallback_available);
        assert_eq!(step.result.route_fence_digest, digest(90));
        assert_eq!(
            step.receipt.authority,
            codex_hepta_types::AuthorityPosture::DENY_ALL
        );
    }

    #[test]
    fn router_rejects_stale_generation_and_missing_fence() {
        let mut input = RouterCircuitInputV1 {
            candidates: vec![route("route.a", 1)],
            legal_route_ids: vec![id("route.a")],
            policy_digest: digest(92),
            expected_generation: Generation::new(3).expect("generation"),
            route_fence_digest: digest(90),
            budget: budget(),
        };
        assert_eq!(
            RouterAdapterV1::adapt(&context(CellRoleV1::Router), &input),
            Err(CircuitRoleErrorV1::GenerationMismatch)
        );
        input.expected_generation = Generation::new(2).expect("generation");
        input.route_fence_digest = Digest32::ZERO;
        assert_eq!(
            RouterAdapterV1::adapt(&context(CellRoleV1::Router), &input),
            Err(CircuitRoleErrorV1::EmptyDigest("route fence"))
        );
    }

    #[test]
    fn planner_replay_recomputes_the_same_step_receipt() {
        let input = PlannerCircuitInputV1 {
            candidates: vec![plan("plan.a", 0, 3)],
            legal_candidate_ids: vec![id("plan.a")],
            policy_digest: digest(91),
            budget: budget(),
            now_micros: 1,
            deadline_micros: 100,
        };
        let first = PlannerAdapterV1::adapt(&context(CellRoleV1::Planner), &input).expect("step");
        let replay = PlannerAdapterV1::replay(&context(CellRoleV1::Planner), &input, &first)
            .expect("replay");
        assert!(replay.matched);
        assert_eq!(replay.step_digest, replay.replay_digest);
    }

    #[test]
    fn router_fence_and_replay_bind_policy_generation_and_route() {
        let input = RouterCircuitInputV1 {
            candidates: vec![route("route.a", 1)],
            legal_route_ids: vec![id("route.a")],
            policy_digest: digest(92),
            expected_generation: Generation::new(2).expect("generation"),
            route_fence_digest: digest(90),
            budget: budget(),
        };
        let first = RouterAdapterV1::adapt(&context(CellRoleV1::Router), &input).expect("step");
        let fence = RouterAdapterV1::fence(&input, &first.result).expect("fence");
        assert_eq!(fence.generation, input.expected_generation);
        assert_eq!(fence.route_fence_digest, input.route_fence_digest);
        assert!(!fence.fence_digest.is_zero());
        let replay =
            RouterAdapterV1::replay(&context(CellRoleV1::Router), &input, &first).expect("replay");
        assert!(replay.matched);
        let mut tampered = first.result.clone();
        tampered.route_fence_digest = digest(91);
        assert_eq!(
            RouterAdapterV1::fence(&input, &tampered),
            Err(CircuitRoleErrorV1::FenceMismatch)
        );
        let mut tampered = first.result.clone();
        tampered.route_predicate_digest = digest(99);
        assert_eq!(
            RouterAdapterV1::fence(&input, &tampered),
            Err(CircuitRoleErrorV1::FenceMismatch)
        );
    }
}
