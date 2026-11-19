//! The legacy compatibility comparator preserves the same incomplete/negative
//! distinction without gaining any production qualification authority.

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn known_regression_with_unknown_metric_support_is_not_complete_ineligible() {
    let mut complete = request();
    let mut latency = complete.comparisons[0].clone();
    latency.metric_id = id("latency");
    latency.hard = false;
    complete.comparisons.push(latency);
    assert_eq!(
        must(evaluate(complete.clone())).disposition,
        Disposition::EligibleForFurtherReview
    );

    complete.comparisons[0].candidate = FixedQ32::ONE;
    complete.comparisons[0].baseline = FixedQ32::ZERO;
    let negative = must(evaluate(complete.clone()));
    assert_eq!(
        (&negative.disposition, &negative.failed_metrics),
        (&Disposition::Ineligible, &vec![id("safety")])
    );
    let mut incomplete = complete.clone();
    incomplete.comparisons[1].support_digest = Digest32::ZERO;
    let unknown = must(evaluate(incomplete.clone()));
    assert_eq!(
        (&unknown.disposition, &unknown.failed_metrics),
        (&Disposition::InsufficientEvidence, &vec![id("safety")])
    );
    assert_ne!(unknown.evidence_digest, negative.evidence_digest);
    incomplete.comparisons.reverse();
    assert_eq!(must(evaluate(incomplete)), unknown);
    assert_eq!(must(evaluate(complete)), negative);
}
