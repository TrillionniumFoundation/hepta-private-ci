//! Registered prompt-optimization policy surface.
//!
//! The types in this module mirror the public V1 prompt receipts registered in
//! `docs/contracts/PROTOCOL_SCHEMAS.json`. The public receipt structs contain
//! only registered semantic fields. Richer diagnostics live in companion audit
//! structs so the wire contract is not silently widened.
//!
//! This module is authority-free. It validates and binds caller-supplied source
//! evidence, performs deterministic pricing and bounded portfolio selection, and
//! emits exercise decisions at registered boundaries. It does not authenticate
//! remote owners, mutate the prompt registry or objective, dispatch a model, or
//! activate an intervention by itself.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub const MAX_POLICY_FACTORS: usize = 128;
pub const MAX_POLICY_SELECTED_FACTORS: usize = 16;
pub const MAX_POLICY_INTERACTION_EDGES: usize = 512;
pub const MAX_POLICY_HARD_CONSTRAINTS: usize = 512;
pub const MAX_POLICY_ENUMERATION_INPUT: usize = 4_096;
pub const MAX_POLICY_TOKEN_BUDGET: u32 = 1_000_000;
pub const MAX_POLICY_MARGINAL_STEPS: usize = 128;
const PPM_ONE: u32 = 1_000_000;

include!("policy_contracts.rs");
include!("policy_enumeration_pricing.rs");
include!("policy_portfolio.rs");
include!("policy_exercise_helpers.rs");
include!("policy_portfolio_helpers.rs");
include!("policy_digest.rs");

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        let Ok(value) = StableId::new(value) else {
            panic!("test identifier must be valid");
        };
        value
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn model_profile() -> PromptModelProfileV1 {
        PromptModelProfileV1 {
            profile_digest: digest("model-profile"),
            tokenizer_digest: digest("tokenizer"),
            system_template_digest: digest("system-template"),
            tool_schema_digest: digest("tool-schema"),
            context_profile_digest: digest("context-profile"),
        }
    }

    fn objective() -> PromptObjectiveContextV1 {
        PromptObjectiveContextV1 {
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            selection_grammar_digest: digest("selection-grammar"),
        }
    }

    fn factor_snapshot(index: usize) -> PromptFactorSnapshotV1 {
        PromptFactorSnapshotV1 {
            factor_id: id(&format!("factor:{index:03}")),
            realization_id: id(&format!("realization:{index:03}")),
            admitted: true,
            legal: true,
            objective_scope_digest: None,
            model_profile_digest: None,
            realization_context_digest: digest(&format!("realization-context:{index:03}")),
            token_upper_bound: 32,
            support_reference_digest: digest(&format!("factor-support:{index:03}")),
        }
    }

    fn candidate_receipt(factor_ids: Vec<StableId>) -> PromptCandidateSetReceiptV1 {
        PromptCandidateSetReceiptV1 {
            set_id: id("candidate-set:test"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            registry_digest: digest("registry"),
            candidate_factor_ids: factor_ids,
            selection_grammar_digest: digest("selection-grammar"),
        }
    }

    fn confidence() -> PromptConfidenceIntervalV1 {
        PromptConfidenceIntervalV1 {
            lower_q32: FixedQ32::from_raw(80),
            upper_q32: FixedQ32::from_raw(120),
            confidence_ppm: 900_000,
            support_digest: digest("confidence-support"),
            scope_digest: digest("confidence-scope"),
        }
    }

    fn price(factor: &str, gain: i64, token_cost: u32) -> PromptPricingReceiptV1 {
        PromptPricingReceiptV1 {
            factor_id: id(factor),
            state_digest: digest("state"),
            expected_utility_q32: FixedQ32::from_raw(gain),
            downside_q32: FixedQ32::ZERO,
            token_cost,
            latency_cost_micros: 10,
            interference_ppm: 0,
            confidence_interval: confidence(),
        }
    }

    fn pricing_batch(
        candidate_set_digest: Digest32,
        prices: Vec<PromptPricingReceiptV1>,
    ) -> PromptPricingBatchV1 {
        PromptPricingBatchV1 {
            candidate_set_digest,
            complete_eligible_set_digest: digest("complete-set"),
            omitted_count: 0,
            model_profile_digest: digest("model-profile"),
            receipts: prices,
            audit_entries: Vec::new(),
            unavailable: Vec::new(),
            batch_digest: digest("pricing-batch"),
        }
    }

    fn graph(
        factor_ids: Vec<StableId>,
        constraints: Vec<PromptHardConstraintV1>,
    ) -> PromptInteractionGraphV1 {
        PromptInteractionGraphV1 {
            candidate_set_digest: digest("candidate-set"),
            candidate_factor_ids: factor_ids,
            missing_interaction_policy: PromptMissingInteractionPolicyV1::AssumeZero,
            edges: Vec::new(),
            hard_constraints: constraints,
            source_evidence_digest: digest("interaction-source"),
        }
    }

    fn budget(maximum_selected_factors: usize, token_budget: u32) -> PromptPortfolioBudgetV1 {
        PromptPortfolioBudgetV1 {
            portfolio_id: id("portfolio:test"),
            token_budget,
            maximum_selected_factors,
            valid_until_unix_ms: 10_000,
        }
    }

    #[test]
    fn enumeration_is_bounded_and_records_omitted_count_and_complete_set_digest() {
        let registry = PromptRegistrySnapshotV1 {
            registry_digest: digest("registry"),
            source_evidence_digest: digest("registry-source"),
            factors: (0..130).map(factor_snapshot).collect(),
        };
        let result = enumerate_factors_audited(&registry, &objective(), &model_profile())
            .unwrap_or_else(|error| panic!("enumeration failed: {error}"));

        assert_eq!(result.receipt.candidate_factor_ids.len(), 128);
        assert_eq!(result.audit.eligible_before_truncation, 130);
        assert_eq!(result.audit.retained_count, 128);
        assert_eq!(result.audit.omitted_count, 2);
        assert!(!result.audit.complete_eligible_set_digest.is_zero());
        assert!(!result.audit.audit_digest.is_zero());
        assert!(!result.receipt.authority().grants_any());
    }

    #[test]
    fn pricing_computes_causal_utility_minus_all_registered_cost_components() {
        let candidates = candidate_receipt(vec![id("factor:000")]);
        let candidate_set_digest = digest_candidate_set_receipt(&candidates);
        let estimates = vec![PromptCausalEstimateV1 {
            factor_id: id("factor:000"),
            candidate_set_digest,
            registry_digest: candidates.registry_digest,
            state_digest: candidates.state_digest,
            model_profile_digest: digest("model-profile"),
            realization_context_digest: digest("realization-context"),
            incremental_recursive_utility_q32: FixedQ32::from_raw(100),
            downside_q32: FixedQ32::from_raw(5),
            confidence_interval: confidence(),
            causal_support_digest: digest("causal-support"),
        }];
        let costs = vec![PromptFactorCostV1 {
            factor_id: id("factor:000"),
            token_cost: 7,
            latency_cost_micros: 50,
            interference_ppm: 25_000,
            token_utility_cost_q32: FixedQ32::from_raw(1),
            latency_utility_cost_q32: FixedQ32::from_raw(1),
            context_crowding_cost_q32: FixedQ32::from_raw(1),
            instruction_interference_cost_q32: FixedQ32::from_raw(1),
            privacy_cost_q32: FixedQ32::from_raw(1),
            instability_cost_q32: FixedQ32::from_raw(1),
            future_context_option_value_cost_q32: FixedQ32::from_raw(1),
            resource_cost_q32: FixedQ32::from_raw(1),
            cost_support_digest: digest("cost-support"),
        }];

        let priced = price_factors(&candidates, &estimates, &costs)
            .unwrap_or_else(|error| panic!("pricing failed: {error}"));
        assert_eq!(priced.len(), 1);
        assert_eq!(priced[0].expected_utility_q32, FixedQ32::from_raw(92));
        assert_eq!(priced[0].token_cost, 7);
        assert!(!priced[0].authority().grants_any());
    }

    #[test]
    fn audited_pricing_marks_model_or_realization_drift_unavailable() {
        let registry = PromptRegistrySnapshotV1 {
            registry_digest: digest("registry"),
            source_evidence_digest: digest("registry-source"),
            factors: vec![factor_snapshot(0)],
        };
        let candidates = enumerate_factors_audited(&registry, &objective(), &model_profile())
            .unwrap_or_else(|error| panic!("enumeration failed: {error}"));
        let estimates = vec![PromptCausalEstimateV1 {
            factor_id: id("factor:000"),
            candidate_set_digest: candidates.audit.candidate_set_digest,
            registry_digest: candidates.receipt.registry_digest,
            state_digest: candidates.receipt.state_digest,
            model_profile_digest: digest("wrong-model-profile"),
            realization_context_digest: candidates.audit.bindings[0].realization_context_digest,
            incremental_recursive_utility_q32: FixedQ32::from_raw(100),
            downside_q32: FixedQ32::ZERO,
            confidence_interval: confidence(),
            causal_support_digest: digest("causal-support"),
        }];
        let costs = vec![PromptFactorCostV1 {
            factor_id: id("factor:000"),
            token_cost: 1,
            latency_cost_micros: 0,
            interference_ppm: 0,
            token_utility_cost_q32: FixedQ32::ZERO,
            latency_utility_cost_q32: FixedQ32::ZERO,
            context_crowding_cost_q32: FixedQ32::ZERO,
            instruction_interference_cost_q32: FixedQ32::ZERO,
            privacy_cost_q32: FixedQ32::ZERO,
            instability_cost_q32: FixedQ32::ZERO,
            future_context_option_value_cost_q32: FixedQ32::ZERO,
            resource_cost_q32: FixedQ32::ZERO,
            cost_support_digest: digest("cost-support"),
        }];

        let priced = price_factors_audited(&candidates, &estimates, &costs)
            .unwrap_or_else(|error| panic!("audited pricing failed: {error}"));
        assert!(priced.receipts.is_empty());
        assert_eq!(
            priced.unavailable,
            vec![PromptUnavailablePricingV1 {
                factor_id: id("factor:000"),
                reason: PromptPricingUnavailableReasonV1::EvidenceBindingMismatch,
            }]
        );
    }

    #[test]
    fn sparse_interaction_policy_supports_128_factors_with_multi_select() {
        let factor_ids = (0..128)
            .map(|index| id(&format!("factor:{index:03}")))
            .collect::<Vec<_>>();
        let prices = factor_ids
            .iter()
            .map(|factor_id| price(factor_id.as_str(), 10, 1))
            .collect::<Vec<_>>();
        let graph = graph(factor_ids, Vec::new());
        let pricing = pricing_batch(graph.candidate_set_digest, prices);
        let result = select_portfolio_audited(&pricing, &graph, &budget(16, 16))
            .unwrap_or_else(|error| panic!("portfolio selection failed: {error}"));

        assert_eq!(result.receipt.factor_ids.len(), 16);
        assert_eq!(result.receipt.factor_ids[0], id("factor:000"));
        assert_eq!(result.receipt.factor_ids[15], id("factor:015"));
        assert_eq!(
            result.audit.optimality,
            PromptOptimalityDisclosureV1::HeuristicNoCertificate
        );
    }

    #[test]
    fn prerequisite_closure_selects_negative_prerequisite_when_bundle_is_positive() {
        let factor_ids = vec![id("factor:000"), id("factor:001")];
        let constraints = vec![PromptHardConstraintV1::Requires {
            factor_id: id("factor:000"),
            prerequisite_factor_id: id("factor:001"),
            support_reference_digest: digest("requires-support"),
        }];
        let graph = graph(factor_ids, constraints);
        let pricing = pricing_batch(
            graph.candidate_set_digest,
            vec![price("factor:000", 100, 1), price("factor:001", -1, 1)],
        );
        let result = select_portfolio_audited(&pricing, &graph, &budget(2, 2))
            .unwrap_or_else(|error| panic!("portfolio selection failed: {error}"));

        assert_eq!(
            result.receipt.factor_ids,
            vec![id("factor:001"), id("factor:000")]
        );
        assert_eq!(result.receipt.expected_utility_q32, FixedQ32::from_raw(99));
    }

    #[test]
    fn requires_cycle_is_rejected_as_structural_constraint_error() {
        let factor_ids = vec![id("factor:000"), id("factor:001")];
        let constraints = vec![
            PromptHardConstraintV1::Requires {
                factor_id: id("factor:000"),
                prerequisite_factor_id: id("factor:001"),
                support_reference_digest: digest("requires-0-1"),
            },
            PromptHardConstraintV1::Requires {
                factor_id: id("factor:001"),
                prerequisite_factor_id: id("factor:000"),
                support_reference_digest: digest("requires-1-0"),
            },
        ];
        let graph = graph(factor_ids, constraints);
        let pricing = pricing_batch(
            graph.candidate_set_digest,
            vec![price("factor:000", 10, 1), price("factor:001", 10, 1)],
        );
        let result = select_portfolio_audited(&pricing, &graph, &budget(2, 2));
        assert!(matches!(result, Err(PolicyError::RequiresCycle(_))));
    }

    #[test]
    fn conflict_inside_transitive_requires_closure_is_rejected_as_unsatisfiable() {
        let factor_ids = vec![id("factor:000"), id("factor:001")];
        let constraints = vec![
            PromptHardConstraintV1::Conflict {
                left_factor_id: id("factor:000"),
                right_factor_id: id("factor:001"),
                support_reference_digest: digest("conflict-support"),
            },
            PromptHardConstraintV1::Requires {
                factor_id: id("factor:000"),
                prerequisite_factor_id: id("factor:001"),
                support_reference_digest: digest("requires-support"),
            },
        ];
        let graph = graph(factor_ids, constraints);
        let pricing = pricing_batch(
            graph.candidate_set_digest,
            vec![price("factor:000", 10, 1), price("factor:001", 10, 1)],
        );
        let result = select_portfolio_audited(&pricing, &graph, &budget(2, 2));
        assert_eq!(
            result,
            Err(PolicyError::UnsatisfiableConstraintGraph(
                "factor:000".to_string()
            ))
        );
    }

    #[test]
    fn portfolio_audit_records_per_candidate_rejection_reasons() {
        let factor_ids = vec![id("factor:000"), id("factor:001"), id("factor:002")];
        let graph = graph(factor_ids, Vec::new());
        let pricing = PromptPricingBatchV1 {
            candidate_set_digest: graph.candidate_set_digest,
            complete_eligible_set_digest: digest("complete-set"),
            omitted_count: 7,
            model_profile_digest: digest("model-profile"),
            receipts: vec![price("factor:000", 10, 1), price("factor:001", -5, 1)],
            audit_entries: Vec::new(),
            unavailable: vec![PromptUnavailablePricingV1 {
                factor_id: id("factor:002"),
                reason: PromptPricingUnavailableReasonV1::MissingCausalEstimate,
            }],
            batch_digest: digest("pricing-batch"),
        };
        let result = select_portfolio_audited(&pricing, &graph, &budget(2, 2))
            .unwrap_or_else(|error| panic!("portfolio selection failed: {error}"));

        assert_eq!(result.audit.omitted_count, 7);
        assert_eq!(result.audit.unavailable_pricing_count, 1);
        assert_eq!(
            result.audit.candidate_decisions,
            vec![
                PromptPortfolioCandidateAuditV1 {
                    factor_id: id("factor:000"),
                    disposition: PromptPortfolioDispositionV1::Selected,
                },
                PromptPortfolioCandidateAuditV1 {
                    factor_id: id("factor:001"),
                    disposition: PromptPortfolioDispositionV1::NonPositivePackageUtility,
                },
                PromptPortfolioCandidateAuditV1 {
                    factor_id: id("factor:002"),
                    disposition: PromptPortfolioDispositionV1::UnavailablePricing,
                },
            ]
        );
        assert!(result.audit.requires_registered_exercise_boundary);
        assert!(!result.audit.audit_digest.is_zero());
    }

    #[test]
    fn exercise_requires_exact_registered_boundary_state_registry_model_and_expiry() {
        let portfolio = PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:test"),
            candidate_set_digest: digest("candidate-set"),
            factor_ids: vec![id("factor:000")],
            interaction_digest: digest("interaction"),
            expected_utility_q32: FixedQ32::from_raw(10),
            total_token_upper_bound: 1,
            valid_until_unix_ms: 100,
        };
        let boundary = RegisteredPromptBoundaryV1 {
            decision_boundary: PromptDecisionBoundaryV1::BeforeFinalResponse,
            portfolio_digest: digest_portfolio_receipt(&portfolio),
            candidate_set_digest: portfolio.candidate_set_digest,
            registry_digest: digest("registry"),
            model_profile_digest: digest("model-profile"),
            registered_state_digest: digest("state"),
            policy_digest: digest("exercise-policy"),
            boundary_support_digest: digest("boundary-support"),
        };
        let state = PromptExerciseStateV1 {
            state_digest: digest("state"),
            registry_digest: digest("registry"),
            model_profile_digest: digest("model-profile"),
            observed_at_unix_ms: 99,
            wait_value_q32: FixedQ32::from_raw(5),
        };
        let decision = exercise(&portfolio, &boundary, &state)
            .unwrap_or_else(|error| panic!("exercise failed: {error}"));
        assert_eq!(decision.decision, PromptExerciseChoiceV1::Exercise);
        assert!(!decision.authority().grants_any());

        let mut drifted = state;
        drifted.state_digest = digest("new-state");
        assert_eq!(
            exercise(&portfolio, &boundary, &drifted),
            Err(PolicyError::StateDrift)
        );
    }
}
