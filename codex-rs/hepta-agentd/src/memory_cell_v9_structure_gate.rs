//! Actual measurements reach the existing full-fixed inventory gate and owner.
//! Unknown exclusive costs stay None; the observed trial cannot force promotion.

use std::path::Path;

use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_plasticity::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde_json::Value;
use serde_json::json;

use crate::memory_cell_release::stage_memory_structure_v9;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_release::test_support::id;

use super::super::data;

fn sum(costs: &Value, field: &str) -> u64 {
    costs
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item[field].as_u64().unwrap())
        .sum()
}

pub(super) fn evaluate(
    release: &ReleaseFixture,
    snapshot: &MemoryCellOwnerSnapshotV1,
    stage: &data::Stage,
    roles: &[Value],
    directory: &Path,
    code: Digest32,
    ledger_bytes: u64,
) -> Value {
    let keep = roles
        .iter()
        .find(|role| role["role"] == "keep-fixed-2")
        .unwrap();
    let task_set_json =
        serde_json::to_string(&json!({"future":stage.future,"retention":stage.retention})).unwrap();
    let task_digest = Digest32::of_bytes(task_set_json.as_bytes());
    let budget = MemoryStructureBudgetV1 {
        required_fixed_shards: (1..=8).collect(),
        max_artifact_bytes: 16_777_216,
        max_resident_payload_bytes: 32_768,
        forecast_queries: 100_000,
        max_retention_error_permyriad: 0,
        error_weight: 1_000_000_000,
        byte_weight: 1,
        wall_ns_weight: 1,
        communication_byte_weight: 1,
    };
    let mut measurements = Vec::new();
    let mut wires = Vec::new();
    let mut exclusions = Vec::new();
    for item in roles {
        let name = item["role"].as_str().unwrap();
        let count = item["shards"].as_u64().unwrap_or(0) as u8;
        let role = if name == "keep-fixed-2" {
            MemoryStructureRoleV1::KeepFixed
        } else if name.starts_with("fixed-") {
            MemoryStructureRoleV1::Fixed
        } else if name == "prefix-selected-learned" && count != 2 {
            if count > 2 {
                MemoryStructureRoleV1::Split
            } else {
                MemoryStructureRoleV1::Merge
            }
        } else {
            exclusions.push(json!({"role":name,"reason":"reference-only or unchanged cardinality; full episode costs retained"}));
            continue;
        };
        let future = &item["phases"][0];
        let retained = &item["phases"][1];
        let costs = &retained["native_cost"];
        let response: Value = serde_json::from_slice(
            &std::fs::read(
                directory
                    .join(item["fit_directory"].as_str().unwrap())
                    .join("FIT_RESPONSE.json"),
            )
            .unwrap(),
        )
        .unwrap();
        let cost = MemoryStructureCostV1 {
            artifact_bytes: item["publication"]["bundle_bytes"].as_u64().unwrap(),
            raw_cache_bytes: sum(costs, "raw_payload_bytes"),
            resident_payload_bytes: [
                "resident_parameter_bytes",
                "resident_catalog_bytes",
                "resident_support_bytes",
                "resident_lineage_bytes",
            ]
            .iter()
            .map(|field| sum(costs, field))
            .sum(),
            resident_metadata_bytes: ["aggregate_support_bytes", "route_bytes", "lineage_bytes"]
                .iter()
                .map(|field| sum(costs, field))
                .sum(),
            catalog_bytes: sum(costs, "catalog_bytes"),
            route_bytes: sum(costs, "route_bytes"),
            source_ledger_bytes: Some(ledger_bytes),
            search_wall_ns: None,
            training_wall_ns: response["whole_worker_wall_ns"].as_u64(),
            replay_wall_ns: None,
            read_compute_wall_ns: sum(costs, "read_wall_ns")
                .checked_sub(sum(costs, "wake_wall_ns")),
            wake_wall_ns: Some(sum(costs, "wake_wall_ns")),
            communication_wall_ns: None,
            communication_bytes: Some(
                item["phases"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|phase| {
                        phase["traffic"]["transmitted_bytes"].as_u64().unwrap()
                            + phase["traffic"]["received_bytes"].as_u64().unwrap()
                    })
                    .sum(),
            ),
        };
        let measured = MemoryStructureMeasurementV1 {
            artifact_digest: item["publication"]["bundle_digest"]
                .as_str()
                .unwrap()
                .parse()
                .unwrap(),
            source_cut_digest: snapshot.owner_cut_digest().to_string().parse().unwrap(),
            task_set_digest: task_digest,
            training_profile_digest: code,
            role,
            shards: count,
            queries: future["queries"].as_u64().unwrap(),
            errors: future["queries"].as_u64().unwrap() - future["correct"].as_u64().unwrap(),
            retention_queries: retained["queries"].as_u64().unwrap(),
            retention_errors: retained["queries"].as_u64().unwrap()
                - retained["correct"].as_u64().unwrap(),
            independent_evaluation: true,
            cost,
        };
        wires.push(json!({"role":format!("{:?}",measured.role),"artifact_digest":measured.artifact_digest.to_string(),
            "source_cut_digest":measured.source_cut_digest.to_string(),"task_set_digest":task_digest.to_string(),"training_profile_digest":code.to_string(),
            "shards":count,"queries":measured.queries,"errors":measured.errors,"retention_queries":measured.retention_queries,
            "retention_errors":measured.retention_errors,"independent_evaluation":true,
            "cost":{"artifact_bytes":measured.cost.artifact_bytes,"raw_cache_bytes":measured.cost.raw_cache_bytes,
                "resident_payload_bytes":measured.cost.resident_payload_bytes,"resident_metadata_bytes":measured.cost.resident_metadata_bytes,
                "catalog_bytes":measured.cost.catalog_bytes,"route_bytes":measured.cost.route_bytes,
                "source_ledger_bytes":measured.cost.source_ledger_bytes,"search_wall_ns":measured.cost.search_wall_ns,
                "training_wall_ns":measured.cost.training_wall_ns,"replay_wall_ns":measured.cost.replay_wall_ns,
                "read_compute_wall_ns":measured.cost.read_compute_wall_ns,"wake_wall_ns":measured.cost.wake_wall_ns,
                "communication_wall_ns":measured.cost.communication_wall_ns,"communication_bytes":measured.cost.communication_bytes}}));
        measurements.push(measured);
    }
    let decision = evaluate_memory_structure_v1(&budget, &measurements).unwrap();
    assert_eq!(
        decision.reason(),
        MemoryStructureKeepReasonV1::MissingMeasurements
    );
    let baseline = keep["publication"]["generation"].as_u64().unwrap();
    let selected: Digest32 = keep["publication"]["bundle_digest"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    let request = TopologyProposalRequestV2 {
        proposal_id: id("memory:v9-observed-proposal"),
        proposer_id: id("memory:v9-observed-learner"),
        evaluator_id: id("memory:v9-observed-evaluator"),
        selected_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: id("memory:v9-observed-window"),
            window_digest: task_digest,
        },
        baseline_generation: Generation::new(baseline).unwrap(),
        candidate_generation: Generation::new(baseline + 1).unwrap(),
        evaluation_digest: decision.evidence_digest(),
        rollback_predecessor_digest: selected,
        changes: Vec::new(),
    };
    let outcome =
        stage_memory_structure_v9(&release.host, snapshot, &decision, request, None).unwrap();
    assert!(outcome.publication.is_none() && !outcome.proposal.authority.grants_any());
    assert_eq!(
        release.host.load_current().unwrap().generation().get(),
        baseline
    );
    json!({"measurements":wires,"task_set_json":task_set_json,"reference_roles_outside_split_merge_gate":exclusions,
        "reason":format!("{:?}",decision.reason()),"evidence_digest":decision.evidence_digest().to_string(),
        "proposed_digest":decision.proposed_digest().map(|digest|digest.to_string()),"best_fixed_digest":decision.best_fixed_digest().map(|digest|digest.to_string()),
        "proposal_digest":outcome.proposal.proposal_digest.to_string(),"proposal_candidates":outcome.proposal.candidates.len(),
        "owner_publication_performed":false,"selected_generation_unchanged":baseline,"full_cost_gain_established":false})
}
