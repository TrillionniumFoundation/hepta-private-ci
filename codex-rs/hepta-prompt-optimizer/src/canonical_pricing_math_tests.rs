use super::*;
use crate::canonical::PromptConfidenceIntervalWireV1;
use crate::canonical::PromptPricingWireV1;
use crate::canonical::decode_pricing_receipt_json_v1;
use crate::canonical::encode_pricing_wire_json_v1;
use codex_hepta_types::Digest32;

fn q(raw: i64) -> FixedQ32 {
    FixedQ32::from_raw(raw)
}

#[test]
fn pricing_net_confidence_subtracts_the_same_costs_from_every_bound() {
    assert_eq!(
        net_interval(q(100), q(80), q(120), [q(30), q(10)]),
        Ok(NetUtilityInterval {
            mean: q(60),
            lower: q(40),
            upper: q(80),
        })
    );
}

#[test]
fn cost_adjusted_pricing_round_trips_through_the_registered_codec() {
    let net = net_interval(q(100), q(80), q(120), [q(40)])
        .unwrap_or_else(|error| panic!("net pricing: {error}"));
    let digest = Digest32::of_bytes(b"net-pricing-test").to_string();
    let wire = PromptPricingWireV1 {
        factor_id: "factor:net-pricing".to_owned(),
        state_digest: digest.clone(),
        expected_utility_q32: net.mean.raw(),
        downside_q32: 0,
        token_cost: 1,
        latency_cost_micros: 0,
        interference_ppm: 0,
        confidence_interval: PromptConfidenceIntervalWireV1 {
            lower_q32: net.lower.raw(),
            upper_q32: net.upper.raw(),
            support_count: 10,
            support_audit_digest: digest,
        },
    };
    let bytes = encode_pricing_wire_json_v1(&wire)
        .unwrap_or_else(|error| panic!("encode net pricing: {error}"));
    assert_eq!(decode_pricing_receipt_json_v1(&bytes), Ok(wire));
}

#[test]
fn pricing_net_interval_keeps_negative_utility_and_zero_cost_semantics() {
    assert_eq!(
        net_interval(q(-5), q(-10), q(0), [q(5)]),
        Ok(NetUtilityInterval {
            mean: q(-10),
            lower: q(-15),
            upper: q(-5),
        })
    );
    assert_eq!(
        net_interval(q(0), q(-2), q(2), [q(0)]),
        Ok(NetUtilityInterval {
            mean: q(0),
            lower: q(-2),
            upper: q(2),
        })
    );
}

#[test]
fn pricing_confidence_overflow_and_negative_costs_fail_closed() {
    assert_eq!(
        net_interval(q(0), q(i64::MIN), q(1), [q(1)]),
        Err(CanonicalPromptError::Arithmetic)
    );
    assert_eq!(
        net_interval(q(0), q(-1), q(1), [q(-1)]),
        Err(CanonicalPromptError::InvalidPricingPolicy)
    );
    assert_eq!(
        net_interval(q(5), q(6), q(7), []),
        Err(CanonicalPromptError::CandidateIntegrity(
            "gross confidence interval"
        ))
    );
}

#[test]
fn sequential_pricing_costs_do_not_require_an_overflowing_cost_sum() {
    assert_eq!(
        net_interval(
            q(i64::MAX),
            q(i64::MAX),
            q(i64::MAX),
            [q(i64::MAX), q(1)],
        ),
        Ok(NetUtilityInterval {
            mean: q(-1),
            lower: q(-1),
            upper: q(-1),
        })
    );
}

#[test]
fn pricing_confidence_small_domain_matches_integer_oracle() {
    for mean in -16..=16_i64 {
        for radius in 0..=8_i64 {
            for cost in 0..=32_i64 {
                assert_eq!(
                    net_interval(q(mean), q(mean - radius), q(mean + radius), [q(cost)]),
                    Ok(NetUtilityInterval {
                        mean: q(mean - cost),
                        lower: q(mean - radius - cost),
                        upper: q(mean + radius - cost),
                    })
                );
            }
        }
    }
}
