//! Materialize one real Memory revision for a named Joint text-loss profile.
//!
//! Reads the existing Memory and signed Ledger owners without creating grants,
//! data, labels, weights, Training receipts or model authority. The returned
//! value is a bounded data snapshot, not a continuing authorization lease.
//! Re-materialize through these owners before later training or artifact use.

use std::collections::BTreeSet;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::TryLockError;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::FederationConsumerAccess;
use codex_hepta_memory::SharedExperiencePurposeV1;
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use sha2::Digest;
use sha2::Sha256;

/// Exact Memory Replay grant scope for this data mapping, not a training grant.
pub const JOINT_MEMORY_TEXT_REPLAY_SCOPE_V1: &str = "joint-v4-verified-memory-text-replay-v1";
const MAX_SOURCE_RECORDS: usize = 4096;
const MAX_PREFIX_BYTES: usize = 4096;
const MAX_CONTINUATION_SCALARS: usize = 128;
const MAX_TEXT_BYTES: usize = MAX_PREFIX_BYTES + 4 * MAX_CONTINUATION_SCALARS;
const PROFILE: &[u8] = b"hepta.joint.memory-text-mapping.v1\0one-memory-revision;lossless-utf8;tail-at-most-128-scalars;prefix-at-most-4096-bytes;fresh-text-loss-state;no-outcome-targets;no-nontext-tensors";

/// Existing owner handles and independently signed dataset evidence. The
/// consumer configuration is not authority by itself: Memory checks its grant.
pub struct JointMemoryTextReplayAdmissionV1<'a> {
    pub consumer: &'a FederationConsumerAccess,
    pub source: &'a SharedExperienceUseV1,
    pub dataset_plan: &'a DatasetFreezePlanV2,
    pub freeze_evidence: &'a SignedLearningEvidenceV1,
    pub expected_dataset_digest: Digest32,
    pub maximum_source_records: usize,
    pub maximum_text_bytes: usize,
}

#[derive(Debug, thiserror::Error)]
pub enum JointMemoryTextReplayErrorV1 {
    #[error("Memory source: {0}")]
    Memory(#[from] CognitiveStoreError),
    #[error("signed dataset owner: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("dataset owner is busy")]
    Busy,
    #[error("dataset owner lock is poisoned")]
    Poisoned,
    #[error("Joint Memory text binding: {0}")]
    Binding(&'static str),
}

/// Immutable, non-authorizing input. Original records preserve scalar outcomes,
/// pending/censored facts and run-snapshot digests; none becomes a text target.
/// This is one sample per Memory revision, not one sample per decision row.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JointVerifiedMemoryTextReplayV1 {
    consumer: FederationConsumerAccess,
    source: SharedExperienceUseV1,
    dataset_plan: DatasetFreezePlanV2,
    freeze_evidence: SignedLearningEvidenceV1,
    dataset: DatasetSnapshotReceiptV3,
    ledger_binding: Digest32,
    trust_distribution: Digest32,
    trust_generation: u64,
    records: Vec<LedgerRecord>,
    prefix: String,
    continuation: String,
    mapping_digest: Digest32,
}

impl JointVerifiedMemoryTextReplayV1 {
    pub fn consumer(&self) -> &FederationConsumerAccess {
        &self.consumer
    }

    pub fn source_use(&self) -> &SharedExperienceUseV1 {
        &self.source
    }

    pub fn dataset_plan(&self) -> &DatasetFreezePlanV2 {
        &self.dataset_plan
    }

    pub fn freeze_evidence(&self) -> &SignedLearningEvidenceV1 {
        &self.freeze_evidence
    }

    pub fn dataset(&self) -> &DatasetSnapshotReceiptV3 {
        &self.dataset
    }

    pub fn ledger_binding(&self) -> Digest32 {
        self.ledger_binding
    }

    pub fn trust_distribution(&self) -> Digest32 {
        self.trust_distribution
    }

    pub fn trust_generation(&self) -> u64 {
        self.trust_generation
    }

    pub fn records(&self) -> &[LedgerRecord] {
        &self.records
    }

    pub fn prefix(&self) -> &str {
        &self.prefix
    }

    pub fn continuation(&self) -> &str {
        &self.continuation
    }

    pub fn mapping_digest(&self) -> Digest32 {
        self.mapping_digest
    }

    /// Describes data splitting only, not an optimizer, evaluation or update rule.
    pub fn profile_digest(&self) -> Digest32 {
        Digest32::of_bytes(PROFILE)
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Read the original owners and preserve the exact source-to-dataset mapping.
/// Signed freeze is repeated after Memory revalidation under the same real
/// LedgerWriter; no lock crosses an await and a busy writer fails immediately.
/// Bounds cover admitted data, not the owners' internal replay/SQLite work.
pub async fn materialize_joint_verified_memory_text_v1(
    memory_owner: &CognitiveStore,
    ledger: &Mutex<LedgerWriter>,
    admission: JointMemoryTextReplayAdmissionV1<'_>,
) -> Result<JointVerifiedMemoryTextReplayV1, JointMemoryTextReplayErrorV1> {
    if admission.maximum_source_records == 0
        || admission.maximum_source_records > MAX_SOURCE_RECORDS
        || admission.maximum_text_bytes == 0
        || admission.maximum_text_bytes > MAX_TEXT_BYTES
        || admission.expected_dataset_digest.is_zero()
    {
        return Err(JointMemoryTextReplayErrorV1::Binding("admission bounds"));
    }
    let purpose = SharedExperiencePurposeV1::Replay {
        parameter_scope: JOINT_MEMORY_TEXT_REPLAY_SCOPE_V1.to_owned(),
        artifact_consumer: admission.consumer.agent_id().clone(),
    };
    if admission.source.purpose() != &purpose {
        return Err(JointMemoryTextReplayErrorV1::Binding(
            "exact Replay purpose",
        ));
    }
    let source = memory_owner
        .read_shared_experience(admission.consumer, admission.source.policy_id(), &purpose)
        .await?;
    if &source != admission.source {
        return Err(JointMemoryTextReplayErrorV1::Binding(
            "Memory source changed",
        ));
    }
    let (prefix, continuation) =
        split_text(&source.memory().content, admission.maximum_text_bytes)?;
    let content_digest: Digest32 = source
        .memory()
        .content_sha256
        .as_str()
        .parse()
        .map_err(|_| JointMemoryTextReplayErrorV1::Binding("content digest"))?;
    if Digest32::of_bytes(source.memory().content.as_bytes()) != content_digest {
        return Err(JointMemoryTextReplayErrorV1::Binding(
            "actual content bytes",
        ));
    }
    let support: Digest32 = source
        .source_support_digest()
        .as_str()
        .parse()
        .map_err(|_| JointMemoryTextReplayErrorV1::Binding("source support"))?;
    let (dataset, records, ledger_binding, trust_distribution, trust_generation) = {
        let owner = lock_ledger(ledger)?;
        let now = unix_now()?;
        // Public receipt fields alone do not prove a signed Evaluator admission.
        let dataset = owner.freeze_dataset(
            admission.dataset_plan.clone(),
            admission.freeze_evidence,
            now,
        )?;
        if dataset.snapshot.dataset_digest != admission.expected_dataset_digest
            || dataset.snapshot.source_record_digests.len() > admission.maximum_source_records
        {
            return Err(JointMemoryTextReplayErrorV1::Binding(
                "dataset pin or capacity",
            ));
        }
        let records = owner.read_dataset_records(&dataset, now)?;
        validate_records(&records, admission.dataset_plan.objective_digest, support)?;
        let records = records.into_iter().cloned().collect();
        (
            dataset,
            records,
            owner.binding_digest(),
            owner.trust_distribution_digest(),
            owner.trust_generation(),
        )
    };
    memory_owner.revalidate_shared_experience(&source).await?;
    {
        let owner = lock_ledger(ledger)?;
        let now = unix_now()?;
        let current = owner.freeze_dataset(
            admission.dataset_plan.clone(),
            admission.freeze_evidence,
            now,
        )?;
        if current != dataset
            || owner.binding_digest() != ledger_binding
            || owner.trust_distribution_digest() != trust_distribution
            || owner.trust_generation() != trust_generation
        {
            return Err(JointMemoryTextReplayErrorV1::Binding(
                "dataset or trust changed",
            ));
        }
        owner.revalidate_dataset_snapshot(&dataset, now)?;
    }
    let mut result = JointVerifiedMemoryTextReplayV1 {
        consumer: admission.consumer.clone(),
        source,
        dataset_plan: admission.dataset_plan.clone(),
        freeze_evidence: admission.freeze_evidence.clone(),
        dataset,
        ledger_binding,
        trust_distribution,
        trust_generation,
        records,
        prefix,
        continuation,
        mapping_digest: Digest32::ZERO,
    };
    result.mapping_digest = mapping_digest(&result);
    Ok(result)
}

fn lock_ledger(
    ledger: &Mutex<LedgerWriter>,
) -> Result<MutexGuard<'_, LedgerWriter>, JointMemoryTextReplayErrorV1> {
    ledger.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => JointMemoryTextReplayErrorV1::Busy,
        TryLockError::Poisoned(_) => JointMemoryTextReplayErrorV1::Poisoned,
    })
}

fn unix_now() -> Result<u64, JointMemoryTextReplayErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .map_err(|_| JointMemoryTextReplayErrorV1::Binding("host clock"))
}

fn split_text(
    content: &str,
    maximum_bytes: usize,
) -> Result<(String, String), JointMemoryTextReplayErrorV1> {
    if content.is_empty() || content.len() > maximum_bytes || content.len() > MAX_TEXT_BYTES {
        return Err(JointMemoryTextReplayErrorV1::Binding("complete text bound"));
    }
    let split = content
        .char_indices()
        .rev()
        .nth(MAX_CONTINUATION_SCALARS - 1)
        .map_or(/*default*/ 0, |(offset, _)| offset);
    if split > MAX_PREFIX_BYTES {
        return Err(JointMemoryTextReplayErrorV1::Binding(
            "complete prefix bound",
        ));
    }
    let (prefix, continuation) = content.split_at(split);
    Ok((prefix.to_owned(), continuation.to_owned()))
}

fn validate_records(
    records: &[&LedgerRecord],
    objective: Digest32,
    support: Digest32,
) -> Result<(), JointMemoryTextReplayErrorV1> {
    let mut episodes = BTreeSet::new();
    for record in records {
        if let LedgerEvent::AuthenticatedDecisionV2(decision) = &record.event {
            if decision.objective_digest != objective || decision.support_digest != support {
                return Err(JointMemoryTextReplayErrorV1::Binding(
                    "decision source or objective",
                ));
            }
            episodes.insert(&decision.episode_id);
        }
    }
    if episodes.is_empty() {
        return Err(JointMemoryTextReplayErrorV1::Binding(
            "authenticated decisions required",
        ));
    }
    for record in records {
        let episode = match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => &value.episode_id,
            LedgerEvent::AuthenticatedOutcomeV2(value) => &value.episode_id,
            LedgerEvent::CreditBatchV2(value) => &value.episode_id,
            LedgerEvent::Decision(_)
            | LedgerEvent::RetrievalAssignment(_)
            | LedgerEvent::Outcome(_)
            | LedgerEvent::Credit(_)
            | LedgerEvent::PromptDelivery(_)
            | LedgerEvent::Revocation(_)
            | LedgerEvent::UnlearningLineageV1(_) => {
                return Err(JointMemoryTextReplayErrorV1::Binding(
                    "unexpected dataset record",
                ));
            }
        };
        if !episodes.contains(episode) {
            return Err(JointMemoryTextReplayErrorV1::Binding(
                "unlinked dataset episode",
            ));
        }
    }
    Ok(())
}

fn mapping_digest(value: &JointVerifiedMemoryTextReplayV1) -> Digest32 {
    let mut hash = Sha256::new();
    let mut signed_bytes = value.freeze_evidence.signing_bytes();
    signed_bytes.extend_from_slice(&value.freeze_evidence.signature);
    let profile = value.profile_digest();
    let policy_revision = value.source.policy_revision().to_be_bytes();
    let support = value.source.source_support_digest();
    let generation = value.trust_generation.to_be_bytes();
    let evidence_digest = Digest32::of_bytes(&signed_bytes);
    let record_count = (value.records.len() as u64).to_be_bytes();
    for part in [
        b"hepta.joint.memory-text-materialization.v1".as_slice(),
        profile.as_array(),
        value.consumer.agent_id().as_str().as_bytes(),
        value.consumer.workspace_sha256().as_str().as_bytes(),
        value.source.policy_id().as_str().as_bytes(),
        &policy_revision,
        support.as_str().as_bytes(),
        value.ledger_binding.as_array(),
        value.trust_distribution.as_array(),
        &generation,
        value.dataset.snapshot.dataset_digest.as_array(),
        evidence_digest.as_array(),
        &record_count,
    ] {
        frame(&mut hash, part);
    }
    for record in &value.records {
        let sequence = record.sequence.get().to_be_bytes();
        for part in [
            sequence.as_slice(),
            record.predecessor_chain_digest.as_array().as_slice(),
            record.event_digest.as_array(),
            record.chain_digest.as_array(),
        ] {
            frame(&mut hash, part);
        }
    }
    frame(&mut hash, value.prefix.as_bytes());
    frame(&mut hash, value.continuation.as_bytes());
    Digest32::from_array(hash.finalize().into())
}

fn frame(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_be_bytes());
    hash.update(bytes);
}

#[cfg(test)]
#[path = "joint_memory_text_replay_tests.rs"]
mod tests;
