//! Independent publication refusal, armed before primary or physical reads.
//! The slot is the original learning operation, never a caller-selected target.
//! Ready proves completed verification, not reply delivery or a new authority.
//! Rollback of the independent Root refusal history is outside this guarantee.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;

use super::*;

const PURPOSE: &str = "runtime.learning.publication-refusal.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PublicationRefusalBinding {
    schema: u8,
    purpose: String,
    publication_purpose: String,
    learning_operation: String,
    initial: String,
    scope: String,
    previous: CellGenerationOwnerBindingV1,
    target: CellGenerationOwnerBindingV1,
}

impl PublicationRefusalBinding {
    pub(super) fn from_original(
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        inputs: &RootGenerationPublicationEnrollmentV1,
        version: PublicationVersion,
    ) -> io::Result<Self> {
        scope.validate_snapshot(initial).map_err(io::Error::other)?;
        Ok(Self {
            schema: 1,
            purpose: PURPOSE.into(),
            publication_purpose: version.purpose().into(),
            learning_operation: initial.request.operation_id.to_string(),
            initial: initial.head_digest.to_string(),
            scope: scope.binding().to_string(),
            previous: CellGenerationOwnerBindingV1::new(
                &inputs.previous.config.generation,
                inputs.previous.config.journal_records,
            )
            .map_err(io::Error::other)?,
            target: CellGenerationOwnerBindingV1::new(
                &inputs.target.config.generation,
                inputs.target.config.journal_records,
            )
            .map_err(io::Error::other)?,
        })
    }

    fn owner(&self) -> String {
        // Changing the target, scope, version or decision cannot create another
        // gate for this same learning operation. All remain in the full record.
        format!(
            "publication-refusal/{}",
            Digest32::of_bytes(self.learning_operation.as_bytes())
        )
    }

    fn require_profile(&self, reserved: &ReservedPublicationProfile) -> io::Result<()> {
        let original = ReservedPublicationProfile::original_for_version(
            reserved,
            PublicationVersion::from_purpose(&self.publication_purpose)?,
        )?;
        if original.learning_operation != self.learning_operation
            || original.initial != self.initial
            || original.scope != self.scope
            || original.intent.previous != self.previous
            || original.intent.target != self.target
        {
            return Err(io::Error::other(
                "original publication refusal binding differs",
            ));
        }
        original.intent.digest().map_err(io::Error::other)?;
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Phase {
    Armed,
    Ready,
    Refused,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RefusalRecord {
    binding: PublicationRefusalBinding,
    attempt: u64,
    phase: Phase,
    // None exists only during the first armed registration. Recovery cannot
    // infer or initialize the complete profile from restored primary bytes.
    original: Option<ReservedPublicationProfile>,
}

pub(super) struct PublicationRefusal {
    store: HostAuthorityFrontierStore<RefusalRecord>,
    binding: PublicationRefusalBinding,
    owner: String,
    gate: Mutex<()>,
    poisoned: AtomicBool,
}

impl PublicationRefusal {
    /// Both modes arm before entering the actual Root registration and all
    /// physical opens. Only Reserve creates; Recover requires an existing Ready
    /// marker, including for legacy records. A missing marker is never repaired.
    pub(super) fn enroll<T>(
        root: Arc<RootAuthorityDirectory>,
        binding: PublicationRefusalBinding,
        mode: RootGenerationPublicationModeV1,
        end: Instant,
        action: impl FnOnce(Arc<Self>) -> io::Result<(T, ReservedPublicationProfile)>,
    ) -> io::Result<T> {
        original_root()?;
        require_end(end)?;
        let owner = binding.owner();
        let store = match mode {
            RootGenerationPublicationModeV1::Reserve => HostAuthorityFrontierStore::initialize(
                root,
                owner.clone(),
                RefusalRecord {
                    binding: binding.clone(),
                    attempt: 1,
                    phase: Phase::Armed,
                    original: None,
                },
            ),
            RootGenerationPublicationModeV1::Recover => {
                HostAuthorityFrontierStore::open(root, owner.clone())
            }
        }
        .map_err(io::Error::other)?;
        let retained = Arc::new(Self {
            store,
            binding,
            owner,
            gate: Mutex::new(()),
            poisoned: AtomicBool::new(false),
        });
        let _gate = retained
            .gate
            .try_lock()
            .map_err(|_| io::Error::other("original publication enrollment busy"))?;
        let observed = retained.load_matching()?;
        let armed = match mode {
            RootGenerationPublicationModeV1::Reserve => {
                if observed.phase != Phase::Armed
                    || observed.attempt != 1
                    || observed.original.is_some()
                {
                    return Err(io::Error::other("fresh original publication arm differs"));
                }
                observed
            }
            RootGenerationPublicationModeV1::Recover => retained.arm_ready(observed)?,
        };
        retained.complete_armed(&armed, end, || action(Arc::clone(&retained)))
    }

    /// The complete writer-context call, CURRENT CAS/readback and physical
    /// postchecks belong inside action. Same-kind operations never nest arms.
    pub(super) fn inspect<T>(
        &self,
        original: &ReservedPublicationProfile,
        end: Instant,
        action: impl FnOnce() -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        let _gate = self
            .gate
            .try_lock()
            .map_err(|_| io::Error::other("original publication inspection busy"))?;
        if self.poisoned.load(Ordering::Acquire) {
            return Err(io::Error::other(
                "original publication refusal handle poisoned",
            ));
        }
        let observed = self.load_matching()?;
        if observed.original.as_ref() != Some(original) {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other("original publication provenance changed"));
        }
        let armed = self.arm_ready(observed)?;
        self.complete_armed(&armed, end, || Ok((action()?, original.clone())))
    }

    fn arm_ready(&self, before: RefusalRecord) -> io::Result<RefusalRecord> {
        if before.phase != Phase::Ready || before.original.is_none() {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "publication verification unfinished or refused",
            ));
        }
        let Some(attempt) = before.attempt.checked_add(1) else {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "publication verification sequence exhausted",
            ));
        };
        let mut armed = before.clone();
        armed.attempt = attempt;
        armed.phase = Phase::Armed;
        // The original backend holds the owner flock and compares the complete
        // attempt. Another handle cannot complete or clear this operation.
        if let Err(error) = self.store.compare_and_set(&self.owner, &before, &armed) {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(error));
        }
        Ok(armed)
    }

    fn complete_armed<T>(
        &self,
        armed: &RefusalRecord,
        end: Instant,
        action: impl FnOnce() -> io::Result<(T, ReservedPublicationProfile)>,
    ) -> io::Result<T> {
        let result = (|| {
            require_end(end)?;
            let (value, original) = action()?;
            self.binding.require_profile(&original)?;
            if self.poisoned.load(Ordering::Acquire)
                || armed
                    .original
                    .as_ref()
                    .is_some_and(|before| before != &original)
            {
                return Err(io::Error::other("original publication completion differs"));
            }
            let mut ready = armed.clone();
            ready.original = Some(original);
            ready.phase = Phase::Ready;
            // Actual Root context and receipt checks have already returned Ok.
            // Clearing this exact attempt never asserts delivery of a reply.
            require_end(end)?;
            self.store
                .compare_and_set(&self.owner, armed, &ready)
                .map_err(io::Error::other)?;
            if self.poisoned.load(Ordering::Acquire) || require_end(end).is_err() {
                self.refuse_locked()?;
                return Err(io::Error::other("original publication completion expired"));
            }
            Ok(value)
        })();
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        // Error, unwind or process exit leaves Armed, without reading the
        // primary record in a failure handler. No retry can clear this attempt.
        result
    }

    pub(super) fn refuse(&self) -> io::Result<()> {
        original_root()?;
        let _gate = self
            .gate
            .try_lock()
            .map_err(|_| io::Error::other("original publication refusal busy"))?;
        self.refuse_locked()
    }

    fn refuse_locked(&self) -> io::Result<()> {
        self.poisoned.store(true, Ordering::Release);
        let before = self.load_matching()?;
        if before.phase == Phase::Refused {
            return Ok(());
        }
        let mut refused = before.clone();
        refused.phase = Phase::Refused;
        self.store
            .compare_and_set(&self.owner, &before, &refused)
            .map_err(io::Error::other)?;
        if self.store.load(&self.owner).map_err(io::Error::other)? != refused {
            return Err(io::Error::other(
                "publication refusal acknowledgement differs",
            ));
        }
        Ok(())
    }

    fn load_matching(&self) -> io::Result<RefusalRecord> {
        let result = (|| {
            let observed = self.store.load(&self.owner).map_err(io::Error::other)?;
            if observed.binding != self.binding || observed.attempt == 0 {
                return Err(io::Error::other(
                    "original publication refusal registration differs",
                ));
            }
            if let Some(original) = &observed.original {
                self.binding.require_profile(original)?;
            }
            Ok(observed)
        })();
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        result
    }
}

pub(super) fn require_end(end: Instant) -> io::Result<()> {
    if Instant::now() >= end {
        return Err(io::Error::other("original publication deadline elapsed"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "authority_host_publication_refusal_tests.rs"]
mod tests;
