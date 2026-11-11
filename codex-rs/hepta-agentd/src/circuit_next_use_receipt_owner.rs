//! Original Observer receipts over a completed, originally published ordinary C.
//! The host supplies enrolled custody, original files and connected predecessor
//! owners. This owner neither runs C nor selects, adopts or enrolls any owner.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
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
}
type Error = OriginalCircuitNextUseReceiptErrorV1;

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
    fn trainer(&self) -> &LearningIterationEvidenceClientV1;
    fn selector(&self) -> &LearningIterationEvidenceClientV1;
    async fn observe(
        &self,
        config: &OriginalCircuitNextUseReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error>;
}

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> NextUseSources
    for OriginalCircuitNextUseReceiptSourcesV1<'_, C, S>
{
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }
    fn trainer(&self) -> &LearningIterationEvidenceClientV1 {
        self.trainer
    }
    fn selector(&self) -> &LearningIterationEvidenceClientV1 {
        self.selector
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
    fn trainer(&self) -> &LearningIterationEvidenceClientV1 {
        self.trainer
    }
    fn selector(&self) -> &LearningIterationEvidenceClientV1 {
        self.selector
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

async fn remote_predecessors(
    source: &OriginalCircuitNextUseRemoteSourcesV1<'_>,
    config: &OriginalCircuitNextUseReceiptConfigV1,
) -> Result<[SignedLearningEvidenceV1; 2], Error> {
    let trainer: &LearningIterationEvidenceClientV1 = source.trainer;
    let selector: &LearningIterationEvidenceClientV1 = source.selector;
    Ok([
        trainer
            .readback(
                source.snapshot,
                prior(config, LearningIterationStageV1::Training)?,
            )
            .await?,
        selector
            .readback(
                source.snapshot,
                prior(config, LearningIterationStageV1::Selection)?,
            )
            .await?,
    ])
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
    let before = remote_predecessors(source, config).await?;
    authenticate_predecessors(config, &before, now()?)?;
    let original = live.read_current().await?;
    let after = remote_predecessors(source, config).await?;
    authenticate_predecessors(config, &after, now()?)?;
    Ok(original.observation().clone())
}

pub struct OriginalCircuitNextUseReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCircuitNextUseReceiptConfigV1,
    key: SigningKey,
    saved: ProductEvaluationExecutionKeyV1,
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
            key,
            saved,
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
            key,
            saved,
        })
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
        require_new_attestation(&self.config, started_at, started_at)?;
        let observed = self.prepare(&source).await?;
        // A completed coordinator can only recover an existing owner result.
        if source.snapshot().receipts.len() > self.config.selection.receipts.len() {
            return self.readback_source(source).await;
        }
        let evidence = self.predecessors(&source).await?;
        authenticate_predecessors(&self.config, &evidence, now()?)?;
        if self.prepare(&source).await? != observed {
            return Err(OwnerError::CommitUncertain.into());
        }
        let config = &self.config;
        let key = &self.key;
        let identity = self.saved.binding_digest;
        let bytes = self.journal.commit_once(&self.saved, || {
            let issued_at = now()?;
            require_new_attestation(config, started_at, issued_at)?;
            let predecessors = authenticate_predecessors(config, &evidence, issued_at)
                .map_err(|_| OwnerError::Binding("current original predecessor roles"))?;
            let receipt = receipt(config, &observed, issued_at)
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
            for predecessor in &predecessors {
                verify_signed_actor_separation(predecessor, &verified, issued_at)?;
            }
            learning_owner_evidence::encode(&payload, &signed)
        })?;
        self.authenticate_completed(&source, &observed, &bytes, started_at, true)
            .await
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
        let observed = self.prepare(&source).await?;
        let bytes = self.journal.read(&self.saved)?;
        self.authenticate_completed(&source, &observed, &bytes, started_at, false)
            .await
    }

    async fn prepare(
        &self,
        source: &impl NextUseSources,
    ) -> Result<LearningIterationObservationV1, Error> {
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
        let observation = source.observe(&self.config).await?;
        self.config.scope.validate_observation(&observation)?;
        Ok(observation)
    }

    async fn predecessors(
        &self,
        source: &impl NextUseSources,
    ) -> Result<[SignedLearningEvidenceV1; 2], Error> {
        let trainer: &LearningIterationEvidenceClientV1 = source.trainer();
        let selector: &LearningIterationEvidenceClientV1 = source.selector();
        Ok([
            trainer
                .readback(
                    source.snapshot(),
                    prior(&self.config, LearningIterationStageV1::Training)?,
                )
                .await?,
            selector
                .readback(
                    source.snapshot(),
                    prior(&self.config, LearningIterationStageV1::Selection)?,
                )
                .await?,
        ])
    }

    async fn authenticate_completed(
        &mut self,
        source: &impl NextUseSources,
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
                .get(self.config.selection.receipts.len())
                .is_some_and(|saved| saved != &receipt)
        {
            return Err(OwnerError::Binding("changed original C receipt").into());
        }
        let evidence = self.predecessors(source).await?;
        if self.prepare(source).await? != *observed {
            return Err(OwnerError::CommitUncertain.into());
        }
        if self.journal.read(&self.saved)? != bytes {
            return Err(OwnerError::CommitUncertain.into());
        }
        let current = now()?;
        if current < started_at {
            return Err(OwnerError::Binding("original Observer clock moved backwards").into());
        }
        if new_attestation {
            require_new_attestation(&self.config, started_at, current)?;
        }
        let predecessors = authenticate_predecessors(&self.config, &evidence, current)?;
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
        for predecessor in &predecessors {
            verify_signed_actor_separation(predecessor, &verified, current)?;
        }
        Ok((receipt, signed))
    }
}

fn validate_config(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    key: &SigningKey,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.selection.clone())?;
    config.scope.validate_snapshot(&config.selection)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::NextUse)
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || config.signer.principal.principal_id != config.selection.owners.next_use_observer
        || config.selection.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.selection.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(OwnerError::Binding("original C Observer capability").into());
    }
    let current = now()?;
    authenticate_predecessors(
        config,
        &[
            config.training_evidence.clone(),
            config.selection_evidence.clone(),
        ],
        current,
    )?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: config.selection.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-next-use-receipt.v1\0",
            config.selection.head_digest.as_array(),
            config.scope.binding().as_array(),
            config.verifier.trust_digest().as_array(),
            config.signer.principal.principal_id.as_str().as_bytes(),
            &config.signer.verifying_key,
            &config.training_evidence.signing_bytes(),
            &config.training_evidence.signature,
            &config.selection_evidence.signing_bytes(),
            &config.selection_evidence.signature,
            &config.maximum_signature_lifetime_seconds.to_be_bytes(),
        ]),
    })
}

fn prior(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    stage: LearningIterationStageV1,
) -> Result<&LearningIterationReceiptV1, Error> {
    config
        .selection
        .receipts
        .iter()
        .find(|receipt| receipt.observation.stage() == stage)
        .ok_or_else(|| OwnerError::Binding("original predecessor receipt").into())
}

fn authenticate_predecessors(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    evidence: &[SignedLearningEvidenceV1; 2],
    current: u64,
) -> Result<[VerifiedLearningEvidenceV1; 2], Error> {
    if evidence[0] != config.training_evidence || evidence[1] != config.selection_evidence {
        return Err(OwnerError::Binding("changed original predecessor signatures").into());
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        current,
    )?;
    let verify = |index, stage, role| -> Result<VerifiedLearningEvidenceV1, Error> {
        let original = prior(config, stage)?;
        let verified = config.verifier.verify(
            role,
            &evidence[index],
            &learning_iteration_receipt_signing_bytes_v1(original)?,
            current,
        )?;
        if verified.principal().principal_id != original.actor_id {
            return Err(OwnerError::Binding("original predecessor actor").into());
        }
        verify_independent_roles(verified.principal(), &config.signer.principal, current)
            .map_err(SignedEvidenceError::from)?;
        if verified.controller_id() == &config.signer.controller_id {
            return Err(SignedEvidenceError::ControllerCollision.into());
        }
        Ok(verified)
    };
    Ok([
        verify(
            0,
            LearningIterationStageV1::Training,
            LearningEvidenceRoleV1::Generator,
        )?,
        verify(
            1,
            LearningIterationStageV1::Selection,
            LearningEvidenceRoleV1::Selector,
        )?,
    ])
}

fn receipt(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    observation: &LearningIterationObservationV1,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let committed = match observation {
        LearningIterationObservationV1::NextUse {
            committed_step_receipt,
            ..
        }
        | LearningIterationObservationV1::RetainedModelNextUse {
            committed_step_receipt,
            ..
        } => committed_step_receipt,
        _ => return Err(OwnerError::Binding("actual original C completion").into()),
    };
    if committed.is_zero() {
        return Err(OwnerError::Binding("empty original C completion").into());
    }
    let receipt = LearningIterationReceiptV1 {
        operation_id: config.selection.request.operation_id.clone(),
        predecessor: config.selection.head_digest,
        actor_id: config.selection.owners.next_use_observer.clone(),
        evidence_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-next-use-evidence.v1\0",
            config.selection.head_digest.as_array(),
            committed.as_array(),
        ]),
        observed_unix_seconds,
        observation: observation.clone(),
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(config.selection.clone())?;
    coordinator.record(receipt.clone(), observed_unix_seconds)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}

fn sign_original(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    key: &SigningKey,
    payload: &[u8],
    identity: Digest32,
    issued_at: u64,
) -> Result<SignedLearningEvidenceV1, OwnerError> {
    let expires_at = issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(OwnerError::Binding("signature deadline overflow"))?
        .min(config.signer.principal.expires_at);
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(identity)?,
        principal_id: config.signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
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

fn require_new_attestation(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    started_at: u64,
    current: u64,
) -> Result<(), OwnerError> {
    if current < started_at || current >= config.selection.request.envelope.expiry_unix_seconds {
        return Err(OwnerError::Binding(
            "new C attestation outside original deadline",
        ));
    }
    Ok(())
}

fn evidence_id(identity: Digest32) -> Result<StableId, OwnerError> {
    StableId::new(format!("original-circuit-next-use:{identity}"))
        .map_err(|_| OwnerError::Binding("original C evidence id"))
}

fn now() -> Result<u64, OwnerError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| OwnerError::Binding("original Observer clock"))
}

#[cfg(test)]
#[path = "circuit_next_use_receipt_owner_tests.rs"]
mod tests;
