use super::*;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identifier is valid")
}

fn fixture() -> (CompilationRequest, CompilationRequirementsV1) {
    let items = [
        ("instruction", ContextRole::TrustedInstruction, 2),
        ("a-optional", ContextRole::UntrustedEvidence, 4),
        ("z-claim", ContextRole::UntrustedEvidence, 3),
        ("z-provenance", ContextRole::UntrustedEvidence, 3),
    ]
    .into_iter()
    .map(|(name, role, token_count)| ContextItem {
        item_id: id(name),
        role,
        token_count,
        content_digest: Digest32::of_bytes(name.as_bytes()),
        source_digest: Digest32::of_bytes(b"scoped-source"),
        contains_secret: false,
    })
    .collect::<Vec<_>>();
    let request = CompilationRequest {
        compilation_id: id("compile"),
        run_snapshot_digest: Digest32::of_bytes(b"snapshot"),
        objective_digest: Digest32::of_bytes(b"objective"),
        token_budget: 8,
        items,
    };
    let requirements = CompilationRequirementsV1 {
        run_snapshot_digest: request.run_snapshot_digest,
        objective_digest: request.objective_digest,
        mandatory_groups: vec![MandatoryContextGroup {
            group_id: id("claim-and-citation"),
            items: request.items[2..].to_vec(),
        }],
    };
    (request, requirements)
}

#[test]
fn reserves_whole_provenance_group_before_optional_evidence() {
    let (request, requirements) = fixture();
    let receipt = compile_with_requirements(request, requirements).unwrap();
    assert_eq!(receipt.trusted_instruction_ids, vec![id("instruction")]);
    assert_eq!(
        receipt.untrusted_evidence_ids,
        vec![id("z-claim"), id("z-provenance")]
    );
    assert_eq!(receipt.omitted_ids, vec![id("a-optional")]);
    assert_eq!(receipt.used_tokens, 8);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn insufficient_floor_never_returns_a_partial_provenance_group() {
    let (mut request, requirements) = fixture();
    request.token_budget = 7;
    assert_eq!(
        compile_with_requirements(request, requirements),
        Err(Error::InsufficientContext {
            required_tokens: 8,
            token_budget: 7
        })
    );
}

#[test]
fn shared_provenance_is_charged_once_and_order_is_canonical() {
    let (mut request, mut requirements) = fixture();
    requirements.mandatory_groups.push(MandatoryContextGroup {
        group_id: id("shared-citation"),
        items: vec![request.items[3].clone()],
    });
    let expected = compile_with_requirements(request.clone(), requirements.clone()).unwrap();
    request.items.reverse();
    requirements.mandatory_groups.reverse();
    for group in &mut requirements.mandatory_groups {
        group.items.reverse();
    }
    assert_eq!(
        compile_with_requirements(request, requirements),
        Ok(expected)
    );
}

#[test]
fn every_required_item_binding_rejects_drift() {
    let (request, requirements) = fixture();
    let original = &request.items[2];
    let changed = Digest32::of_bytes(b"changed");
    let variants = [
        ContextItem {
            content_digest: changed,
            ..original.clone()
        },
        ContextItem {
            source_digest: changed,
            ..original.clone()
        },
        ContextItem {
            role: ContextRole::TrustedInstruction,
            ..original.clone()
        },
        ContextItem {
            token_count: 1,
            ..original.clone()
        },
    ];
    for item in variants {
        let mut candidate = request.clone();
        candidate.items[2] = item;
        assert_eq!(
            compile_with_requirements(candidate, requirements.clone()),
            Err(Error::RequiredItemMismatch("z-claim".to_owned()))
        );
    }
}

#[test]
fn unknown_member_and_mismatched_snapshot_or_objective_are_rejected() {
    let (request, requirements) = fixture();
    let mut changed = requirements.clone();
    changed.mandatory_groups[0].items[0].item_id = id("missing");
    assert_eq!(
        compile_with_requirements(request.clone(), changed),
        Err(Error::UnknownRequiredItem("missing".to_owned()))
    );
    let mut changed = requirements.clone();
    changed.run_snapshot_digest = Digest32::of_bytes(b"other-snapshot");
    assert_eq!(
        compile_with_requirements(request.clone(), changed),
        Err(Error::RequirementSnapshotMismatch)
    );
    let mut changed = requirements;
    changed.objective_digest = Digest32::of_bytes(b"other-objective");
    assert_eq!(
        compile_with_requirements(request, changed),
        Err(Error::RequirementObjectiveMismatch)
    );
}

#[test]
fn required_group_semantics_are_part_of_the_receipt_digest() {
    let (request, requirements) = fixture();
    let first = compile_with_requirements(request.clone(), requirements.clone()).unwrap();
    let mut changed = requirements;
    changed.mandatory_groups[0].group_id = id("contradiction-pair");
    let second = compile_with_requirements(request, changed).unwrap();
    assert_eq!(first.untrusted_evidence_ids, second.untrusted_evidence_ids);
    assert_ne!(first.context_digest, second.context_digest);
}

#[test]
fn malformed_groups_and_reference_saturation_are_rejected() {
    let (request, requirements) = fixture();
    let mut changed = requirements.clone();
    changed.mandatory_groups[0].items.clear();
    assert_eq!(
        compile_with_requirements(request.clone(), changed),
        Err(Error::EmptyRequirementGroup(
            "claim-and-citation".to_owned()
        ))
    );
    let mut changed = requirements.clone();
    changed
        .mandatory_groups
        .push(changed.mandatory_groups[0].clone());
    assert_eq!(
        compile_with_requirements(request.clone(), changed),
        Err(Error::DuplicateRequirementGroup(
            "claim-and-citation".to_owned()
        ))
    );
    let mut changed = requirements.clone();
    let member = changed.mandatory_groups[0].items[0].clone();
    changed.mandatory_groups[0].items.push(member.clone());
    assert_eq!(
        compile_with_requirements(request.clone(), changed),
        Err(Error::DuplicateRequirementItem("z-claim".to_owned()))
    );
    let mut changed = requirements;
    changed.mandatory_groups[0].items = vec![member; MAX_ITEMS + 1];
    assert_eq!(
        compile_with_requirements(request, changed),
        Err(Error::RequirementLimitExceeded)
    );
}
