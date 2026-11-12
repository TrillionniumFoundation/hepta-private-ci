//! Existing first-publication evidence under the original durable refusal.
//! Recovery cannot infer acceptance from CURRENT, choose a new slot or create
//! an absent marker. The entire new recipient context belongs in `action`.

use std::marker::PhantomData;
use std::rc::Rc;

use super::*;

/// A stack-borrowed original Root record, not a deserializable authority. Its
/// timestamp belongs only to historical verification of this exact selection.
pub(crate) struct OriginalPublicationHistoryProofV1<'a> {
    original: &'a ReservedPublicationProfile,
    accepted: &'a PublicationAcceptance,
    not_send: PhantomData<Rc<()>>,
}

impl OriginalPublicationHistoryProofV1<'_> {
    pub(crate) fn original_profile(&self) -> io::Result<&PublicationProfile> {
        self.accepted.require_original(self.original)?;
        self.original
            .original_for_version(PublicationVersion::DurableV2)
    }

    pub(crate) fn verified_at_unix_ms(&self) -> u64 {
        self.accepted.verified_at_unix_ms()
    }

    pub(crate) fn original_current(&self) -> &CurrentHead {
        self.accepted.original_current()
    }

    pub(crate) fn original_work_expiry_seconds(&self) -> u64 {
        self.accepted.original_work_expiry_seconds()
    }

    pub(crate) fn acceptance_digest(&self) -> io::Result<Digest32> {
        self.accepted.require_original(self.original)?;
        Ok(Digest32::of_parts(&[
            b"hepta.root.original-publication-acceptance.v1\0",
            &serde_json::to_vec(self.original).map_err(io::Error::other)?,
            &serde_json::to_vec(self.accepted).map_err(io::Error::other)?,
        ]))
    }

    pub(in super::super) fn original_reserved(&self) -> &ReservedPublicationProfile {
        self.original
    }

    pub(in super::super) fn require_original_observations(
        &self,
        previous: Digest32,
        target: Digest32,
    ) -> io::Result<()> {
        self.accepted
            .require_original_observations(previous, target)
    }
}

impl PublicationRefusal {
    pub(in super::super) fn with_completed_history<T>(
        root: Arc<RootAuthorityDirectory>,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        end: Instant,
        action: impl FnOnce(&OriginalPublicationHistoryProofV1<'_>) -> io::Result<T>,
    ) -> io::Result<(T, Digest32)> {
        original_root()?;
        require_end(end)?;
        scope.validate_snapshot(initial).map_err(io::Error::other)?;
        let owner = format!(
            "publication-refusal/{}",
            Digest32::of_bytes(initial.request.operation_id.as_str().as_bytes())
        );
        // The first read is only this independently retained control marker.
        // No publication primary, material, Artifact, or C file precedes arm.
        let store = HostAuthorityFrontierStore::<RefusalRecord>::open(root, owner.clone())
            .map_err(io::Error::other)?;
        let retained = store.load(&owner).map_err(io::Error::other)?;
        if retained.binding.schema != 1
            || retained.binding.purpose != PURPOSE
            || retained.binding.publication_purpose != PublicationVersion::DurableV2.purpose()
            || retained.binding.learning_operation != initial.request.operation_id.as_str()
            || retained.binding.initial != initial.head_digest.to_string()
            || retained.binding.scope != scope.binding().to_string()
            || retained.binding.owner() != owner
        {
            return Err(io::Error::other("completed publication scope differs"));
        }
        let held = Self {
            store,
            binding: retained.binding.clone(),
            owner,
            gate: Mutex::new(()),
            poisoned: AtomicBool::new(false),
        };
        let _gate = held
            .gate
            .try_lock()
            .map_err(|_| io::Error::other("completed publication busy"))?;
        let before = held.load_matching()?;
        if before != retained {
            return Err(io::Error::other("completed publication marker changed"));
        }
        let armed = held.arm_ready(before)?;
        let value = held.complete_armed(&armed, end, || {
            let original = armed
                .original
                .as_ref()
                .ok_or_else(|| io::Error::other("original publication provenance missing"))?;
            let accepted = armed
                .publication
                .as_ref()
                .ok_or_else(|| io::Error::other("first real publication acceptance missing"))?;
            accepted.require_original(original)?;
            if accepted.original_work_expiry_seconds()
                != initial.request.envelope.expiry_unix_seconds
            {
                return Err(io::Error::other("original publication work window differs"));
            }
            let proof = OriginalPublicationHistoryProofV1 {
                original,
                accepted,
                not_send: PhantomData,
            };
            // The caller must let the actual new recipient's complete Root
            // context return and finish its physical reads before returning.
            let result = action(&proof)?;
            if held.load_matching()? != armed {
                return Err(io::Error::other(
                    "publication changed during completed read",
                ));
            }
            require_end(end)?;
            Ok((result, original.clone(), None))
        })?;
        let ready = held.load_matching()?;
        let mut expected = armed;
        expected.phase = Phase::Ready;
        if ready != expected || require_end(end).is_err() {
            held.refuse_locked()?;
            return Err(io::Error::other(
                "completed publication Ready readback differs",
            ));
        }
        let digest = Digest32::of_parts(&[
            b"hepta.root.original-publication-ready.v1\0",
            &serde_json::to_vec(&ready).map_err(io::Error::other)?,
        ]);
        Ok((value, digest))
    }
}
