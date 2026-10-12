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
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::neuron_ndu_read::NduReadVerifierV1;
use crate::neuron_ndu_read::SignedNduSnapshotReadV1;

/// Independently owned current Control/Selector admission. This port MUST
/// inspect the live scope registry and Selector membership/frontier, not
/// derive the scope digest from a caller-provided snapshot or treat the old
/// opaque VerifiedSelection token as a fresh authorization.
pub trait CellSplitScopeSelectionAdmissionV1 {
    type Error: std::fmt::Display;

    fn current_scope_digest(&self, scope: &StableId) -> Result<Digest32, Self::Error>;

    /// Read the current Objective revision from the independently owned
    /// Control registry. A previously signed Selector decision is not valid
    /// after this macro-control objective changes, even if Scope is unchanged.
    fn current_objective_digest(&self, scope: &StableId) -> Result<Digest32, Self::Error>;

    fn verify_current_selection(
        &self,
        scope: &StableId,
        split_id: &StableId,
        selected: &VerifiedSelfEvolutionSelectionV1,
    ) -> Result<(), Self::Error>;
}

/// Compatibility entry deliberately remains fail-closed: the original
/// signature has no independent current-scope/Selector reader and therefore
/// cannot establish that the signed NDU snapshot belongs to this split.
/// Use advance_scope_bound_selected_cell_split_v1 with a real registry port.
pub fn advance_selected_cell_split_v1(
    _config_path: &Path,
    _externally_pinned_config_sha256: &str,
    _selected_split_id: &StableId,
    _selection: &VerifiedSelfEvolutionSelectionV1,
    _signed_ndu_read: &SignedNduSnapshotReadV1,
    _ndu_read_verifier: &NduReadVerifierV1,
) -> Result<CellSplitExecutionCliOutcomeV1, String> {
    Err("CellSplit advancement requires independent live scope and Selector admission".into())
}

/// Opt-in admission-bound Agentd ingress. The external caller supplies the
/// selected scope identity from the trusted runtime context; the independently
/// backed Control registry supplies its digest. No cross-scope NDU token or
/// stale Selector result can prepare the first coordinator intent.
///
/// Real Artifact/CNS/Supervisor owners still independently enforce final-use
/// for each effect. This entry never activates a physical split or promotion.
#[allow(clippy::too_many_arguments)]
pub fn advance_scope_bound_selected_cell_split_v1<A: CellSplitScopeSelectionAdmissionV1>(
    config_path: &Path,
    externally_pinned_config_sha256: &str,
    selected_scope_id: &StableId,
    selected_split_id: &StableId,
    selection: &VerifiedSelfEvolutionSelectionV1,
    signed_ndu_read: &SignedNduSnapshotReadV1,
    ndu_read_verifier: &NduReadVerifierV1,
    admission: &A,
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
            validate_scope_binding(
                plan,
                selected_scope_id,
                &signed_ndu_read.snapshot.scope_id,
                admission,
            )?;
            validate_objective_binding(selected_scope_id, selected.objective_digest, admission)?;
            // Independently refresh Selector membership, not merely the
            // signature originally verified when the token was constructed.
            admission
                .verify_current_selection(selected_scope_id, selected_split_id, selection)
                .map_err(|e| format!("current independent Selector rejected split: {e}"))?;
            // Verify NDU signature, protected time and live Control frontier
            // immediately before the coordinator can create an intent.
            ndu_read_verifier
                .verify(signed_ndu_read)
                .map_err(|e| format!("current signed NDU read denied: {e}"))?;
            Ok(())
        },
    )
}

fn validate_scope_binding<A: CellSplitScopeSelectionAdmissionV1>(
    plan: &CellSplitExecutionPlanV1,
    requested_scope: &StableId,
    ndu_read_scope: &StableId,
    admission: &A,
) -> Result<(), String> {
    if requested_scope != ndu_read_scope {
        return Err("NDU snapshot scope differs from selected execution scope".into());
    }
    let current = admission
        .current_scope_digest(requested_scope)
        .map_err(|e| format!("current Control scope unavailable: {e}"))?;
    if current.to_string() != plan.scope_digest {
        return Err("current Control scope differs from frozen CellSplit plan".into());
    }
    Ok(())
}

fn validate_objective_binding<A: CellSplitScopeSelectionAdmissionV1>(
    scope: &StableId,
    selected_objective_digest: Digest32,
    admission: &A,
) -> Result<(), String> {
    if selected_objective_digest.is_zero() {
        return Err("frozen Selector objective is missing".into());
    }
    let current = admission
        .current_objective_digest(scope)
        .map_err(|e| format!("current Control objective unavailable: {e}"))?;
    if current.is_zero() || current != selected_objective_digest {
        return Err("current Control objective differs from frozen Selector objective".into());
    }
    Ok(())
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

    struct CurrentScope {
        expected_scope: StableId,
        current_digest: Digest32,
        current_objective: Digest32,
        unavailable: bool,
    }

    impl CellSplitScopeSelectionAdmissionV1 for CurrentScope {
        type Error = &'static str;

        fn current_scope_digest(&self, scope: &StableId) -> Result<Digest32, Self::Error> {
            if self.unavailable || scope != &self.expected_scope {
                Err("independent Control scope missing")
            } else {
                Ok(self.current_digest)
            }
        }

        fn current_objective_digest(&self, scope: &StableId) -> Result<Digest32, Self::Error> {
            if self.unavailable || scope != &self.expected_scope {
                Err("independent Control objective missing")
            } else {
                Ok(self.current_objective)
            }
        }

        fn verify_current_selection(
            &self,
            _scope: &StableId,
            _split_id: &StableId,
            _selected: &VerifiedSelfEvolutionSelectionV1,
        ) -> Result<(), Self::Error> {
            Err("fixture never issues Selector approval")
        }
    }

    #[test]
    fn scope_bound_admission_rejects_cross_scope_ndu_and_scope_frontier_drift() {
        let requested = StableId::new("scope-a").expect("scope");
        let other = StableId::new("scope-b").expect("other scope");
        let current = CurrentScope {
            expected_scope: requested.clone(),
            current_digest: Digest32::from_array([0x11; 32]),
            current_objective: Digest32::from_array([0x66; 32]),
            unavailable: false,
        };
        let frozen = plan();
        assert!(validate_scope_binding(&frozen, &requested, &requested, &current).is_ok());
        assert!(
            validate_scope_binding(&frozen, &requested, &other, &current).is_err(),
            "a signed NDU snapshot for another scope must not prepare an intent"
        );
        let changed = CurrentScope {
            current_digest: Digest32::from_array([0x77; 32]),
            ..current
        };
        assert!(
            validate_scope_binding(&frozen, &requested, &requested, &changed).is_err(),
            "a previous Control scope digest is not a current binding"
        );
        let unavailable = CurrentScope {
            unavailable: true,
            ..changed
        };
        assert!(
            validate_scope_binding(&frozen, &requested, &requested, &unavailable).is_err(),
            "loss of live scope authority fails closed"
        );
    }

    #[test]
    fn current_control_objective_fences_stale_ndu_selector_decisions() {
        let scope = StableId::new("scope-a").expect("scope");
        let frozen_objective = Digest32::from_array([0x66; 32]);
        let current = CurrentScope {
            expected_scope: scope.clone(),
            current_digest: Digest32::from_array([0x11; 32]),
            current_objective: frozen_objective,
            unavailable: false,
        };
        assert!(validate_objective_binding(&scope, frozen_objective, &current).is_ok());
        assert!(validate_objective_binding(&scope, Digest32::ZERO, &current).is_err());

        // Scope and signed Selection can remain unchanged while the actual
        // Objective owner has moved to a new revision. Reject before intent.
        let changed = CurrentScope {
            current_objective: Digest32::from_array([0x77; 32]),
            ..current
        };
        assert!(validate_objective_binding(&scope, frozen_objective, &changed).is_err());
        let unavailable = CurrentScope {
            unavailable: true,
            ..changed
        };
        assert!(validate_objective_binding(&scope, frozen_objective, &unavailable).is_err());
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
