//! A reserved seal is not usable until the exact sealed response is recorded.
//! Cancellation drops the reservation; it never publishes an origin receipt.

use super::*;

const PENDING: u8 = 0;
const PUBLISHED: u8 = 1;
const ABANDONED: u8 = 2;

pub(super) struct SealEntryV2 {
    seal: IssuedContextSealV2,
    state: Arc<AtomicU8>,
}

#[must_use = "dropping a seal reservation abandons publication"]
pub(super) struct PendingContextSealV2 {
    digest: Digest32,
    state: Arc<AtomicU8>,
    published: bool,
}

impl PendingContextSealV2 {
    pub(super) fn digest(&self) -> Digest32 {
        self.digest
    }

    /// No allocation, locking, I/O or response mutation is allowed after the
    /// learning append. Expiry is not renewed: final use still checks the
    /// original monotonic deadline, even when recording took a long time.
    pub(super) fn publish(mut self) {
        self.published = true;
        self.state.store(PUBLISHED, Ordering::Release);
    }
}

impl Drop for PendingContextSealV2 {
    fn drop(&mut self) {
        if !self.published {
            self.state.store(ABANDONED, Ordering::Release);
        }
    }
}

fn lease_current(seal: &IssuedContextSealV2, now: u64) -> bool {
    seal.issued_at_micros <= now
        && now < seal.expires_at_micros
        && seal.expires_at_micros - seal.issued_at_micros <= CONTEXT_LEASE_MICROS
}

pub(super) fn reserve(
    seal: IssuedContextSealV2,
) -> Result<PendingContextSealV2, CognitiveContextError> {
    let now = helpers::monotonic_micros()?;
    if !lease_current(&seal, now) {
        return Err(CognitiveContextError::ReadUnavailable(
            "context lease expired before publication reservation".to_string(),
        ));
    }
    let digest = seal.digest();
    let state = Arc::new(AtomicU8::new(PENDING));
    let mut issued = ISSUED_CONTEXT_SEALS
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| {
            CognitiveContextError::ReadUnavailable("context seal registry poisoned".to_string())
        })?;
    issued.retain(|_, existing| {
        lease_current(&existing.seal, now)
            && existing.state.load(Ordering::Acquire) != ABANDONED
    });
    // Never share the revocation state of a prior publication with a new
    // reservation. Dropping one request must not revoke another response.
    if issued.contains_key(&digest) {
        return Err(CognitiveContextError::ReadUnavailable(
            "context delivery seal identity is already reserved".to_string(),
        ));
    }
    if issued.len() >= MAX_ISSUED_CONTEXT_SEALS {
        return Err(CognitiveContextError::ReadUnavailable(
            "context delivery seal registry is full".to_string(),
        ));
    }
    issued.insert(
        digest,
        SealEntryV2 {
            seal,
            state: Arc::clone(&state),
        },
    );
    Ok(PendingContextSealV2 {
        digest,
        state,
        published: false,
    })
}

pub(super) fn issued_seal(digest: Digest32) -> Result<IssuedContextSealV2, CognitiveContextError> {
    let now = helpers::monotonic_micros()?;
    let mut issued = ISSUED_CONTEXT_SEALS
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| {
            CognitiveContextError::ReadUnavailable("context seal registry poisoned".to_string())
        })?;
    issued.retain(|_, existing| {
        lease_current(&existing.seal, now)
            && existing.state.load(Ordering::Acquire) != ABANDONED
    });
    issued
        .get(&digest)
        .filter(|entry| entry.state.load(Ordering::Acquire) == PUBLISHED)
        .map(|entry| entry.seal.clone())
        .ok_or_else(|| {
            CognitiveContextError::ReadUnavailable(
                "context seal is unrecorded, abandoned, expired or from another process"
                    .to_string(),
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seal(name: &str) -> IssuedContextSealV2 {
        let now = helpers::monotonic_micros().expect("clock");
        let digest = Digest32::of_bytes(name.as_bytes());
        IssuedContextSealV2 {
            owner: AgentId::parse("00000000-0000-4000-8000-000000000881").expect("owner"),
            body_generation: 1,
            snapshot_digest: digest,
            read_binding_digest: digest,
            evaluated_context_digest: digest,
            raw_plan_receipt_digest: digest,
            request_binding_digest: digest,
            retrieval_context_digest: None,
            ranker_policy_digest: None,
            record_set_digest: digest,
            visible_record_count: 0,
            issued_at_micros: now,
            expires_at_micros: now + CONTEXT_LEASE_MICROS,
            read_allowed: false,
            query: name.to_string(),
        }
    }

    #[test]
    fn pending_and_abandoned_seals_never_pass_final_use() {
        let pending = reserve(seal("pending-and-abandoned")).expect("reserve");
        let digest = pending.digest();
        assert!(issued_seal(digest).is_err());
        drop(pending);
        assert!(issued_seal(digest).is_err());
    }

    #[test]
    fn publication_preserves_the_original_receipt_and_deadline() {
        let original = seal("publish-exact-receipt");
        let pending = reserve(original.clone()).expect("reserve");
        let digest = pending.digest();
        pending.publish();
        assert_eq!(issued_seal(digest).expect("published"), original);
        assert!(reserve(original.clone()).is_err());
        assert_eq!(issued_seal(digest).expect("not revoked by retry"), original);
    }

    #[test]
    fn lease_rejects_time_reversal_and_expiry_without_sleeping() {
        let mut value = seal("lease-boundaries");
        value.issued_at_micros = 100;
        value.expires_at_micros = 200;
        assert!(!lease_current(&value, 99));
        assert!(lease_current(&value, 100));
        assert!(lease_current(&value, 199));
        assert!(!lease_current(&value, 200));
        value.expires_at_micros = 100 + CONTEXT_LEASE_MICROS + 1;
        assert!(!lease_current(&value, 100));
    }

    #[test]
    fn every_request_scope_field_changes_its_binding() {
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000882").expect("owner");
        let other = AgentId::parse("00000000-0000-4000-8000-000000000883").expect("other");
        let policy = Some(Digest32::of_bytes(b"policy"));
        let ranker = Some(Digest32::of_bytes(b"ranker"));
        let bind = helpers::request_binding_digest;
        let expected = bind(&owner, 1, "query", 4, Some(1), policy, ranker);
        for changed in [
            bind(&other, 1, "query", 4, Some(1), policy, ranker),
            bind(&owner, 2, "query", 4, Some(1), policy, ranker),
            bind(&owner, 1, "other query", 4, Some(1), policy, ranker),
            bind(&owner, 1, "query", 3, Some(1), policy, ranker),
            bind(&owner, 1, "query", 4, Some(2), policy, ranker),
            bind(&owner, 1, "query", 4, None, policy, ranker),
            bind(&owner, 1, "query", 4, Some(1), None, ranker),
            bind(&owner, 1, "query", 4, Some(1), policy, None),
        ] {
            assert_ne!(expected, changed);
        }
    }

}
