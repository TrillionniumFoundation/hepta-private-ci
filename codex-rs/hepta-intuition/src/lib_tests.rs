use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn probability(raw: u64) -> ProbabilityQ32 {
    let Ok(value) = ProbabilityQ32::from_raw(raw) else {
        panic!("test probability must be in range");
    };
    value
}

fn candidate(name: &str, utility: i64, confidence: u64) -> ActionCandidate {
    ActionCandidate {
        candidate_id: id(name),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(utility),
        confidence: probability(confidence),
        support_digest: digest(name.as_bytes()),
    }
}

fn request(candidates: Vec<ActionCandidate>) -> DecisionRequest {
    DecisionRequest {
        decision_id: id("decision:1"),
        objective_digest: digest(b"objective"),
        candidate_set_digest: digest(b"candidate-set"),
        minimum_confidence: probability(1),
        candidates,
    }
}

#[test]
fn hard_veto_cannot_be_overridden() {
    let mut vetoed = candidate("action:vetoed", 100, ProbabilityQ32::ONE.raw());
    vetoed.hard_veto = true;
    let allowed = candidate("action:allowed", 10, ProbabilityQ32::ONE.raw());
    let Ok(receipt) = decide(request(vec![vetoed, allowed])) else {
        panic!("decision must succeed");
    };
    assert_eq!(receipt.decision, Decision::Selected(id("action:allowed")));
    assert!(!receipt.authority.grants_any());
}

#[test]
fn low_confidence_abstains_and_records_complete_propensities() {
    let mut value = request(vec![candidate("action:a", 10, 1)]);
    value.minimum_confidence = ProbabilityQ32::ONE;
    let Ok(receipt) = decide(value) else {
        panic!("decision must succeed");
    };
    assert_eq!(
        receipt.decision,
        Decision::Abstained(AbstentionReason::LowConfidence)
    );
    assert_eq!(receipt.propensities.len(), 1);
    assert_eq!(receipt.propensities[0].probability, ProbabilityQ32::ZERO);
    assert_eq!(receipt.abstain_probability, ProbabilityQ32::ONE);
}

#[test]
fn tie_breaking_is_canonical() {
    let left = candidate("action:b", 10, ProbabilityQ32::ONE.raw());
    let right = candidate("action:a", 10, ProbabilityQ32::ONE.raw());
    let Ok(receipt) = decide(request(vec![left, right])) else {
        panic!("decision must succeed");
    };
    assert_eq!(receipt.decision, Decision::Selected(id("action:a")));
}

#[test]
fn duplicate_candidates_are_rejected() {
    let value = candidate("action:a", 10, ProbabilityQ32::ONE.raw());
    assert_eq!(
        decide(request(vec![value.clone(), value])),
        Err(Error::DuplicateCandidate("action:a".to_string()))
    );
}

#[test]
fn candidate_ceiling_is_enforced_at_128() {
    let at_limit = (0..128)
        .map(|index| candidate(&format!("action:{index}"), index, 1))
        .collect();
    let receipt = decide(request(at_limit))
        .unwrap_or_else(|error| panic!("128 candidates must be accepted: {error:?}"));
    assert_eq!(receipt.propensities.len(), 128);

    let over_limit = (0..129)
        .map(|index| candidate(&format!("action:{index}"), index, 1))
        .collect();
    assert_eq!(
        decide(request(over_limit)),
        Err(Error::CandidateLimitExceeded)
    );
}

#[test]
fn maximum_candidate_receipt_is_canonical_and_digest_complete() {
    let mut candidates = (0..128)
        .map(|index| {
            candidate(
                &format!("action:{index:03}"),
                index,
                ProbabilityQ32::ONE.raw(),
            )
        })
        .collect::<Vec<_>>();
    candidates[0].utility = FixedQ32::from_raw(i64::MIN);
    candidates[127].utility = FixedQ32::from_raw(i64::MAX);

    let receipt = decide(request(candidates.clone()))
        .unwrap_or_else(|error| panic!("maximum candidate set must be decided: {error:?}"));
    assert_eq!(receipt.decision, Decision::Selected(id("action:127")));
    let probability_total = receipt
        .propensities
        .iter()
        .map(|propensity| u128::from(propensity.probability.raw()))
        .sum::<u128>()
        + u128::from(receipt.abstain_probability.raw());
    assert_eq!(probability_total, u128::from(ProbabilityQ32::ONE.raw()));

    let mut reversed = candidates.clone();
    reversed.reverse();
    assert_eq!(
        decide(request(reversed)).unwrap_or_else(|error| {
            panic!("permuted candidate set must be decided: {error:?}")
        }),
        receipt
    );

    candidates[127].support_digest = digest(b"changed-final-support");
    let changed = decide(request(candidates.clone()))
        .unwrap_or_else(|error| panic!("changed candidate set must be decided: {error:?}"));
    assert_eq!(changed.decision, receipt.decision);
    assert_eq!(changed.propensities, receipt.propensities);
    assert_eq!(changed.abstain_probability, receipt.abstain_probability);
    assert_ne!(changed.receipt_digest, receipt.receipt_digest);

    let mut rebound = request(candidates);
    rebound.candidate_set_digest = digest(b"different-candidate-set");
    let rebound = decide(rebound)
        .unwrap_or_else(|error| panic!("rebound candidate set must be decided: {error:?}"));
    assert_ne!(rebound.receipt_digest, changed.receipt_digest);
}
