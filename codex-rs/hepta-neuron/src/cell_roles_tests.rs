use pretty_assertions::assert_eq;

use super::*;

fn contract() -> CellCapabilityContractV1 {
    CellCapabilityContractV1 {
        type_id: StableId::new("memory.code.association").expect("type"),
        generation: Generation::new(1).expect("generation"),
        role: CellFunctionalRoleV1::MemoryAssociation,
        input_schema_digest: Digest32::of_bytes(b"input schema"),
        output_schema_digest: Digest32::of_bytes(b"output schema"),
        state_schema_digest: Digest32::of_bytes(b"state schema"),
        behavior_contract_digest: Digest32::of_bytes(b"source-bound associations"),
    }
}

#[test]
fn exact_capability_binding_changes_with_identity_schema_and_semantics() {
    let original = contract();
    let expected = original.digest().expect("original");
    let mut mutations = Vec::new();
    let mut changed = original.clone();
    changed.type_id = StableId::new("memory.science.association").expect("type");
    mutations.push(changed);
    let mut changed = original.clone();
    changed.generation = changed.generation.next().expect("next generation");
    mutations.push(changed);
    let mut changed = original.clone();
    changed.role = CellFunctionalRoleV1::VerificationMetacognition;
    mutations.push(changed);
    for field in 0..4 {
        let mut changed = original.clone();
        let replacement = Digest32::of_bytes(b"replacement");
        match field {
            0 => changed.input_schema_digest = replacement,
            1 => changed.output_schema_digest = replacement,
            2 => changed.state_schema_digest = replacement,
            3 => changed.behavior_contract_digest = replacement,
            _ => unreachable!(),
        }
        mutations.push(changed);
    }
    for changed in mutations {
        assert_ne!(changed.digest().expect("changed"), expected);
    }
    assert_eq!(original.digest(), Ok(expected));
}

#[test]
fn absent_schema_or_behavior_is_rejected_before_creating_a_binding() {
    for field in 0..4 {
        let mut changed = contract();
        let name = match field {
            0 => {
                changed.input_schema_digest = Digest32::ZERO;
                "input schema"
            }
            1 => {
                changed.output_schema_digest = Digest32::ZERO;
                "output schema"
            }
            2 => {
                changed.state_schema_digest = Digest32::ZERO;
                "state schema"
            }
            3 => {
                changed.behavior_contract_digest = Digest32::ZERO;
                "behavior contract"
            }
            _ => unreachable!(),
        };
        assert_eq!(
            changed.digest(),
            Err(CellCapabilityErrorV1::EmptyDigest(name))
        );
    }
}
