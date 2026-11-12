//! Exact protected Source pin record operations.

use super::super::data_refusal::RootDataKind;
use super::*;

impl RootHistoricalSourcePinV1 {
    /// Only the actual capture caller supplies the action. Its complete Root
    /// context, including postchecks, returns inside this persistent arm.
    pub(super) fn capture(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
        capture: impl FnOnce(PinRecordAccess) -> io::Result<RetainedSourcePinRecordV1>,
    ) -> io::Result<Self> {
        original_root()?;
        let mut capture = Some(capture);
        let created = RootDataRefusalV1::create_fresh(
            Arc::clone(&root),
            RootDataKind::SourcePin,
            target,
            || {
                let action = capture
                    .take()
                    .ok_or_else(|| io::Error::other("original source capture consumed"))?;
                action(PinRecordAccess::Fresh)
            },
        );
        let (refusal, record) = match created {
            Ok(retained) => retained,
            Err(error) if capture.is_some() && error.kind() == io::ErrorKind::AlreadyExists => {
                let refusal =
                    RootDataRefusalV1::open_existing(root, RootDataKind::SourcePin, target)?;
                let action = capture
                    .take()
                    .ok_or_else(|| io::Error::other("original source capture consumed"))?;
                let record = refusal.inspect(|| action(PinRecordAccess::Existing))?;
                (refusal, record)
            }
            Err(error) => return Err(error),
        };
        Ok(Self {
            store: record.store,
            owner: record.owner,
            expected: record.expected,
            poisoned: Mutex::new(false),
            refusal,
        })
    }

    pub(crate) fn open_existing(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Self> {
        original_root()?;
        let refusal =
            RootDataRefusalV1::open_existing(Arc::clone(&root), RootDataKind::SourcePin, target)?;
        let owner = owner(target)?;
        let (store, expected) = refusal.inspect(|| {
            // HostAuthorityFrontierStore::open itself physically reads, so it
            // too belongs after the independent arm, not merely its load.
            let store =
                HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?;
            let expected: PinRecord = store.load(&owner).map_err(io::Error::other)?;
            if expected.fenced
                || expected.pin.schema != 1
                || expected.pin.purpose != PIN_PURPOSE
                || &expected.pin.target != target
            {
                return Err(io::Error::other("original historical source pin differs"));
            }
            Ok((store, expected))
        })?;
        Ok(Self {
            store,
            owner,
            expected,
            poisoned: Mutex::new(false),
            refusal,
        })
    }

    pub(crate) fn readback_digest(&self) -> io::Result<Digest32> {
        self.inspect_exact(|| {
            Ok(Digest32::of_parts(&[
                b"hepta.root.historical-source-pin.v1\0",
                &serde_json::to_vec(&self.expected).map_err(io::Error::other)?,
            ]))
        })
    }

    pub(in crate::authority_host_service::generation_initial) fn require_original_registration(
        &self,
        profile: &InitialProfile,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
    ) -> io::Result<()> {
        self.inspect_exact(|| {
            let pin = &self.expected.pin;
            if pin.initial_profile != profile.binding
                || pin.identity != profile.identity
                || pin.writer != profile.writer
                || pin.target != profile.deployment.target
                || pin.target_files != profile.target_files
                || pin.publisher_epoch != registration.publisher_epoch
                || pin.publisher
                    != (CognitiveCheckpointPeerLifetime {
                        uid: config.peer_uid,
                        pid: registration.peer_pid,
                        boot_id: registration.boot_id.clone(),
                        process_start_ticks: registration.process_start_ticks,
                    })
            {
                return Err(io::Error::other(
                    "source pin is not this original publisher",
                ));
            }
            Ok(())
        })
    }

    fn inspect_exact<T>(&self, action: impl FnOnce() -> io::Result<T>) -> io::Result<T> {
        original_root()?;
        let mut poisoned = self
            .poisoned
            .lock()
            .map_err(|_| io::Error::other("source pin poisoned"))?;
        if *poisoned {
            return Err(io::Error::other("original historical source pin changed"));
        }
        let result = self.refusal.inspect(|| {
            if self.store.load(&self.owner).map_err(io::Error::other)? != self.expected {
                return Err(io::Error::other("original historical source pin changed"));
            }
            action()
        });
        if result.is_err() {
            *poisoned = true;
        }
        result
    }

    /// Called only inside capture's existing arm. Fresh marker registration
    /// must never reuse an old primary; existing registration never initializes.
    pub(super) fn retain_unchecked(
        root: Arc<RootAuthorityDirectory>,
        pin: SourcePin,
        access: PinRecordAccess,
    ) -> io::Result<RetainedSourcePinRecordV1> {
        let owner = owner(&pin.target)?;
        let expected = PinRecord { pin, fenced: false };
        let store = match access {
            PinRecordAccess::Fresh => {
                HostAuthorityFrontierStore::initialize(root, owner.clone(), expected.clone())
                    .map_err(io::Error::other)?
            }
            PinRecordAccess::Existing => {
                HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?
            }
        };
        if store.load(&owner).map_err(io::Error::other)? != expected {
            return Err(io::Error::other("original historical source pin changed"));
        }
        Ok(RetainedSourcePinRecordV1 {
            store,
            owner,
            expected,
        })
    }

    pub(crate) fn fence(&self) -> io::Result<()> {
        original_root()?;
        // This independent refusal must succeed before decoding the primary.
        self.refusal.refuse()?;
        *self
            .poisoned
            .lock()
            .map_err(|_| io::Error::other("source pin poisoned"))? = true;
        let mut next = self.expected.clone();
        next.fenced = true;
        if self.store.load(&self.owner).map_err(io::Error::other)? == next {
            return Ok(());
        }
        self.store
            .compare_and_set(&self.owner, &self.expected, &next)
            .map_err(io::Error::other)?;
        if self.store.load(&self.owner).map_err(io::Error::other)? != next {
            return Err(io::Error::other("original source pin fence differs"));
        }
        Ok(())
    }
}
