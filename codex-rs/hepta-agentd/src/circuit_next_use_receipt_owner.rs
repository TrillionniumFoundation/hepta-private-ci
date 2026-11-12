//! Original Observer receipts over a completed, originally published ordinary C.
//! The host supplies enrolled custody, original files and connected predecessor
//! owners. This owner neither runs C nor selects, adopts or enrolls any owner.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CircuitTaskSourceReadbackV1;
use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadErrorV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitNextUseReceiptErrorV1 {
    #[error("original C Observer owner: {0}")]
    Owner(#[from] OwnerError),
    #[error("original published C observation: {0}")]
    Observation(#[from] AgentdError),
    #[error("original learning iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original predecessor evidence owner: {0}")]
    Connection(#[from] LearningIterationRuntimeErrorV1),
    #[error("original role evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original published Circuit read capability: {0}")]
    PublishedRead(#[from] OriginalCircuitLearningReadErrorV1),
    #[error("original evaluated retention predecessor: {0}")]
    Evaluated(#[from] crate::OriginalCircuitRetainedPublicationErrorV1),
    #[error("original evaluated Selector predecessor: {0}")]
    EvaluatedSelection(#[from] crate::OriginalCircuitSelectionReceiptErrorV1),
}
type Error = OriginalCircuitNextUseReceiptErrorV1;

#[path = "circuit_next_use_receipt_binding.rs"]
mod binding;
use binding::authenticate_predecessors;
use binding::evidence_id;
use binding::now;
use binding::prior;
use binding::receipt;
use binding::receipt_with_domain;
use binding::require_new_attestation;
use binding::sign_original;
use binding::validate_config;

#[path = "circuit_next_use_readback_host.rs"]
mod readback_host;

#[path = "circuit_evaluated_next_use_receipt.rs"]
mod evaluated;
pub use evaluated::OriginalCircuitEvaluatedNextUseReceiptConfigV1;
pub use evaluated::OriginalCircuitEvaluatedNextUseReceiptSourcesV1;
pub use evaluated::OriginalCircuitEvaluatedNextUseReceiptV1;
pub use evaluated::OriginalCircuitEvaluatedNextUseRemoteSourcesV1;
use evaluated::Profile;

/// Fixed original Selection cut and host-enrolled Observer. An immutable trust
/// snapshot is not an enrollment operation or evidence of independent operators.
#[derive(Clone)]
pub struct OriginalCircuitNextUseReceiptConfigV1 {
    pub selection: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub training_evidence: SignedLearningEvidenceV1,
    pub selection_evidence: SignedLearningEvidenceV1,
    pub maximum_signature_lifetime_seconds: u64,
}

/// Borrow the sealed original Cell, live source and connected original owners.
/// The complete recovered history is sent to the predecessor evidence owners.
/// No receipt, observation, caller clock or replacement CURRENT is accepted.
pub struct OriginalCircuitNextUseReceiptSourcesV1<'a, C: AnchorWitnessStore, S: AnchorWitnessStore>
{
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub cell: &'a PublishedCircuitCellOwnerV1<C>,
    pub source: &'a CircuitTaskSourceReadbackV1<S>,
    pub identity: &'a AgentdIdentity,
    pub trainer: &'a LearningIterationEvidenceClientV1,
    pub selector: &'a LearningIterationEvidenceClientV1,
}

/// A purpose-fixed original task peer for the TrainingNoUpdate profile.
/// Every use rereads the actual C publication, committed Cell and TaskSource;
/// a saved observation is never accepted as CURRENT or as a signing input.
pub struct OriginalCircuitNextUseRemoteSourcesV1<'a> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub live: &'a OriginalCircuitLearningReadClientV1,
    pub trainer: &'a LearningIterationEvidenceClientV1,
    pub selector: &'a LearningIterationEvidenceClientV1,
}

trait NextUseSources {
    fn snapshot(&self) -> &LearningIterationSnapshotV1;
    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1>;
    fn selector(&self) -> &LearningIterationEvidenceClientV1;
    fn evaluated_owners(
        &self,
    ) -> Option<(
        &crate::OriginalCellQ24TrainingCommandClientV1,
        &crate::OriginalCellEvaluationCommandClientV1,
    )> {
        None
    }
    fn location(&self) -> ObservationLocation;
    fn require_profile(&self, _profile: &Profile) -> Result<(), Error> {
        Ok(())
    }
    async fn observe(
        &self,
        config: &OriginalCircuitNextUseReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error>;
}

// Only the concrete original sources choose this private location.
// The remote path brackets this Observer's journal with both live predecessor
// owners. The existing local-owner protocol keeps its original read count.
enum ObservationLocation {
    LocalOwner,
    RemoteOwner,
    EvaluatedOwner,
}

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> NextUseSources
    for OriginalCircuitNextUseReceiptSourcesV1<'_, C, S>
{
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }
    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> {
        Some(self.trainer)
    }
    fn selector(&self) -> &LearningIterationEvidenceClientV1 {
        self.selector
    }
    fn location(&self) -> ObservationLocation {
        ObservationLocation::LocalOwner
    }
    async fn observe(
        &self,
        config: &OriginalCircuitNextUseReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        read_local_next_use(self, config)
    }
}

impl NextUseSources for OriginalCircuitNextUseRemoteSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }
    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> {
        Some(self.trainer)
    }
    fn selector(&self) -> &LearningIterationEvidenceClientV1 {
        self.selector
    }
    fn location(&self) -> ObservationLocation {
        ObservationLocation::RemoteOwner
    }
    async fn observe(
        &self,
        config: &OriginalCircuitNextUseReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        read_remote_next_use(self, config).await
    }
}

fn read_local_next_use(
    source: &OriginalCircuitNextUseReceiptSourcesV1<
        '_,
        impl AnchorWitnessStore,
        impl AnchorWitnessStore,
    >,
    config: &OriginalCircuitNextUseReceiptConfigV1,
) -> Result<LearningIterationObservationV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.selection.clone())?;
    let cell: &PublishedCircuitCellOwnerV1<_> = source.cell;
    Ok(cell.read_learning_next_use(&coordinator, source.source, source.identity)?)
}

async fn read_remote_next_use(
    source: &OriginalCircuitNextUseRemoteSourcesV1<'_>,
    config: &OriginalCircuitNextUseReceiptConfigV1,
) -> Result<LearningIterationObservationV1, Error> {
    let live: &OriginalCircuitLearningReadClientV1 = source.live;
    live.require_original_context(
        &config.selection,
        &config.scope,
        &config.verifier,
        &config.training_evidence,
        Some(&config.selection_evidence),
    )?;
    let original = live.read_current().await?;
    Ok(original.observation().clone())
}

enum CommandOrigin {
    FreshCreate,
    Recovered,
}

pub struct OriginalCircuitNextUseReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCircuitNextUseReceiptConfigV1,
    profile: Profile,
    key: SigningKey,
    saved: ProductEvaluationExecutionKeyV1,
    command_origin: CommandOrigin,
    completion_fenced: bool,
}

impl<W: AnchorWitnessStore> OriginalCircuitNextUseReceiptOwnerV1<W> {
    pub fn create(
        file: File,
        witness: W,
        config: OriginalCircuitNextUseReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let saved = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            profile: Profile::Legacy,
            key,
            saved,
            command_origin: CommandOrigin::FreshCreate,
            completion_fenced: false,
        })
    }

    /// Reopen the same independently witnessed signature journal. Recovery
    /// cannot sign, resolve Pending, execute C or renew a validity window.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCircuitNextUseReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let saved = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            profile: Profile::Legacy,
            key,
            saved,
            command_origin: CommandOrigin::Recovered,
            completion_fenced: false,
        })
    }

    /// Transfer this original Observer into its one shared command host.
    /// The task and predecessor channels are already original capabilities.
    /// This performs no C execution, observation signing or custody reopening.
    pub fn into_command_owner(
        self,
        live: OriginalCircuitLearningReadClientV1,
        trainer: LearningIterationEvidenceClientV1,
        selector: LearningIterationEvidenceClientV1,
    ) -> Result<
        crate::OriginalCircuitNextUseCommandOwnerV1<W>,
        crate::OriginalCircuitNextUseCommandErrorV1,
    >
    where
        W: Send + 'static,
    {
        crate::OriginalCircuitNextUseCommandOwnerV1::from_original_receipt_owner(
            self, live, trainer, selector,
        )
    }

    pub(crate) fn original_command_profile(
        &self,
    ) -> (&OriginalCircuitNextUseReceiptConfigV1, bool) {
        (
            &self.config,
            matches!(self.command_origin, CommandOrigin::Recovered),
        )
    }

    /// Claim once, then sign only an actual original C completion. The original
    /// Trainer and Selector are read on both sides of the claim/completion.
    /// Missing, uncertain or withdrawn material is an error, never NoUpdate.
    pub async fn attest_original_completion(
        &mut self,
        source: OriginalCircuitNextUseReceiptSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.attest_source(source).await
    }

    /// Sign only after the same originally published C is read from its
    /// purpose-fixed task process, with both original evidence owners live.
    pub async fn attest_original_remote_completion(
        &mut self,
        source: OriginalCircuitNextUseRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.attest_source(source).await
    }

    async fn attest_source(
        &mut self,
        source: impl NextUseSources,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let started_at = now()?;
        if self.completion_fenced {
            return Err(OwnerError::CommitUncertain.into());
        }
        self.profile.require_new(started_at)?;
        require_new_attestation(&self.config, started_at, started_at)?;
        let observed = self.prepare(&source).await?;
        // A completed coordinator can only recover an existing owner result.
        if source.snapshot().receipts.len() > self.config.selection.receipts.len() {
            return self.readback_source(source).await;
        }
        let evidence = self.predecessors(&source).await?;
        evaluated::authenticate_predecessors(&self.config, &self.profile, &evidence, now()?)?;
        if self.prepare(&source).await? != observed {
            return Err(OwnerError::CommitUncertain.into());
        }
        let config = &self.config;
        let profile = &self.profile;
        let key = &self.key;
        let identity = self.saved.binding_digest;
        let bytes = self.journal.commit_once(&self.saved, || {
            let issued_at = now()?;
            profile.require_new(issued_at)?;
            require_new_attestation(config, started_at, issued_at)?;
            let predecessors =
                evaluated::authenticate_predecessors(config, profile, &evidence, issued_at)
                    .map_err(|_| OwnerError::Binding("current original predecessor roles"))?;
            let receipt = evaluated::receipt(config, profile, &observed, issued_at)
                .map_err(|_| OwnerError::Binding("original C receipt"))?;
            let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
                .map_err(|_| OwnerError::Binding("original C receipt bytes"))?;
            let signed = sign_original(config, key, &payload, identity, issued_at)?;
            let verified = config.verifier.verify(
                LearningEvidenceRoleV1::Observer,
                &signed,
                &payload,
                issued_at,
            )?;
            profile
                .require_signed_separation(&verified, issued_at)
                .map_err(|_| OwnerError::Binding("original evaluated C role separation"))?;
            for predecessor in &predecessors {
                verify_signed_actor_separation(predecessor, &verified, issued_at)?;
            }
            learning_owner_evidence::encode(&payload, &signed)
        })?;
        let result = self
            .finish_original_readback(
                &source, &observed, &bytes, started_at, /*new_attestation*/ true,
            )
            .await;
        if result.is_err() {
            self.completion_fenced = true;
        }
        result
    }

    /// Read the same signature against current original C and predecessor
    /// evidence, including after the work deadline while evidence remains valid.
    /// No claim, signature, private step, publication or clock renewal occurs.
    pub async fn readback(
        &mut self,
        source: OriginalCircuitNextUseReceiptSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.readback_source(source).await
    }

    /// Recover the original signature through fresh task and predecessor
    /// readbacks. This never runs C, signs again or extends the original window.
    pub async fn readback_remote(
        &mut self,
        source: OriginalCircuitNextUseRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.readback_source(source).await
    }

    async fn readback_source(
        &mut self,
        source: impl NextUseSources,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let started_at = now()?;
        if self.completion_fenced {
            return Err(OwnerError::CommitUncertain.into());
        }
        let observed = self.prepare(&source).await?;
        if matches!(
            source.location(),
            ObservationLocation::RemoteOwner | ObservationLocation::EvaluatedOwner
        ) {
            let before = self.predecessors(&source).await?;
            evaluated::authenticate_predecessors(&self.config, &self.profile, &before, now()?)?;
        }
        let bytes = self.journal.read(&self.saved)?;
        let result = self
            .finish_original_readback(
                &source, &observed, &bytes, started_at, /*new_attestation*/ false,
            )
            .await;
        if result.is_err() {
            self.completion_fenced = true;
        }
        result
    }

    async fn prepare(
        &self,
        source: &impl NextUseSources,
    ) -> Result<LearningIterationObservationV1, Error> {
        match (&self.profile, source.location()) {
            (
                Profile::Legacy,
                ObservationLocation::LocalOwner | ObservationLocation::RemoteOwner,
            )
            | (Profile::Evaluated(_), ObservationLocation::EvaluatedOwner) => {}
            _ => return Err(OwnerError::Binding("same original C source profile").into()),
        }
        LearningIterationCoordinatorV1::from_snapshot(source.snapshot().clone())?;
        self.config.scope.validate_snapshot(source.snapshot())?;
        if source.snapshot().request != self.config.selection.request
            || source.snapshot().owners != self.config.selection.owners
            || !source
                .snapshot()
                .receipts
                .starts_with(&self.config.selection.receipts)
        {
            return Err(OwnerError::Binding("original Selection prefix").into());
        }
        source.require_profile(&self.profile)?;
        let observation = source.observe(&self.config).await?;
        self.config.scope.validate_observation(&observation)?;
        Ok(observation)
    }

    async fn predecessors(
        &self,
        source: &impl NextUseSources,
    ) -> Result<[SignedLearningEvidenceV1; 2], Error> {
        let training = match &self.profile {
            Profile::Legacy => {
                let trainer: &LearningIterationEvidenceClientV1 = source
                    .trainer()
                    .ok_or(OwnerError::Binding("original C Trainer source"))?;
                LearningIterationEvidenceClientV1::readback(
                    trainer,
                    source.snapshot(),
                    prior(&self.config, LearningIterationStageV1::Training)?,
                )
                .await?
            }
            Profile::Evaluated(selection) => {
                let (trainer, evaluator) = source
                    .evaluated_owners()
                    .ok_or(OwnerError::Binding("original C evaluated sources"))?;
                selection
                    .original_context()
                    .require_original_receipt_owners(trainer, evaluator)
                    .await?;
                self.config.training_evidence.clone()
            }
        };
        let selector: &LearningIterationEvidenceClientV1 = source.selector();
        let selection = selector
            .readback(
                source.snapshot(),
                prior(&self.config, LearningIterationStageV1::Selection)?,
            )
            .await?;
        Ok([training, selection])
    }

    async fn finish_original_readback(
        &mut self,
        source: &impl NextUseSources,
        observed: &LearningIterationObservationV1,
        bytes: &[u8],
        started_at: u64,
        new_attestation: bool,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let completed = self.decode_completed(source, observed, bytes)?;
        // Both original owners are reread after the post-C observation and
        // before the final physical journal read. No nested prepare or role
        // authentication sends another predecessor request.
        let evidence = match source.location() {
            ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {
                let evidence = self.predecessors(source).await?;
                if self.prepare(source).await? != *observed {
                    return Err(OwnerError::CommitUncertain.into());
                }
                evidence
            }
            ObservationLocation::RemoteOwner => {
                if self.prepare(source).await? != *observed {
                    return Err(OwnerError::CommitUncertain.into());
                }
                self.predecessors(source).await?
            }
        };
        if self.journal.read(&self.saved)? != bytes {
            return Err(OwnerError::CommitUncertain.into());
        }
        let current = now()?;
        self.authenticate_completed(completed, &evidence, started_at, current, new_attestation)
    }

    fn decode_completed(
        &self,
        source: &impl NextUseSources,
        observed: &LearningIterationObservationV1,
        bytes: &[u8],
    ) -> Result<
        (
            LearningIterationReceiptV1,
            Vec<u8>,
            SignedLearningEvidenceV1,
        ),
        Error,
    > {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let receipt = evaluated::receipt(&self.config, &self.profile, observed, signed.issued_at)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?
            || source
                .snapshot()
                .receipts
                .get(self.config.selection.receipts.len())
                .is_some_and(|saved| saved != &receipt)
        {
            return Err(OwnerError::Binding("changed original C receipt").into());
        }
        Ok((receipt, payload, signed))
    }

    fn authenticate_completed(
        &self,
        completed: (
            LearningIterationReceiptV1,
            Vec<u8>,
            SignedLearningEvidenceV1,
        ),
        evidence: &[SignedLearningEvidenceV1; 2],
        started_at: u64,
        current: u64,
        new_attestation: bool,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (receipt, payload, signed) = completed;
        if current < started_at {
            return Err(OwnerError::Binding("original Observer clock moved backwards").into());
        }
        if new_attestation {
            self.profile.require_new(current)?;
            require_new_attestation(&self.config, started_at, current)?;
        }
        let predecessors =
            evaluated::authenticate_predecessors(&self.config, &self.profile, evidence, current)?;
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &signed,
            &payload,
            current,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
            || signed.evidence_id != evidence_id(self.saved.binding_digest)?
        {
            return Err(OwnerError::Binding("original C Observer identity").into());
        }
        self.profile.require_signed_separation(&verified, current)?;
        for predecessor in &predecessors {
            verify_signed_actor_separation(predecessor, &verified, current)?;
        }
        Ok((receipt, signed))
    }
}

#[cfg(test)]
#[path = "circuit_next_use_receipt_owner_tests.rs"]
mod tests;
