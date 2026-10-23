use std::fmt::Debug;

use pretty_assertions::assert_eq;

use super::*;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn subject() -> GroupNduSubjectV1 {
    GroupNduSubjectV1 {
        subject_id: "domain:demo".to_owned(),
        subject_class: GroupSubjectClassV1::Domain,
        group_id: "group:demo".to_owned(),
        generation: 1,
        objective_digest: digest("objective"),
        encoder_digest: digest("encoder"),
        utility_profile_digest: digest("utility"),
        resource_ceiling_micros: 100,
    }
}

fn candidate_fixtures() -> Vec<GroupContinuationCandidateV1> {
    vec![
        GroupContinuationCandidateV1 {
            candidate_id: "continue".to_owned(),
            current_value_q32: 10,
            continuation_value_q32: 30,
            cost_q32: 2,
            risk_q32: 1,
            legal: true,
            abstain: false,
        },
        GroupContinuationCandidateV1 {
            candidate_id: "abstain".to_owned(),
            current_value_q32: 10,
            continuation_value_q32: 10,
            cost_q32: 0,
            risk_q32: 0,
            legal: true,
            abstain: true,
        },
    ]
}

fn make_trace(
    subject: &GroupNduSubjectV1,
    candidates: &[GroupContinuationCandidateV1],
) -> GroupDecisionTraceV1 {
    GroupDecisionTraceV1 {
        run_id: "run:demo".to_owned(),
        subject_id: subject.subject_id.clone(),
        subject_binding_digest: canonical_group_subject_binding_digest_v1(subject),
        input_digest: digest("input"),
        generation: subject.generation,
        route_digest: digest("route"),
        complete_candidate_set_digest: must(group_candidate_set_digest(candidates)),
        behavior_digest: digest("behavior"),
        terminal_outcome_digest: digest("terminal"),
        cells: vec![GroupCellObservationV1 {
            cell_id: "cell:0".to_owned(),
            head_digest: digest("head"),
            action_digest: digest("action"),
            evidence_digest: digest("evidence"),
            value_q32: 20,
            cost_micros: 5,
            uncertainty_q32: 1,
            abstain: false,
        }],
    }
}

#[test]
fn positive_continuation_is_selected() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let result = must(decide_group_continuation_v1(
        &subject,
        &make_trace(&subject, &candidates),
        &candidates,
    ));
    assert_eq!(result.selected_candidate_id, "continue");
    assert_eq!(result.net_value_q32, 17);
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn non_positive_continuation_abstains() {
    let subject = subject();
    let mut candidates = candidate_fixtures();
    candidates[0].continuation_value_q32 = 10;
    let result = must(decide_group_continuation_v1(
        &subject,
        &make_trace(&subject, &candidates),
        &candidates,
    ));
    assert_eq!(result.selected_candidate_id, "abstain");
}

#[test]
fn legal_abstain_with_higher_net_prevents_worse_positive_continuation() {
    let subject = subject();
    let mut candidates = candidate_fixtures();
    // Continuation has +17, but legal abstention has +40 in this
    // candidate set. Positive net alone must not override abstention.
    candidates[1].continuation_value_q32 = 50;
    let result = must(decide_group_continuation_v1(
        &subject,
        &make_trace(&subject, &candidates),
        &candidates,
    ));
    assert_eq!(result.selected_candidate_id, "abstain");
    assert_eq!(result.net_value_q32, 40);
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn equal_net_preference_fails_closed_to_abstain() {
    let subject = subject();
    let mut candidates = candidate_fixtures();
    candidates[1].continuation_value_q32 = 27;
    let result = must(decide_group_continuation_v1(
        &subject,
        &make_trace(&subject, &candidates),
        &candidates,
    ));
    assert_eq!(result.selected_candidate_id, "abstain");
    assert_eq!(result.net_value_q32, 17);
}

#[test]
fn malformed_abstain_net_cannot_hide_behind_positive_continuation() {
    let subject = subject();
    let mut candidates = candidate_fixtures();
    // This i128 net cannot be represented in the Q32 i64 contract.
    // Old selection did not evaluate abstain when continuation won.
    candidates[1].current_value_q32 = i64::MIN;
    candidates[1].continuation_value_q32 = i64::MAX;
    assert_eq!(
        decide_group_continuation_v1(&subject, &make_trace(&subject, &candidates), &candidates,),
        Err(GroupSystem2Error::ArithmeticOverflow)
    );
}

#[test]
fn exhausted_resource_budget_abstains_with_positive_net() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let mut trace = make_trace(&subject, &candidates);
    trace.cells[0].cost_micros = subject.resource_ceiling_micros;
    let result = must(decide_group_continuation_v1(&subject, &trace, &candidates));
    assert_eq!(result.selected_candidate_id, "abstain");
    assert_eq!(result.net_value_q32, 0);
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);

    // With a nonzero remaining balance, the existing positive-net baseline
    // remains advisory; an execution owner must still reserve actual work.
    trace.cells[0].cost_micros = subject.resource_ceiling_micros - 1;
    let still_possible = must(decide_group_continuation_v1(&subject, &trace, &candidates));
    assert_eq!(still_possible.selected_candidate_id, "continue");

    trace.cells[0].cost_micros = subject.resource_ceiling_micros + 1;
    assert_eq!(
        decide_group_continuation_v1(&subject, &trace, &candidates),
        Err(GroupSystem2Error::ResourceCeilingExceeded {
            used: subject.resource_ceiling_micros + 1,
            ceiling: subject.resource_ceiling_micros,
        })
    );
}

#[test]
fn exhausted_budget_is_aggregated_across_distinct_cells() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let mut trace = make_trace(&subject, &candidates);
    trace.cells[0].cost_micros = 80;
    let mut second = trace.cells[0].clone();
    second.cell_id = "cell:1".to_owned();
    second.cost_micros = 20;
    trace.cells.push(second);

    let decision = must(decide_group_continuation_v1(&subject, &trace, &candidates));
    assert_eq!(decision.selected_candidate_id, "abstain");
    assert_eq!(decision.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn candidate_set_digest_is_bound_and_deterministic() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let first = make_trace(&subject, &candidates);
    let second = make_trace(&subject, &candidates);
    assert_eq!(
        must(decide_group_continuation_v1(&subject, &first, &candidates)).trace_digest,
        must(decide_group_continuation_v1(&subject, &second, &candidates)).trace_digest
    );
    let mut reordered = candidates.clone();
    reordered.reverse();
    assert_ne!(
        must(group_candidate_set_digest(&candidates)),
        must(group_candidate_set_digest(&reordered))
    );
}

#[test]
fn missing_abstain_and_zero_digest_fail_closed() {
    let subject = subject();
    let mut candidates = candidate_fixtures();
    candidates.pop();
    let missing_trace = make_trace(&subject, &candidates);
    assert_eq!(
        decide_group_continuation_v1(&subject, &missing_trace, &candidates),
        Err(GroupSystem2Error::MissingAbstainCandidate)
    );

    let mut invalid_subject = subject;
    invalid_subject.encoder_digest = Digest32::ZERO;
    let candidates = candidate_fixtures();
    assert_eq!(
        decide_group_continuation_v1(
            &invalid_subject,
            &make_trace(&invalid_subject, &candidates),
            &candidates
        ),
        Err(GroupSystem2Error::ZeroDigest("encoder_digest"))
    );
}

#[test]
fn duplicate_cell_observations_fail_closed() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let mut trace = make_trace(&subject, &candidates);
    trace.cells.push(trace.cells[0].clone());

    assert_eq!(
        decide_group_continuation_v1(&subject, &trace, &candidates),
        Err(GroupSystem2Error::DuplicateCellId("cell:0".to_owned()))
    );
}

#[test]
fn same_generation_cross_group_or_encoder_trace_is_rejected() {
    let original = subject();
    let candidates = candidate_fixtures();
    let trace = make_trace(&original, &candidates);
    let expected = Err(GroupSystem2Error::TraceBindingMismatch(
        "subject_binding_digest",
    ));

    let mut changed = original.clone();
    changed.group_id = "group:other".to_owned();
    assert_eq!(
        decide_group_continuation_v1(&changed, &trace, &candidates),
        expected
    );

    let mut changed = original.clone();
    changed.encoder_digest = digest("other-encoder");
    assert_eq!(
        decide_group_continuation_v1(&changed, &trace, &candidates),
        expected
    );

    let mut changed = original.clone();
    changed.objective_digest = digest("other-objective");
    assert_eq!(
        decide_group_continuation_v1(&changed, &trace, &candidates),
        expected
    );

    let mut changed = original.clone();
    changed.utility_profile_digest = digest("other-profile");
    assert_eq!(
        decide_group_continuation_v1(&changed, &trace, &candidates),
        expected
    );

    let mut changed = original.clone();
    changed.subject_class = GroupSubjectClassV1::Agent;
    assert_eq!(
        decide_group_continuation_v1(&changed, &trace, &candidates),
        expected
    );

    let mut changed = original;
    changed.resource_ceiling_micros += 1;
    assert_eq!(
        decide_group_continuation_v1(&changed, &trace, &candidates),
        expected
    );
}

#[test]
fn valid_owner_trace_is_replayable_but_missing_binding_is_rejected() {
    let owner = subject();
    let candidates = candidate_fixtures();
    let mut trace = make_trace(&owner, &candidates);
    let first = must(decide_group_continuation_v1(&owner, &trace, &candidates));
    assert_eq!(first.selected_candidate_id, "continue");
    trace.subject_binding_digest = Digest32::ZERO;
    assert_eq!(
        decide_group_continuation_v1(&owner, &trace, &candidates),
        Err(GroupSystem2Error::TraceBindingMismatch(
            "subject_binding_digest",
        ))
    );
}

#[test]
fn trace_identity_and_generation_mismatch_fail_closed() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let mut trace = make_trace(&subject, &candidates);

    trace.subject_id = "domain:other".to_owned();
    assert_eq!(
        decide_group_continuation_v1(&subject, &trace, &candidates),
        Err(GroupSystem2Error::TraceBindingMismatch("subject_id"))
    );

    trace.subject_id = subject.subject_id.clone();
    trace.generation += 1;
    assert_eq!(
        decide_group_continuation_v1(&subject, &trace, &candidates),
        Err(GroupSystem2Error::TraceBindingMismatch("generation"))
    );
}

#[test]
fn stable_group_ids_reject_control_and_noncanonical_tokens() {
    for invalid in [
        "bad\nline",
        "bad\tfield",
        "bad/route",
        "bad id",
        "bad\u{202e}",
    ] {
        let candidates = candidate_fixtures();

        let mut invalid_subject = subject();
        invalid_subject.subject_id = invalid.to_owned();
        assert_eq!(
            decide_group_continuation_v1(
                &invalid_subject,
                &make_trace(&invalid_subject, &candidates),
                &candidates,
            ),
            Err(GroupSystem2Error::InvalidId("subject_id"))
        );

        let mut invalid_subject = subject();
        invalid_subject.group_id = invalid.to_owned();
        assert_eq!(
            decide_group_continuation_v1(
                &invalid_subject,
                &make_trace(&invalid_subject, &candidates),
                &candidates,
            ),
            Err(GroupSystem2Error::InvalidId("group_id"))
        );

        let valid_subject = subject();
        let mut invalid_trace = make_trace(&valid_subject, &candidates);
        invalid_trace.run_id = invalid.to_owned();
        assert_eq!(
            decide_group_continuation_v1(&valid_subject, &invalid_trace, &candidates),
            Err(GroupSystem2Error::InvalidId("run_id"))
        );

        let mut invalid_trace = make_trace(&valid_subject, &candidates);
        invalid_trace.cells[0].cell_id = invalid.to_owned();
        assert_eq!(
            decide_group_continuation_v1(&valid_subject, &invalid_trace, &candidates),
            Err(GroupSystem2Error::InvalidId("cell_id"))
        );

        let mut invalid_candidates = candidates.clone();
        invalid_candidates[0].candidate_id = invalid.to_owned();
        assert_eq!(
            decide_group_continuation_v1(
                &valid_subject,
                &make_trace(&valid_subject, &candidates),
                &invalid_candidates,
            ),
            Err(GroupSystem2Error::InvalidId("candidate_id"))
        );
    }
}

#[test]
fn budget_preflight_recomputes_exact_selected_trace_and_quotes_remaining() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let trace = make_trace(&subject, &candidates);
    let decision = must(decide_group_continuation_v1(&subject, &trace, &candidates));

    // Five microseconds were actually observed; a future quoted invocation
    // must fit within the remaining 95, independent of its Q32 utility cost.
    let first = must(preflight_group_future_cost_v1(
        &subject,
        &trace,
        &candidates,
        &decision,
        95,
    ));
    let again = must(preflight_group_future_cost_v1(
        &subject,
        &trace,
        &candidates,
        &decision,
        95,
    ));
    assert_eq!(first, again);
    assert_eq!(first.selected_candidate_id, "continue");
    assert_eq!(first.requested_future_micros, 95);
    assert_eq!(first.remaining_micros, 95);
    assert_eq!(first.authority, AuthorityPosture::DENY_ALL);

    let smaller = must(preflight_group_future_cost_v1(
        &subject,
        &trace,
        &candidates,
        &decision,
        94,
    ));
    assert_ne!(first.preflight_digest, smaller.preflight_digest);
    assert_eq!(smaller.remaining_micros, first.remaining_micros);
}

#[test]
fn budget_preflight_rejects_forged_selection_and_mismatched_trace() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let trace = make_trace(&subject, &candidates);
    let decision = must(decide_group_continuation_v1(&subject, &trace, &candidates));

    let mut forged = decision.clone();
    forged.selected_candidate_id = "abstain".to_owned();
    assert_eq!(
        preflight_group_future_cost_v1(&subject, &trace, &candidates, &forged, 1),
        Err(GroupSystem2Error::DecisionMismatch)
    );

    let mut altered = trace.clone();
    altered.behavior_digest = digest("new-behavior");
    assert_eq!(
        preflight_group_future_cost_v1(&subject, &altered, &candidates, &decision, 1),
        Err(GroupSystem2Error::DecisionMismatch)
    );
}

#[test]
fn budget_preflight_denies_zero_and_over_remaining_future_cost() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let trace = make_trace(&subject, &candidates);
    let decision = must(decide_group_continuation_v1(&subject, &trace, &candidates));
    assert_eq!(
        preflight_group_future_cost_v1(&subject, &trace, &candidates, &decision, 0),
        Err(GroupSystem2Error::ZeroFutureCost)
    );
    assert_eq!(
        preflight_group_future_cost_v1(&subject, &trace, &candidates, &decision, 96),
        Err(GroupSystem2Error::FutureCostExceedsRemaining {
            requested: 96,
            remaining: 95,
        })
    );

    let mut nearly_exhausted = trace.clone();
    nearly_exhausted.cells[0].cost_micros = 99;
    let decision = must(decide_group_continuation_v1(
        &subject,
        &nearly_exhausted,
        &candidates,
    ));
    assert_eq!(
        preflight_group_future_cost_v1(&subject, &nearly_exhausted, &candidates, &decision, 2,),
        Err(GroupSystem2Error::FutureCostExceedsRemaining {
            requested: 2,
            remaining: 1,
        })
    );
}

#[test]
fn abstention_preflight_must_quote_exactly_zero_work() {
    let subject = subject();
    let candidates = candidate_fixtures();
    let mut trace = make_trace(&subject, &candidates);
    trace.cells[0].cost_micros = subject.resource_ceiling_micros;
    let decision = must(decide_group_continuation_v1(&subject, &trace, &candidates));
    assert_eq!(decision.selected_candidate_id, "abstain");
    assert_eq!(
        preflight_group_future_cost_v1(&subject, &trace, &candidates, &decision, 1),
        Err(GroupSystem2Error::AbstainFutureCost)
    );
    let preflight = must(preflight_group_future_cost_v1(
        &subject,
        &trace,
        &candidates,
        &decision,
        0,
    ));
    assert_eq!(preflight.remaining_micros, 0);
    assert_eq!(preflight.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn budget_preflight_rejects_stale_owner_before_decision_or_quote() {
    let original = subject();
    let candidates = candidate_fixtures();
    let trace = make_trace(&original, &candidates);
    let mut forged = must(decide_group_continuation_v1(&original, &trace, &candidates));
    forged.net_value_q32 += 1;

    let changed_owners = [
        GroupNduSubjectV1 {
            group_id: "group:other".to_owned(),
            ..original.clone()
        },
        GroupNduSubjectV1 {
            encoder_digest: digest("other-encoder"),
            ..original.clone()
        },
        GroupNduSubjectV1 {
            objective_digest: digest("other-objective"),
            ..original.clone()
        },
        GroupNduSubjectV1 {
            utility_profile_digest: digest("other-utility"),
            ..original.clone()
        },
        GroupNduSubjectV1 {
            subject_class: GroupSubjectClassV1::Agent,
            ..original.clone()
        },
        GroupNduSubjectV1 {
            resource_ceiling_micros: 101,
            ..original.clone()
        },
    ];
    for changed in changed_owners {
        // Binding must reject before the forged decision or a zero/huge quote
        // can influence the error, even with unchanged subject ID/generation.
        for requested_future_micros in [0, 1, u64::MAX] {
            assert_eq!(
                preflight_group_future_cost_v1(
                    &changed,
                    &trace,
                    &candidates,
                    &forged,
                    requested_future_micros,
                ),
                Err(GroupSystem2Error::TraceBindingMismatch(
                    "subject_binding_digest",
                ))
            );
        }
    }

    let mut missing_binding = trace;
    missing_binding.subject_binding_digest = Digest32::ZERO;
    assert_eq!(
        preflight_group_future_cost_v1(
            &original,
            &missing_binding,
            &candidates,
            &forged,
            /*requested_future_micros*/ 0,
        ),
        Err(GroupSystem2Error::TraceBindingMismatch(
            "subject_binding_digest",
        ))
    );
}

#[test]
fn budget_preflight_rebinding_requires_new_decision_before_quote_checks() {
    let original = subject();
    let candidates = candidate_fixtures();
    let trace = make_trace(&original, &candidates);
    let decision = must(decide_group_continuation_v1(&original, &trace, &candidates));
    let before = must(preflight_group_future_cost_v1(
        &original,
        &trace,
        &candidates,
        &decision,
        /*requested_future_micros*/ 95,
    ));
    let changed = GroupNduSubjectV1 {
        encoder_digest: digest("other-encoder"),
        ..original
    };
    let mut rebound = trace;
    rebound.subject_binding_digest = canonical_group_subject_binding_digest_v1(&changed);
    for requested_future_micros in [0, 95, u64::MAX] {
        assert_eq!(
            preflight_group_future_cost_v1(
                &changed,
                &rebound,
                &candidates,
                &decision,
                requested_future_micros,
            ),
            Err(GroupSystem2Error::DecisionMismatch)
        );
    }
    let new_decision = must(decide_group_continuation_v1(
        &changed,
        &rebound,
        &candidates,
    ));
    let after = must(preflight_group_future_cost_v1(
        &changed,
        &rebound,
        &candidates,
        &new_decision,
        /*requested_future_micros*/ 95,
    ));
    assert_ne!(decision.trace_digest, new_decision.trace_digest);
    assert_ne!(before.preflight_digest, after.preflight_digest);
    assert_eq!(
        (
            &after.selected_candidate_id,
            after.requested_future_micros,
            after.remaining_micros,
            after.authority,
        ),
        (
            &before.selected_candidate_id,
            before.requested_future_micros,
            before.remaining_micros,
            AuthorityPosture::DENY_ALL,
        )
    );
}

#[test]
fn budget_preflight_enforces_the_rebound_owner_ceiling() {
    let original = subject();
    let candidates = candidate_fixtures();
    let mut trace = make_trace(&original, &candidates);
    let changed = GroupNduSubjectV1 {
        resource_ceiling_micros: 6,
        ..original
    };
    trace.subject_binding_digest = canonical_group_subject_binding_digest_v1(&changed);
    let decision = must(decide_group_continuation_v1(&changed, &trace, &candidates));
    let preflight = must(preflight_group_future_cost_v1(
        &changed,
        &trace,
        &candidates,
        &decision,
        /*requested_future_micros*/ 1,
    ));
    assert_eq!(
        (
            preflight.requested_future_micros,
            preflight.remaining_micros,
            preflight.authority,
        ),
        (1, 1, AuthorityPosture::DENY_ALL)
    );
    assert_eq!(
        preflight_group_future_cost_v1(
            &changed,
            &trace,
            &candidates,
            &decision,
            /*requested_future_micros*/ 2,
        ),
        Err(GroupSystem2Error::FutureCostExceedsRemaining {
            requested: 2,
            remaining: 1,
        })
    );
}
