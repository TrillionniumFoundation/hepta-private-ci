//! Explicit Root completion of an already committed original lease state.
//! Ordinary runtime reopen remains strict; this cannot issue a fresh lease.
use super::*;
use crate::HostAuthorityClock;
use crate::HostAuthorityFrontierStore;
use crate::RootAuthorityDirectory;

/// Original administrator input used only to reject a different genesis.
/// It contains no issued time, expiry, verified token or mutable state claim.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityLeaseInitialization {
    pub lease_id: String,
    pub binding: AuthorityLeaseBinding,
    pub lifetime_ms: u64,
}

impl AuthorityLeaseInitialization {
    fn validate(&self) -> Result<(), AuthorityLeaseError> {
        if !identifier(&self.lease_id)
            || !binding_valid(&self.binding)
            || !(1..=MAX_AUTHORITY_LEASE_LIFETIME_MS).contains(&self.lifetime_ms)
        {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        Ok(())
    }

    fn matches(&self, state: &State) -> bool {
        if !state_valid(state)
            || state.failed
            || state.authority_epoch != 1
            || !state.revocations.is_empty()
            || !state.retired_revisions.is_empty()
        {
            return false;
        }
        match state.store_revision {
            1 => state.leases.is_empty(),
            2 if state.leases.len() == 1 => state.leases.get(&self.lease_id).is_some_and(|lease| {
                lease.schema_version == LEASE_SCHEMA_VERSION
                    && lease.authority_epoch == 1
                    && lease.revision == 1
                    && lease.binding == self.binding
                    && lease
                        .expires_at_unix_ms
                        .checked_sub(lease.issued_at_unix_ms)
                        == Some(self.lifetime_ms)
            }),
            _ => false,
        }
    }
}

impl AuthorityLeaseRegistry {
    /// Explicitly complete a previously started Root initialization under the
    /// original exclusive local lock and actual protected frontier lock.
    /// Only epoch-1 empty state or its exact first lease is admissible. The
    /// full candidate must hash to the actual durable frontier; caller fields
    /// cannot authorize another state or replace retained issued/expiry times.
    ///
    /// Ordinary `open_state_dir_with_trust` is unchanged and still rejects a
    /// canonical state behind its frontier. This method neither advances that
    /// frontier nor issues/renews a lease. After success, use `read_lease` to
    /// recover the exact original first lease rather than sampling new times.
    pub fn resume_initialization_with_trust(
        directory: &Path,
        owner_id: String,
        initialization: &AuthorityLeaseInitialization,
        clock: Arc<HostAuthorityClock>,
        frontier_store: Arc<HostAuthorityFrontierStore<AuthorityLeaseFrontier>>,
    ) -> Result<Self, AuthorityLeaseError> {
        initialization.validate()?;
        Self::resume_original_publication(
            directory,
            owner_id,
            Some(initialization),
            clock,
            frontier_store,
        )
    }

    /// Complete only an original local state already committed by the actual
    /// protected full frontier. The complete retained candidate must match
    /// that frontier exactly. No new state, lease time, epoch or revision is
    /// inferred from the caller, and no frontier CAS is performed.
    ///
    /// This explicit Root administration path does not change ordinary open.
    /// If the canonical state already matches, an uncommitted `.next` is left
    /// untouched. Missing, corrupt or different committed candidates fail
    /// closed; this method cannot reconstruct a missing canonical store.
    pub fn resume_prepared_state_with_trust(
        directory: &Path,
        owner_id: String,
        clock: Arc<HostAuthorityClock>,
        frontier_store: Arc<HostAuthorityFrontierStore<AuthorityLeaseFrontier>>,
    ) -> Result<Self, AuthorityLeaseError> {
        Self::resume_original_publication(directory, owner_id, None, clock, frontier_store)
    }

    fn resume_original_publication(
        directory: &Path,
        owner_id: String,
        initialization: Option<&AuthorityLeaseInitialization>,
        clock: Arc<HostAuthorityClock>,
        frontier_store: Arc<HostAuthorityFrontierStore<AuthorityLeaseFrontier>>,
    ) -> Result<Self, AuthorityLeaseError> {
        if !identifier(&owner_id) {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        // Actual Root and every protected ancestor are required. This check
        // also refuses a missing directory before Store's create-capable helper.
        let _root = RootAuthorityDirectory::open(directory).map_err(map_trust_error)?;
        clock.now_unix_ms().map_err(map_trust_error)?;
        let root = prepare_directory(directory)?;
        let lock = open_private(&root, "authority-leases.lock", Access::Create)?;
        lock.try_lock()
            .map_err(|_| AuthorityLeaseError::StateLocked)?;
        let store = Store {
            root,
            owner_id: owner_id.clone(),
            _lock: lock,
        };
        let state = frontier_store
            .with_locked_durable(&owner_id, |trusted| {
                resume_locked(&store, initialization, *trusted)
            })
            .map_err(map_trust_error)??;
        // A publication may already be complete. An unavailable real clock
        // remains an error; no record is rolled back or published again here.
        clock.now_unix_ms().map_err(map_trust_error)?;
        Ok(Self(Arc::new(Inner {
            owner_id,
            state: Mutex::new(state),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }
}

fn read_original(
    store: &Store,
    initialization: Option<&AuthorityLeaseInitialization>,
    name: &str,
) -> Result<Option<(State, File)>, AuthorityLeaseError> {
    if !entry_exists(&store.root, name)? {
        return Ok(None);
    }
    let file = open_private(&store.root, name, Access::Read)?;
    let mut bytes = Vec::new();
    (&file)
        .take((MAX_AUTHORITY_STORE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| AuthorityLeaseError::Unavailable)?;
    if bytes.len() > MAX_AUTHORITY_STORE_BYTES {
        return Err(AuthorityLeaseError::InvalidTrust);
    }
    let stored: Stored =
        serde_json::from_slice(&bytes).map_err(|_| AuthorityLeaseError::InvalidTrust)?;
    if stored.schema_version != STORE_SCHEMA_VERSION
        || stored.owner_id != store.owner_id
        || !state_valid(&stored.state)
        || stored.state.failed
        || initialization.is_some_and(|initial| !initial.matches(&stored.state))
    {
        return Err(AuthorityLeaseError::InvalidTrust);
    }
    Ok(Some((stored.state, file)))
}

fn resume_locked(
    store: &Store,
    initialization: Option<&AuthorityLeaseInitialization>,
    trusted: AuthorityLeaseFrontier,
) -> Result<State, AuthorityLeaseError> {
    if trusted.authority_epoch == 0
        || trusted.store_revision == 0
        || trusted.state_sha256 == [0; 32]
        || (initialization.is_some()
            && (trusted.authority_epoch != 1 || !matches!(trusted.store_revision, 1 | 2)))
    {
        return Err(AuthorityLeaseError::InvalidTrust);
    }
    let empty = State {
        authority_epoch: 1,
        store_revision: 1,
        leases: BTreeMap::new(),
        revocations: BTreeMap::new(),
        retired_revisions: BTreeMap::new(),
        failed: false,
    };
    let empty_frontier = frontier_for_state(&empty);
    match read_original(store, initialization, "authority-leases.json")? {
        Some((state, file)) if frontier_for_state(&state) == trusted => {
            // Re-acknowledge visibility left by a lost directory-sync return.
            // Full readback below still occurs under both original locks.
            file.sync_all()
                .map_err(|_| AuthorityLeaseError::Unavailable)?;
            store
                .root
                .sync_all()
                .map_err(|_| AuthorityLeaseError::Unavailable)?;
            return readback(store, initialization, trusted);
        }
        Some((state, _))
            if initialization.is_some()
                && frontier_for_state(&state) == empty_frontier
                && trusted.store_revision == 2 => {}
        Some((state, _))
            if initialization.is_none()
                && state.authority_epoch <= trusted.authority_epoch
                && state.store_revision < trusted.store_revision => {}
        Some(_) => return Err(AuthorityLeaseError::AntiRollbackViolation),
        None if initialization.is_some() && trusted == empty_frontier => {}
        None => return Err(AuthorityLeaseError::AntiRollbackViolation),
    }
    match read_original(store, initialization, "authority-leases.next")? {
        Some((state, file)) if frontier_for_state(&state) == trusted => {
            file.sync_all()
                .map_err(|_| AuthorityLeaseError::Unavailable)?;
            let prepared = PreparedState { store, _file: file };
            prepared.sync_name()?;
            prepared.publish()?;
        }
        Some(_) => return Err(AuthorityLeaseError::AntiRollbackViolation),
        None if initialization.is_some() && trusted == empty_frontier => {
            // The earliest crash can leave only the original lock. The
            // deterministic original empty state is bound by the independently
            // retained full digest; no above-genesis data is reconstructed.
            store.persist(&empty)?;
        }
        None => return Err(AuthorityLeaseError::AntiRollbackViolation),
    }
    readback(store, initialization, trusted)
}

fn readback(
    store: &Store,
    initialization: Option<&AuthorityLeaseInitialization>,
    trusted: AuthorityLeaseFrontier,
) -> Result<State, AuthorityLeaseError> {
    let (state, _) = read_original(store, initialization, "authority-leases.json")?
        .ok_or(AuthorityLeaseError::Unavailable)?;
    if frontier_for_state(&state) != trusted {
        return Err(AuthorityLeaseError::AntiRollbackViolation);
    }
    Ok(state)
}
