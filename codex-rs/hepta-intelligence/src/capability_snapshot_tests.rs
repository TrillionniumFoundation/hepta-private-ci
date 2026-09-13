use super::*;
use codex_hepta_types::AuthorityPosture;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn request() -> CapabilitySnapshotRequestV2 {
    let contract = Digest32::of_bytes(b"contract");
    CapabilitySnapshotRequestV2 {
        objective_digest: Digest32::of_bytes(b"objective"),
        authority_epoch: 1,
        body_generation: Generation::new(/*value*/ 1).expect("generation"),
        configuration_digest: Digest32::of_bytes(b"configuration"),
        revocation_frontier_digest: Digest32::of_bytes(b"revocations"),
        requirements: vec![
            CapabilityRequirementV2 {
                capability_id: id("context"),
                owner_id: id("context.compiler"),
                contract_digest: contract,
                necessity: CapabilityNecessityV2::Required,
            },
            CapabilityRequirementV2 {
                capability_id: id("neural-hint"),
                owner_id: id("neuron.runtime"),
                contract_digest: contract,
                necessity: CapabilityNecessityV2::Optional,
            },
        ],
        bindings: vec![CapabilityBindingV2 {
            capability_id: id("context"),
            owner_id: id("context.compiler"),
            contract_digest: contract,
            implementation_digest: Digest32::of_bytes(b"implementation"),
            generation: Generation::new(/*value*/ 1).expect("generation"),
        }],
    }
}

#[test]
fn absent_optional_capability_composes_without_neural_or_model_artifact() {
    let snapshot = CapabilitySnapshotV2::admit(request()).expect("admitted");
    assert_eq!(snapshot.absent_optional(), &[id("neural-hint")]);
    let plan = snapshot
        .compose_plan(id("plan"), Digest32::of_bytes(b"context"), vec![])
        .expect("existing composer");
    assert_eq!(plan.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        plan.decision,
        crate::PlanDecision::Abstained(crate::AbstentionReason::NoEligibleCandidate)
    );
    assert!(!plan.effect_authority);
}

#[test]
fn required_missing_and_fabricated_zero_artifact_reject() {
    let mut missing = request();
    missing.bindings.clear();
    assert_eq!(
        CapabilitySnapshotV2::admit(missing),
        Err(CapabilitySnapshotErrorV2::MissingRequiredCapability(id(
            "context"
        )))
    );
    let mut empty = request();
    empty.bindings[0].implementation_digest = Digest32::ZERO;
    assert_eq!(
        CapabilitySnapshotV2::admit(empty),
        Err(CapabilitySnapshotErrorV2::BindingMismatch(id("context")))
    );
}

#[test]
fn declaration_reordering_is_stable_but_replacement_changes_actual_plan() {
    let mut reordered = request();
    reordered.requirements.reverse();
    let first = CapabilitySnapshotV2::admit(request()).expect("admitted");
    assert_eq!(
        CapabilitySnapshotV2::admit(reordered).expect("admitted"),
        first
    );
    let mut replaced = request();
    replaced.bindings[0].implementation_digest = Digest32::of_bytes(b"replacement");
    let second = CapabilitySnapshotV2::admit(replaced).expect("admitted");
    assert_ne!(first.digest(), second.digest());
    assert_ne!(
        first
            .compose_plan(id("plan"), Digest32::of_bytes(b"context"), vec![])
            .expect("plan"),
        second
            .compose_plan(id("plan"), Digest32::of_bytes(b"context"), vec![])
            .expect("plan")
    );
}

#[test]
fn optional_add_remove_is_explicit_and_does_not_weaken_requirements() {
    let mut selected = request();
    let requirement = selected.requirements[1].clone();
    let mut binding = selected.bindings[0].clone();
    binding.capability_id = requirement.capability_id;
    binding.owner_id = requirement.owner_id;
    selected.bindings.push(binding);
    let first = CapabilitySnapshotV2::admit(selected.clone()).expect("admitted");
    assert!(first.absent_optional().is_empty());
    selected.bindings.pop();
    let second = CapabilitySnapshotV2::admit(selected.clone()).expect("admitted");
    assert_ne!(first.digest(), second.digest());
    selected.requirements[1].necessity = CapabilityNecessityV2::Required;
    assert_eq!(
        CapabilitySnapshotV2::admit(selected),
        Err(CapabilitySnapshotErrorV2::MissingRequiredCapability(id(
            "neural-hint"
        )))
    );
}

#[test]
fn duplicate_unknown_and_wrong_owner_are_not_admitted() {
    let mut duplicate = request();
    duplicate.bindings.push(duplicate.bindings[0].clone());
    assert_eq!(
        CapabilitySnapshotV2::admit(duplicate),
        Err(CapabilitySnapshotErrorV2::DuplicateBinding(id("context")))
    );
    let mut unknown = request();
    unknown.bindings[0].capability_id = id("unregistered");
    assert_eq!(
        CapabilitySnapshotV2::admit(unknown),
        Err(CapabilitySnapshotErrorV2::UnknownCapability(id(
            "unregistered"
        )))
    );
    let mut wrong = request();
    wrong.bindings[0].owner_id = id("other.owner");
    assert_eq!(
        CapabilitySnapshotV2::admit(wrong),
        Err(CapabilitySnapshotErrorV2::BindingMismatch(id("context")))
    );
}

#[test]
fn optional_absence_keeps_existing_selection_and_hard_veto_semantics() {
    let snapshot = CapabilitySnapshotV2::admit(request()).expect("admitted");
    let allowed = PlanCandidate {
        candidate_id: id("allowed"),
        legal: true,
        hard_veto: false,
        score: codex_hepta_types::FixedQ32::from_raw(1),
        support_digest: Digest32::of_bytes(b"allowed"),
    };
    let mut vetoed = allowed.clone();
    vetoed.candidate_id = id("vetoed");
    vetoed.hard_veto = true;
    vetoed.score = codex_hepta_types::FixedQ32::from_raw(100);
    let plan = snapshot
        .compose_plan(
            id("plan"),
            Digest32::of_bytes(b"context"),
            vec![allowed, vetoed],
        )
        .expect("existing composer");
    assert_eq!(plan.decision, crate::PlanDecision::Selected(id("allowed")));
    assert_eq!(plan.authority, AuthorityPosture::DENY_ALL);
    assert!(!plan.effect_authority);
}

#[test]
fn snapshot_binds_core_freshness_and_bounded_unique_requirements() {
    let first = CapabilitySnapshotV2::admit(request()).expect("admitted");
    let mut changed = request();
    changed.authority_epoch += 1;
    assert_ne!(
        CapabilitySnapshotV2::admit(changed)
            .expect("admitted")
            .digest(),
        first.digest()
    );
    let mut changed = request();
    changed.revocation_frontier_digest = Digest32::of_bytes(b"new-revocation");
    assert_ne!(
        CapabilitySnapshotV2::admit(changed)
            .expect("admitted")
            .digest(),
        first.digest()
    );
    let mut repeated = request();
    repeated.requirements.push(repeated.requirements[0].clone());
    assert_eq!(
        CapabilitySnapshotV2::admit(repeated),
        Err(CapabilitySnapshotErrorV2::DuplicateRequirement(id(
            "context"
        )))
    );
    let mut oversized = request();
    oversized.requirements = vec![oversized.requirements[0].clone(); 129];
    assert_eq!(
        CapabilitySnapshotV2::admit(oversized),
        Err(CapabilitySnapshotErrorV2::CapacityExceeded)
    );
}
