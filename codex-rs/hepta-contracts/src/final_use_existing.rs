//! Explicit fresh initialization and strict runtime reopen. Neither operation
//! supplies issuer trust, an independent floor or permission to use an effect.
//! Concrete host owners must derive those inputs from their protected custody.

use super::*;

#[derive(Clone, Copy)]
enum JournalOpenSelection {
    Fresh,
    Existing,
}

impl FinalUseAuthority {
    /// Initialize exactly once inside an already-existing private directory
    /// owned by the executing consumer UID. Every known journal entry must be
    /// absent; the exclusive lock creation makes a partial attempt permanent.
    /// This does not create/chown the directory or retry a failed first start.
    pub fn initialize_fresh_state_dir_with_issuer_keys(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        Self::open_selected_issuer_journal(
            directory,
            signer_id,
            issuer_keys,
            head,
            clock,
            frontier_store,
            JournalOpenSelection::Fresh,
        )
    }

    /// Open only complete current-schema state. Missing/partial state, missing
    /// lock or claims, and legacy schema require independent recovery; this
    /// path never creates a directory, initializes a snapshot or migrates it.
    pub fn open_existing_state_dir_with_issuer_keys(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        Self::open_selected_issuer_journal(
            directory,
            signer_id,
            issuer_keys,
            head,
            clock,
            frontier_store,
            JournalOpenSelection::Existing,
        )
    }

    fn open_selected_issuer_journal(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
        selection: JournalOpenSelection,
    ) -> Result<Self, FinalUseError> {
        if !identifier(&signer_id) || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (issuer_keys, issuer_trust_sha256) = pin_issuer_keys(issuer_keys)?;
        // A fresh consumer may initialize only the original empty frontier.
        // Check it before creating the one-shot lock; an uncertain read does
        // not authorize a local genesis. Recheck the actual opened state below.
        if matches!(selection, JournalOpenSelection::Fresh)
            && frontier_store.load(&signer_id).map_err(map_trust_error)?
                != FinalUseFrontier::for_initial_head(&head)?
        {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        let (store, state) = match selection {
            JournalOpenSelection::Fresh => store::Store::initialize_key_ring_fresh(
                directory,
                &signer_id,
                issuer_trust_sha256,
                head,
            )?,
            JournalOpenSelection::Existing => store::Store::open_key_ring_existing(
                directory,
                &signer_id,
                issuer_trust_sha256,
                head,
            )?,
        };
        let observed = frontier_for_state(&state);
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        // The concrete clock is memory-only; no refresh or transport callback
        // is introduced under a FinalUse state or store lock.
        clock.now_unix_ms().map_err(map_trust_error)?;
        store.revalidate_owner()?;
        Ok(Self(Arc::new(Inner {
            signer_id,
            profile: FinalUseAuthenticationProfile::ClassicalV1,
            issuer_keys,
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }
}
