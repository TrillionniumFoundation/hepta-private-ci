//! An independent Root registration and refusal history for one B operation.
//! The full Root context and all primary I/O belong inside the armed action.
//! An interrupted or refused action is never repaired from valid-looking data.
//! This does not protect rollback of the entire original Root authority store.

use std::io;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::files::OriginalBFileIdentity;

#[path = "authority_host_q24_evaluation_acceptance.rs"]
mod acceptance;
use acceptance::OriginalBCompletedAcceptanceV1;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBOutputHeads {
    pub(super) holdout_generation: u64,
    pub(super) holdout_records: u64,
    pub(super) holdout_state: [u8; 32],
    pub(super) execution_sequence: u64,
    pub(super) execution_history: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBEnrollment {
    pub(super) initial_head: [u8; 32],
    pub(super) protocol: [u8; 32],
    pub(super) trust: [u8; 32],
    pub(super) deployment: [u8; 32],
    pub(super) protocol_statement: [u8; 32],
    pub(super) files: Vec<OriginalBFileIdentity>,
    pub(super) registered_at_seconds: u64,
    pub(super) expires_at_seconds: u64,
    pub(super) namespace: [u8; 32],
    pub(super) original_generation: u64,
    pub(super) original_lease: [u8; 32],
    pub(super) heads: Option<OriginalBOutputHeads>,
    pub(super) cell_images: Option<Vec<[u8; 32]>>,
    pub(super) realized_training_head: Option<[u8; 32]>,
    pub(super) realized_plan: Option<[u8; 32]>,
    pub(super) completed_receipt: Option<[u8; 32]>,
    pub(super) released_source: Option<super::provider::OriginalBReleasedSource>,
    pub(super) output_images: Vec<[u8; 32]>,
    pub(super) realized_plan_statement: Option<[u8; 32]>,
    pub(super) original_training_attestation: Option<Vec<u8>>,
    pub(super) original_training_work:
        Option<crate::cell_composed_q24::OriginalQ24TrainingWorkDataV1>,
    pub(super) admitted_source: Option<super::provider::OriginalBReleasedSource>,
    pub(super) completed_acceptance: Option<OriginalBCompletedAcceptanceV1>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Phase {
    Registering,
    Ready,
    Inspecting,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Record {
    schema: u8,
    purpose: String,
    initial_head: [u8; 32],
    attempt: u64,
    phase: Phase,
    enrollment: Option<OriginalBEnrollment>,
}

pub(super) struct OriginalBRecord {
    store: HostAuthorityFrontierStore<Record>,
    owner: String,
    initial_head: [u8; 32],
    gate: Mutex<()>,
    poisoned: AtomicBool,
}

impl OriginalBRecord {
    pub(super) fn register<T>(
        root: Arc<RootAuthorityDirectory>,
        initial: &LearningIterationSnapshotV1,
        end: Instant,
        action: impl FnOnce() -> io::Result<(OriginalBEnrollment, T)>,
    ) -> io::Result<(Self, T)> {
        crate::authority_host_service::generation_initial::original_root()?;
        let owner = owner(initial)?;
        let armed = Record {
            schema: 2,
            purpose: "runtime.learning.independent-b-registration.v2".into(),
            initial_head: initial.head_digest.into_array(),
            attempt: 1,
            phase: Phase::Registering,
            enrollment: None,
        };
        let store = HostAuthorityFrontierStore::initialize(root, owner.clone(), armed.clone())
            .map_err(io::Error::other)?;
        let held = Self {
            store,
            owner,
            initial_head: initial.head_digest.into_array(),
            gate: Mutex::new(()),
            poisoned: AtomicBool::new(false),
        };
        let (enrollment, result) = action()?;
        if Instant::now() >= end
            || enrollment.initial_head != armed.initial_head
            || enrollment.protocol != initial.request.evaluation_profile.into_array()
            || enrollment.trust != initial.owners.evidence_trust_digest.into_array()
            || enrollment.protocol_statement == [0; 32]
            || enrollment.registered_at_seconds == 0
            || enrollment.registered_at_seconds >= enrollment.expires_at_seconds
            || enrollment.expires_at_seconds != initial.request.envelope.expiry_unix_seconds
            || enrollment.heads.is_some()
            || enrollment.cell_images.is_some()
            || enrollment.realized_plan.is_some()
            || enrollment.realized_training_head.is_some()
            || enrollment.completed_receipt.is_some()
            || enrollment.released_source.is_some()
            || !enrollment.output_images.is_empty()
            || enrollment.realized_plan_statement.is_some()
            || enrollment.original_training_attestation.is_some()
            || enrollment.original_training_work.is_some()
            || enrollment.admitted_source.is_some()
            || enrollment.completed_acceptance.is_some()
            || enrollment.files.is_empty()
            || enrollment.files.len() > 64
            || enrollment.namespace == [0; 32]
            || enrollment.original_generation == 0
            || enrollment.original_lease == [0; 32]
        {
            return Err(io::Error::other(
                "original B registration differs from its Root owner",
            ));
        }
        let mut ready = armed.clone();
        ready.phase = Phase::Ready;
        ready.enrollment = Some(enrollment);
        held.store
            .compare_and_set(&held.owner, &armed, &ready)
            .map_err(io::Error::other)?;
        if held.store.load(&held.owner).map_err(io::Error::other)? != ready {
            return Err(io::Error::other(
                "original B registration acknowledgement differs",
            ));
        }
        Ok((held, result))
    }

    pub(super) fn open(
        root: Arc<RootAuthorityDirectory>,
        initial: &LearningIterationSnapshotV1,
    ) -> io::Result<Self> {
        crate::authority_host_service::generation_initial::original_root()?;
        let owner = owner(initial)?;
        let store =
            HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?;
        let held = Self {
            store,
            owner,
            initial_head: initial.head_digest.into_array(),
            gate: Mutex::new(()),
            poisoned: AtomicBool::new(false),
        };
        held.load_ready()?;
        Ok(held)
    }

    /// Only the private original host can update its actual output heads.
    /// Immutable preregistration identity cannot be replaced by an action.
    pub(super) fn inspect<T>(
        &self,
        end: Instant,
        action: impl FnOnce(&mut OriginalBEnrollment) -> io::Result<T>,
    ) -> io::Result<T> {
        crate::authority_host_service::generation_initial::original_root()?;
        let _gate = self
            .gate
            .try_lock()
            .map_err(|_| io::Error::other("original B owner is busy"))?;
        let before = self.load_ready()?;
        let mut armed = before.clone();
        armed.attempt = before
            .attempt
            .checked_add(1)
            .ok_or_else(|| io::Error::other("original B attempt exhausted"))?;
        armed.phase = Phase::Inspecting;
        let result = (|| {
            self.store
                .compare_and_set(&self.owner, &before, &armed)
                .map_err(io::Error::other)?;
            let mut enrollment = before
                .enrollment
                .clone()
                .ok_or_else(|| io::Error::other("original B registration missing"))?;
            let value = action(&mut enrollment)?;
            let mut immutable = enrollment.clone();
            let original = before
                .enrollment
                .as_ref()
                .ok_or_else(|| io::Error::other("original B registration missing"))?;
            immutable.heads = original.heads.clone();
            immutable.cell_images = original.cell_images.clone();
            immutable.realized_training_head = original.realized_training_head;
            immutable.realized_plan = original.realized_plan;
            immutable.completed_receipt = original.completed_receipt;
            immutable.released_source = original.released_source.clone();
            immutable.output_images = original.output_images.clone();
            immutable.realized_plan_statement = original.realized_plan_statement;
            immutable.original_training_attestation =
                original.original_training_attestation.clone();
            immutable.admitted_source = original.admitted_source.clone();
            immutable.original_training_work = original.original_training_work.clone();
            immutable.completed_acceptance = original.completed_acceptance.clone();
            if &immutable != original
                || original
                    .completed_acceptance
                    .as_ref()
                    .is_some_and(|old| enrollment.completed_acceptance.as_ref() != Some(old))
                || original
                    .original_training_work
                    .as_ref()
                    .is_some_and(|old| enrollment.original_training_work.as_ref() != Some(old))
                || original
                    .admitted_source
                    .as_ref()
                    .is_some_and(|old| enrollment.admitted_source.as_ref() != Some(old))
                || self.poisoned.load(Ordering::Acquire)
                || Instant::now() >= end
            {
                return Err(io::Error::other("original B registration was changed"));
            }
            OriginalBEnrollment::require_completed_acceptance(&enrollment)?;
            let mut ready = armed.clone();
            ready.phase = Phase::Ready;
            ready.enrollment = Some(enrollment);
            self.store
                .compare_and_set(&self.owner, &armed, &ready)
                .map_err(io::Error::other)?;
            if self.store.load(&self.owner).map_err(io::Error::other)? != ready {
                return Err(io::Error::other("original B final readback differs"));
            }
            Ok(value)
        })();
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        result
    }

    fn load_ready(&self) -> io::Result<Record> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(io::Error::other("original B owner was refused"));
        }
        let loaded = match self.store.load(&self.owner) {
            Ok(loaded) => loaded,
            Err(error) => {
                self.poisoned.store(true, Ordering::Release);
                return Err(io::Error::other(error));
            }
        };
        if loaded.schema != 2
            || loaded.purpose != "runtime.learning.independent-b-registration.v2"
            || loaded.initial_head != self.initial_head
            || loaded.attempt == 0
            || loaded.phase != Phase::Ready
            || loaded
                .enrollment
                .as_ref()
                .is_none_or(|entry| entry.initial_head != self.initial_head)
        {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "original B attempt is absent, unfinished or refused",
            ));
        }
        let acceptance = OriginalBEnrollment::require_completed_acceptance(
            loaded
                .enrollment
                .as_ref()
                .ok_or_else(|| io::Error::other("original B enrollment absent"))?,
        );
        if let Err(error) = acceptance {
            self.poisoned.store(true, Ordering::Release);
            return Err(error);
        }
        Ok(loaded)
    }
}

fn owner(initial: &LearningIterationSnapshotV1) -> io::Result<String> {
    let request = &initial.request;
    let encoded = serde_json::to_vec(&(
        request.principal_id.as_str(),
        request.agent_id.as_str(),
        request.cell_id.as_str(),
        request.operation_id.as_str(),
    ))
    .map_err(io::Error::other)?;
    Ok(format!("independent-b-v1/{}", Digest32::of_bytes(&encoded)))
}
