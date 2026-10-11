//! Opt-in Agentd ingress for an independently selected CellSplit.
//!
//! The operator coordinator owns the four-step durable intent journal. Agentd
//! must not invent CAS, CNS, Supervisor or final-use receipts. This bridge
//! rechecks the signed, live NDU read and the independently verified
//! longitudinal Selector result against the exact pinned execution plan before
//! the coordinator can prepare an intent.
//!
//! Each effect owner still independently revalidates the current Selector/NDU
//! frontier and final-use grant. This bridge never grants activation, promotion
//! or release authority and is not included in default Agentd startup.

use std::path::Path;

use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_operator_acceptance::CellSplitExecutionCliOutcomeV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_with_admission_v1;
use codex_hepta_types::StableId;

use crate::neuron_ndu_read::NduReadVerifierV1;
use crate::neuron_ndu_read::SignedNduSnapshotReadV1;

/// The split identity must come from Agentd's independently selected, immutable
/// runtime context. A signed Selection is an eligibility/choice proof, not an
/// effect capability; real effect owners must enforce final use themselves.
pub fn advance_selected_cell_split_v1(
    config_path: &Path,
    externally_pinned_config_sha256: &str,
    selected_split_id: &StableId,
    selection: &VerifiedSelfEvolutionSelectionV1,
    signed_ndu_read: &SignedNduSnapshotReadV1,
    ndu_read_verifier: &NduReadVerifierV1,
) -> Result<CellSplitExecutionCliOutcomeV1, String> {
    run_pinned_cell_split_execution_with_admission_v1(
        "advance",
        config_path,
        externally_pinned_config_sha256,
        |plan| {
            let selected = selection.receipt();
            validate_selected_plan_lineage(
                plan,
                selected_split_id.as_str(),
                selected.predecessor_generation.get(),
                selected.candidate_generation.get(),
                &selected.predecessor_artifact_digest.to_string(),
                &selected.candidate_artifact_digest.to_string(),
                &signed_ndu_read.snapshot.snapshot_digest.to_string(),
            )?;
            // Verify signature, protected time and the live Control frontier
            // here, not at construction time. Repeat on every advance.
            ndu_read_verifier
                .verify(signed_ndu_read)
                .map_err(|error| format!("current signed NDU read denied: {error}"))?;
            Ok(())
        },
    )
}

fn validate_selected_plan_lineage(
    plan: &CellSplitExecutionPlanV1,
    selected_split_id: &str,
    predecessor_generation: u64,
    successor_generation: u64,
    predecessor_artifact_digest: &str,
    successor_artifact_digest: &str,
    selected_ndu_snapshot_digest: &str,
) -> Result<(), String> {
    if plan.split_id != selected_split_id
        || plan.parent_generation != predecessor_generation
        || plan.child_generation != successor_generation
        || plan.parent_artifact_digest != predecessor_artifact_digest
        || plan.child_artifact_digest != successor_artifact_digest
        || plan.ndu_snapshot_digest != selected_ndu_snapshot_digest
    {
        return Err("independent NDU/Selector selection differs from frozen CellSplit".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plan() -> CellSplitExecutionPlanV1 {
        CellSplitExecutionPlanV1 {
            split_id: "split-one".to_string(),
            scope_digest: "11".repeat(32),
            parent_generation: 7,
            child_generation: 8,
            parent_artifact_digest: "22".repeat(32),
            child_artifact_digest: "33".repeat(32),
            ndu_snapshot_digest: "44".repeat(32),
            route_fence_digest: "55".repeat(32),
            owner_ids: [
                "artifact-owner".to_string(),
                "migration-owner".to_string(),
                "cns-owner".to_string(),
                "supervisor-owner".to_string(),
            ],
        }
    }

    #[test]
    fn independently_selected_lineage_must_match_every_frozen_identity() {
        let selected = plan();
        let assert_selection = |plan: &CellSplitExecutionPlanV1| {
            validate_selected_plan_lineage(
                plan,
                "split-one",
                7,
                8,
                &"22".repeat(32),
                &"33".repeat(32),
                &"44".repeat(32),
            )
        };
        assert!(assert_selection(&selected).is_ok());

        let mut changed = selected.clone();
        changed.split_id = "other-split".to_string();
        assert!(assert_selection(&changed).is_err());

        changed = selected.clone();
        changed.parent_generation = 6;
        assert!(assert_selection(&changed).is_err());

        changed = selected.clone();
        changed.child_generation = 9;
        assert!(assert_selection(&changed).is_err());

        changed = selected.clone();
        changed.parent_artifact_digest = "aa".repeat(32);
        assert!(assert_selection(&changed).is_err());

        changed = selected.clone();
        changed.child_artifact_digest = "bb".repeat(32);
        assert!(assert_selection(&changed).is_err());

        changed = selected;
        changed.ndu_snapshot_digest = "cc".repeat(32);
        assert!(assert_selection(&changed).is_err());
    }
}
