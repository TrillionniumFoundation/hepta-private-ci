use pretty_assertions::assert_eq;

use super::*;
use crate::CellBundleComponentsV1;
use crate::CellTrainingLineageV1;
use crate::test_support::FixtureValue;
use codex_hepta_types::Generation;

fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).fixture("id")
}
fn source() -> CellCompatibilityBundleV1 {
    CellCompatibilityBundleV1 {
        artifact_id: id("artifact:base"),
        generation: Generation::new(1).fixture("generation"),
        components: CellBundleComponentsV1 {
            base: d("base"),
            organ_adapter: None,
            cell_adapter: None,
            heads: d("heads"),
            composition: d("composition"),
            encoder: d("encoder"),
            tokenizer: d("tokenizer"),
            normalizer: d("normalizer"),
            calibration: d("calibration"),
            numeric_profile: d("numeric"),
            output_schema: d("output"),
            state_schema: d("schema"),
            state_semantics: d("semantics"),
        },
        training_lineage: None,
        rollback_predecessor: None,
    }
}
fn candidate(base: &CellCompatibilityBundleV1) -> CellCompatibilityBundleV1 {
    let mut next = base.clone();
    next.artifact_id = id("artifact:next");
    next.generation = base.generation.next().fixture("next generation");
    let previous = base.digest().fixture("base");
    next.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle: previous,
        dataset: d("dataset"),
        update_rule: d("rule"),
        evaluation_profile: d("evaluation"),
    });
    next.rollback_predecessor = Some(previous);
    next.components.heads = d("trained-heads");
    next
}
fn semantic() -> CellImplementationFamilyV1 {
    CellImplementationFamilyV1::SharedSemantic {
        trainable: SemanticTrainablePartV1::Heads,
    }
}

#[test]
fn local_head_update_cannot_change_shared_base_or_domain_or_encoding() {
    let base = source();
    let next = candidate(&base);
    assert_eq!(
        validate_cell_local_update_v1(semantic(), &base, &next),
        next.digest().map_err(Into::into)
    );
    let changes: [fn(&mut CellBundleComponentsV1); 5] = [
        |c| c.base = d("other"),
        |c| c.organ_adapter = Some(d("other")),
        |c| c.encoder = d("other"),
        |c| c.composition = d("other"),
        |c| c.cell_adapter = Some(d("other")),
    ];
    for change in changes {
        let mut wrong = next.clone();
        change(&mut wrong.components);
        assert_eq!(
            validate_cell_local_update_v1(semantic(), &base, &wrong),
            Err(CellLocalUpdateErrorV1::FrozenComponentChanged)
        );
    }
}

#[test]
fn adapter_training_is_explicit_and_does_not_expand_to_domain_adapter() {
    let base = source();
    let mut next = candidate(&base);
    next.components.cell_adapter = Some(d("trained-adapter"));
    let family = CellImplementationFamilyV1::SharedSemantic {
        trainable: SemanticTrainablePartV1::CellAdapterAndHeads,
    };
    assert!(validate_cell_local_update_v1(family, &base, &next).is_ok());
    next.components.organ_adapter = Some(d("domain-change"));
    assert_eq!(
        validate_cell_local_update_v1(family, &base, &next),
        Err(CellLocalUpdateErrorV1::FrozenComponentChanged)
    );
}

#[test]
fn temporal_kernel_updates_keep_state_meaning_and_input_contract_frozen() {
    let base = source();
    let mut next = candidate(&base);
    next.components.base = d("trained-kernel");
    let family = CellImplementationFamilyV1::StatefulTemporal {
        kernel: TemporalCellKernelV1::Gru,
    };
    assert!(validate_cell_local_update_v1(family, &base, &next).is_ok());
    next.components.state_semantics = d("incompatible-state");
    assert_eq!(
        validate_cell_local_update_v1(family, &base, &next),
        Err(CellLocalUpdateErrorV1::FrozenComponentChanged)
    );
}

#[test]
fn deterministic_components_reject_neural_training_and_bad_lineage() {
    let base = source();
    let mut next = candidate(&base);
    for kind in [
        DeterministicCellKindV1::Retrieval,
        DeterministicCellKindV1::RuleVerifier,
        DeterministicCellKindV1::Numerical,
        DeterministicCellKindV1::ToolWrapper,
    ] {
        assert_eq!(
            validate_cell_local_update_v1(
                CellImplementationFamilyV1::Deterministic { kind },
                &base,
                &next
            ),
            Err(CellLocalUpdateErrorV1::NotTrainable)
        );
    }
    next.generation = Generation::new(3).fixture("generation");
    assert_eq!(
        validate_cell_local_update_v1(semantic(), &base, &next),
        Err(CellLocalUpdateErrorV1::WrongSuccessor)
    );
    next = candidate(&base);
    next.components = base.components.clone();
    assert_eq!(
        validate_cell_local_update_v1(semantic(), &base, &next),
        Err(CellLocalUpdateErrorV1::NoParameterChange)
    );
}

#[test]
fn python_bundle_and_native_reset_have_identical_commitments() {
    let base = source();
    let next = candidate(&base);
    let plan = prepare_cell_local_reset_v1(
        semantic(),
        id("cutover:one"),
        id("owner:state"),
        CellStatePartitionV1 {
            principal_id: id("principal:one"),
            agent_id: id("agent:one"),
            cell_id: id("cell:one"),
            run_id: id("run:next"),
        },
        &base,
        &next,
        CellLocalResetV1 {
            initializer: d("initializer"),
            target_checkpoint: d("reset"),
        },
    )
    .fixture("reset plan");
    // Produced independently by scripts/hepta_cells/bundle.py with these inputs.
    assert_eq!(
        (
            base.digest().fixture("base").to_string(),
            next.digest().fixture("next").to_string(),
            plan.plan_digest().to_string()
        ),
        (
            "50c9be0c39fe042b5f88525823511181448080cdac871815201735cb0986dda1".to_owned(),
            "6cd309665ea081b3dfa00433df7d8643860e4be00a285fb48e0fd87ea3983d6d".to_owned(),
            "900f2fd17f892c382d69ab31ced5db8fdac81dd293297263f103d785013e5db8".to_owned()
        )
    );
    assert_eq!(
        plan.transition(),
        &CellStateTransitionV1::Reset {
            initializer: d("initializer"),
            target_checkpoint: d("reset")
        }
    );
}
