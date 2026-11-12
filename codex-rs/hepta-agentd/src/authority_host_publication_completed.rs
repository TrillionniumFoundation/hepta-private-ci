//! A completed-history observation under the original refusal and an actual
//! new recipient context. No historical timestamp grants another execution.

use std::time::Instant;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;

use super::completed_files::OriginalControlRecord;
use super::*;
use crate::authority_host_runtime::OriginalCompletedLearningContextV1;

#[path = "authority_host_publication_completed_next_use.rs"]
mod next_use;
#[path = "authority_host_publication_completed_open.rs"]
mod open;

/// Chosen by Root's completed-history deployment, never inferred from Missing.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum OriginalCompletedPublicationModeV1 {
    AcceptedPublication,
    CaptureRetired,
    ReadFinalized,
}

/// Exact read-only DATA. Only the enclosing completed-history lane can attest
/// its final admission, after this reader and the original refusal finish.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OriginalCompletedPublicationDataV1 {
    pub(crate) acceptance: Digest32,
    pub(crate) current_head: Digest32,
    pub(crate) successor: Option<RootCompletedSuccessorDataV1>,
}

enum ReadPhase {
    AwaitingContext,
    Failed,
    Observed(OriginalCompletedPublicationDataV1),
}

pub(crate) struct OriginalCompletedPublicationReadV1<'a> {
    proof: &'a OriginalPublicationHistoryProofV1<'a>,
    service: &'a HostAuthorityService,
    mode: OriginalCompletedPublicationModeV1,
    end: Instant,
    profile_store: HostAuthorityFrontierStore<PublicationRecord>,
    profile_owner: String,
    profile_pin: OriginalControlRecord,
    current: HostAuthorityFrontierStore<CurrentHead>,
    current_owner: String,
    current_pin: OriginalControlRecord,
    previous: CellGenerationJournalObserverV1,
    target: CellGenerationJournalObserverV1,
    artifacts: LearningArtifactReadViewV1,
    selected: AgentdSelectedGenerationV1,
    consumer: RootFinalUseObserverV1,
    consumer_pin: OriginalControlRecord,
    successor: Option<(RegisteredSuccessorData, OriginalControlRecord)>,
    phase: ReadPhase,
}

pub(crate) fn with_original_publication_history<T>(
    root: Arc<RootAuthorityDirectory>,
    root_path: &std::path::Path,
    initial: &LearningIterationSnapshotV1,
    scope: &FrozenLearningScopeV2,
    end: Instant,
    action: impl FnOnce(&OriginalPublicationHistoryProofV1<'_>) -> io::Result<T>,
) -> io::Result<(T, Digest32)> {
    PublicationRefusal::with_completed_history(root, root_path, initial, scope, end, action)
}

impl OriginalCompletedPublicationReadV1<'_> {
    pub(crate) fn observe(
        &mut self,
        context: &OriginalCompletedLearningContextV1<'_>,
    ) -> io::Result<OriginalCompletedPublicationDataV1> {
        if !matches!(self.phase, ReadPhase::AwaitingContext) {
            self.phase = ReadPhase::Failed;
            return Err(io::Error::other(
                "completed publication observation is one-shot",
            ));
        }
        // A caught error, unused reader or second read cannot clear the Arm.
        self.phase = ReadPhase::Failed;
        context.require_original_publication_context(self.service, self.end)?;
        let original = self.proof.original_profile()?;
        context
            .frozen_scope()
            .validate_snapshot(context.initial())
            .map_err(io::Error::other)?;
        context
            .frozen_scope()
            .validate_snapshot(context.terminal())
            .map_err(io::Error::other)?;
        if original.initial != context.initial().head_digest.to_string()
            || original.scope != context.frozen_scope().binding().to_string()
            || original.learning_operation != context.initial().request.operation_id.as_str()
            || context.terminal().request != context.initial().request
            || context.terminal().owners != context.initial().owners
            || context.original_writer_proof().is_empty()
        {
            return Err(io::Error::other(
                "original completed learning/publication scope differs",
            ));
        }
        self.require_terminal_selection(context)?;
        self.require_physical()?;
        let successor = match self.mode {
            OriginalCompletedPublicationModeV1::AcceptedPublication => None,
            OriginalCompletedPublicationModeV1::CaptureRetired
            | OriginalCompletedPublicationModeV1::ReadFinalized => {
                let (held, pin) = self
                    .successor
                    .as_ref()
                    .ok_or_else(|| io::Error::other("original successor custody missing"))?;
                pin.require_original_lock()?;
                let cut = RegisteredSuccessorData::observe_retired(
                    held,
                    self.mode == OriginalCompletedPublicationModeV1::CaptureRetired,
                )?;
                Some(RegisteredSuccessorData::read_data(held, cut)?)
            }
        };
        if let Some(data) = &successor {
            self.require_original_next_use(context, data)?;
        }
        self.require_physical()?;
        context.require_original_publication_context(self.service, self.end)?;
        let data = OriginalCompletedPublicationDataV1 {
            acceptance: self.proof.acceptance_digest()?,
            current_head: head_digest(self.proof.original_current())?
                .parse()
                .map_err(io::Error::other)?,
            successor,
        };
        self.phase = ReadPhase::Observed(data.clone());
        Ok(data)
    }

    /// The actual new recipient's complete Root context has returned before
    /// this call. Its error must be propagated by the enclosing durable Arm.
    pub(crate) fn finish(&mut self) -> io::Result<()> {
        let ReadPhase::Observed(expected) = std::mem::replace(&mut self.phase, ReadPhase::Failed)
        else {
            return Err(io::Error::other(
                "actual completed publication read did not finish",
            ));
        };
        self.require_physical()?;
        match (&self.successor, &expected.successor) {
            (Some((held, pin)), Some(data)) => {
                RegisteredSuccessorData::finish_observed(held, &data.cut)?;
                if RegisteredSuccessorData::read_data(held, data.cut.clone())? != *data {
                    return Err(io::Error::other(
                        "completed successor changed after recipient postchecks",
                    ));
                }
                pin.require_original_lock()?;
            }
            (None, None)
                if self.mode == OriginalCompletedPublicationModeV1::AcceptedPublication => {}
            _ => return Err(io::Error::other("completed successor mode differs")),
        }
        self.require_physical()?;
        refusal::require_end(self.end)
    }

    fn require_physical(&mut self) -> io::Result<()> {
        original_root()?;
        refusal::require_end(self.end)?;
        let profile = self.proof.original_profile()?;
        self.profile_pin.require_unchanged()?;
        self.current_pin.require_unchanged()?;
        self.consumer_pin.require_unchanged()?;
        if self
            .profile_store
            .load(&self.profile_owner)
            .map_err(io::Error::other)?
            != (PublicationRecord {
                profile: self.proof.original_reserved().clone(),
                fenced: false,
            })
            || self
                .current
                .load(&self.current_owner)
                .map_err(io::Error::other)?
                != *self.proof.original_current()
            || self.previous.files_binding().to_string() != profile.previous_files
            || self.target.files_binding().to_string() != profile.target_files
        {
            return Err(io::Error::other(
                "original completed publication record changed",
            ));
        }
        let previous = self.previous.observe().map_err(io::Error::other)?;
        let target = self.target.observe().map_err(io::Error::other)?;
        if !previous.is_drained()
            || previous.owner_binding() != &profile.intent.previous
            || previous.observation().owner_checkpoint().into_array()
                != profile.intent.previous_checkpoint
            || !target.is_genesis()
            || target.owner_binding() != &profile.intent.target
            || target.observation().owner_checkpoint().into_array()
                != profile.intent.genesis_checkpoint
        {
            return Err(io::Error::other(
                "original completed Generation cut changed",
            ));
        }
        self.proof.require_original_observations(
            Digest32::from_array(previous.observation().digest().map_err(io::Error::other)?),
            Digest32::from_array(target.observation().digest().map_err(io::Error::other)?),
        )?;
        self.selected
            .revalidate_original_artifacts(&self.artifacts, self.proof.verified_at_unix_ms())
            .map_err(io::Error::other)?;
        if self.selected.observation().digest().into_array() != profile.intent.selection {
            return Err(io::Error::other("original accepted Selection changed"));
        }
        let published = self
            .proof
            .original_current()
            .published
            .as_ref()
            .ok_or_else(|| io::Error::other("original completed Published missing"))?;
        let actual = self
            .consumer
            .verify_original_retained_use(
                &published.signed,
                &profile.intent.binding().map_err(io::Error::other)?,
                &published.witness,
            )
            .map_err(io::Error::other)?;
        if self.service.issuer.revocations()? != actual {
            return Err(io::Error::other(
                "current Root denies original consumed publication",
            ));
        }
        self.profile_pin.require_unchanged()?;
        self.current_pin.require_unchanged()?;
        self.consumer_pin.require_unchanged()?;
        refusal::require_end(self.end)
    }

    fn require_terminal_selection(
        &self,
        context: &OriginalCompletedLearningContextV1<'_>,
    ) -> io::Result<()> {
        let terminal = context.terminal();
        let completed = LearningIterationCoordinatorV1::from_snapshot(terminal.clone())
            .map_err(io::Error::other)?;
        let bundle = completed
            .next_task_bundle()
            .ok_or_else(|| io::Error::other("completed bundle missing"))?;
        if completed.next_stage().is_some() || terminal.training_no_update_v2().is_some() {
            return Err(io::Error::other("full evaluated terminal history required"));
        }
        crate::cell_composed_q24::validate_manifest(bundle, self.selected.manifest())
            .map_err(io::Error::other)?;
        let profile = self.proof.original_profile()?;
        let mut replay =
            LearningIterationCoordinatorV1::new(terminal.request.clone(), terminal.owners.clone())
                .map_err(io::Error::other)?;
        let mut decision = None;
        for receipt in &terminal.receipts {
            replay
                .record(receipt.clone(), receipt.observed_unix_seconds)
                .map_err(io::Error::other)?;
            if let Ok(value) = crate::cell_q24_publication_driver::validation::Decision::new(
                replay.snapshot().clone(),
            ) {
                value.require_root_publication().map_err(io::Error::other)?;
                if decision.replace(value).is_some() {
                    return Err(io::Error::other("ambiguous completed publication decision"));
                }
            }
        }
        let decision =
            decision.ok_or_else(|| io::Error::other("original publication decision missing"))?;
        let selection_index = terminal
            .receipts
            .len()
            .checked_sub(2)
            .ok_or_else(|| io::Error::other("completed Selection/NextUse missing"))?;
        if decision.snapshot.head_digest.to_string() != profile.decision
            || decision.operation.as_str() != profile.intent.operation_id
            || &decision.bundle != bundle
            || terminal.receipts[selection_index].observation
                != (LearningIterationObservationV1::Selection {
                    candidate_bundle: bundle.digest().map_err(io::Error::other)?,
                    selection_digest: Digest32::from_array(profile.intent.selection),
                })
        {
            return Err(io::Error::other(
                "completed publication decision/Selection differs",
            ));
        }
        Ok(())
    }
}
