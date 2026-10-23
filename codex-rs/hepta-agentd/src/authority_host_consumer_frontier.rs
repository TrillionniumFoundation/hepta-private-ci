//! Protected adapter for an existing original FinalUse consumer frontier.
//! The trusted launcher fixes each owner; the wire cannot select or reset it.

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::HostConsumerFrontierRequestV1 as Request;
use codex_hepta_contracts::HostConsumerFrontierResponseV1 as Response;
use codex_hepta_contracts::HostConsumerFrontierStatusV1 as Status;
use codex_hepta_contracts::RootAuthorityDirectory;
use std::sync::Arc;
use std::sync::Mutex;

const FRAME_LIMIT: usize = 16 * 1024;

struct SessionState {
    last_request_id: u64,
    closed: bool,
}

/// One of the two existing consumer stores, not a third consumer or nonce log.
/// The service must pin the actual peer/pidfd and execute this adapter inside
/// the original live writer-lease dispatch fence. `observed_head` must come
/// from the same protected issuer within that fence, never from peer JSON.
/// Opaque state hashes remain the responsibility of the original trusted
/// FinalUseAuthority. This adapter cannot validate a complete nonce set.
pub struct HostConsumerFrontier {
    owner_id: String,
    store: HostAuthorityFrontierStore<FinalUseFrontier>,
    clock: Arc<dyn AuthorityClock>,
    expires_at_unix_ms: u64,
    session: Mutex<SessionState>,
}

impl HostConsumerFrontier {
    /// Trusted fresh bootstrap only. The original issuer supplies the exact
    /// initial head before the genuinely fresh consumer is opened. Existing
    /// or partial registrations are conflicts, never replaced with genesis.
    pub fn initialize_fresh(
        directory: Arc<RootAuthorityDirectory>,
        owner_id: String,
        initial_head: &FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        expires_at_unix_ms: u64,
    ) -> Result<Self, AuthorityTrustError> {
        let initial = FinalUseFrontier::for_initial_head(initial_head)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        if clock.now_unix_ms()? >= expires_at_unix_ms {
            return Err(AuthorityTrustError::Invalid);
        }
        let store = HostAuthorityFrontierStore::initialize(directory, owner_id.clone(), initial)?;
        let result = Self::configured(owner_id, store, clock, expires_at_unix_ms);
        result.read_existing()?;
        Ok(result)
    }

    /// Runtime open only. The trusted launcher supplies the current lease's
    /// expiry and fixed original owner. No missing record is initialized.
    pub fn open(
        directory: Arc<RootAuthorityDirectory>,
        owner_id: String,
        clock: Arc<dyn AuthorityClock>,
        expires_at_unix_ms: u64,
    ) -> Result<Self, AuthorityTrustError> {
        let store = HostAuthorityFrontierStore::open(directory, owner_id.clone())?;
        let result = Self::configured(owner_id, store, clock, expires_at_unix_ms);
        result.read_existing()?;
        Ok(result)
    }

    fn configured(
        owner_id: String,
        store: HostAuthorityFrontierStore<FinalUseFrontier>,
        clock: Arc<dyn AuthorityClock>,
        expires_at_unix_ms: u64,
    ) -> Self {
        Self {
            owner_id,
            store,
            clock,
            expires_at_unix_ms,
            session: Mutex::new(SessionState {
                last_request_id: 0,
                closed: false,
            }),
        }
    }

    fn read_existing(&self) -> Result<FinalUseFrontier, AuthorityTrustError> {
        let frontier = self.store.load(&self.owner_id)?;
        if !valid_frontier(&frontier)
            || self.clock.now_unix_ms()? >= self.expires_at_unix_ms
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(frontier)
    }

    /// One original closed request. A successful CAS already includes durable
    /// file/directory synchronization and exact readback under its publication
    /// lock. Post-I/O expiry/uncertainty returns Unknown without a head and
    /// permanently fences this object. Never retry an uncertain CAS.
    pub fn exchange(
        &self,
        bytes: &[u8],
        observed_head: &FinalUseRevocations,
    ) -> Result<Vec<u8>, AuthorityTrustError> {
        if bytes.is_empty() || bytes.len() > FRAME_LIMIT {
            return Err(AuthorityTrustError::Invalid);
        }
        let request: Request =
            serde_json::from_slice(bytes).map_err(|_| AuthorityTrustError::Invalid)?;
        let (schema, id) = match &request {
            Request::Load { schema_version, request_id }
            | Request::CompareAndSet { schema_version, request_id, .. } => (*schema_version, *request_id),
        };
        if schema != 1 || id == 0 {
            return Err(AuthorityTrustError::Invalid);
        }
        FinalUseFrontier::for_initial_head(observed_head)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        let mut session = self.session.try_lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        if id <= session.last_request_id {
            return Err(AuthorityTrustError::Invalid);
        }
        session.last_request_id = id;
        let mut response = Response { schema_version: 1, request_id: id, status: Status::Unknown, frontier: None };
        if session.closed {
            return serde_json::to_vec(&response).map_err(|_| AuthorityTrustError::Unavailable);
        }
        if !matches!(self.clock.now_unix_ms(), Ok(now) if now < self.expires_at_unix_ms) {
            session.closed = true;
            return serde_json::to_vec(&response).map_err(|_| AuthorityTrustError::Unavailable);
        }
        let result = match request {
            Request::Load { .. } => self.store.load(&self.owner_id),
            Request::CompareAndSet { expected, next, .. } => {
                if !valid_frontier(&expected)
                    || !valid_frontier(&next)
                    || next.authority_epoch < expected.authority_epoch
                    || (next.authority_epoch == expected.authority_epoch
                        && next.revocation_revision < expected.revocation_revision)
                    || next.authority_epoch != observed_head.authority_epoch
                    || next.revocation_revision != observed_head.revision
                {
                    return Err(AuthorityTrustError::Invalid);
                }
                self.store.compare_and_set(&self.owner_id, &expected, &next).map(|()| next)
            }
        };
        match result {
            Ok(frontier) if valid_frontier(&frontier)
                && frontier.authority_epoch <= observed_head.authority_epoch
                && (frontier.authority_epoch != observed_head.authority_epoch
                    || frontier.revocation_revision <= observed_head.revision) => {
                response.status = Status::Ack;
                response.frontier = Some(frontier);
            }
            Err(AuthorityTrustError::Conflict) => response.status = Status::Conflict,
            Ok(_) | Err(AuthorityTrustError::Invalid | AuthorityTrustError::Unavailable) => session.closed = true,
        }
        if !matches!(self.clock.now_unix_ms(), Ok(now) if now < self.expires_at_unix_ms) {
            session.closed = true;
        }
        if session.closed {
            response.status = Status::Unknown;
            response.frontier = None;
        }
        let encoded = serde_json::to_vec(&response).map_err(|_| AuthorityTrustError::Unavailable)?;
        if encoded.len() > FRAME_LIMIT {
            session.closed = true;
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(encoded)
    }
}

fn valid_frontier(frontier: &FinalUseFrontier) -> bool {
    frontier.authority_epoch != 0
        && frontier.revocation_revision != 0
        && frontier.state_sha256 != [0; 32]
}

#[cfg(test)]
#[path = "authority_host_consumer_frontier_tests.rs"]
mod tests;
