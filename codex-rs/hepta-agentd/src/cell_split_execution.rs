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
use std::sync::Arc;

use codex_hepta_evidence::metrics_group_commit::MetricPhaseV1;
use codex_hepta_evidence::metrics_group_commit::MetricsCommittedSampleQueryV1;
use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;

use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_operator_acceptance::CellSplitEvidenceMetricBindingV1;
use codex_hepta_operator_acceptance::CellSplitExecutionCliOutcomeV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use codex_hepta_operator_acceptance::CellSplitExecutionTranscriptV1;
use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_with_admission_and_metrics_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::neuron_ndu_read::NduReadVerifierV1;
use crate::neuron_ndu_read::SignedNduSnapshotReadV1;

/// One atomic Control observation. All three digests must come from the same
/// independently authenticated Control revision, never separate cache reads.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitCurrentControlSnapshotV1 {
    pub control_revision: u64,
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
}

/// Independently owned current Control/Selector admission. This port MUST
/// inspect the live scope registry and Selector membership/frontier, not
/// derive the scope digest from a caller-provided snapshot or treat the old
/// opaque VerifiedSelection token as a fresh authorization.
pub trait CellSplitScopeSelectionAdmissionV1 {
    type Error: std::fmt::Display;

    /// Return an authoritative same-revision Scope, Objective and NDU view.
    fn current_control_snapshot(
        &self,
        scope: &StableId,
    ) -> Result<CellSplitCurrentControlSnapshotV1, Self::Error>;

    /// Resolve the independently *selected successor route plan* commitment
    /// for this exact split and generation pair from current Selector state.
    /// This is NOT a serving CNS route: the successor is not cut over yet.
    /// The live CNS owner must separately verify predecessor and successor
    /// routes, writer fencing, and final-use at the actual cutover boundary.
    fn current_selected_route_fence_digest(
        &self,
        scope: &StableId,
        split_id: &StableId,
        parent_generation: u64,
        child_generation: u64,
    ) -> Result<Digest32, Self::Error>;

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

/// Compatibility entry without an Evidence-owned durable writer is denied.
/// Even independently valid Selector/NDU membership is not enough for a
/// production CellSplit mutation without auditable phase observations.
/// Transcript recovery remains available through the read-only CLI path.
#[allow(clippy::too_many_arguments)]
pub fn advance_scope_bound_selected_cell_split_v1<A: CellSplitScopeSelectionAdmissionV1>(
    _config_path: &Path,
    _externally_pinned_config_sha256: &str,
    _selected_scope_id: &StableId,
    _selected_split_id: &StableId,
    _selection: &VerifiedSelfEvolutionSelectionV1,
    _signed_ndu_read: &SignedNduSnapshotReadV1,
    _ndu_read_verifier: &NduReadVerifierV1,
    _admission: &A,
) -> Result<CellSplitExecutionCliOutcomeV1, String> {
    Err("CellSplit advancement requires an Evidence-owned durable phase metric sink".into())
}

/// Opt-in product ingress with an actual Evidence-owned durable writer,
/// independently admitted live Scope/Selector/NDU and four original effect
/// owners. No caller-implemented always-healthy metric trait may substitute
/// for DurablePhaseMetricSinkV1 at this Agentd boundary.
///
/// The Evidence sink does not authorize anything: each original CAS, child
/// migration, CNS and Supervisor owner must still verify fresh Final-use.
#[allow(clippy::too_many_arguments)]
pub fn advance_scope_bound_selected_cell_split_with_metrics_v1<
    A: CellSplitScopeSelectionAdmissionV1,
>(
    config_path: &Path,
    externally_pinned_config_sha256: &str,
    selected_scope_id: &StableId,
    selected_split_id: &StableId,
    selection: &VerifiedSelfEvolutionSelectionV1,
    signed_ndu_read: &SignedNduSnapshotReadV1,
    ndu_read_verifier: &NduReadVerifierV1,
    admission: &A,
    metric_sink: Arc<DurablePhaseMetricSinkV1>,
) -> Result<CellSplitExecutionCliOutcomeV1, String> {
    // The coordinator distinguishes new execution from a durable prepared
    // intent. Never deny read-only original-owner reconciliation merely
    // because telemetry is unhealthy; the owner blocks any new dispatch.

    run_pinned_cell_split_execution_with_admission_and_metrics_v1(
        "advance",
        config_path,
        externally_pinned_config_sha256,
        metric_sink,
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
            let before = validate_current_control_binding(
                plan,
                selected_scope_id,
                &signed_ndu_read.snapshot.scope_id,
                selected.objective_digest,
                admission,
            )?;
            // Independently refresh Selector membership, not merely the
            // signature originally verified when the token was constructed.
            admission
                .verify_current_selection(selected_scope_id, selected_split_id, selection)
                .map_err(|e| format!("current independent Selector rejected split: {e}"))?;
            validate_selected_route_binding(plan, selected_scope_id, selected_split_id, admission)?;
            // Verify NDU signature, protected time and live Control frontier
            // immediately before the coordinator can create an intent.
            ndu_read_verifier
                .verify(signed_ndu_read)
                .map_err(|e| format!("current signed NDU read denied: {e}"))?;
            // Independent signature verification may span a Control revision.
            // An ABA replacement is still a new revision even if all digests
            // happen to match. Recheck independent Selector membership and
            // the selected successor route without minting cutover authority.
            let after = validate_current_control_binding(
                plan,
                selected_scope_id,
                &signed_ndu_read.snapshot.scope_id,
                selected.objective_digest,
                admission,
            )?;
            ensure_control_frontier_unchanged(before, after)?;
            admission
                .verify_current_selection(selected_scope_id, selected_split_id, selection)
                .map_err(|e| format!("current independent Selector rejected split: {e}"))?;
            validate_selected_route_binding(plan, selected_scope_id, selected_split_id, admission)?;
            Ok(())
        },
    )
}

/// Adapter from the REAL Evidence-owned durable writer into the existing
/// independent Observer verifier's lightweight typed candidate.
///
/// This READ-ONLY function never signs, flushes, reconciles or dispatches a
/// Split effect. The transcript and local sample are NOT trusted on their own:
/// the external independent Observer retention + real four-owner Deep Join
/// must still validate them under separately pinned keys.
pub fn read_original_cell_split_metric_candidate_v1(
    original_evidence: &DurablePhaseMetricSinkV1,
    transcript: &CellSplitExecutionTranscriptV1,
    step_index: usize,
) -> Result<Option<CellSplitEvidenceMetricBindingV1>, String> {
    if transcript.receipts.len() != 4 {
        return Err("Evidence readback requires four frozen owner receipts".into());
    }
    let receipt = transcript
        .receipts
        .get(step_index)
        .ok_or_else(|| "invalid original CellSplit metric step".to_string())?;
    let plan_digest = transcript
        .plan
        .digest()
        .map_err(|error| format!("unverified Evidence plan identity: {error}"))?;
    if receipt.intent.step.index() != step_index
        || receipt.intent.plan_digest != plan_digest
        || receipt.intent.owner_id != transcript.plan.owner_ids[step_index]
    {
        return Err("Evidence original owner receipt is cross-bound".into());
    }
    let scope_digest: Digest32 = transcript
        .plan
        .scope_digest
        .parse()
        .map_err(|_| "Evidence Scope digest is not canonical")?;
    let operation_digest: Digest32 = receipt
        .intent
        .idempotency_key
        .parse()
        .map_err(|_| "Evidence idempotency key is not canonical")?;
    if scope_digest.is_zero() || operation_digest.is_zero() {
        return Err("Evidence original operation digest is missing".into());
    }
    let phase = match receipt.intent.step {
        CellSplitExecutionStepV1::ArtifactCas => MetricPhaseV1::Cas,
        CellSplitExecutionStepV1::ChildStateMigration => MetricPhaseV1::Signature,
        CellSplitExecutionStepV1::CnsRouteCutover => MetricPhaseV1::Cns,
        CellSplitExecutionStepV1::SupervisorGenerationFence => MetricPhaseV1::Signature,
    };
    let query = MetricsCommittedSampleQueryV1 {
        scope_digest,
        operation_digest,
        phase,
        succeeded: true,
    };
    let found = original_evidence
        .read_committed_sample(query)
        .map_err(|error| format!("original Evidence owner readback unavailable: {error:?}"))?;
    let Some(readback) = found else {
        return Ok(None);
    };
    if readback.query != query
        || readback.matching_rows != 1
        || readback.first_group_sequence == 0
        || readback.first_group_sequence != readback.last_group_sequence
    {
        return Err("Evidence sample is not unique and committed".into());
    }
    Ok(Some(CellSplitEvidenceMetricBindingV1 {
        split_id: transcript.plan.split_id.clone(),
        plan_digest,
        scope_digest: readback.query.scope_digest.to_string(),
        operation_digest: readback.query.operation_digest.to_string(),
        phase: readback.query.phase as u8,
        succeeded: readback.query.succeeded,
        matching_rows: readback.matching_rows,
        first_group_sequence: readback.first_group_sequence,
        last_group_sequence: readback.last_group_sequence,
        last_group_head_digest: readback.last_group_head.to_string(),
        terminal_group_sequence: readback.frontier.sequence,
        terminal_head_digest: readback.frontier.head_digest.to_string(),
        terminal_committed_rows: readback.frontier.committed_rows,
        terminal_journal_bytes: readback.frontier.journal_bytes,
        wal_device: readback.frontier.wal_device,
        wal_inode: readback.frontier.wal_inode,
        marker_device: readback.frontier.marker_device,
        marker_inode: readback.frontier.marker_inode,
    }))
}

fn validate_current_control_binding<A: CellSplitScopeSelectionAdmissionV1>(
    plan: &CellSplitExecutionPlanV1,
    requested_scope: &StableId,
    ndu_read_scope: &StableId,
    selected_objective_digest: Digest32,
    admission: &A,
) -> Result<CellSplitCurrentControlSnapshotV1, String> {
    if requested_scope != ndu_read_scope {
        return Err("NDU snapshot scope differs from selected execution scope".into());
    }
    if selected_objective_digest.is_zero() {
        return Err("frozen Selector objective is missing".into());
    }
    let current = admission
        .current_control_snapshot(requested_scope)
        .map_err(|e| format!("current Control snapshot unavailable: {e}"))?;
    if current.control_revision == 0 {
        return Err("current Control revision is missing".into());
    }
    if current.scope_digest.is_zero() || current.scope_digest.to_string() != plan.scope_digest {
        return Err("current Control scope differs from frozen CellSplit plan".into());
    }
    if current.objective_digest.is_zero() || current.objective_digest != selected_objective_digest {
        return Err("current Control objective differs from frozen Selector objective".into());
    }
    if current.ndu_snapshot_digest.is_zero()
        || current.ndu_snapshot_digest.to_string() != plan.ndu_snapshot_digest
    {
        return Err("current Control NDU frontier differs from signed CellSplit snapshot".into());
    }
    Ok(current)
}

fn ensure_control_frontier_unchanged(
    before: CellSplitCurrentControlSnapshotV1,
    after: CellSplitCurrentControlSnapshotV1,
) -> Result<(), String> {
    if before != after {
        return Err("Control revision changed during CellSplit admission".into());
    }
    Ok(())
}

fn validate_selected_route_binding<A: CellSplitScopeSelectionAdmissionV1>(
    plan: &CellSplitExecutionPlanV1,
    scope: &StableId,
    split_id: &StableId,
    admission: &A,
) -> Result<(), String> {
    let current = admission
        .current_selected_route_fence_digest(
            scope,
            split_id,
            plan.parent_generation,
            plan.child_generation,
        )
        .map_err(|e| format!("current independent selected route unavailable: {e}"))?;
    if current.is_zero() || current.to_string() != plan.route_fence_digest {
        return Err("current selected route fence differs from frozen CellSplit plan".into());
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
        control_revision: u64,
        current_digest: Digest32,
        current_objective: Digest32,
        current_ndu_snapshot: Digest32,
        route_fence_digest: Digest32,
        unavailable: bool,
    }

    impl CellSplitScopeSelectionAdmissionV1 for CurrentScope {
        type Error = &'static str;

        fn current_control_snapshot(
            &self,
            scope: &StableId,
        ) -> Result<CellSplitCurrentControlSnapshotV1, Self::Error> {
            if self.unavailable || scope != &self.expected_scope {
                Err("independent Control snapshot missing")
            } else {
                Ok(CellSplitCurrentControlSnapshotV1 {
                    control_revision: self.control_revision,
                    scope_digest: self.current_digest,
                    objective_digest: self.current_objective,
                    ndu_snapshot_digest: self.current_ndu_snapshot,
                })
            }
        }

        fn current_selected_route_fence_digest(
            &self,
            scope: &StableId,
            split_id: &StableId,
            parent_generation: u64,
            child_generation: u64,
        ) -> Result<Digest32, Self::Error> {
            if self.unavailable
                || scope != &self.expected_scope
                || split_id.as_str() != "split-one"
                || parent_generation != 7
                || child_generation != 8
            {
                Err("independent CNS binding unavailable")
            } else {
                Ok(self.route_fence_digest)
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
            control_revision: 11,
            current_digest: Digest32::from_array([0x11; 32]),
            current_objective: Digest32::from_array([0x66; 32]),
            current_ndu_snapshot: Digest32::from_array([0x44; 32]),
            route_fence_digest: Digest32::from_array([0x55; 32]),
            unavailable: false,
        };
        let frozen = plan();
        let objective = Digest32::from_array([0x66; 32]);
        assert!(
            validate_current_control_binding(&frozen, &requested, &requested, objective, &current)
                .is_ok()
        );
        assert!(
            validate_current_control_binding(&frozen, &requested, &other, objective, &current)
                .is_err(),
            "a signed NDU snapshot for another scope must not prepare an intent"
        );
        let changed = CurrentScope {
            current_digest: Digest32::from_array([0x77; 32]),
            ..current
        };
        assert!(
            validate_current_control_binding(&frozen, &requested, &requested, objective, &changed)
                .is_err(),
            "a previous Control scope digest is not a current binding"
        );
        let unavailable = CurrentScope {
            unavailable: true,
            ..changed
        };
        assert!(
            validate_current_control_binding(
                &frozen,
                &requested,
                &requested,
                objective,
                &unavailable,
            )
            .is_err(),
            "loss of live scope authority fails closed"
        );
    }

    #[test]
    fn current_selected_route_fence_must_match_frozen_generation() {
        let scope = StableId::new("scope-a").expect("scope");
        let split_id = StableId::new("split-one").expect("split");
        let plan = plan();
        let current = CurrentScope {
            expected_scope: scope.clone(),
            control_revision: 11,
            current_digest: Digest32::from_array([0x11; 32]),
            current_objective: Digest32::from_array([0x66; 32]),
            current_ndu_snapshot: Digest32::from_array([0x44; 32]),
            route_fence_digest: Digest32::from_array([0x55; 32]),
            unavailable: false,
        };
        assert!(validate_selected_route_binding(&plan, &scope, &split_id, &current).is_ok());

        let another_split = StableId::new("different-split").expect("other split");
        assert!(validate_selected_route_binding(&plan, &scope, &another_split, &current).is_err());
        let another_generation = CellSplitExecutionPlanV1 {
            child_generation: 9,
            ..plan.clone()
        };
        assert!(
            validate_selected_route_binding(&another_generation, &scope, &split_id, &current)
                .is_err()
        );
        let stale = CurrentScope {
            route_fence_digest: Digest32::from_array([0x66; 32]),
            ..current
        };
        assert!(validate_selected_route_binding(&plan, &scope, &split_id, &stale).is_err());
        let zero = CurrentScope {
            route_fence_digest: Digest32::ZERO,
            ..stale
        };
        assert!(validate_selected_route_binding(&plan, &scope, &split_id, &zero).is_err());
        let missing = CurrentScope {
            unavailable: true,
            ..zero
        };
        assert!(validate_selected_route_binding(&plan, &scope, &split_id, &missing).is_err());
    }

    #[test]
    fn atomic_control_snapshot_fences_objective_ndu_and_aba_revision() {
        let scope = StableId::new("scope-a").expect("scope");
        let frozen = plan();
        let objective = Digest32::from_array([0x66; 32]);
        let original = CurrentScope {
            expected_scope: scope.clone(),
            control_revision: 11,
            current_digest: Digest32::from_array([0x11; 32]),
            current_objective: objective,
            current_ndu_snapshot: Digest32::from_array([0x44; 32]),
            route_fence_digest: Digest32::from_array([0x55; 32]),
            unavailable: false,
        };
        let observe = |owner: &CurrentScope| {
            validate_current_control_binding(&frozen, &scope, &scope, objective, owner)
        };
        let before = observe(&original).expect("current Control");
        assert!(ensure_control_frontier_unchanged(before, before).is_ok());

        let altered_objective = CurrentScope {
            current_objective: Digest32::from_array([0x77; 32]),
            ..original
        };
        assert!(observe(&altered_objective).is_err());
        let altered_ndu = CurrentScope {
            current_objective: objective,
            current_ndu_snapshot: Digest32::from_array([0x88; 32]),
            ..altered_objective
        };
        assert!(observe(&altered_ndu).is_err());

        // Digests may return to their old values after an authority change.
        // Do not treat a different Control revision as the same selection.
        let advanced_revision = CurrentScope {
            control_revision: 12,
            current_ndu_snapshot: Digest32::from_array([0x44; 32]),
            ..altered_ndu
        };
        let after = observe(&advanced_revision).expect("unchanged digest, newer revision");
        assert!(ensure_control_frontier_unchanged(before, after).is_err());

        let missing_revision = CurrentScope {
            control_revision: 0,
            ..advanced_revision
        };
        assert!(observe(&missing_revision).is_err());
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

    fn evidence_transcript_fixture() -> CellSplitExecutionTranscriptV1 {
        use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
        use codex_hepta_operator_acceptance::CellSplitExecutionReceiptV1;

        let frozen = plan();
        let digest = frozen.digest().expect("frozen plan");
        let steps = [
            CellSplitExecutionStepV1::ArtifactCas,
            CellSplitExecutionStepV1::ChildStateMigration,
            CellSplitExecutionStepV1::CnsRouteCutover,
            CellSplitExecutionStepV1::SupervisorGenerationFence,
        ];
        let receipts = steps
            .iter()
            .enumerate()
            .map(|(index, step)| CellSplitExecutionReceiptV1 {
                intent: CellSplitExecutionIntentV1 {
                    schema: "hepta.learning.cell-split.execution-owner.v1".into(),
                    plan_digest: digest.clone(),
                    step: *step,
                    owner_id: frozen.owner_ids[index].clone(),
                    idempotency_key: format!("{:02x}", index + 1).repeat(32),
                    previous_receipt_digest: "66".repeat(32),
                },
                owner_sequence: index as u64 + 1,
                output_digest: "77".repeat(32),
                owner_receipt_bytes: Vec::new(),
                owner_signature_bytes: Vec::new(),
                receipt_digest: "88".repeat(32),
            })
            .collect();
        CellSplitExecutionTranscriptV1 {
            plan: frozen,
            receipts,
            transcript_digest: "99".repeat(32),
        }
    }

    #[test]
    fn original_evidence_actor_adapter_never_invents_uncommitted_split_metrics() {
        use codex_hepta_types::PhaseMetricEventV1;
        use codex_hepta_types::PhaseMetricKindV1;
        use codex_hepta_types::PhaseMetricSinkV1 as _;
        use std::os::unix::fs::PermissionsExt as _;

        let dir = tempfile::tempdir().expect("private original Evidence owner");
        std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700))
            .expect("owner-only journal directory");
        let sink = DurablePhaseMetricSinkV1::open(
            dir.path().join("original-split-metrics.wal"),
            8,
            4,
            60_000,
        )
        .expect("original Evidence Writer");
        let transcript = evidence_transcript_fixture();
        let event = PhaseMetricEventV1 {
            scope_digest: Digest32::from_array([0x11; 32]),
            operation_digest: Digest32::from_array([0x01; 32]),
            phase: PhaseMetricKindV1::Cas,
            latency_micros: 1,
            succeeded: true,
        };
        sink.record(event).expect("queued original CAS metric");
        assert_eq!(
            read_original_cell_split_metric_candidate_v1(&sink, &transcript, 0).unwrap(),
            None,
            "unflushed original WAL sample is not independent Evidence"
        );
        sink.flush()
            .expect("real original WAL and F1 fsync barriers");
        let binding = read_original_cell_split_metric_candidate_v1(&sink, &transcript, 0)
            .expect("original readback")
            .expect("one committed CAS metric");
        assert_eq!(binding.phase, 3);
        assert_eq!(binding.matching_rows, 1);
        assert_eq!(binding.first_group_sequence, 1);
        assert_eq!(binding.last_group_sequence, 1);
        assert_eq!(binding.terminal_group_sequence, 1);
        assert_eq!(binding.operation_digest, "01".repeat(32));
        assert_eq!(binding.scope_digest, transcript.plan.scope_digest);
        assert_eq!(
            read_original_cell_split_metric_candidate_v1(&sink, &transcript, 2).unwrap(),
            None,
            "one CAS metric cannot justify an unrelated CNS effect"
        );
        sink.record(event)
            .expect("duplicated telemetry is not a second CAS");
        sink.flush().expect("second original durable metric group");
        assert!(
            read_original_cell_split_metric_candidate_v1(&sink, &transcript, 0).is_err(),
            "duplicate successful CAS samples must never qualify one original effect"
        );
        assert!(
            sink.healthy(),
            "a well-formed duplicate is not WAL corruption"
        );
    }

    #[test]
    fn original_evidence_adapter_denies_invalid_or_cross_bound_transcripts_before_io() {
        use std::os::unix::fs::PermissionsExt as _;

        let dir = tempfile::tempdir().expect("private original Evidence owner");
        std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700))
            .expect("owner-only journal directory");
        let sink =
            DurablePhaseMetricSinkV1::open(dir.path().join("frozen-metrics.wal"), 8, 2, 60_000)
                .expect("original Evidence Writer");
        let mut forged = evidence_transcript_fixture();
        forged.receipts[0].intent.idempotency_key = "00".repeat(32);
        assert!(read_original_cell_split_metric_candidate_v1(&sink, &forged, 0).is_err());
        let mut cross_bound = evidence_transcript_fixture();
        cross_bound.receipts[0].intent.owner_id = "unexpected-owner".into();
        assert!(read_original_cell_split_metric_candidate_v1(&sink, &cross_bound, 0).is_err());
        let mut missing = evidence_transcript_fixture();
        missing.receipts.pop();
        assert!(read_original_cell_split_metric_candidate_v1(&sink, &missing, 0).is_err());
        assert!(
            read_original_cell_split_metric_candidate_v1(&sink, &evidence_transcript_fixture(), 4,)
                .is_err()
        );
        assert!(
            sink.healthy(),
            "rejected read-only callers do not poison Evidence"
        );
    }
}
