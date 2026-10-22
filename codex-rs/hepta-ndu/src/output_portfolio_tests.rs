use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn q(percent: i64) -> FixedQ32 {
    FixedQ32::from_raw(percent * (1_i64 << 32) / 100)
}

fn future_window() -> Digest32 {
    Digest32::of_bytes(b"future-window")
}

fn probability(percent: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(percent * (1_u64 << 32) / 100).expect("valid probability")
}

fn risk(mean: i64) -> SemanticRiskEstimateV1 {
    SemanticRiskEstimateV1 {
        future_window_digest: future_window(),
        mean_loss: q(mean),
        cvar_loss: FixedQ32::ZERO,
        failure_probability: ProbabilityQ32::ZERO,
        cross_modal_inconsistency: FixedQ32::ZERO,
    }
}

fn candidate(
    name: &str,
    utility: i64,
    risk_value: i64,
    is_no_change: bool,
) -> OutputPortfolioCandidateV1 {
    OutputPortfolioCandidateV1 {
        candidate_id: id(name),
        candidate_digest: Digest32::of_bytes(name.as_bytes()),
        objective_digest: Digest32::of_bytes(b"objective"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        generation: Generation::new(1).expect("candidate generation"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        composition_domain_digest: if is_no_change {
            Digest32::ZERO
        } else {
            Digest32::of_bytes(b"shared-output-space")
        },
        protocol: if is_no_change {
            OutputProtocolV1::NoChange
        } else {
            OutputProtocolV1::TextLogit
        },
        utility_delta: q(utility),
        risk: risk(risk_value),
        resource_cost: if is_no_change { FixedQ32::ZERO } else { q(10) },
        latency_cost: if is_no_change { FixedQ32::ZERO } else { q(5) },
        weight_cap: FixedQ32::ONE,
        is_no_change,
    }
}

fn context(count: usize) -> OutputPortfolioContextV1 {
    OutputPortfolioContextV1 {
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: Generation::new(1).expect("generation"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        future_window_digest: future_window(),
        semantic_covariance: vec![FixedQ32::ZERO; count * count],
    }
}

fn budget(max_selected: usize) -> OutputPortfolioBudgetV1 {
    OutputPortfolioBudgetV1 {
        max_selected,
        risk_budget: q(100),
        resource_budget: q(100),
        latency_budget: q(100),
        risk_aversion: FixedQ32::ONE,
        cvar_aversion: FixedQ32::ONE,
        failure_aversion: FixedQ32::ONE,
        inconsistency_aversion: FixedQ32::ONE,
        resource_price: FixedQ32::ZERO,
        latency_price: FixedQ32::ZERO,
        switch_penalty: FixedQ32::ZERO,
    }
}

#[test]
fn negative_direction_falls_back_to_no_change() {
    let receipt = select_output_portfolio_v1(
        &context(2),
        &budget(1),
        &[
            candidate("baseline", 0, 0, true),
            candidate("unsafe", 10, 30, false),
        ],
    )
    .expect("bounded selection");
    assert_eq!(receipt.disposition, OutputPortfolioDispositionV1::NoChange);
    assert_eq!(receipt.allocations.len(), 1);
    assert_eq!(receipt.total_utility, FixedQ32::ZERO);
}

#[test]
fn risk_adjusted_score_selects_the_lower_risk_direction() {
    let receipt = select_output_portfolio_v1(
        &context(3),
        &budget(1),
        &[
            candidate("baseline", 0, 0, true),
            candidate("high-risk", 90, 80, false),
            candidate("stable", 60, 10, false),
        ],
    )
    .expect("bounded selection");
    assert_eq!(
        receipt.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert_eq!(receipt.allocations.len(), 1);
    assert_eq!(receipt.allocations[0].candidate_id, id("stable"));
}

#[test]
fn covariance_dimension_and_snapshot_are_fail_closed() {
    let mut bad_context = context(2);
    bad_context.semantic_covariance.pop();
    let error = select_output_portfolio_v1(
        &bad_context,
        &budget(1),
        &[
            candidate("baseline", 0, 0, true),
            candidate("x", 20, 1, false),
        ],
    )
    .expect_err("dimension mismatch");
    assert_eq!(error, NduError::DimensionMismatch);

    let mut mismatched = candidate("x", 20, 1, false);
    mismatched.snapshot_digest = Digest32::of_bytes(b"other-snapshot");
    let error = select_output_portfolio_v1(
        &context(2),
        &budget(1),
        &[candidate("baseline", 0, 0, true), mismatched],
    )
    .expect_err("snapshot mismatch");
    assert_eq!(error, NduError::StateDigestMismatch);

    let mut wrong_window = candidate("window-drift", 20, 1, false);
    wrong_window.risk.future_window_digest = Digest32::of_bytes(b"other-window");
    let error = select_output_portfolio_v1(
        &context(2),
        &budget(1),
        &[candidate("baseline", 0, 0, true), wrong_window],
    )
    .expect_err("future-window mismatch");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("future-window digest")
    );
}

#[test]
fn frontier_is_deterministic_and_excludes_dominated_candidate() {
    let points = output_efficient_frontier_v1(
        &context(4),
        &[
            candidate("baseline", 0, 0, true),
            candidate("good", 50, 10, false),
            candidate("dominated", 40, 20, false),
            candidate("risky-upside", 90, 60, false),
        ],
    )
    .expect("frontier");
    assert!(points.iter().any(|point| point.candidate_id == id("good")));
    assert!(
        points
            .iter()
            .any(|point| point.candidate_id == id("risky-upside"))
    );
    assert!(
        !points
            .iter()
            .any(|point| point.candidate_id == id("dominated"))
    );

    let first = select_output_portfolio_v1(
        &context(2),
        &budget(1),
        &[
            candidate("baseline", 0, 0, true),
            candidate("x", 20, 1, false),
        ],
    )
    .expect("receipt");
    let second = select_output_portfolio_v1(
        &context(2),
        &budget(1),
        &[
            candidate("x", 20, 1, false),
            candidate("baseline", 0, 0, true),
        ],
    )
    .expect("receipt");
    assert_eq!(first.selection_digest, second.selection_digest);
}

#[test]
fn probability_is_represented_in_semantic_risk() {
    let mut risky = candidate("probabilistic", 80, 0, false);
    risky.risk.failure_probability = probability(25);
    let receipt = select_output_portfolio_v1(
        &context(2),
        &budget(1),
        &[candidate("baseline", 0, 0, true), risky],
    )
    .expect("bounded selection");
    assert_eq!(
        receipt.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert!(receipt.total_risk > FixedQ32::ZERO);
}

#[test]
fn whole_candidate_protocol_requires_full_weight_cap() {
    let mut tool = candidate("tool", 80, 1, false);
    tool.protocol = OutputProtocolV1::ToolAction;
    tool.weight_cap = q(50);
    let error = select_output_portfolio_v1(
        &context(2),
        &budget(1),
        &[candidate("baseline", 0, 0, true), tool],
    )
    .expect_err("tool action cannot be fractionally allocated");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("whole-candidate weight cap")
    );
}

#[test]
fn incompatible_generation_protocols_cannot_share_one_allocation() {
    let mut text = candidate("text", 80, 0, false);
    text.weight_cap = q(40);
    let mut flow = candidate("flow", 70, 0, false);
    flow.protocol = OutputProtocolV1::LatentFlow;
    let receipt = select_output_portfolio_v1(
        &context(3),
        &budget(3),
        &[candidate("baseline", 0, 0, true), flow, text],
    )
    .expect("protocol-specific advisory selection");
    assert_eq!(
        receipt.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert!(
        receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("text"))
    );
    assert!(
        receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("baseline"))
    );
    assert!(
        !receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("flow"))
    );
}

#[test]
fn incompatible_composition_domains_cannot_be_blended() {
    let mut first = candidate("first", 80, 0, false);
    first.weight_cap = q(40);
    let mut different_space = candidate("different-space", 70, 0, false);
    different_space.composition_domain_digest = Digest32::of_bytes(b"other-tokenizer");
    let receipt = select_output_portfolio_v1(
        &context(3),
        &budget(3),
        &[candidate("baseline", 0, 0, true), first, different_space],
    )
    .expect("domain-aware advisory routing");
    assert!(
        receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("first"))
    );
    assert!(
        !receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("different-space"))
    );
    assert!(
        receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("baseline"))
    );
}

#[test]
fn fractional_portfolio_counts_the_no_change_residual_against_max_selected() {
    let mut fractional = candidate("fractional", 70, 0, false);
    fractional.weight_cap = q(40);
    let candidates = [candidate("baseline", 0, 0, true), fractional];

    let one_slot = select_output_portfolio_v1(&context(2), &budget(1), &candidates)
        .expect("a single slot cannot represent a fractional direction and the baseline");
    assert_eq!(one_slot.disposition, OutputPortfolioDispositionV1::NoChange);
    assert_eq!(one_slot.allocations.len(), 1);
    assert_eq!(one_slot.allocations[0].weight, FixedQ32::ONE);

    let two_slots = select_output_portfolio_v1(&context(2), &budget(2), &candidates)
        .expect("bounded two-asset advisory allocation");
    assert_eq!(
        two_slots.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert_eq!(two_slots.allocations.len(), 2);
    // Q32 percentages truncate independently: q(40) + q(60) = ONE - 1
    // least-significant unit. The NoChange allocation is the exact residual.
    let exact_no_change_residual = FixedQ32::ONE
        .checked_sub(q(40))
        .expect("Q32 complement must be representable");
    assert_eq!(
        q(40)
            .checked_add(exact_no_change_residual)
            .expect("bounded weights"),
        FixedQ32::ONE
    );
    assert!(
        two_slots
            .allocations
            .iter()
            .any(|item| { item.candidate_id == id("fractional") && item.weight == q(40) })
    );
    assert!(two_slots.allocations.iter().any(|item| {
        item.candidate_id == id("baseline") && item.weight == exact_no_change_residual
    }));
}

#[test]
fn missing_composition_domain_is_rejected() {
    let mut unbound = candidate("unbound", 70, 0, false);
    unbound.composition_domain_digest = Digest32::ZERO;
    let error = select_output_portfolio_v1(
        &context(2),
        &budget(2),
        &[candidate("baseline", 0, 0, true), unbound],
    )
    .expect_err("output geometry must be committed");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("composition domain digest")
    );
}

#[test]
fn masked_diffusion_unmask_plan_must_be_atomic() {
    let mut masked = candidate("unmask", 90, 0, false);
    masked.protocol = OutputProtocolV1::MaskedDiffusion;
    masked.weight_cap = q(50);
    let error = select_output_portfolio_v1(
        &context(2),
        &budget(2),
        &[candidate("baseline", 0, 0, true), masked],
    )
    .expect_err("discrete unmasking cannot be fractionally mixed");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("whole-candidate weight cap")
    );
}

#[test]
fn candidate_costs_must_not_be_negative() {
    for negative_resource in [true, false] {
        let mut target = candidate("negative-cost", 90, 0, false);
        if negative_resource {
            target.resource_cost = q(-10);
        } else {
            target.latency_cost = q(-10);
        }
        let error = select_output_portfolio_v1(
            &context(2),
            &budget(2),
            &[candidate("baseline", 0, 0, true), target],
        )
        .expect_err("negative costs cannot subsidize the portfolio");
        assert_eq!(
            error,
            NduError::InvalidSolverReceipt("negative portfolio cost")
        );
    }
}

#[test]
fn no_change_protocol_cannot_masquerade_as_a_second_positive_asset() {
    let mut disguised = candidate("masquerading-baseline", 90, 0, false);
    disguised.protocol = OutputProtocolV1::NoChange;
    let error = select_output_portfolio_v1(
        &context(2),
        &budget(2),
        &[candidate("baseline", 0, 0, true), disguised],
    )
    .expect_err("unmarked NoChange asset must be rejected");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("unmarked no-change asset")
    );
}

#[test]
fn fractionally_admits_a_direction_to_honor_semantic_risk_budget() {
    let mut limits = budget(2);
    limits.risk_budget = q(8);
    let receipt = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("limited-by-risk", 80, 20, false),
        ],
    )
    .expect("bounded fractional risk allocation");
    assert_eq!(
        receipt.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert!(receipt.total_risk <= limits.risk_budget);
    let active = receipt
        .allocations
        .iter()
        .find(|item| item.candidate_id == id("limited-by-risk"))
        .expect("a feasible direction is retained");
    let abstain = receipt
        .allocations
        .iter()
        .find(|item| item.candidate_id == id("baseline"))
        .expect("unused weight stays with no-change");
    assert!(active.weight >= q(39));
    assert!(active.weight <= q(40));
    assert_eq!(
        active
            .weight
            .checked_add(abstain.weight)
            .expect("weights sum"),
        FixedQ32::ONE
    );
}

#[test]
fn fractionally_admits_a_direction_to_honor_resource_and_latency_budgets() {
    let mut limits = budget(2);
    limits.resource_budget = q(5);
    limits.latency_budget = q(2);
    let receipt = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("bounded", 80, 0, false),
        ],
    )
    .expect("bounded fractional resource allocation");
    assert!(receipt.total_resource <= limits.resource_budget);
    assert!(receipt.total_latency <= limits.latency_budget);
    assert_eq!(receipt.allocations.len(), 2);
    let active = receipt
        .allocations
        .iter()
        .find(|item| item.candidate_id == id("bounded"))
        .expect("direction admitted");
    assert!(active.weight >= q(39));
    assert!(active.weight <= q(40));
}

#[test]
fn covariance_risk_budget_bounds_fractional_weight() {
    let mut limits = budget(2);
    limits.risk_budget = q(20);
    let mut correlated = context(2);
    correlated.semantic_covariance[3] = q(80);
    let receipt = select_output_portfolio_v1(
        &correlated,
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("variance", 80, 0, false),
        ],
    )
    .expect("PSD risk-bounded selection");
    assert!(receipt.total_risk <= limits.risk_budget);
    let active = receipt
        .allocations
        .iter()
        .find(|item| item.candidate_id == id("variance"))
        .expect("partial covariance-aware direction");
    assert!(active.weight >= q(49));
    assert!(active.weight <= q(50));
}

#[test]
fn hard_slot_and_atomic_protocol_constraints_survive_fractional_optimization() {
    let mut limits = budget(1);
    limits.resource_budget = q(2);
    let receipt = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("partial", 80, 0, false),
        ],
    )
    .expect("no hidden slot for residual baseline");
    assert_eq!(receipt.disposition, OutputPortfolioDispositionV1::NoChange);

    limits.max_selected = 2;
    let mut tool = candidate("tool", 80, 0, false);
    tool.protocol = OutputProtocolV1::ToolAction;
    tool.resource_cost = q(10);
    let receipt = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[candidate("baseline", 0, 0, true), tool],
    )
    .expect("tool actions remain whole or skipped");
    assert_eq!(receipt.disposition, OutputPortfolioDispositionV1::NoChange);
}

#[test]
fn hard_zero_resource_and_latency_budgets_reject_rounded_positive_costs() {
    // 40% of one Q32 least-significant cost unit rounds to zero.
    // A hard zero budget must reject that exposure before weighted totals.
    for resource_cost in [true, false] {
        let mut limits = budget(2);
        let mut exposure = candidate("tiny-positive-cost", 80, 0, false);
        exposure.weight_cap = q(40);
        if resource_cost {
            limits.resource_budget = FixedQ32::ZERO;
            exposure.resource_cost = FixedQ32::from_raw(1);
        } else {
            limits.latency_budget = FixedQ32::ZERO;
            exposure.latency_cost = FixedQ32::from_raw(1);
        }
        let receipt = select_output_portfolio_v1(
            &context(2),
            &limits,
            &[candidate("baseline", 0, 0, true), exposure],
        )
        .expect("a positive cost must never fit a hard-zero limit");
        assert_eq!(receipt.disposition, OutputPortfolioDispositionV1::NoChange);
        assert_eq!(receipt.allocations.len(), 1);
        assert_eq!(receipt.allocations[0].candidate_id, id("baseline"));
    }

    // The hard-zero gate must still admit a genuinely free, riskless
    // fractional direction and preserve its exact NoChange residual.
    let mut limits = budget(2);
    limits.resource_budget = FixedQ32::ZERO;
    limits.latency_budget = FixedQ32::ZERO;
    let mut free = candidate("free-direction", 80, 0, false);
    free.resource_cost = FixedQ32::ZERO;
    free.latency_cost = FixedQ32::ZERO;
    free.weight_cap = q(40);
    let receipt = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[candidate("baseline", 0, 0, true), free],
    )
    .expect("genuinely zero-cost directions remain admissible");
    assert_eq!(
        receipt.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert_eq!(receipt.total_resource, FixedQ32::ZERO);
    assert_eq!(receipt.total_latency, FixedQ32::ZERO);
    let active = receipt
        .allocations
        .iter()
        .find(|allocation| allocation.candidate_id == id("free-direction"))
        .expect("zero-cost direction admitted");
    let baseline = receipt
        .allocations
        .iter()
        .find(|allocation| allocation.candidate_id == id("baseline"))
        .expect("unspent weight stays with NoChange");
    assert_eq!(active.weight, q(40));
    assert_eq!(
        active
            .weight
            .checked_add(baseline.weight)
            .expect("exact Q32 complement"),
        FixedQ32::ONE
    );
}

#[test]
fn hard_zero_risk_budget_rejects_positive_loss_hidden_by_q32_rounding() {
    // A 1-ULP Q32 risk can be rounded to zero at a large fractional weight:
    // 50% * 1 ULP = 0.5 ULP and ties-to-even reports zero. Likewise, a
    // quadratic variance of 1 ULP rounds to zero for a 50% allocation.
    // Hard-zero risk must reject those directions before solving.
    let mut limits = budget(2);
    limits.risk_budget = FixedQ32::ZERO;

    for covariance_only in [false, true] {
        let mut ctx = context(2);
        let mut exposure = candidate("one-ulp-exposure", 80, 0, false);
        if covariance_only {
            ctx.semantic_covariance[3] = FixedQ32::from_raw(1);
        } else {
            exposure.risk.mean_loss = FixedQ32::from_raw(1);
        }
        let receipt = select_output_portfolio_v1(
            &ctx,
            &limits,
            &[candidate("baseline", 0, 0, true), exposure],
        )
        .expect("a positive-risk direction cannot bypass a zero budget");
        assert_eq!(receipt.disposition, OutputPortfolioDispositionV1::NoChange);
        assert_eq!(receipt.allocations.len(), 1);
        assert_eq!(receipt.allocations[0].candidate_id, id("baseline"));
        assert_eq!(receipt.allocations[0].weight, FixedQ32::ONE);
        assert_eq!(receipt.total_risk, FixedQ32::ZERO);
    }

    // Zero budget must not ban a genuinely risk-free relative direction.
    let allowed = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("actually-zero-risk", 80, 0, false),
        ],
    )
    .expect("the zero-risk feasible direction remains available");
    assert_eq!(
        allowed.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert_eq!(allowed.total_risk, FixedQ32::ZERO);
}

#[test]
fn hard_semantic_risk_budget_is_independent_of_pricing() {
    // A zero risk aversion parameter only changes ranking; it must never
    // convert positive tail/failure/inconsistency risk into a free asset.
    for risk_component in 0..4 {
        let mut limits = budget(2);
        limits.risk_budget = q(10);
        limits.risk_aversion = FixedQ32::ZERO;
        limits.cvar_aversion = FixedQ32::ZERO;
        limits.failure_aversion = FixedQ32::ZERO;
        limits.inconsistency_aversion = FixedQ32::ZERO;
        let mut exposure = candidate("risk-bearing", 90, 0, false);
        match risk_component {
            0 => exposure.risk.mean_loss = q(50),
            1 => exposure.risk.cvar_loss = q(50),
            2 => exposure.risk.failure_probability = probability(50),
            _ => exposure.risk.cross_modal_inconsistency = q(50),
        }
        let receipt = select_output_portfolio_v1(
            &context(2),
            &limits,
            &[candidate("baseline", 0, 0, true), exposure],
        )
        .expect("hard risk bound must hold regardless of scoring prices");
        assert!(receipt.total_risk <= limits.risk_budget);
        assert!(receipt.total_risk > FixedQ32::ZERO);
        let active = receipt
            .allocations
            .iter()
            .find(|item| item.candidate_id == id("risk-bearing"))
            .expect("limited admissible allocation");
        // 10% hard risk / 50% candidate risk caps weight at about 20%.
        assert!(active.weight >= q(19));
        assert!(active.weight <= q(21));
        assert!(
            receipt.allocations.iter().any(|item| {
                item.candidate_id == id("baseline") && item.weight > FixedQ32::ZERO
            })
        );
    }
}

#[test]
fn optimization_risk_prices_still_affect_candidate_ranking() {
    let mut limits = budget(1);
    limits.risk_budget = q(100);
    limits.risk_aversion = FixedQ32::ZERO;
    let receipt = select_output_portfolio_v1(
        &context(3),
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("safer", 60, 10, false),
            candidate("higher-utility", 80, 70, false),
        ],
    )
    .expect("preference parameters are independent of hard limits");
    assert_eq!(receipt.allocations.len(), 1);
    assert_eq!(receipt.allocations[0].candidate_id, id("higher-utility"));
    assert!(receipt.total_risk <= limits.risk_budget);
}

#[test]
fn standalone_frontier_includes_covariance_and_preserves_nondominance() {
    let mut correlated = context(3);
    correlated.semantic_covariance[4] = q(40);
    let candidates = [
        candidate("baseline", 0, 0, true),
        candidate("high-upside", 80, 10, false),
        candidate("stable", 70, 20, false),
    ];
    // Ignoring the diagonal would incorrectly let high-upside dominate
    // stable: the former has 10% linear loss but 40% standalone variance.
    let points = output_efficient_frontier_v1(&correlated, &candidates)
        .expect("covariance-aware standalone frontier");
    let high = points
        .iter()
        .find(|point| point.candidate_id == id("high-upside"))
        .expect("higher-upside frontier point");
    let stable = points
        .iter()
        .find(|point| point.candidate_id == id("stable"))
        .expect("lower-variance frontier point");
    assert_eq!(
        high.semantic_risk,
        q(10).checked_add(q(40)).expect("Q32 risk")
    );
    assert_eq!(stable.semantic_risk, q(20));

    let selected = select_output_portfolio_v1(&correlated, &budget(2), &candidates)
        .expect("advisory selection");
    assert_eq!(selected.frontier, points);
}

#[test]
fn standalone_frontier_rejects_nonzero_abstain_covariance() {
    let mut malformed = context(2);
    malformed.semantic_covariance[0] = q(1);
    let error = output_efficient_frontier_v1(
        &malformed,
        &[
            candidate("baseline", 0, 0, true),
            candidate("direction", 70, 10, false),
        ],
    )
    .expect_err("no-change must remain zero relative covariance");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("no-change covariance")
    );
}

#[test]
fn standalone_frontier_denies_risk_overflow() {
    let mut correlated = context(2);
    correlated.semantic_covariance[3] = q(1);
    let mut candidate_with_max_loss = candidate("max-loss", 80, 0, false);
    candidate_with_max_loss.risk.mean_loss = FixedQ32::from_raw(i64::MAX);
    let error = output_efficient_frontier_v1(
        &correlated,
        &[candidate("baseline", 0, 0, true), candidate_with_max_loss],
    )
    .expect_err("standalone variance must be added with checked arithmetic");
    assert_eq!(error, NduError::Arithmetic);
}

#[test]
fn portfolio_rejects_cross_generation_proposals_even_with_matching_feature_bytes() {
    let mut stale = candidate("stale", 90, 0, false);
    stale.generation = Generation::new(2).expect("successor generation");
    let candidates = [candidate("baseline", 0, 0, true), stale];
    let ctx = context(2);
    let error = select_output_portfolio_v1(&ctx, &budget(2), &candidates)
        .expect_err("a matching snapshot digest cannot authorize a different generation");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("portfolio candidate generation")
    );
    assert_eq!(
        output_efficient_frontier_v1(&ctx, &candidates)
            .expect_err("frontier must validate the same provenance"),
        error
    );

    let mut mismatched_baseline = candidate("baseline", 0, 0, true);
    mismatched_baseline.generation = Generation::new(2).expect("successor generation");
    let error = select_output_portfolio_v1(
        &ctx,
        &budget(2),
        &[mismatched_baseline, candidate("fresh", 90, 0, false)],
    )
    .expect_err("the baseline also belongs to the exact generation");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("portfolio candidate generation")
    );
}

#[test]
fn portfolio_rejects_cross_encoder_proposals_even_with_matching_feature_bytes() {
    let mut wrong_encoder = candidate("wrong-encoder", 90, 0, false);
    wrong_encoder.encoder_digest = Digest32::of_bytes(b"another-encoder");
    let candidates = [candidate("baseline", 0, 0, true), wrong_encoder];
    let ctx = context(2);
    let error = select_output_portfolio_v1(&ctx, &budget(2), &candidates)
        .expect_err("an unrelated encoder cannot reuse this feature binding");
    assert_eq!(
        error,
        NduError::InvalidSolverReceipt("portfolio candidate encoder")
    );
    assert_eq!(
        output_efficient_frontier_v1(&ctx, &candidates)
            .expect_err("the standalone frontier must also reject encoder drift"),
        error
    );
}

#[test]
fn covariance_pricing_prevents_harmful_full_weight_allocation() {
    let mut correlated = context(2);
    correlated.semantic_covariance[3] = q(80);
    let receipt = select_output_portfolio_v1(
        &correlated,
        &budget(2),
        &[
            candidate("baseline", 0, 0, true),
            candidate("risky-direction", 40, 0, false),
        ],
    )
    .expect("use a covariance-priced fractional direction");
    assert_eq!(
        receipt.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    let active = receipt
        .allocations
        .iter()
        .find(|item| item.candidate_id == id("risky-direction"))
        .expect("strictly positive marginal allocation");
    assert!(active.weight >= q(24));
    assert!(active.weight <= q(26));
    assert!(receipt.total_utility > receipt.total_risk);
    assert_eq!(receipt.allocations.len(), 2);

    // A one-slot receipt cannot hide the abstain residual.
    let single_slot = select_output_portfolio_v1(
        &correlated,
        &budget(1),
        &[
            candidate("baseline", 0, 0, true),
            candidate("risky-direction", 40, 0, false),
        ],
    )
    .expect("no slot to represent a positive and a baseline arm");
    assert_eq!(
        single_slot.disposition,
        OutputPortfolioDispositionV1::NoChange
    );
}

#[test]
fn positive_individual_scores_cannot_hide_negative_correlation_gain() {
    let mut correlated = context(3);
    // Candidate b looks profitable alone but is redundant against candidate a.
    // This is symmetric diagonally dominant and therefore PSD.
    correlated.semantic_covariance[4] = q(50);
    correlated.semantic_covariance[5] = q(50);
    correlated.semantic_covariance[7] = q(50);
    correlated.semantic_covariance[8] = q(50);
    let mut first = candidate("a", 50, 5, false);
    let mut second = candidate("b", 50, 5, false);
    first.weight_cap = q(50);
    second.weight_cap = q(50);
    let receipt = select_output_portfolio_v1(
        &correlated,
        &budget(3),
        &[candidate("baseline", 0, 0, true), first, second],
    )
    .expect("prefer positive portfolio marginal utility");
    assert!(
        receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("a"))
    );
    assert!(
        !receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("b"))
    );
    assert!(
        receipt
            .allocations
            .iter()
            .any(|item| item.candidate_id == id("baseline"))
    );
    assert!(receipt.total_utility > receipt.total_risk);
}

#[test]
fn fixed_switch_cost_cannot_be_amortized_by_fractional_weight() {
    let mut limits = budget(2);
    limits.switch_penalty = q(30);
    let mut partial = candidate("partial-switch", 80, 0, false);
    partial.weight_cap = q(10);
    let denied = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[candidate("baseline", 0, 0, true), partial],
    )
    .expect("risk-free baseline remains feasible");
    assert_eq!(denied.disposition, OutputPortfolioDispositionV1::NoChange);
    assert_eq!(denied.allocations.len(), 1);

    // The same fixed charge is affordable when the full positive gain
    // is realized by a whole candidate, not diluted across a small share.
    let admitted = select_output_portfolio_v1(
        &context(2),
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("whole-switch", 80, 0, false),
        ],
    )
    .expect("full-weight admission");
    assert_eq!(
        admitted.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    assert_eq!(admitted.allocations.len(), 1);
    assert_eq!(admitted.allocations[0].weight, FixedQ32::ONE);
}

#[test]
fn covariance_pricing_does_not_hide_fixed_switch_cost() {
    let mut limits = budget(2);
    limits.switch_penalty = q(45);
    let mut measured = context(2);
    measured.semantic_covariance[3] = q(50);
    // Gross utility 0.8*w minus 0.5*w^2 peaks at w=0.8:
    // the maximum gross gain is 0.32, below the fixed 0.45 cost.
    let receipt = select_output_portfolio_v1(
        &measured,
        &limits,
        &[
            candidate("baseline", 0, 0, true),
            candidate("covariant-switch", 80, 0, false),
        ],
    )
    .expect("negative net gain selects no change");
    assert_eq!(receipt.disposition, OutputPortfolioDispositionV1::NoChange);
    assert_eq!(receipt.total_risk, FixedQ32::ZERO);
}

#[test]
fn receipt_integrity_replay_rejects_tampered_fields() {
    let source = [
        candidate("baseline", 0, 0, true),
        candidate("direction", 80, 1, false),
    ];
    let state = context(source.len());
    let limits = budget(2);
    let receipt = select_output_portfolio_v1(&state, &limits, &source)
        .expect("deterministic advisory receipt");
    assert_eq!(
        receipt.disposition,
        OutputPortfolioDispositionV1::AdvisorySelection
    );
    verify_output_portfolio_receipt_v1(&state, &limits, &source, &receipt)
        .expect("untampered receipt must replay exactly");

    let mut tampered_resource = receipt.clone();
    tampered_resource.total_resource = FixedQ32::ZERO;
    let mut tampered_latency = receipt.clone();
    tampered_latency.total_latency = FixedQ32::ZERO;
    let mut tampered_disposition = receipt.clone();
    tampered_disposition.disposition = OutputPortfolioDispositionV1::NoChange;
    let mut tampered_frontier = receipt.clone();
    tampered_frontier.frontier.clear();
    let mut tampered_allocation = receipt.clone();
    tampered_allocation.allocations[0].weight = FixedQ32::ZERO;
    let mut tampered_digest = receipt.clone();
    tampered_digest.selection_digest = Digest32::ZERO;

    for forged in [
        tampered_resource,
        tampered_latency,
        tampered_disposition,
        tampered_frontier,
        tampered_allocation,
        tampered_digest,
    ] {
        assert_eq!(
            verify_output_portfolio_receipt_v1(&state, &limits, &source, &forged)
                .expect_err("a forged advisory receipt must fail closed"),
            NduError::InvalidSolverReceipt("portfolio receipt replay mismatch")
        );
    }
}

#[test]
fn selection_digest_binds_every_displayed_advisory_component() {
    let source = [
        candidate("baseline", 0, 0, true),
        candidate("direction", 80, 1, false),
    ];
    let state = context(source.len());
    let limits = budget(2);
    let receipt = select_output_portfolio_v1(&state, &limits, &source)
        .expect("deterministic advisory receipt");
    let canonical = canonical_candidates(&state, &source).expect("canonical candidates");
    let covariance =
        canonical_covariance(&state, &source, &canonical).expect("canonical covariance");
    let fingerprint = |disposition: OutputPortfolioDispositionV1,
                       frontier: &[OutputPortfolioFrontierPointV1],
                       resource: FixedQ32,
                       latency: FixedQ32| {
        digest_selection(
            &state,
            &limits,
            &canonical,
            &covariance,
            &receipt.allocations,
            disposition,
            frontier,
            receipt.total_risk,
            receipt.total_utility,
            resource,
            latency,
        )
    };
    let original = fingerprint(
        receipt.disposition,
        &receipt.frontier,
        receipt.total_resource,
        receipt.total_latency,
    );
    assert_eq!(original, receipt.selection_digest);
    assert_ne!(
        original,
        fingerprint(
            OutputPortfolioDispositionV1::NoChange,
            &receipt.frontier,
            receipt.total_resource,
            receipt.total_latency,
        )
    );
    assert_ne!(
        original,
        fingerprint(
            receipt.disposition,
            &[],
            receipt.total_resource,
            receipt.total_latency,
        )
    );
    assert_ne!(
        original,
        fingerprint(
            receipt.disposition,
            &receipt.frontier,
            FixedQ32::ZERO,
            receipt.total_latency,
        )
    );
    assert_ne!(
        original,
        fingerprint(
            receipt.disposition,
            &receipt.frontier,
            receipt.total_resource,
            FixedQ32::ZERO,
        )
    );
}

#[test]
fn objective_bound_candidate_rejects_cross_objective_replay() {
    let state = context(2);
    let limits = budget(2);
    let mut foreign = candidate("same-feature-different-objective", 90, 0, false);
    foreign.objective_digest = Digest32::of_bytes(b"foreign-objective");
    let candidates = [candidate("baseline", 0, 0, true), foreign];
    assert_eq!(
        select_output_portfolio_v1(&state, &limits, &candidates)
            .expect_err("a Cell utility estimate belongs to exactly one objective"),
        NduError::InvalidSolverReceipt("portfolio candidate objective")
    );
    assert_eq!(
        output_efficient_frontier_v1(&state, &candidates)
            .expect_err("a frontier cannot contain cross-objective utility estimates"),
        NduError::InvalidSolverReceipt("portfolio candidate objective")
    );

    let mut changed_context = state;
    changed_context.objective_digest = Digest32::of_bytes(b"foreign-objective");
    assert_eq!(
        select_output_portfolio_v1(&changed_context, &limits, &candidates)
            .expect_err("switching the objective must not make the original baseline valid"),
        NduError::InvalidSolverReceipt("portfolio candidate objective")
    );
}
