//! Original Selector receipts for an actual retained-model task publication.
//! The host supplies its enrolled Selector custody and original signature store.
//! A Training NoUpdate is necessary for this profile, but cannot stand in for
//! the original version owner's independently authorized publication.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
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
use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadErrorV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitSelectionReceiptErrorV1 {
    #[error("original Selector owner: {0}")]
    Owner(#[from] OwnerError),
    #[error("original published selection: {0}")]
    Observation(#[from] AgentdError),
    #[error("original learning iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Training evidence owner: {0}")]
    Connection(#[from] LearningIterationRuntimeErrorV1),
    #[error("original role evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original published Circuit read capability: {0}")]
    PublishedRead(#[from] OriginalCircuitLearningReadErrorV1),
}
type Error = OriginalCircuitSelectionReceiptErrorV1;

/// One original TrainingNoUpdate cut. The complete original Generator signature
/// is pinned across live reads and cold recovery, including its validity window.
/// This profile admits no unverified Evaluation or Proposal predecessor.
#[derive(Clone)]
pub struct OriginalCircuitSelectionReceiptConfigV1 {
    pub decision: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub training_evidence: SignedLearningEvidenceV1,
    pub maximum_signature_lifetime_seconds: u64,
}

/// Borrow the original sealed Cell publication and connected Training owner.
/// No claimed selection observation, publication digest or caller clock is input.
pub struct OriginalCircuitSelectionReceiptSourcesV1<'a, C: AnchorWitnessStore> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub cell: &'a PublishedCircuitCellOwnerV1<C>,
    pub trainer: &'a LearningIterationEvidenceClientV1,
}

/// The original task process is read afresh on every observation. The client
/// must be bound to this exact TrainingNoUpdate cut and complete Generator
/// signature. Neither a previously returned value nor caller observation is input.
pub struct OriginalCircuitSelectionRemoteSourcesV1<'a> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub live: &'a OriginalCircuitLearningReadClientV1,
    pub trainer: &'a LearningIterationEvidenceClientV1,
}

// Private dispatch has exactly the two concrete original source implementations.
// It cannot be supplied as a public callback or implemented by another module.
trait SelectionSources {
    fn snapshot(&self) -> &LearningIterationSnapshotV1;
    fn trainer(&self) -> &LearningIterationEvidenceClientV1;
    async fn observe(
        &self,
        config: &OriginalCircuitSelectionReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error>;
}

impl<C: AnchorWitnessStore> SelectionSources for OriginalCircuitSelectionReceiptSourcesV1<'_, C> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }
    fn trainer(&self) -> &LearningIterationEvidenceClientV1 {
        self.trainer
    }
    async fn observe(
        &self,
        config: &OriginalCircuitSelectionReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        read_local_selection(self, config)
    }
}

impl SelectionSources for OriginalCircuitSelectionRemoteSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }
    fn trainer(&self) -> &LearningIterationEvidenceClientV1 {
        self.trainer
    }
    async fn observe(
        &self,
        config: &OriginalCircuitSelectionReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        read_remote_selection(self, config).await
    }
}

fn read_local_selection(
    source: &OriginalCircuitSelectionReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    config: &OriginalCircuitSelectionReceiptConfigV1,
) -> Result<LearningIterationObservationV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?;
    let cell: &PublishedCircuitCellOwnerV1<_> = source.cell;
    Ok(cell.read_learning_selection(&coordinator)?)
}

async fn read_remote_selection(
    source: &OriginalCircuitSelectionRemoteSourcesV1<'_>,
    config: &OriginalCircuitSelectionReceiptConfigV1,
) -> Result<LearningIterationObservationV1, Error> {
    let live: &OriginalCircuitLearningReadClientV1 = source.live;
    live.require_original_context(
        &config.decision,
        &config.scope,
        &config.verifier,
        &config.training_evidence,
        None,
    )?;
    let trainer: &LearningIterationEvidenceClientV1 = source.trainer;
    let before = trainer
        .readback(source.snapshot, training_receipt(config)?)
        .await?;
    authenticate_training(config, &before, now()?)?;
    let original = live.read_current().await?;
    let after = trainer
        .readback(source.snapshot, training_receipt(config)?)
        .await?;
    authenticate_training(config, &after, now()?)?;
    Ok(original.observation().clone())
}

enum CommandOrigin {
    FreshCreate,
    Recovered,
}

pub struct OriginalCircuitSelectionReceiptOwnerV1<W: AnchorWitnessStore> {
    command_origin: CommandOrigin,
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCircuitSelectionReceiptConfigV1,
    key: SigningKey,
    saved: ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> OriginalCircuitSelectionReceiptOwnerV1<W> {
    /// Read only this object's private origin and fixed configuration for its
    /// consuming command adapter. No caller-provided tag or key is returned.
    pub(crate) fn original_command_profile(
        &self,
    ) -> (&OriginalCircuitSelectionReceiptConfigV1, bool) {
        (
            &self.config,
            matches!(self.command_origin, CommandOrigin::Recovered),
        )
    }

    pub fn create(
        file: File,
        witness: W,
        config: OriginalCircuitSelectionReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let saved = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
        Ok(Self {
            command_origin: CommandOrigin::FreshCreate,
            journal,
            config,
            key,
            saved,
        })
    }

    /// Recover the same independently witnessed store. Pending stays unresolved;
    /// neither a selection, signature nor prior validity window is recreated.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCircuitSelectionReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let saved = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
        Ok(Self {
            command_origin: CommandOrigin::Recovered,
            journal,
            config,
            key,
            saved,
        })
    }

    /// Sign only an original version owner's actual retained-model publication.
    /// A genuinely missing record may claim once. Existing results only read back,
    /// including after the work deadline while all original evidence stays valid.
    pub async fn attest_original_selection(
        &mut self,
        source: OriginalCircuitSelectionReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.attest_source(source).await
    }

    /// Observe the same original publication through its purpose-fixed peer.
    /// This retains original Selector custody and performs fresh remote reads.
    pub async fn attest_original_remote_selection(
        &mut self,
        source: OriginalCircuitSelectionRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.attest_source(source).await
    }

    async fn attest_source(
        &mut self,
        source: impl SelectionSources,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let started_at = now()?;
        if source.snapshot().receipts.len() > self.config.decision.receipts.len() {
            return self.readback_source(source).await;
        }
        match self.journal.read(&self.saved) {
            Ok(_) => return self.readback_source(source).await,
            Err(OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {}
            Err(error) => return Err(error.into()),
        }
        require_new_attestation(&self.config, started_at, now()?)?;
        let observed = self.prepare(&source).await?;
        let evidence = self.training_evidence(&source).await?;
        authenticate_training(&self.config, &evidence, now()?)?;
        if self.prepare(&source).await? != observed {
            return Err(OwnerError::CommitUncertain.into());
        }
        let claim_at = now()?;
        require_new_attestation(&self.config, started_at, claim_at)?;
        let config = &self.config;
        let key = &self.key;
        let identity = self.saved.binding_digest;
        let bytes = self.journal.commit_once(&self.saved, || {
            let issued_at = now()?;
            require_new_attestation(config, started_at, issued_at)?;
            let training = authenticate_training(config, &evidence, issued_at)
                .map_err(|_| OwnerError::Binding("current original Training role"))?;
            let receipt = receipt(config, &observed, issued_at)
                .map_err(|_| OwnerError::Binding("original Selection receipt"))?;
            let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
                .map_err(|_| OwnerError::Binding("original Selection bytes"))?;
            let signed = sign_original(config, key, &payload, identity, issued_at)?;
            let verified = config.verifier.verify(
                LearningEvidenceRoleV1::Selector,
                &signed,
                &payload,
                issued_at,
            )?;
            verify_signed_actor_separation(&training, &verified, issued_at)?;
            learning_owner_evidence::encode(&payload, &signed)
        })?;
        self.authenticate_completed(&source, &observed, &bytes, started_at, true)
            .await
    }

    /// Revalidate the actual version owner, original Generator and original
    /// signature bytes. This cannot select, publish, claim, fit, sign or renew.
    pub async fn readback(
        &mut self,
        source: OriginalCircuitSelectionReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.readback_source(source).await
    }

    /// Cold or live recovery keeps the original signature and reads the
    /// purpose-fixed task owner again; this cannot execute or renew anything.
    pub async fn readback_remote(
        &mut self,
        source: OriginalCircuitSelectionRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.readback_source(source).await
    }

    async fn readback_source(
        &mut self,
        source: impl SelectionSources,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let started_at = now()?;
        let observed = self.prepare(&source).await?;
        let bytes = self.journal.read(&self.saved)?;
        self.authenticate_completed(&source, &observed, &bytes, started_at, false)
            .await
    }

    async fn prepare(
        &self,
        source: &impl SelectionSources,
    ) -> Result<LearningIterationObservationV1, Error> {
        LearningIterationCoordinatorV1::from_snapshot(source.snapshot().clone())?;
        self.config.scope.validate_snapshot(source.snapshot())?;
        if source.snapshot().request != self.config.decision.request
            || source.snapshot().owners != self.config.decision.owners
            || !source
                .snapshot()
                .receipts
                .starts_with(&self.config.decision.receipts)
        {
            return Err(OwnerError::Binding("original TrainingNoUpdate prefix").into());
        }
        let observed = source.observe(&self.config).await?;
        self.config.scope.validate_observation(&observed)?;
        Ok(observed)
    }

    async fn training_evidence(
        &self,
        source: &impl SelectionSources,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let trainer: &LearningIterationEvidenceClientV1 = source.trainer();
        Ok(trainer
            .readback(source.snapshot(), training_receipt(&self.config)?)
            .await?)
    }

    async fn authenticate_completed(
        &mut self,
        source: &impl SelectionSources,
        observed: &LearningIterationObservationV1,
        bytes: &[u8],
        started_at: u64,
        new_attestation: bool,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let receipt = receipt(&self.config, observed, signed.issued_at)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?
            || source
                .snapshot()
                .receipts
                .get(self.config.decision.receipts.len())
                .is_some_and(|original| original != &receipt)
        {
            return Err(OwnerError::Binding("changed original Selection receipt").into());
        }
        let evidence = self.training_evidence(source).await?;
        if self.prepare(source).await? != *observed {
            return Err(OwnerError::CommitUncertain.into());
        }
        if self.journal.read(&self.saved)? != bytes {
            return Err(OwnerError::CommitUncertain.into());
        }
        let current = now()?;
        if current < started_at {
            return Err(OwnerError::Binding("original Selector clock moved backwards").into());
        }
        if new_attestation {
            require_new_attestation(&self.config, started_at, current)?;
        }
        let training = authenticate_training(&self.config, &evidence, current)?;
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Selector,
            &signed,
            &payload,
            current,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
            || signed.evidence_id != evidence_id(self.saved.binding_digest)?
            || signed.expires_at != signature_expiry(&self.config, signed.issued_at)?
        {
            return Err(OwnerError::Binding("original Selector identity").into());
        }
        verify_signed_actor_separation(&training, &verified, current)?;
        Ok((receipt, signed))
    }
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitSelectionReceiptOwnerV1<W> {
    /// Move this exact original owner into its purpose-fixed role service.
    /// Recovered owners remain readback-only. The actual task and Trainer
    /// clients are consumed here; neither a cached observation nor key leaves.
    /// Construct within the original host runtime; serving uses blocking lanes.
    pub fn into_command_owner(
        self,
        live: OriginalCircuitLearningReadClientV1,
        trainer: LearningIterationEvidenceClientV1,
    ) -> Result<
        crate::OriginalCircuitSelectionCommandOwnerV1<W>,
        crate::OriginalCircuitSelectionCommandErrorV1,
    > {
        crate::OriginalCircuitSelectionCommandOwnerV1::from_original_receipt_owner(
            self, live, trainer,
        )
    }
}

fn validate_config(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    key: &SigningKey,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?;
    config.scope.validate_snapshot(&config.decision)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Selection)
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || config.signer.principal.principal_id != config.decision.owners.selector
        || config.decision.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.decision.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(OwnerError::Binding("original Selector capability").into());
    }
    training_receipt(config)?;
    authenticate_training(config, &config.training_evidence, now()?)?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: config.decision.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-selection-receipt.v1\0",
            config.decision.head_digest.as_array(),
            config.scope.binding().as_array(),
            config.verifier.trust_digest().as_array(),
            config.signer.principal.principal_id.as_str().as_bytes(),
            &config.signer.verifying_key,
            &config.training_evidence.signing_bytes(),
            &config.training_evidence.signature,
            &config.maximum_signature_lifetime_seconds.to_be_bytes(),
        ]),
    })
}

fn training_receipt(
    config: &OriginalCircuitSelectionReceiptConfigV1,
) -> Result<&LearningIterationReceiptV1, Error> {
    let original = config
        .decision
        .receipts
        .last()
        .ok_or(OwnerError::Binding("original TrainingNoUpdate receipt"))?;
    if !matches!(
        &original.observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ) {
        return Err(
            OwnerError::Binding("only original TrainingNoUpdate selection is supported").into(),
        );
    }
    Ok(original)
}

fn authenticate_training(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    evidence: &SignedLearningEvidenceV1,
    current: u64,
) -> Result<VerifiedLearningEvidenceV1, Error> {
    if evidence != &config.training_evidence {
        return Err(OwnerError::Binding("changed original Training signature").into());
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Selector,
        &config.signer,
        current,
    )?;
    let original = training_receipt(config)?;
    let verified = config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        evidence,
        &learning_iteration_receipt_signing_bytes_v1(original)?,
        current,
    )?;
    if verified.principal().principal_id != original.actor_id {
        return Err(OwnerError::Binding("original Training actor").into());
    }
    verify_independent_roles(verified.principal(), &config.signer.principal, current)
        .map_err(SignedEvidenceError::from)?;
    if verified.controller_id() == &config.signer.controller_id {
        return Err(SignedEvidenceError::ControllerCollision.into());
    }
    Ok(verified)
}

fn receipt(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    observation: &LearningIterationObservationV1,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let LearningIterationObservationV1::Selection {
        candidate_bundle,
        selection_digest,
    } = observation
    else {
        return Err(OwnerError::Binding("actual original Selection observation").into());
    };
    if selection_digest.is_zero() {
        return Err(OwnerError::Binding("empty original Selection publication").into());
    }
    let receipt = LearningIterationReceiptV1 {
        operation_id: config.decision.request.operation_id.clone(),
        predecessor: config.decision.head_digest,
        actor_id: config.decision.owners.selector.clone(),
        evidence_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-selection-evidence.v1\0",
            config.decision.head_digest.as_array(),
            candidate_bundle.as_array(),
            selection_digest.as_array(),
        ]),
        observed_unix_seconds,
        observation: observation.clone(),
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?;
    coordinator.record(receipt.clone(), observed_unix_seconds)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}

fn sign_original(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    key: &SigningKey,
    payload: &[u8],
    identity: Digest32,
    issued_at: u64,
) -> Result<SignedLearningEvidenceV1, OwnerError> {
    let expires_at = signature_expiry(config, issued_at)?;
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(identity)?,
        principal_id: config.signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Selector,
        trust_digest: config.verifier.trust_digest(),
        scope_digest: config.verifier.scope_digest(),
        objective_digest: config.verifier.objective_digest(),
        authority_epoch: config.signer.principal.authority_epoch,
        issued_at,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    Ok(signed)
}

fn signature_expiry(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    issued_at: u64,
) -> Result<u64, OwnerError> {
    Ok(issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(OwnerError::Binding("signature deadline overflow"))?
        .min(config.signer.principal.expires_at))
}

fn require_new_attestation(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    started_at: u64,
    current: u64,
) -> Result<(), OwnerError> {
    if current < started_at || current >= config.decision.request.envelope.expiry_unix_seconds {
        return Err(OwnerError::Binding(
            "new Selection attestation outside original deadline",
        ));
    }
    Ok(())
}

fn evidence_id(identity: Digest32) -> Result<StableId, OwnerError> {
    StableId::new(format!("original-circuit-selection:{identity}"))
        .map_err(|_| OwnerError::Binding("original Selection evidence id"))
}

fn now() -> Result<u64, OwnerError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| OwnerError::Binding("original Selector clock"))
}
