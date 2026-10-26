//! A request acceptance or ordinary short completion is not a cap witness.

use serde_json::Value;

pub(super) struct Decision {
    pub qualified: bool,
    pub status: &'static str,
}

pub(super) fn decide(
    retained: Option<&Value>,
    input_reservation: u64,
    requested_cap: u64,
    transport_invoked: bool,
    original_terminal_acks: bool,
    expected_incomplete_failure: bool,
    unexpected_tool: bool,
) -> Decision {
    let no = |status| Decision {
        qualified: false,
        status,
    };
    if !transport_invoked {
        return no("not_dispatched");
    }
    if !original_terminal_acks {
        return no("unresolved_terminal_owner");
    }
    if unexpected_tool {
        return no("inconclusive_unexpected_tool");
    }
    let Some(retained) = retained else {
        return no("refused_or_unresolved_without_private_terminal");
    };
    if retained["terminal"] != "incomplete" {
        return no("inconclusive_completed_response");
    }
    if !expected_incomplete_failure {
        return no("inconclusive_native_or_owner_failure");
    }
    if retained["terminal_consistent"] != true || retained["reason"] != "max_output_tokens" {
        return no("inconclusive_incomplete_reason");
    }
    if retained["usage_status"] != "observed" {
        return no("inconclusive_incomplete_usage");
    }
    if retained["reservation_settlement"] != "retained_indeterminate"
        || retained["retained_reservation"]["provider_input_tokens"].as_u64()
            != Some(input_reservation)
        || retained["retained_reservation"]["output_tokens"].as_u64() != Some(requested_cap)
        || retained["retained_reservation"]["provider_calls"] != 1
    {
        return no("inconclusive_reservation_binding");
    }
    let usage = &retained["usage"];
    if usage["input_tokens"]
        .as_u64()
        .is_none_or(|n| n > input_reservation)
        || usage["output_tokens"]
            .as_u64()
            .is_none_or(|n| n > requested_cap)
    {
        return no("refuted_declared_usage_bound");
    }
    if retained
        .get("echoed_max_output_tokens")
        .and_then(Value::as_u64)
        .is_some_and(|n| n != requested_cap)
    {
        return no("contradictory_limit_echo");
    }
    Decision {
        qualified: true,
        status: "cap_witness_observed_for_this_exact_request",
    }
}

#[cfg(test)]
#[path = "budget_report_tests.rs"]
mod tests;
