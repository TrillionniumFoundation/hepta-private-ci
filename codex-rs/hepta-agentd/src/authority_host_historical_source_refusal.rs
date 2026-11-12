//! Independent durable refusal for an original Root data record.
//! Restoring only the primary record cannot erase an observed refusal. This
//! does not protect against rollback of this record with the entire Root state.

use super::*;

#[derive(Clone, Copy, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum RefusalState {
    Pending,
    Open,
    Refused,
}

#[derive(Clone, Copy)]
pub(super) enum Registration {
    New,
    Existing,
}

/// No peer or recovery reader can initialize this record. Original creation
/// registers it before the primary; reopening requires both existing records.
pub(super) struct HistoricalSourceRefusalV1 {
    store: HostAuthorityFrontierStore<RefusalState>,
    owner: String,
}

impl HistoricalSourceRefusalV1 {
    fn owner(primary: &str) -> String {
        format!(
            "historical-refusal/{}",
            Digest32::of_parts(&[b"hepta.root.historical-refusal.v1\0", primary.as_bytes()])
        )
    }

    pub(super) fn register_original(
        root: Arc<RootAuthorityDirectory>,
        primary: &str,
    ) -> io::Result<(Self, Registration)> {
        original_root()?;
        let owner = Self::owner(primary);
        let (store, registration) =
            match HostAuthorityFrontierStore::initialize(Arc::clone(&root), owner.clone(), RefusalState::Pending) {
                Ok(store) => (store, Registration::New),
                Err(codex_hepta_contracts::AuthorityTrustError::Conflict) => (
                    HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?,
                    Registration::Existing,
                ),
                Err(error) => return Err(io::Error::other(error)),
            };
        let retained = Self { store, owner };
        if matches!(registration, Registration::Existing) {
            HistoricalSourceRefusalV1::require_open(&retained)?;
        }
        Ok((retained, registration))
    }

    pub(super) fn open_existing(
        root: Arc<RootAuthorityDirectory>,
        primary: &str,
    ) -> io::Result<Self> {
        original_root()?;
        let owner = Self::owner(primary);
        let store =
            HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?;
        let retained = Self { store, owner };
        HistoricalSourceRefusalV1::require_open(&retained)?;
        Ok(retained)
    }

    pub(super) fn complete_original_registration(&self) -> io::Result<()> {
        original_root()?;
        self.store
            .compare_and_set(&self.owner, &RefusalState::Pending, &RefusalState::Open)
            .map_err(io::Error::other)?;
        HistoricalSourceRefusalV1::require_open(self)
    }

    pub(super) fn require_open(&self) -> io::Result<()> {
        original_root()?;
        match self.store.load(&self.owner) {
            Ok(RefusalState::Open) => Ok(()),
            Ok(RefusalState::Pending | RefusalState::Refused) =>
                Err(io::Error::other("original historical data not admitted")),
            Err(error) => Err(io::Error::other(error)),
        }
    }

    pub(super) fn refuse(&self) -> io::Result<()> {
        original_root()?;
        let observed = self.store.load(&self.owner).map_err(io::Error::other)?;
        if observed == RefusalState::Refused {
            return Ok(());
        }
        match self.store.compare_and_set(&self.owner, &observed, &RefusalState::Refused) {
            Ok(()) => Ok(()),
            Err(codex_hepta_contracts::AuthorityTrustError::Conflict)
                if self.store.load(&self.owner)
                    == Ok(RefusalState::Refused) => Ok(()),
            Err(error) => Err(io::Error::other(error)),
        }
    }
}
