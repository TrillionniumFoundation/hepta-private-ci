//! Synthetic gate measurements test action wiring, not empirical net benefit.

use std::collections::BTreeMap;

use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_plasticity::*;
use codex_hepta_types::Generation;
use serde_json::Value;
use serde_json::json;

use super::*;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_release::test_support::digest;
use crate::memory_cell_release::test_support::id;
use crate::memory_cell_release::test_support::single_value_model;
use crate::memory_cell_runtime_tests::TestRoute;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_runtime_tests::attach;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request as read_request;

fn population(
    snapshot: &MemoryCellOwnerSnapshotV1,
    kind: MemoryCellKindV1,
    count: usize,
) -> Vec<u8> {
    let template: Value = serde_json::from_slice(&single_value_model(snapshot, kind)).unwrap();
    let supports = template["supports"].as_object().unwrap();
    let addresses = supports.keys().cloned().collect::<Vec<_>>();
    let routes: BTreeMap<_, _> = addresses
        .iter()
        .enumerate()
        .map(|(rank, key)| (key.clone(), rank * count / addresses.len()))
        .collect();
    let mut shards = Vec::new();
    for index in 0..count {
        let selected: BTreeMap<_, _> = supports
            .iter()
            .filter(|(key, _)| routes[*key] == index)
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        let mut model = template.clone();
        let mut lineage = selected
            .values()
            .flat_map(|value| value.as_array().unwrap())
            .cloned()
            .collect::<Vec<_>>();
        lineage.sort_by(|left, right| left.as_str().cmp(&right.as_str()));
        model["supports"] = json!(selected);
        model["lineage_sources"] = json!(lineage);
        let raw = serde_json::to_string(&model).unwrap();
        shards.push(json!({"digest":Digest32::of_bytes(raw.as_bytes()).to_string(),"payload":raw}));
    }
    serde_json::to_vec(
        &json!({"schema":"hepta.memory.population.native.v2","kind":kind,
        "partition_profile":"hepta.memory.sha256-address-rank.v1","shards":shards,"routes":routes,
        "lineage_sources":template["lineage_sources"]}),
    )
    .unwrap()
}

fn measurement(
    artifact: Digest32,
    role: MemoryStructureRoleV1,
    shards: u8,
) -> MemoryStructureMeasurementV1 {
    let changed = matches!(
        role,
        MemoryStructureRoleV1::Split | MemoryStructureRoleV1::Merge
    );
    MemoryStructureMeasurementV1 {
        artifact_digest: artifact,
        source_cut_digest: digest("test-cut"),
        task_set_digest: digest("test-task"),
        training_profile_digest: digest("test-profile"),
        role,
        shards,
        queries: 100,
        errors: if changed { 0 } else { 10 },
        retention_queries: 100,
        retention_errors: 0,
        independent_evaluation: true,
        cost: MemoryStructureCostV1 {
            artifact_bytes: 1000,
            raw_cache_bytes: 800,
            resident_payload_bytes: 300,
            resident_metadata_bytes: 200,
            catalog_bytes: 80,
            route_bytes: 20,
            source_ledger_bytes: Some(4000),
            search_wall_ns: Some(100),
            training_wall_ns: Some(1000),
            replay_wall_ns: Some(200),
            read_compute_wall_ns: Some(if changed { 80 } else { 100 }),
            wake_wall_ns: Some(10),
            communication_wall_ns: Some(20),
            communication_bytes: Some(50),
        },
    }
}

fn request(
    keep: Digest32,
    candidate: Digest32,
    operation: TopologyOperationV2,
    decision: &MemoryStructureDecisionV1,
) -> TopologyProposalRequestV2 {
    let evidence = decision.evidence_digest();
    TopologyProposalRequestV2 {
        proposal_id: id("memory:v9-proposal"),
        proposer_id: id("memory:v9-learner"),
        evaluator_id: id("memory:v9-independent"),
        selected_artifact_digest: keep,
        window: ProposalWindowV2 {
            window_id: id("memory:v9-window"),
            window_digest: digest("test-window"),
        },
        baseline_generation: Generation::new(1).unwrap(),
        candidate_generation: Generation::new(2).unwrap(),
        evaluation_digest: evidence,
        rollback_predecessor_digest: keep,
        changes: vec![TopologyChangeV2 {
            module_id: id("memory:v9-populations"),
            operation,
            predecessor_digest: Some(keep),
            candidate_digest: Some(candidate),
            capability_typing_digest: digest("test-type"),
            compatibility_plan_digest: digest("test-compatible"),
            lesion_ablation_digest: digest("test-ablation"),
            resource_review_digest: evidence,
            security_review_digest: digest("test-security"),
            migration_digest: digest("test-migration"),
            rollback_digest: digest("test-rollback"),
            writer_handoff_digest: digest("test-handoff"),
            evidence_digest: evidence,
        }],
    }
}

#[tokio::test]
async fn split_merge_sleep_wake_use_real_owner_and_independent_selection() {
    for (before, after, operation, role) in [
        (
            2,
            4,
            TopologyOperationV2::Split,
            MemoryStructureRoleV1::Split,
        ),
        (
            4,
            2,
            TopologyOperationV2::Merge,
            MemoryStructureRoleV1::Merge,
        ),
    ] {
        let owner = ControlFixture::new().await;
        let initial = owner.snapshot().await;
        for index in 0..3 {
            for kind in [
                MemoryCellKindV1::Event,
                MemoryCellKindV1::Semantic,
                MemoryCellKindV1::Procedure,
            ] {
                let mut record = initial
                    .current(&ContractIdV1::new("meter:agentd-cell").unwrap(), kind)
                    .unwrap()
                    .record
                    .clone();
                record.entity = ContractIdV1::new(format!("meter:v9-action-{index}")).unwrap();
                owner
                    .store
                    .write_memory_cell(
                        &owner.access(),
                        &CognitiveScope::AgentPrivate,
                        &record,
                        MemoryCellWriteModeV1::Create,
                    )
                    .await
                    .unwrap();
            }
        }
        let snapshot = owner.snapshot().await;
        let release = ReleaseFixture::from_populations_with_training_code(
            &snapshot,
            &population(&snapshot, MemoryCellKindV1::Semantic, before),
            &population(&snapshot, MemoryCellKindV1::Procedure, before),
            digest("synthetic-action-no-training"),
        );
        let resolver = TrustedTestResolver::new(&owner);
        let runtime = attach(&owner, &release, &resolver);
        let selected = release.host.load_current().unwrap();
        let keep = selected.bundle_digest().to_string().parse().unwrap();
        let candidate = release.prepare_populations(
            &snapshot,
            2,
            &population(&snapshot, MemoryCellKindV1::Semantic, after),
            &population(&snapshot, MemoryCellKindV1::Procedure, after),
            digest("synthetic-action-no-training"),
        );
        let target = candidate.admission.validated_manifest.manifest.bytes_digest;
        let budget = MemoryStructureBudgetV1 {
            required_fixed_shards: vec![1, 2, 4],
            max_artifact_bytes: 1_000_000,
            max_resident_payload_bytes: 1_000_000,
            forecast_queries: 100_000,
            max_retention_error_permyriad: 100,
            error_weight: 10_000,
            byte_weight: 1,
            wall_ns_weight: 1,
            communication_byte_weight: 1,
        };
        let mut measured = vec![measurement(
            keep,
            MemoryStructureRoleV1::KeepFixed,
            before as u8,
        )];
        for count in [1, 2, 4] {
            measured.push(measurement(
                digest(&format!("fixed:{count}")),
                MemoryStructureRoleV1::Fixed,
                count,
            ));
        }
        measured.push(measurement(target, role, after as u8));
        measured.last_mut().unwrap().cost.communication_wall_ns = None;
        let missing = evaluate_memory_structure_v1(&budget, &measured).unwrap();
        let unchanged = stage_memory_structure_v9(
            &release.host,
            &snapshot,
            &missing,
            request(keep, target, operation, &missing),
            Some(candidate.clone()),
        )
        .unwrap();
        assert!(unchanged.publication.is_none());
        assert_eq!(
            release.host.load_current().unwrap().bundle_digest(),
            selected.bundle_digest()
        );
        measured.last_mut().unwrap().cost.communication_wall_ns = Some(20);
        let decision = evaluate_memory_structure_v1(&budget, &measured).unwrap();
        assert_eq!(decision.proposed_digest(), Some(target));
        let staged = stage_memory_structure_v9(
            &release.host,
            &snapshot,
            &decision,
            request(keep, target, operation, &decision),
            Some(candidate.clone()),
        )
        .unwrap();
        assert!(staged.publication.is_some() && !staged.proposal.authority.grants_any());
        assert!(
            release.host.load_current().is_err(),
            "publication cannot select its own candidate"
        );
        release.install(&candidate).unwrap();
        let installed = release.host.load_current().unwrap();
        for cell in [installed.semantic(), installed.procedure()] {
            assert_eq!(cell.shard_count(), after);
            cell.set_resident_budget(2048).unwrap();
        }
        assert!(
            sleep_selected_memory_v9(&release.host, keep).is_err(),
            "obsolete version cannot sleep its replacement"
        );
        let sleeping = sleep_selected_memory_v9(&release.host, target).unwrap();
        assert!(sleeping.iter().all(|cost| cost.resident_shards == 0));
        resolver.set(TestRoute::Read(MemoryOperationV1::Apply));
        assert_eq!(
            owner
                .client
                .memory_cell_read(read_request(snapshot.scope().clone()))
                .await
                .unwrap()
                .status,
            MemoryReadStatusV1::Ok
        );
        assert!(installed.semantic().cost().unwrap().wake_count > 0);
        assert!(installed.procedure().cost().unwrap().wake_count > 0);
        drop(runtime);
        drop(resolver);
        drop(release);
        owner.finish().await;
    }
}
