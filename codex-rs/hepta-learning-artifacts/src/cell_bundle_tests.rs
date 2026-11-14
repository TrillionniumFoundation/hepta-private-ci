use pretty_assertions::assert_eq;

use super::*;
use crate::test_support::FixtureValue;

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn partition() -> CellStatePartitionV1 {
    CellStatePartitionV1 {
        principal_id: id("principal:one"),
        agent_id: id("agent:one"),
        cell_id: id("cell:one"),
        run_id: id("run:next"),
    }
}
fn bundle() -> CellCompatibilityBundleV1 {
    CellCompatibilityBundleV1 {
        artifact_id: id("artifact:base"),
        generation: Generation::new(1).fixture("generation"),
        components: CellBundleComponentsV1 {
            base: digest("base"),
            organ_adapter: None,
            cell_adapter: None,
            heads: digest("heads"),
            composition: digest("composition"),
            encoder: digest("encoder"),
            tokenizer: digest("tokenizer"),
            normalizer: digest("normalizer"),
            calibration: digest("calibration"),
            numeric_profile: digest("numeric"),
            output_schema: digest("output"),
            state_schema: digest("schema"),
            state_semantics: digest("semantics"),
        },
        training_lineage: None,
        rollback_predecessor: None,
    }
}
fn successor(source: &CellCompatibilityBundleV1) -> CellCompatibilityBundleV1 {
    let mut next = source.clone();
    next.artifact_id = id("artifact:next");
    next.generation = source.generation.next().fixture("generation");
    let source_bundle = source.digest().fixture("source bundle");
    next.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle,
        dataset: digest("dataset"),
        update_rule: digest("rule"),
        evaluation_profile: digest("evaluation"),
    });
    next.rollback_predecessor = Some(source_bundle);
    next
}

#[test]
fn changed_computation_requires_explicit_reset_or_qualified_migration() {
    let source = bundle();
    let mut next = successor(&source);
    let original = prepare_cell_bundle_cutover_v1(
        id("cutover:one"),
        id("owner:state"),
        partition(),
        &source,
        &next,
        CellStateTransitionV1::Preserve {
            checkpoint: digest("checkpoint"),
        },
    )
    .fixture("preserve");
    next.components.encoder = digest("new-encoder");
    assert_eq!(
        prepare_cell_bundle_cutover_v1(
            id("cutover:one"),
            id("owner:state"),
            partition(),
            &source,
            &next,
            CellStateTransitionV1::Preserve {
                checkpoint: digest("checkpoint")
            }
        ),
        Err(CellBundleError::IncompatiblePreservedState)
    );
    let reset = prepare_cell_bundle_cutover_v1(
        id("cutover:one"),
        id("owner:state"),
        partition(),
        &source,
        &next,
        CellStateTransitionV1::Reset {
            initializer: digest("initializer"),
            target_checkpoint: digest("reset"),
        },
    )
    .fixture("reset");
    assert_ne!(reset.plan_digest(), original.plan_digest());
    assert_eq!(
        prepare_cell_bundle_cutover_v1(
            id("cutover:one"),
            id("owner:state"),
            partition(),
            &source,
            &next,
            CellStateTransitionV1::Migrate {
                transform: digest("transform"),
                source_checkpoint: digest("old"),
                target_checkpoint: digest("migrated"),
                qualification: Digest32::ZERO
            }
        ),
        Err(CellBundleError::InvalidStateTransition)
    );
}

#[test]
fn bundle_binds_every_component_and_rejects_missing_lineage() {
    let source = bundle();
    let expected = source.digest().fixture("bundle");
    let changes: [fn(&mut CellBundleComponentsV1); 13] = [
        |c| c.base = digest("changed"),
        |c| c.organ_adapter = Some(digest("changed")),
        |c| c.cell_adapter = Some(digest("changed")),
        |c| c.heads = digest("changed"),
        |c| c.composition = digest("changed"),
        |c| c.encoder = digest("changed"),
        |c| c.tokenizer = digest("changed"),
        |c| c.normalizer = digest("changed"),
        |c| c.calibration = digest("changed"),
        |c| c.numeric_profile = digest("changed"),
        |c| c.output_schema = digest("changed"),
        |c| c.state_schema = digest("changed"),
        |c| c.state_semantics = digest("changed"),
    ];
    for change in changes {
        let mut altered = source.clone();
        change(&mut altered.components);
        assert_ne!(altered.digest().fixture("altered"), expected);
    }
    let mut next = successor(&source);
    next.training_lineage = None;
    assert_eq!(next.digest(), Err(CellBundleError::MissingLineage));
}

#[test]
fn readback_rejects_other_partition_owner_operation_version_or_checkpoint() {
    let source = bundle();
    let mut next = successor(&source);
    next.components.cell_adapter = Some(digest("adapter"));
    let plan = prepare_cell_bundle_cutover_v1(
        id("cutover:one"),
        id("owner:state"),
        partition(),
        &source,
        &next,
        CellStateTransitionV1::Migrate {
            transform: digest("transform"),
            source_checkpoint: digest("checkpoint"),
            target_checkpoint: digest("migrated"),
            qualification: digest("qualified"),
        },
    )
    .fixture("plan");
    let receipt = CellBundleCutoverReceiptV1 {
        operation_id: plan.operation_id().clone(),
        state_owner: plan.state_owner().clone(),
        state_partition_digest: plan.state_partition().digest(),
        plan_digest: plan.plan_digest(),
        observed_bundle: plan.successor_bundle(),
        observed_generation: plan.successor_generation(),
        observed_checkpoint: digest("migrated"),
        owner_receipt_digest: digest("committed"),
    };
    assert_eq!(validate_cell_bundle_readback_v1(&plan, &receipt), Ok(()));
    let changes: [fn(&mut CellBundleCutoverReceiptV1); 6] = [
        |r| r.state_partition_digest = digest("wrong-partition"),
        |r| r.state_owner = id("wrong:owner"),
        |r| r.operation_id = id("wrong:operation"),
        |r| r.observed_bundle = digest("wrong"),
        |r| r.observed_checkpoint = digest("old-state"),
        |r| r.observed_generation = Generation::new(1).fixture("generation"),
    ];
    for change in changes {
        let mut altered = receipt.clone();
        change(&mut altered);
        assert_eq!(
            validate_cell_bundle_readback_v1(&plan, &altered),
            Err(CellBundleError::WrongOwnerReceipt)
        );
    }
    let mut other = partition();
    other.cell_id = id("cell:other");
    let other_plan = prepare_cell_bundle_cutover_v1(
        id("cutover:one"),
        id("owner:state"),
        other,
        &source,
        &next,
        plan.transition().clone(),
    )
    .fixture("other partition plan");
    assert_ne!(other_plan.plan_digest(), plan.plan_digest());
}

#[test]
fn rollback_is_a_new_generation_bound_to_the_actual_current_bundle() {
    let source = bundle();
    let mut current = successor(&source);
    current.components.cell_adapter = Some(digest("candidate"));
    let mut rollback = successor(&current);
    rollback.artifact_id = id("artifact:rollback");
    rollback.components = source.components.clone();
    let plan = prepare_cell_bundle_cutover_v1(
        id("rollback:one"),
        id("owner:state"),
        partition(),
        &current,
        &rollback,
        CellStateTransitionV1::Reset {
            initializer: digest("base-initializer"),
            target_checkpoint: digest("clean"),
        },
    )
    .fixture("rollback");
    assert_eq!(
        plan.successor_generation(),
        Generation::new(3).fixture("generation")
    );
    rollback.rollback_predecessor = Some(source.digest().fixture("base"));
    assert_eq!(rollback.digest(), Err(CellBundleError::WrongPredecessor));
}
