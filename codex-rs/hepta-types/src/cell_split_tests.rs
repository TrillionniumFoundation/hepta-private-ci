use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(seed: u8) -> Digest32 {
    Digest32::from_array([seed; 32])
}

fn transform(seed: u8, kind: CellStateTransformKindV1) -> CellStateTransformV1 {
    CellStateTransformV1 {
        kind,
        source_schema_digest: digest(seed),
        target_schema_digest: digest(seed + 1),
        mapping_digest: match kind {
            CellStateTransformKindV1::Partition | CellStateTransformKindV1::Custom => {
                digest(seed + 2)
            }
            CellStateTransformKindV1::Copy | CellStateTransformKindV1::Reset => Digest32::ZERO,
        },
    }
}

fn split() -> CellSplitV1 {
    let children = vec![
        CellChildV1 {
            child_cell_id: id("cell.a"),
            child_generation: Generation::new(8).expect("generation"),
            child_scope_digest: digest(10),
            lineage_digest: digest(17),
            child_definition_digest: digest(11),
            child_bundle_digest: digest(12),
            dataset_partition_digest: digest(13),
            task_objective_digest: digest(14),
            route_predicate_digest: digest(15),
            fallback_route_digest: digest(16),
            route_mode: CellRouteModeV1::Exclusive,
        },
        CellChildV1 {
            child_cell_id: id("cell.b"),
            child_generation: Generation::new(8).expect("generation"),
            child_scope_digest: digest(20),
            lineage_digest: digest(27),
            child_definition_digest: digest(21),
            child_bundle_digest: digest(22),
            dataset_partition_digest: digest(23),
            task_objective_digest: digest(24),
            route_predicate_digest: digest(25),
            fallback_route_digest: digest(26),
            route_mode: CellRouteModeV1::Exclusive,
        },
    ];
    let bundles = children
        .iter()
        .enumerate()
        .map(|(index, child)| CellBundleBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            base_digest: digest(30),
            organ_adapter_digest: digest(40),
            cell_adapter_digest: digest(50 + index as u8),
            head_digest: digest(60 + index as u8),
            compatibility_digest: digest(70 + index as u8),
        })
        .collect();
    let ports = children
        .iter()
        .enumerate()
        .map(|(index, child)| CellChildPortBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            input_port_digest: digest(80 + index as u8),
            output_port_digest: digest(90 + index as u8),
            termination_port_digest: digest(100 + index as u8),
            compatibility_digest: digest(110 + index as u8),
        })
        .collect();
    CellSplitV1 {
        split_id: id("split.1"),
        proposer_id: id("proposer"),
        evaluator_id: id("evaluator"),
        parent_cell_id: id("cell.parent"),
        organ_id: id("organ.retrieval"),
        parent_scope_digest: digest(1),
        predecessor_generation: Generation::new(7).expect("generation"),
        successor_generation: Generation::new(8).expect("generation"),
        parent_definition_digest: digest(2),
        parent_bundle_digest: digest(3),
        children,
        inheritance: CellBundleInheritanceV1 {
            base_mode: CellBundleModeV1::SharedImmutable,
            organ_adapter_mode: CellBundleModeV1::SharedImmutable,
            cell_adapter_mode: CellBundleModeV1::CloneMutable,
            head_mode: CellBundleModeV1::CloneMutable,
            compatibility_digest: digest(4),
            children: bundles,
        },
        state: CellStateSplitPlanV1 {
            recurrent: transform(120, CellStateTransformKindV1::Partition),
            eligibility: transform(123, CellStateTransformKindV1::Partition),
            optimizer: transform(126, CellStateTransformKindV1::Reset),
            cache_policy: CellCachePolicyV1::Revalidate,
            in_flight_policy: CellInFlightPolicyV1::Drain,
            state_evidence_digest: digest(129),
        },
        ports: CellPortCompatibilityV1 {
            parent_input_port_digest: digest(130),
            parent_output_port_digest: digest(131),
            circuit_route_digest: digest(132),
            abi_digest: digest(133),
            children: ports,
        },
        resources: CellResourceDeltaV1 {
            inference_latency_micros: 100,
            training_steps: 200,
            communication_bytes: 300,
            migration_bytes: 400,
            evaluation_steps: 500,
            resident_bytes: 600,
            checkpoint_bytes: 700,
        },
        retirement: CellParentRetirementPlanV1 {
            disposition: CellParentDispositionV1::Retire,
            drain_watermark_digest: digest(134),
            tombstone_digest: digest(135),
            deletion_lineage_digest: digest(136),
            rollback_digest: digest(137),
        },
        evaluation: CellSplitEvaluationBindingV1 {
            no_change_baseline_id: id("baseline.no-change"),
            evaluation_id: id("evaluation.1"),
            evaluator_id: id("evaluator"),
            evaluation_receipt_digest: digest(138),
            retention_receipt_digest: digest(139),
            negative_transfer_receipt_digest: digest(140),
            cost_receipt_digest: digest(141),
        },
        rollback_predecessor_digest: digest(142),
        evidence_digest: digest(143),
    }
}

#[test]
fn complete_split_validates_and_has_stable_digest() {
    let value = split();
    value.validate().expect("valid split");
    assert_eq!(value.content_digest(), value.content_digest());
}

#[test]
fn split_requires_two_children_and_exact_successor() {
    let mut value = split();
    value.children.pop();
    value.inheritance.children.pop();
    value.ports.children.pop();
    assert_eq!(value.validate(), Err(CellSplitContractErrorV1::ChildCount));

    let mut value = split();
    value.successor_generation = Generation::new(9).expect("generation");
    assert_eq!(
        value.validate(),
        Err(CellSplitContractErrorV1::GenerationNotExactSuccessor)
    );
}

#[test]
fn split_rejects_unbound_state_mapping_and_overlapping_routes() {
    let mut value = split();
    value.state.recurrent.mapping_digest = Digest32::ZERO;
    assert_eq!(
        value.validate(),
        Err(CellSplitContractErrorV1::EmptyDigest("recurrent state"))
    );

    let mut value = split();
    value.children[1].route_predicate_digest = value.children[0].route_predicate_digest;
    assert_eq!(
        value.validate(),
        Err(CellSplitContractErrorV1::InvalidRoutePartition)
    );
}

#[test]
fn child_generation_and_lineage_are_required() {
    let mut value = split();
    value.children[0].child_generation = Generation::new(9).expect("generation");
    assert_eq!(
        value.validate(),
        Err(CellSplitContractErrorV1::ChildGenerationMismatch)
    );

    let mut value = split();
    value.children[0].lineage_digest = Digest32::ZERO;
    assert_eq!(
        value.validate(),
        Err(CellSplitContractErrorV1::EmptyDigest("child lineage"))
    );
}

#[test]
fn evaluation_subject_excludes_final_receipts() {
    let value = split();
    let subject = value.evaluation_subject_digest().expect("subject digest");
    let content = value.content_digest().expect("content digest");
    assert_ne!(subject, content);

    let mut changed = value;
    changed.evaluation.evaluation_receipt_digest = digest(201);
    changed.evaluation.retention_receipt_digest = digest(202);
    changed.evaluation.negative_transfer_receipt_digest = digest(203);
    changed.evaluation.cost_receipt_digest = digest(204);
    assert_eq!(
        subject,
        changed.evaluation_subject_digest().expect("subject digest")
    );
    assert_ne!(content, changed.content_digest().expect("content digest"));
}

#[test]
fn split_digest_binds_child_bundle_and_route_semantics() {
    let value = split();
    let original = value.content_digest().expect("digest");
    let mut changed = value;
    changed.children[0].child_bundle_digest = digest(200);
    assert_ne!(original, changed.content_digest().expect("digest"));
}

#[test]
fn proposer_and_evaluator_must_be_distinct() {
    let mut value = split();
    value.evaluator_id = value.proposer_id.clone();
    assert_eq!(
        value.validate(),
        Err(CellSplitContractErrorV1::EvaluatorEqualsProposer)
    );
}

#[test]
fn shared_components_must_have_one_digest_and_partitions_must_be_unique() {
    let mut value = split();
    value.inheritance.children[1].base_digest = digest(201);
    assert_eq!(
        value.validate_plan(),
        Err(CellSplitContractErrorV1::InheritanceModeMismatch("base"))
    );

    let mut value = split();
    value.children[1].dataset_partition_digest = value.children[0].dataset_partition_digest;
    assert_eq!(
        value.validate_plan(),
        Err(CellSplitContractErrorV1::InvalidRoutePartition)
    );
}

#[test]
fn typed_split_binds_to_generic_runtime_delta() {
    let value = split();
    let deltas = value
        .runtime_topology_deltas(id("organ.module"), digest(150), digest(151))
        .expect("runtime deltas");
    assert_eq!(deltas.len(), 3);
    assert_eq!(deltas[0].operation, RuntimeTopologyOperationV1::Split);
    assert_eq!(
        deltas[0].related_module_ids,
        vec![id("cell.a"), id("cell.b")]
    );
    assert_eq!(
        deltas[0].evidence_digest,
        value.content_digest().expect("digest")
    );
    assert!(
        deltas[1..]
            .iter()
            .all(|delta| delta.operation == RuntimeTopologyOperationV1::Add)
    );

    let candidate = value
        .runtime_topology_candidate(
            digest(152),
            id("candidate.cell-split"),
            id("organ.module"),
            digest(150),
            digest(151),
        )
        .expect("runtime candidate");
    candidate.validate().expect("validated runtime candidate");
}
