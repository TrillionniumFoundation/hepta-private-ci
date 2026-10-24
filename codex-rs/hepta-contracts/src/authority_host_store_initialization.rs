//! Explicit exact-value completion of an original Root bootstrap publication.
//! Runtime open and ordinary initialize retain their existing behavior.
use super::*;

impl<F: Serialize + DeserializeOwned + Eq> HostAuthorityFrontierStore<F> {
    /// Observe actual absence of both original publication names while holding
    /// the original publication lock. The callback must not re-enter this
    /// store. Its return value, including an error value, is returned only
    /// after checking both names again. No store or frontier is published.
    ///
    /// This proves absence during this locked observation, not that a previous
    /// owner never published or has retired. Callers retain those independent
    /// original identity, sequence and lifecycle obligations.
    pub fn with_absent_initialization<R>(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
        inspect: impl FnOnce() -> R,
    ) -> Result<R, AuthorityTrustError> {
        let store = Self::configured(root, owner_id)?;
        let _lock = store.publication_lock()?;
        let temporary = format!("{}.next", store.name);
        if store.root.exists(&store.name)? || store.root.exists(&temporary)? {
            return Err(AuthorityTrustError::Conflict);
        }
        let result = inspect();
        if store.root.exists(&store.name)? || store.root.exists(&temporary)? {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(result)
    }

    /// Resume a separately authorized, exact original bootstrap value.
    /// A canonical record must already equal `initial`; a retained candidate
    /// must be complete, correctly owned and equal to that same value. Neither
    /// a corrupt candidate nor a later canonical frontier is overwritten.
    ///
    /// The original publication lock covers all decisions and full readback.
    /// Only genuine absence permits the original initial publication. This is
    /// not runtime rollback repair, and callers must not reconstruct a lost
    /// time-dependent record from a new clock sample.
    pub fn resume_initialization(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
        initial: F,
    ) -> Result<Self, AuthorityTrustError> {
        let store = Self::configured(root, owner_id)?;
        let _lock = store.publication_lock()?;
        if store.root.exists(&store.name)? {
            if store.read_durable()? != initial {
                return Err(AuthorityTrustError::Conflict);
            }
            return Ok(store);
        }
        let temporary = format!("{}.next", store.name);
        if store.root.exists(&temporary)? {
            let file = store
                .root
                .open_private(&temporary, OFlags::RDONLY | OFlags::NONBLOCK)?;
            let (retained, record) = store.read_opened_record(file)?;
            if retained != initial {
                return Err(AuthorityTrustError::Conflict);
            }
            record.file.sync_all().map_err(unavailable)?;
            store.root.sync_directory()?;
            store.forget_durability()?;
            rustix::fs::renameat_with(
                &store.root.directory,
                &temporary,
                &store.root.directory,
                &store.name,
                rustix::fs::RenameFlags::NOREPLACE,
            )
            .map_err(|error| {
                if error == rustix::io::Errno::EXIST {
                    AuthorityTrustError::Conflict
                } else {
                    AuthorityTrustError::Unavailable
                }
            })?;
            store.root.sync_directory()?;
        } else {
            store.persist(&initial)?;
        }
        store.acknowledge_persisted(&initial)?;
        Ok(store)
    }
}

#[cfg(test)]
#[path = "authority_host_store_initialization_tests.rs"]
mod tests;
