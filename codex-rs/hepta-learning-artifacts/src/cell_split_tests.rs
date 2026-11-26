use std::fmt::Debug;

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
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

fn must<T, E: Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
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
            // The generic V1 registry requires one objective lineage.  The
            // typed contract can still carry heterogeneous objectives; those
            // require its sidecar registry adapter instead.
            task_objective_digest: digest(14),
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

fn parent_manifest() -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id("cell.parent"),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(7).expect("generation"),
        predecessor_id: None,
        content_digest: digest(3),
        objective_digest: digest(14),
        support_digest: digest(99),
        producer_id: id("parent-producer"),
        compatibility_digest: digest(4),
        encoded_size_bytes: 1024,
    }
}

fn cas_receipt(
    operation_id: StableId,
    child: &CellParameterBundleManifestV1,
    fence_digest: Digest32,
) -> CellArtifactCasReceiptV1 {
    let mut value = CellArtifactCasReceiptV1 {
        operation_id,
        child_artifact_id: child.artifact_id.clone(),
        payload_digest: child.child_bundle_digest,
        encoded_size_bytes: child.encoded_size_bytes,
        predecessor_cas_head_digest: digest(3),
        fence_digest,
        receipt_digest: Digest32::ZERO,
    };
    value.receipt_digest = value.content_digest();
    value
}

#[test]
fn child_manifests_bind_split_and_payload_digest() {
    let value = split();
    let child = must(CellParameterBundleManifestV1::from_split(
        &value,
        id("cell.parent"),
        id("bundle-owner"),
        &id("cell.a"),
        digest(12),
        2048,
    ));
    child.validate().expect("valid child manifest");
    assert_eq!(child.as_registry_manifest().content_digest, digest(12));
    assert_ne!(child.content_digest(), digest(12));
    let mut materialization = CellParameterBundleMaterializationV1 {
        child_cell_id: id("cell.a"),
        base_digest: digest(30),
        organ_adapter_digest: digest(40),
        cell_adapter_digest: digest(50),
        head_digest: digest(60),
        output_bundle_digest: digest(12),
        encoded_size_bytes: 2048,
        materialization_receipt_digest: Digest32::ZERO,
    };
    materialization.materialization_receipt_digest = materialization.content_digest();
    materialization
        .validate_against(&value, &child)
        .expect("component materialization");
}

#[test]
fn publication_requires_all_receipts_before_registry_commit() {
    let value = split();
    let parent = parent_manifest();
    let children = value
        .children
        .iter()
        .map(|child| {
            CellParameterBundleManifestV1::from_split(
                &value,
                parent.artifact_id.clone(),
                id("bundle-owner"),
                &child.child_cell_id,
                child.child_bundle_digest,
                2048,
            )
        })
        .collect::<Result<Vec<_>, _>>()
        .expect("children");
    let operation_id = id("cell-split-op");
    let mut owner = must(CellArtifactPublicationV1::begin(
        operation_id.clone(),
        &value,
        &parent,
        children,
        Digest32::ZERO,
    ));
    let mut registry = ArtifactRegistry::new();
    must(registry.append(ArtifactEvent::Register {
        event_id: id("parent-register"),
        manifest: parent,
    }));
    assert_eq!(
        owner.commit_registry(&mut registry),
        Err(CellArtifactOwnerErrorV1::InvalidState)
    );

    let receipts = owner
        .children()
        .iter()
        .map(|child| cas_receipt(operation_id.clone(), child, owner.fence_digest()))
        .collect();
    owner
        .record_payloads_durable(receipts)
        .expect("all payload receipts");
    let expected_head = registry.snapshot().head_digest;
    assert_eq!(
        owner.commit_registry(&mut registry),
        Err(CellArtifactOwnerErrorV1::RegistryHeadMismatch)
    );

    // The operation fence was computed against an empty registry head. A new
    // owner using the actual parent head is required; this proves stale fences
    // cannot be reused after a registry transition.
    let _ = expected_head;
}

#[test]
fn publication_quarantine_is_staged_and_rolls_back_to_parent() {
    let value = split();
    let parent = parent_manifest();
    let children = value
        .children
        .iter()
        .map(|child| {
            CellParameterBundleManifestV1::from_split(
                &value,
                parent.artifact_id.clone(),
                id("bundle-owner"),
                &child.child_cell_id,
                child.child_bundle_digest,
                2048,
            )
        })
        .collect::<Result<Vec<_>, _>>()
        .expect("children");
    let operation_id = id("cell-split-op");
    let mut registry = ArtifactRegistry::new();
    must(registry.append(ArtifactEvent::Register {
        event_id: id("parent-register"),
        manifest: parent.clone(),
    }));
    let expected_head = registry.snapshot().head_digest;
    let mut owner = must(CellArtifactPublicationV1::begin(
        operation_id.clone(),
        &value,
        &parent,
        children,
        expected_head,
    ));
    let receipts = owner
        .children()
        .iter()
        .map(|child| cas_receipt(operation_id.clone(), child, owner.fence_digest()))
        .collect();
    owner.record_payloads_durable(receipts).expect("receipts");
    owner.commit_registry(&mut registry).expect("registry");
    assert_eq!(
        owner.acknowledge(),
        Err(CellArtifactOwnerErrorV1::InvalidState)
    );
    owner
        .quarantine_children(&mut registry, id("independent-evaluator"), digest(201))
        .expect("quarantine");
    assert_eq!(owner.state(), CellArtifactPublicationStateV1::Quarantined);
    let parent_id = owner.rollback().expect("rollback");
    assert_eq!(parent_id, id("cell.parent"));
    assert!(registry.is_eligible(&id("cell.parent")));
    assert!(!registry.is_eligible(&id("cell.a")));
    assert!(!registry.is_eligible(&id("cell.b")));
}
