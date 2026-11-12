//! Exact protected Source pin record operations.

use super::*;

impl RootHistoricalSourcePinV1 {
    pub(crate) fn open_existing(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Self> {
        original_root()?;
        let owner = owner(target)?;
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
        Ok(Self {
            store,
            owner,
            expected,
            poisoned: Mutex::new(false),
        })
    }

    pub(crate) fn readback_digest(&self) -> io::Result<Digest32> {
        original_root()?;
        let mut poisoned = self
            .poisoned
            .lock()
            .map_err(|_| io::Error::other("source pin poisoned"))?;
        if *poisoned
            || !matches!(self.store.load(&self.owner), Ok(record) if record == self.expected)
        {
            *poisoned = true;
            return Err(io::Error::other("original historical source pin changed"));
        }
        Ok(Digest32::of_parts(&[
            b"hepta.root.historical-source-pin.v1\0",
            &serde_json::to_vec(&self.expected).map_err(io::Error::other)?,
        ]))
    }

    pub(in crate::authority_host_service::generation_initial) fn require_original_registration(
        &self,
        profile: &InitialProfile,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
    ) -> io::Result<()> {
        self.readback_digest()?;
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
    }

    pub(super) fn retain(root: Arc<RootAuthorityDirectory>, pin: SourcePin) -> io::Result<Self> {
        original_root()?;
        let owner = owner(&pin.target)?;
        let expected = PinRecord { pin, fenced: false };
        let store = match HostAuthorityFrontierStore::initialize(
            Arc::clone(&root),
            owner.clone(),
            expected.clone(),
        ) {
            Ok(store) => store,
            Err(AuthorityTrustError::Conflict) => {
                HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?
            }
            Err(error) => return Err(io::Error::other(error)),
        };
        let retained = Self {
            store,
            owner,
            expected,
            poisoned: Mutex::new(false),
        };
        retained.readback_digest()?;
        Ok(retained)
    }

    pub(crate) fn fence(&self) -> io::Result<()> {
        original_root()?;
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
            .map_err(io::Error::other)
    }
}
