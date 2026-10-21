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
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
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
