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

fn candidate(name: &str, gain: i64, cost: u64) -> PromptCandidate {
    PromptCandidate {
        candidate_id: id(name),
        factor_id: id(&format!("factor:{name}")),
        realization_id: id(&format!("realization:{name}")),
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(gain),
        cost,
        registry_digest: digest(b"registry"),
        support_digest: digest(name.as_bytes()),
    }
}

fn request(candidates: Vec<PromptCandidate>) -> OptimizationRequest {
    OptimizationRequest {
        decision_id: id("decision:1"),
        objective_digest: digest(b"objective"),
        registry_snapshot_digest: digest(b"registry"),
        budget: 10,
        maximum_selected: 2,
        candidates,
    }
}

#[test]
fn illegal_and_unadmitted_candidates_are_never_selected() {
    let mut illegal = candidate("illegal", 100, 1);
    illegal.legal = false;
    let mut unadmitted = candidate("unadmitted", 90, 1);
    unadmitted.admitted = false;
    let allowed = candidate("allowed", 10, 1);
    let Ok(receipt) = optimize(request(vec![illegal, unadmitted, allowed])) else {
        panic!("optimization must succeed");
    };
    assert_eq!(receipt.selected, vec![id("allowed")]);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn budget_and_selection_limits_are_enforced() {
    let value = request(vec![
        candidate("a", 30, 7),
        candidate("b", 20, 4),
        candidate("c", 10, 3),
    ]);
    let Ok(receipt) = optimize(value) else {
        panic!("optimization must succeed");
    };
    assert_eq!(receipt.selected, vec![id("a"), id("c")]);
    assert_eq!(receipt.total_cost, 10);
    assert_eq!(receipt.unspent_budget, 0);
}

#[test]
fn canonical_tie_breaking_uses_identifier_order() {
    let left = candidate("b", 10, 1);
    let right = candidate("a", 10, 1);
    let mut value = request(vec![left, right]);
    value.maximum_selected = 1;
    let Ok(receipt) = optimize(value) else {
        panic!("optimization must succeed");
    };
    assert_eq!(receipt.selected, vec![id("a")]);
}

#[test]
fn registry_snapshot_drift_is_rejected() {
    let mut value = candidate("a", 10, 1);
    value.registry_digest = digest(b"other");
    assert_eq!(
        optimize(request(vec![value])),
        Err(Error::RegistrySnapshotMismatch("a".to_string()))
    );
}
