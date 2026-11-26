use super::*;
use codex_hepta_types::CellBundleBindingV1;
use codex_hepta_types::CellBundleInheritanceV1;
use codex_hepta_types::CellBundleModeV1;
use codex_hepta_types::CellCachePolicyV1;
use codex_hepta_types::CellChildPortBindingV1;
use codex_hepta_types::CellChildV1;
use codex_hepta_types::CellInFlightPolicyV1;
use codex_hepta_types::CellParentDispositionV1;
use codex_hepta_types::CellParentRetirementPlanV1;
use codex_hepta_types::CellPortCompatibilityV1;
use codex_hepta_types::CellResourceDeltaV1;
use codex_hepta_types::CellRouteModeV1;
use codex_hepta_types::CellSplitEvaluationBindingV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::CellStateSplitPlanV1;
use codex_hepta_types::CellStateTransformKindV1;
use codex_hepta_types::CellStateTransformV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(seed: u8) -> Digest32 {
    Digest32::from_array([seed; 32])
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
    let transform = |seed, kind| CellStateTransformV1 {
        kind,
        source_schema_digest: digest(seed),
        target_schema_digest: digest(seed + 1),
        mapping_digest: match kind {
            CellStateTransformKindV1::Partition | CellStateTransformKindV1::Custom => {
                digest(seed + 2)
            }
            CellStateTransformKindV1::Copy | CellStateTransformKindV1::Reset => Digest32::ZERO,
        },
    };
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
            inference_latency_micros: 1,
            training_steps: 2,
            communication_bytes: 3,
            migration_bytes: 4,
            evaluation_steps: 5,
            resident_bytes: 6,
            checkpoint_bytes: 7,
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
fn typed_split_builds_proposal_change_and_runtime_candidate() {
    let split = split();
    let binding = CellSplitTopologyCandidateV1 {
        proposal_digest: digest(150),
        candidate_id: id("candidate.cell-split"),
        module_id: id("organ.module"),
        predecessor_digest: digest(151),
        candidate_graph_digest: digest(152),
        split,
    };
    let change = binding
        .topology_change(
            digest(153),
            digest(154),
            digest(155),
            digest(156),
            digest(157),
            digest(158),
            digest(159),
            digest(160),
        )
        .expect("topology change");
    assert_eq!(change.operation, TopologyOperationV2::Split);
    assert_eq!(
        change.evidence_digest,
        binding
            .split
            .evaluation_subject_digest()
            .expect("split subject digest")
    );

    let runtime = binding
        .build_runtime_candidate()
        .expect("runtime candidate");
    runtime.validate().expect("runtime candidate validates");
    assert_eq!(
        runtime.deltas[0].operation,
        RuntimeTopologyOperationV1::Split
    );
    assert_eq!(runtime.deltas.len(), 3);
}

#[test]
fn typed_split_rejects_zero_topology_digest_before_projection() {
    let binding = CellSplitTopologyCandidateV1 {
        proposal_digest: digest(150),
        candidate_id: id("candidate.cell-split"),
        module_id: id("organ.module"),
        predecessor_digest: Digest32::ZERO,
        candidate_graph_digest: digest(152),
        split: split(),
    };
    assert_eq!(
        binding.build_runtime_candidate(),
        Err(CellSplitTopologyCandidateErrorV1::Contract(
            codex_hepta_types::CellSplitContractErrorV1::EmptyDigest("topology predecessor",)
        ))
    );
}
