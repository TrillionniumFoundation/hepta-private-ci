//! One fail-closed execution boundary for physical Cell Split stages.
//!
//! The evaluator/selector cannot mint execution authority here. In particular,
//! a signed selection is a prerequisite, not a replacement for the independent
//! Supervisor handoff and the CNS, CAS, and child-state owners. Every advance
//! below follows an actual owner call and is persisted by the fsync-backed
//! writer-handoff journal. Ambiguous outcomes MUST be reconciled against the
//! authoritative owner; this type never retries the affected external effect.

use std::fs::File;
use std::path::Path;

use codex_hepta_control_plane::CellSplitRouteControllerV1;
use codex_hepta_control_plane::CellSplitRouteErrorV1;
use codex_hepta_control_plane::CellSplitRouteFenceReceiptV1;
use codex_hepta_control_plane::CellSplitRoutePhaseV1;
use codex_hepta_control_plane::CnsOrganHostV1;
use codex_hepta_control_plane::CnsRouteV1;
use codex_hepta_intelligence_eval::CellSplitAutomationErrorV1;
use codex_hepta_intelligence_eval::CellSplitAutomationJournalOwnerV1;
use codex_hepta_intelligence_eval::CellSplitLearningLedgerJournalOwnerV1;
use codex_hepta_intelligence_eval::CellSplitLifecycleStateV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::ArtifactCasOwnerV1;
use codex_hepta_learning_artifacts::ArtifactLoadReceiptV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::ArtifactWriteReceiptV1;
use codex_hepta_learning_artifacts::ProductionOwnerError;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationDisposition;
use codex_hepta_ndu::NduAuthenticatedOwnerV1;
use codex_hepta_ndu::NduEvaluationReceiptV2;
use codex_hepta_ndu::NduOwnerError;
use codex_hepta_neuron::CellStateMigrationErrorV1;
use codex_hepta_neuron::CellStateMigrationPhaseV1;
use codex_hepta_neuron::CellStateMigrationReceiptV1;
use codex_hepta_neuron::CellStateMigrationV1;
use codex_hepta_neuron::DurableCellStateCasDirectoryOwnerV1;
use codex_hepta_supervisor::DurableWriterHandoffJournalV1;
use codex_hepta_supervisor::WriterHandoffAdvanceV1;
use codex_hepta_supervisor::WriterHandoffCheckpointV1;
use codex_hepta_supervisor::WriterHandoffErrorV1;
use codex_hepta_supervisor::WriterHandoffPhaseV1;
use codex_hepta_supervisor::WriterResultFenceErrorV1;
use codex_hepta_supervisor::WriterResultFenceV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;

#[derive(Debug)]
pub enum CellSplitExecutionErrorV1 {
    Binding(&'static str),
    Phase(WriterHandoffPhaseV1),
    Artifact(ProductionOwnerError),
    Migration(CellStateMigrationErrorV1),
    Ndu(NduOwnerError),
    Cns(CellSplitRouteErrorV1),
    Handoff(WriterHandoffErrorV1),
    Lifecycle(CellSplitAutomationErrorV1),
    ResultFence(WriterResultFenceErrorV1),
    Io(std::io::ErrorKind),
}

impl std::fmt::Display for CellSplitExecutionErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for CellSplitExecutionErrorV1 {}

impl From<ProductionOwnerError> for CellSplitExecutionErrorV1 {
    fn from(error: ProductionOwnerError) -> Self {
        Self::Artifact(error)
    }
}
impl From<CellStateMigrationErrorV1> for CellSplitExecutionErrorV1 {
    fn from(error: CellStateMigrationErrorV1) -> Self {
        Self::Migration(error)
    }
}
impl From<NduOwnerError> for CellSplitExecutionErrorV1 {
    fn from(error: NduOwnerError) -> Self {
        Self::Ndu(error)
    }
}
impl From<CellSplitRouteErrorV1> for CellSplitExecutionErrorV1 {
    fn from(error: CellSplitRouteErrorV1) -> Self {
        Self::Cns(error)
    }
}
impl From<WriterHandoffErrorV1> for CellSplitExecutionErrorV1 {
    fn from(error: WriterHandoffErrorV1) -> Self {
        Self::Handoff(error)
    }
}
impl From<CellSplitAutomationErrorV1> for CellSplitExecutionErrorV1 {
    fn from(error: CellSplitAutomationErrorV1) -> Self {
        Self::Lifecycle(error)
    }
}
impl From<WriterResultFenceErrorV1> for CellSplitExecutionErrorV1 {
    fn from(error: WriterResultFenceErrorV1) -> Self {
        Self::ResultFence(error)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitArtifactExecutionReceiptV1 {
    pub write: ArtifactWriteReceiptV1,
    pub load: ArtifactLoadReceiptV1,
    pub handoff: WriterHandoffCheckpointV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitMigrationExecutionReceiptV1 {
    pub migration: CellStateMigrationReceiptV1,
    pub handoff: WriterHandoffCheckpointV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitRouteExecutionReceiptV1 {
    pub route: CellSplitRouteFenceReceiptV1,
    pub handoff: WriterHandoffCheckpointV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitSelectionExecutionReceiptV1 {
    pub ndu: NduEvaluationReceiptV2,
    pub handoff: WriterHandoffCheckpointV1,
}

/// This owner deliberately cannot create a Supervisor "drained", "fenced" or
/// "new writer fenced" fact from caller-supplied hashes. Those phases must
/// first be committed by the actual Supervisor with its live outbox/lease
/// observations. Nor does this object turn a selected cell into production
/// authority: a separate operator grant is still required at final use.
pub struct CellSplitExecutionOwnerV1 {
    split: CellSplitV1,
    selection: VerifiedSelfEvolutionSelectionV1,
    handoff: DurableWriterHandoffJournalV1,
    lifecycle: CellSplitLearningLedgerJournalOwnerV1,
    artifacts: ArtifactCasOwnerV1,
    child_state: DurableCellStateCasDirectoryOwnerV1,
    routes: CellSplitRouteControllerV1,
}

impl CellSplitExecutionOwnerV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn bind(
        split: CellSplitV1,
        selection: VerifiedSelfEvolutionSelectionV1,
        handoff: DurableWriterHandoffJournalV1,
        lifecycle: CellSplitLearningLedgerJournalOwnerV1,
        artifacts: ArtifactCasOwnerV1,
        child_state: DurableCellStateCasDirectoryOwnerV1,
        routes: CellSplitRouteControllerV1,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        split
            .validate()
            .map_err(|_| CellSplitExecutionErrorV1::Binding("complete split"))?;
        let plan = &handoff.checkpoint().plan;
        if plan.operation_id != split.split_id
            || plan.domain_id != split.parent_cell_id
            || plan.source_writer != split.parent_cell_id
            || plan.old_generation != split.predecessor_generation
            || plan.new_generation != split.successor_generation
            || plan.rollback_predecessor_digest != split.rollback_predecessor_digest
        {
            return Err(CellSplitExecutionErrorV1::Binding(
                "supervisor handoff plan",
            ));
        }

        let selected = selection.receipt();
        if selected.candidate_id != split.split_id
            || selected.predecessor_id != split.parent_cell_id
            || selected.predecessor_generation != split.predecessor_generation
            || selected.candidate_generation != split.successor_generation
            || selected.predecessor_artifact_digest != split.parent_bundle_digest
            || selected.no_change_baseline_id != split.evaluation.no_change_baseline_id
            || selected.no_change_baseline_digest.is_zero()
            || selection.selector_id() == &split.evaluator_id
        {
            return Err(CellSplitExecutionErrorV1::Binding("independent selection"));
        }
        let admitted =
            lifecycle
                .load(&split.split_id)?
                .ok_or(CellSplitExecutionErrorV1::Binding(
                    "missing witnessed lifecycle",
                ))?;
        // A merely accepted evaluation or in-flight canary is never a physical
        // deployment decision. Retired also allows read-only crash recovery.
        if !matches!(
            admitted.current_state,
            CellSplitLifecycleStateV1::Retained | CellSplitLifecycleStateV1::Retired
        ) {
            return Err(CellSplitExecutionErrorV1::Binding("canary not retained"));
        }
        if matches!(
            handoff.checkpoint().phase,
            WriterHandoffPhaseV1::RoutePublished | WriterHandoffPhaseV1::Retired
        ) && routes.phase() != CellSplitRoutePhaseV1::ChildrenActive
        {
            return Err(CellSplitExecutionErrorV1::Binding(
                "reopened CNS route unavailable",
            ));
        }
        if handoff.checkpoint().phase == WriterHandoffPhaseV1::NewWriterFenced
            && !matches!(
                routes.phase(),
                CellSplitRoutePhaseV1::ParentActive | CellSplitRoutePhaseV1::ChildrenActive
            )
        {
            return Err(CellSplitExecutionErrorV1::Binding("unreconciled CNS route"));
        }
        Ok(Self {
            split,
            selection,
            handoff,
            lifecycle,
            artifacts,
            child_state,
            routes,
        })
    }

    pub fn checkpoint(&self) -> &WriterHandoffCheckpointV1 {
        self.handoff.checkpoint()
    }

    pub fn routes(&self) -> &CellSplitRouteControllerV1 {
        &self.routes
    }

    fn require_phase(&self, phase: WriterHandoffPhaseV1) -> Result<(), CellSplitExecutionErrorV1> {
        if self.handoff.checkpoint().phase != phase {
            return Err(CellSplitExecutionErrorV1::Phase(
                self.handoff.checkpoint().phase,
            ));
        }
        Ok(())
    }

    /// Real create-only Artifact CAS write -> parent directory fsync -> real
    /// authenticated read -> both production-signature checks -> durable
    /// Supervisor snapshot event. A crash between these operations leaves
    /// OldWriterFenced and MUST be reconciled; never overwrite CAS on retry.
    #[allow(clippy::too_many_arguments)]
    pub fn persist_artifact_snapshot(
        &mut self,
        root: &Path,
        relative: &Path,
        registry: &ArtifactRegistry,
        candidate: &StableId,
        bytes: &[u8],
        host_evidence: Digest32,
        observer_evidence: Digest32,
        verifying_key: &VerifyingKey,
    ) -> Result<CellSplitArtifactExecutionReceiptV1, CellSplitExecutionErrorV1> {
        self.require_phase(WriterHandoffPhaseV1::OldWriterFenced)?;
        if candidate != &self.selection.receipt().candidate_id
            || host_evidence.is_zero()
            || observer_evidence.is_zero()
            || Digest32::of_bytes(bytes) != self.selection.receipt().candidate_artifact_digest
        {
            return Err(CellSplitExecutionErrorV1::Binding("candidate CAS binding"));
        }
        let write = self.artifacts.write_candidate(
            self.split.split_id.clone(),
            root,
            relative,
            registry,
            candidate,
            bytes,
            Some(host_evidence),
            Some(observer_evidence),
        )?;
        // Reopen and authenticate actual bytes before entering the durable
        // frontier. If this call fails after CAS create, never call write again:
        // reconcile with the exact signed write receipt and original registry.
        self.reconcile_artifact_snapshot(
            root,
            relative,
            registry,
            &write,
            host_evidence,
            observer_evidence,
            verifying_key,
        )
    }

    /// Recovery only: verify an independently retained signed write receipt,
    /// current registry head and actual existing CAS file. This cannot invent
    /// the lost original write receipt; without it a create-only orphan stays
    /// quarantined for operator reconciliation. No create or overwrite occurs.
    #[allow(clippy::too_many_arguments)]
    pub fn reconcile_artifact_snapshot(
        &mut self,
        root: &Path,
        relative: &Path,
        registry: &ArtifactRegistry,
        write: &ArtifactWriteReceiptV1,
        host_evidence: Digest32,
        observer_evidence: Digest32,
        verifying_key: &VerifyingKey,
    ) -> Result<CellSplitArtifactExecutionReceiptV1, CellSplitExecutionErrorV1> {
        let phase = self.handoff.checkpoint().phase;
        if !matches!(
            phase,
            WriterHandoffPhaseV1::OldWriterFenced | WriterHandoffPhaseV1::Snapshotted
        ) {
            return Err(CellSplitExecutionErrorV1::Phase(phase));
        }
        if write.operation_id != self.split.split_id
            || write.artifact_id != self.selection.receipt().candidate_id
            || write.artifact_digest != self.selection.receipt().candidate_artifact_digest
            || write.registry_head_digest != registry.snapshot().head_digest
            || host_evidence.is_zero()
            || observer_evidence.is_zero()
            || write.host_evidence_digest != Some(host_evidence)
            || write.observer_evidence_digest != Some(observer_evidence)
        {
            return Err(CellSplitExecutionErrorV1::Binding(
                "recovered CAS write receipt",
            ));
        }
        write.verify_production(verifying_key)?;
        let path = root.join(relative);
        let (read_bytes, load) = self.artifacts.load_candidate(
            self.split.split_id.clone(),
            File::open(&path).map_err(|error| CellSplitExecutionErrorV1::Io(error.kind()))?,
            registry,
            &write.artifact_id,
            write,
            relative,
            Some(host_evidence),
            Some(observer_evidence),
        )?;
        load.verify_production(verifying_key)?;
        if Digest32::of_bytes(&read_bytes) != write.artifact_digest
            || load.payload_digest != write.artifact_digest
            || load.operation_id != write.operation_id
        {
            return Err(CellSplitExecutionErrorV1::Binding("CAS readback mismatch"));
        }
        // The CAS owner fsyncs the file; preserve directory-entry durability
        // before publishing a recovered or first-attempt handoff checkpoint.
        File::open(
            path.parent()
                .ok_or(CellSplitExecutionErrorV1::Binding("CAS parent"))?,
        )
        .and_then(|file| file.sync_all())
        .map_err(|error| CellSplitExecutionErrorV1::Io(error.kind()))?;
        let observed = Digest32::of_parts(&[
            b"hepta.cell-split.actual-artifact-cas.v1",
            write.receipt_digest.as_array(),
            load.receipt_digest.as_array(),
        ]);
        let handoff = if phase == WriterHandoffPhaseV1::Snapshotted {
            let saved = self.handoff.checkpoint();
            if saved.evidence_digest != observed {
                return Err(CellSplitExecutionErrorV1::Binding(
                    "reopened CAS handoff differs",
                ));
            }
            saved.clone()
        } else {
            self.handoff.advance(WriterHandoffAdvanceV1 {
                phase: WriterHandoffPhaseV1::Snapshotted,
                evidence_digest: observed,
                outbox_watermark: None,
                unknown_effect_count: 0,
            })?
        };
        Ok(CellSplitArtifactExecutionReceiptV1 {
            write: write.clone(),
            load,
            handoff,
        })
    }

    /// Real child-Q24 CAS and batch marker sync precede migration ack and
    /// durable Supervisor journal advancement. Retrying is allowed only via
    /// the child owner, which reopens and byte-checks existing objects.
    pub fn persist_child_migration(
        &mut self,
        migration: &mut CellStateMigrationV1,
    ) -> Result<CellSplitMigrationExecutionReceiptV1, CellSplitExecutionErrorV1> {
        let phase = self.handoff.checkpoint().phase;
        if !matches!(
            phase,
            WriterHandoffPhaseV1::Snapshotted | WriterHandoffPhaseV1::Migrated
        ) {
            return Err(CellSplitExecutionErrorV1::Phase(phase));
        }
        if migration.phase() != CellStateMigrationPhaseV1::Prepared {
            return Err(CellSplitExecutionErrorV1::Binding("migration not prepared"));
        }
        let receipt = self.child_state.persist_commit_and_acknowledge(migration)?;
        if receipt.operation_id != self.split.split_id
            || receipt.rollback_parent_cell_id != self.split.parent_cell_id
            || receipt.split_digest
                != self
                    .split
                    .evaluation_subject_digest()
                    .map_err(|_| CellSplitExecutionErrorV1::Binding("split subject"))?
            || receipt.phase != CellStateMigrationPhaseV1::Acknowledged
            || receipt.receipt_digest.is_zero()
        {
            return Err(CellSplitExecutionErrorV1::Binding("migration receipt"));
        }
        let handoff = if phase == WriterHandoffPhaseV1::Migrated {
            let saved = self.handoff.checkpoint();
            if saved.evidence_digest != receipt.receipt_digest {
                return Err(CellSplitExecutionErrorV1::Binding(
                    "reopened child migration differs",
                ));
            }
            saved.clone()
        } else {
            self.handoff.advance(WriterHandoffAdvanceV1 {
                phase: WriterHandoffPhaseV1::Migrated,
                evidence_digest: receipt.receipt_digest,
                outbox_watermark: None,
                unknown_effect_count: 0,
            })?
        };
        Ok(CellSplitMigrationExecutionReceiptV1 {
            migration: receipt,
            handoff,
        })
    }

    /// No-change comparison is evaluated by the live, policy-frozen NDU
    /// owner. Arbitrary NDU advice cannot replace the independently signed
    /// Selector/evaluator/observer chain: it can only veto the already
    /// retained candidate. Only a unique/scalarized recommendation may pass.
    /// Candidate and baseline source digests must be explicitly pinned to
    /// authenticated independent evidence, not newly asserted utility data.
    pub fn validate_selection(
        &mut self,
        ndu: &NduAuthenticatedOwnerV1,
        contributions: ContributionSet,
    ) -> Result<CellSplitSelectionExecutionReceiptV1, CellSplitExecutionErrorV1> {
        self.require_phase(WriterHandoffPhaseV1::Migrated)?;
        let selected = self.selection.receipt();
        let baseline_id = &selected.no_change_baseline_id;
        if contributions.objective_digest != selected.objective_digest
            || contributions.generation != self.split.successor_generation
            || selected.candidate_id == *baseline_id
            || !contributions.contributions.iter().any(|row| {
                row.candidate_id == selected.candidate_id
                    && row.support_digest == selected.evaluation_evidence_digest
            })
            || !contributions.contributions.iter().any(|row| {
                row.candidate_id == *baseline_id
                    && row.support_digest == selected.no_change_baseline_digest
            })
        {
            return Err(CellSplitExecutionErrorV1::Binding(
                "NDU candidate/no-change baseline source",
            ));
        }
        let ndu_receipt = ndu.evaluate(contributions)?;
        if ndu_receipt.base.objective_digest != selected.objective_digest
            || ndu_receipt.base.generation != self.split.successor_generation
            || ndu_receipt.base.advisory_recommendation.as_ref() != Some(&selected.candidate_id)
            || !matches!(
                ndu_receipt.base.disposition,
                EvaluationDisposition::UniqueParetoRecommendation
                    | EvaluationDisposition::ScalarizedRecommendation
            )
            || !ndu_receipt
                .base
                .evaluated_candidates
                .iter()
                .any(|row| row.candidate_id == *baseline_id)
            || !ndu_receipt
                .base
                .evaluated_candidates
                .iter()
                .any(|row| row.candidate_id == selected.candidate_id)
            || ndu_receipt.evaluation_digest_v2.is_zero()
        {
            return Err(CellSplitExecutionErrorV1::Binding(
                "NDU did not select independently evaluated candidate",
            ));
        }
        let lifecycle = self.lifecycle.load(&self.split.split_id)?.ok_or(
            CellSplitExecutionErrorV1::Binding("missing lifecycle after migration"),
        )?;
        if lifecycle.current_state != CellSplitLifecycleStateV1::Retained {
            return Err(CellSplitExecutionErrorV1::Binding("retention revoked"));
        }
        let evidence = Digest32::of_parts(&[
            b"hepta.cell-split.actual-ndu-and-independent-selection.v1",
            self.selection.selection_digest().as_array(),
            lifecycle.head_digest.as_array(),
            ndu_receipt.evaluation_digest_v2.as_array(),
        ]);
        let handoff = self.handoff.advance(WriterHandoffAdvanceV1 {
            phase: WriterHandoffPhaseV1::Validated,
            evidence_digest: evidence,
            outbox_watermark: None,
            unknown_effect_count: 0,
        })?;
        Ok(CellSplitSelectionExecutionReceiptV1 {
            ndu: ndu_receipt,
            handoff,
        })
    }

    /// Invokes the real CNS replacement and observes its route fence before
    /// entering the persistent RoutePublished state. A network/IO failure
    /// after replacement is ambiguous: use observe_cutover, never replay.
    pub fn publish_routes(
        &mut self,
        next: CnsOrganHostV1,
        child_routes: Vec<CnsRouteV1>,
    ) -> Result<CellSplitRouteExecutionReceiptV1, CellSplitExecutionErrorV1> {
        self.require_phase(WriterHandoffPhaseV1::NewWriterFenced)?;
        if self.routes.phase() != CellSplitRoutePhaseV1::ParentActive {
            return Err(CellSplitExecutionErrorV1::Binding(
                "CNS cutover already dispatched",
            ));
        }
        self.routes
            .activate_children(self.split.predecessor_generation, next, child_routes)?;
        self.observe_cutover()
    }

    /// Read-only reconciliation of an already activated CNS host. No cutover
    /// call is issued, so a successful RPC followed by an fsync failure cannot
    /// make the parent route visible again.
    pub fn observe_cutover(
        &mut self,
    ) -> Result<CellSplitRouteExecutionReceiptV1, CellSplitExecutionErrorV1> {
        let phase = self.handoff.checkpoint().phase;
        if !matches!(
            phase,
            WriterHandoffPhaseV1::NewWriterFenced | WriterHandoffPhaseV1::RoutePublished
        ) {
            return Err(CellSplitExecutionErrorV1::Phase(phase));
        }
        if self.routes.phase() != CellSplitRoutePhaseV1::ChildrenActive
            || self.routes.generation() != self.split.successor_generation
        {
            return Err(CellSplitExecutionErrorV1::Binding(
                "CNS cutover not observed",
            ));
        }
        let fence = self
            .routes
            .route_fence_receipt()
            .ok_or(CellSplitExecutionErrorV1::Binding("CNS fence receipt"))?
            .clone();
        fence.verify(&self.split, self.routes.parent_route())?;
        let handoff = if phase == WriterHandoffPhaseV1::RoutePublished {
            let saved = self.handoff.checkpoint();
            if saved.evidence_digest != fence.fence_digest {
                return Err(CellSplitExecutionErrorV1::Binding(
                    "reopened CNS handoff differs",
                ));
            }
            saved.clone()
        } else {
            self.handoff.advance(WriterHandoffAdvanceV1 {
                phase: WriterHandoffPhaseV1::RoutePublished,
                evidence_digest: fence.fence_digest,
                outbox_watermark: None,
                unknown_effect_count: 0,
            })?
        };
        Ok(CellSplitRouteExecutionReceiptV1 {
            route: fence,
            handoff,
        })
    }

    /// Revalidate result authority at the final-use boundary. Merely having a
    /// child process running before route publication cannot authorize writes.
    pub fn admit_successor_result(
        &self,
        fence: &WriterResultFenceV1,
    ) -> Result<(), CellSplitExecutionErrorV1> {
        self.handoff.checkpoint().validate_result_fence(fence)?;
        if fence.generation != self.split.successor_generation
            || self.routes.phase() != CellSplitRoutePhaseV1::ChildrenActive
        {
            return Err(CellSplitExecutionErrorV1::Binding(
                "successor result not serving",
            ));
        }
        Ok(())
    }
}
