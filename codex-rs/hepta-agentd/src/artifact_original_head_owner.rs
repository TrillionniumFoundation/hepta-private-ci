//! Original enrolled HEAD key custody and one durable signing attempt.
//! Native create/recover are explicit deployment operations, never commands.
//! Recovery retains the original journal's minimum-anchor reconciliation;
//! command readback never calls create, recover, repair or a signing closure.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::UntrustedArtifactRegistryDurableV1;
use codex_hepta_learning_artifacts::decode_artifact_head_bytes_v1;
use codex_hepta_learning_artifacts::encode_artifact_head_bytes_v1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::sync::Semaphore;

use super::Error;
use super::OriginalArtifactRegistrySourceClientV1;
use super::fresh;
use super::now;
use super::source::QueueFence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

pub struct OriginalArtifactHeadOwnerV1<W: AnchorWitnessStore> {
    pub(super) source: Arc<OriginalArtifactRegistrySourceClientV1>,
    journal: Mutex<LearningOwnerJournalV1<W>>,
    original_key: Mutex<Option<SigningKey>>,
    key: ProductEvaluationExecutionKeyV1,
    original_subject: Digest32,
    admitted: AtomicBool,
    pub(super) connections: Arc<Semaphore>,
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalArtifactHeadOwnerV1<W> {
    /// Consume an already-enrolled native key and the original File/witness.
    /// This is not an Agentd RPC or key-provisioning entrance. The deployment
    /// must already hold the RegistryDurable source; absent custody is an error.
    pub async fn create(
        file: File, witness: W, original_key: SigningKey,
        source: OriginalArtifactRegistrySourceClientV1,
    ) -> Result<Self, Error> {
        let source = Arc::new(source);
        let started = now()?;
        source.config.require_registered_key(&original_key.verifying_key().to_bytes(), started)?;
        let before = source.read_current().await?;
        before.require_unsigned_phase()?;
        let binding = source.config.binding()?;
        let original_subject = before.subject_binding(&source.config)?;
        let queued_source = Arc::clone(&source);
        let queued_before = before.clone();
        let verifying_key = original_key.verifying_key().to_bytes();
        let cancelled = Arc::new(AtomicBool::new(false));
        let waiting = QueueFence(Arc::clone(&cancelled));
        let journal = tokio::task::spawn_blocking(move || {
            if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
            let current_source = queued_source.read_current_in_lane(&cancelled)?;
            if !queued_before.same_original_observation(&current_source) { return Err(Error::CommitUncertain); }
            let current = fresh(started)?;
            queued_source.config.require_registered_key(&verifying_key, current)?;
            current_source.authenticate_current(&queued_source.config, current)?;
            if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
            Ok::<_, Error>(LearningOwnerJournalV1::create(file, witness, binding)?)
        }).await.map_err(|_| Error::CommitUncertain)??;
        drop(waiting);
        let after = source.read_current().await?;
        if !before.same_original_observation(&after) { return Err(Error::CommitUncertain); }
        let current = fresh(started)?;
        after.authenticate_current(&source.config, current)?;
        source.config.require_registered_key(&original_key.verifying_key().to_bytes(), current)?;
        let key = ProductEvaluationExecutionKeyV1 {
            plan_id: source.config.publication.operation_id.clone(),
            binding_digest: original_subject,
        };
        Ok(Self {
            source, journal: Mutex::new(journal), original_key: Mutex::new(Some(original_key)),
            key, original_subject, admitted: AtomicBool::new(false),
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    /// Explicit native recovery consumes only the same original File/witness
    /// and source. No key is needed and no subsequent connection may Sign.
    /// The original recover API may reconcile its retained minimum anchor.
    pub async fn recover(
        file: File, witness: W, source: OriginalArtifactRegistrySourceClientV1,
    ) -> Result<Self, Error> {
        let source = Arc::new(source);
        let started = now()?;
        let before = source.read_current().await?;
        let binding = source.config.binding()?;
        let original_subject = before.subject_binding(&source.config)?;
        let queued_source = Arc::clone(&source);
        let queued_before = before.clone();
        let cancelled = Arc::new(AtomicBool::new(false));
        let waiting = QueueFence(Arc::clone(&cancelled));
        let journal = tokio::task::spawn_blocking(move || {
            if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
            let current_source = queued_source.read_current_in_lane(&cancelled)?;
            if !queued_before.same_original_observation(&current_source) { return Err(Error::CommitUncertain); }
            current_source.authenticate_current(&queued_source.config, fresh(started)?)?;
            if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
            Ok::<_, Error>(LearningOwnerJournalV1::recover(file, witness, binding)?)
        }).await.map_err(|_| Error::CommitUncertain)??;
        drop(waiting);
        let after = source.read_current().await?;
        if !before.same_original_observation(&after) { return Err(Error::CommitUncertain); }
        after.authenticate_current(&source.config, fresh(started)?)?;
        let key = ProductEvaluationExecutionKeyV1 {
            plan_id: source.config.publication.operation_id.clone(),
            binding_digest: original_subject,
        };
        Ok(Self {
            source, journal: Mutex::new(journal), original_key: Mutex::new(None),
            key, original_subject, admitted: AtomicBool::new(true),
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    pub(super) fn sign_original(
        &self, cancelled: &AtomicBool,
    ) -> Result<Vec<u8>, Error> {
        // Called only after the fixed request has authenticated its context.
        // This same owner bit is shared across every connection.
        if self.admitted.swap(true, Ordering::AcqRel) { return Err(Error::ReadbackRequired); }
        if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
        let started = now()?;
        let before = self.source.read_current_in_lane(cancelled)?;
        self.require_subject(&before)?;
        before.require_unsigned_phase()?;
        let key = self.original_key.try_lock().map_err(|_| Error::Busy)?
            .take().ok_or(Error::ReadbackRequired)?;
        if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
        let bytes = {
            let mut journal = self.journal.try_lock().map_err(|_| Error::Busy)?;
            if cancelled.load(Ordering::Acquire) { return Err(Error::CommitUncertain); }
            journal.commit_once(&self.key, || {
                let current = fresh(started).map_err(|_| LearningOriginalOwnerErrorV1::Binding("HEAD claim clock"))?;
                if cancelled.load(Ordering::Acquire) {
                    return Err(LearningOriginalOwnerErrorV1::CommitUncertain);
                }
                self.source.config.require_registered_key(&key.verifying_key().to_bytes(), current)
                    .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original registered HEAD key"))?;
                let mut signed = self.source.config.unsigned_head(&before, current)
                    .map_err(|_| LearningOriginalOwnerErrorV1::Binding("exact current registry subject"))?;
                signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
                let encoded = encode_artifact_head_bytes_v1(&signed)
                    .map_err(|_| LearningOriginalOwnerErrorV1::Binding("canonical original HEAD"))?;
                Ok(encode_record(self.original_subject, &encoded))
            }).map_err(original_journal_error)?
        };
        drop(key);
        // No journal mutex is held while the source reenters its writer host.
        let after = self.source.read_current_in_lane(cancelled)?;
        if !before.same_original_observation(&after) { return Err(Error::CommitUncertain); }
        let saved = self.read_record()?;
        if saved != bytes { return Err(Error::CommitUncertain); }
        let signed = decode_record(self.original_subject, &saved)?;
        let current = fresh(started)?;
        self.require_subject(&after)?;
        self.source.config.verify_original_head(&after, &signed, current)?;
        encode_artifact_head_bytes_v1(&signed).map_err(Error::from)
    }

    pub(super) fn read_original(&self, cancelled: &AtomicBool) -> Result<Vec<u8>, Error> {
        let started = now()?;
        let before = self.source.read_current_in_lane(cancelled)?;
        self.require_subject(&before)?;
        let bytes = self.read_record()?;
        let signed = decode_record(self.original_subject, &bytes)?;
        let after = self.source.read_current_in_lane(cancelled)?;
        // Progress at the writer (including HEAD -> ACK) is never merged into
        // an observation made across a changing read. A later call may observe
        // one stable phase, but it can only return this saved original HEAD.
        if !before.same_original_observation(&after) { return Err(Error::CommitUncertain); }
        let saved = self.read_record()?;
        if saved != bytes { return Err(Error::CommitUncertain); }
        let current = fresh(started)?;
        self.require_subject(&after)?;
        self.source.config.verify_original_head(&after, &signed, current)?;
        encode_artifact_head_bytes_v1(&signed).map_err(Error::from)
    }

    fn require_subject(&self, source: &UntrustedArtifactRegistryDurableV1) -> Result<(), Error> {
        if source.subject_binding(&self.source.config)? != self.original_subject {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    fn read_record(&self) -> Result<Vec<u8>, Error> {
        self.journal.try_lock().map_err(|_| Error::Busy)?.read(&self.key).map_err(original_journal_error)
    }
}

fn original_journal_error(error: LearningOriginalOwnerErrorV1) -> Error {
    match error {
        LearningOriginalOwnerErrorV1::Pending => Error::Pending,
        LearningOriginalOwnerErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing) => Error::Missing,
        other => Error::Journal(other),
    }
}

fn encode_record(subject: Digest32, signed: &[u8]) -> Vec<u8> {
    let mut bytes = b"HARHS001".to_vec();
    bytes.extend_from_slice(subject.as_array());
    bytes.extend_from_slice(&(signed.len() as u32).to_be_bytes());
    bytes.extend_from_slice(signed);
    bytes
}

fn decode_record(subject: Digest32, bytes: &[u8]) -> Result<SignedCurrentArtifactHeadV1, Error> {
    if bytes.len() < 44 || bytes.len() > 16_384
        || bytes.get(..8) != Some(b"HARHS001".as_slice())
        || bytes[8..40] != *subject.as_array()
    {
        return Err(Error::CommitUncertain);
    }
    let length = u32::from_be_bytes(bytes[40..44].try_into().map_err(|_| Error::CommitUncertain)?) as usize;
    if length != bytes.len() - 44 { return Err(Error::CommitUncertain); }
    decode_artifact_head_bytes_v1(&bytes[44..]).map_err(Error::from)
}
