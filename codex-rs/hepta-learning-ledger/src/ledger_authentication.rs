//! Authentication profiles change canonical history identities, not only headers.
use super::*;

impl Default for LearningLedger {
    fn default() -> Self {
        Self {
            authentication_profile: LearningAuthenticationProfile::ClassicalV1,
            records: Default::default(),
            record_digests: Default::default(),
            digest_positions: Default::default(),
            record_kinds: Default::default(),
            decisions: Default::default(),
            outcomes: Default::default(),
            outcome_lineage_heads: Default::default(),
            deliveries: Default::default(),
            credit_ids: Default::default(),
            credit_keys: Default::default(),
            credit_batch_ids: Default::default(),
            credited_outcomes: Default::default(),
            revoked: Default::default(),
            unlearning_lineage_ids: Default::default(),
            unlearning_keys: Default::default(),
        }
    }
}

impl LearningLedger {
    pub(crate) fn new_with_authentication_profile(profile: LearningAuthenticationProfile) -> Self {
        Self {
            authentication_profile: profile,
            ..Self::default()
        }
    }

    #[must_use]
    pub const fn authentication_profile(&self) -> LearningAuthenticationProfile {
        self.authentication_profile
    }
}

pub(super) fn event_digest(
    profile: LearningAuthenticationProfile,
    event: &LedgerEvent,
) -> Digest32 {
    match profile {
        LearningAuthenticationProfile::ClassicalV1 => digest_event(event),
        LearningAuthenticationProfile::MlDsa65V2 => {
            let mut bytes = b"hepta.learning-ledger.event.pq.v2\0".to_vec();
            bytes.extend_from_slice(&encode_event(event));
            Digest32::of_bytes(&bytes)
        }
    }
}

pub(super) fn chain_digest(
    profile: LearningAuthenticationProfile,
    predecessor: Digest32,
    sequence: LogicalSequence,
    event_digest: Digest32,
) -> Digest32 {
    match profile {
        LearningAuthenticationProfile::ClassicalV1 => {
            digest_chain(predecessor, sequence, event_digest)
        }
        LearningAuthenticationProfile::MlDsa65V2 => {
            let mut bytes = b"hepta.learning-ledger.chain.pq.v2\0".to_vec();
            bytes.extend_from_slice(predecessor.as_array());
            bytes.extend_from_slice(&sequence.get().to_be_bytes());
            bytes.extend_from_slice(event_digest.as_array());
            Digest32::of_bytes(&bytes)
        }
    }
}
