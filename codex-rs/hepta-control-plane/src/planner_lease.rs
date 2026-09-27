//! Process-local final-use binding. No receipt is an execution capability.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

/// Complete owner-verified request identity supplied by a trusted product host.
/// Digests bind authenticated inputs, but do not authenticate their producer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerRequestBindingV1 {
    pub owner_digest: Digest32,
    pub generation: u64,
    pub request_digest: Digest32,
    pub query_digest: Digest32,
    pub retrieval_profile_digest: Digest32,
    pub ranker_digest: Digest32,
    pub owner_cut_digest: Digest32,
    pub read_receipt_digest: Digest32,
    pub context_digest: Digest32,
    pub plan_receipt_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerLeaseError {
    MissingIdentity,
    InvalidLifetime,
    Expired,
    BindingChanged,
}

impl std::fmt::Display for PlannerLeaseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for PlannerLeaseError {}

impl PlannerRequestBindingV1 {
    pub fn digest(&self) -> Result<Digest32, PlannerLeaseError> {
        let fields = [
            self.owner_digest,
            self.request_digest,
            self.query_digest,
            self.retrieval_profile_digest,
            self.ranker_digest,
            self.owner_cut_digest,
            self.read_receipt_digest,
            self.context_digest,
            self.plan_receipt_digest,
        ];
        if self.generation == 0 || fields.iter().any(|value| value.is_zero()) {
            return Err(PlannerLeaseError::MissingIdentity);
        }
        let mut bytes = b"hepta.control.request-final-use.v1\0".to_vec();
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        for value in fields {
            bytes.extend_from_slice(value.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// A non-serializable lease retained by the host, never reconstructed from a
/// client-supplied digest. Restart invalidates it. Wall-clock adjustments do not
/// extend its lifetime. Use an explicit digest for the unranked policy as well.
#[derive(Debug)]
pub struct PlannerFinalUseLeaseV1 {
    binding: Digest32,
    deadline: Instant,
}

impl PlannerFinalUseLeaseV1 {
    pub fn new(binding: &PlannerRequestBindingV1, ttl: Duration) -> Result<Self, PlannerLeaseError> {
        if ttl.is_zero() || ttl > Duration::from_secs(1) {
            return Err(PlannerLeaseError::InvalidLifetime);
        }
        let deadline = Instant::now()
            .checked_add(ttl)
            .ok_or(PlannerLeaseError::InvalidLifetime)?;
        Ok(Self {
            binding: binding.digest()?,
            deadline,
        })
    }

    /// The host must also revalidate current owner/ranker authorization after
    /// awaiting any owner read and immediately before publishing context.
    pub fn revalidate(&self, binding: &PlannerRequestBindingV1) -> Result<(), PlannerLeaseError> {
        self.revalidate_at(binding, Instant::now())
    }

    fn revalidate_at(
        &self,
        binding: &PlannerRequestBindingV1,
        now: Instant,
    ) -> Result<(), PlannerLeaseError> {
        if now >= self.deadline {
            return Err(PlannerLeaseError::Expired);
        }
        if binding.digest()? != self.binding {
            return Err(PlannerLeaseError::BindingChanged);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn binding() -> PlannerRequestBindingV1 {
        PlannerRequestBindingV1 {
            owner_digest: Digest32::of_bytes(b"owner"),
            generation: 1,
            request_digest: Digest32::of_bytes(b"request"),
            query_digest: Digest32::of_bytes(b"query"),
            retrieval_profile_digest: Digest32::of_bytes(b"retrieval"),
            ranker_digest: Digest32::of_bytes(b"unranked"),
            owner_cut_digest: Digest32::of_bytes(b"cut"),
            read_receipt_digest: Digest32::of_bytes(b"read"),
            context_digest: Digest32::of_bytes(b"context"),
            plan_receipt_digest: Digest32::of_bytes(b"plan"),
        }
    }

    #[test]
    fn every_request_field_is_bound() {
        let original = binding();
        let original_digest = original.digest().unwrap();
        for index in 0..10 {
            let mut changed = original.clone();
            let replacement = Digest32::of_bytes(b"changed");
            match index {
                0 => changed.owner_digest = replacement,
                1 => changed.generation += 1,
                2 => changed.request_digest = replacement,
                3 => changed.query_digest = replacement,
                4 => changed.retrieval_profile_digest = replacement,
                5 => changed.ranker_digest = replacement,
                6 => changed.owner_cut_digest = replacement,
                7 => changed.read_receipt_digest = replacement,
                8 => changed.context_digest = replacement,
                _ => changed.plan_receipt_digest = replacement,
            }
            assert_ne!(changed.digest().unwrap(), original_digest);
        }
    }

    #[test]
    fn expiry_is_inclusive_and_plan_substitution_rejects() {
        let original = binding();
        let now = Instant::now();
        let deadline = now + Duration::from_secs(1);
        let lease = PlannerFinalUseLeaseV1 {
            binding: original.digest().unwrap(),
            deadline,
        };
        assert_eq!(lease.revalidate_at(&original, now), Ok(()));
        assert_eq!(
            lease.revalidate_at(&original, deadline),
            Err(PlannerLeaseError::Expired)
        );
        let mut changed = original;
        changed.plan_receipt_digest = Digest32::of_bytes(b"substituted-plan");
        assert_eq!(
            lease.revalidate_at(&changed, now),
            Err(PlannerLeaseError::BindingChanged)
        );
    }

    #[test]
    fn zero_identity_and_unbounded_lifetime_reject() {
        let mut input = binding();
        input.request_digest = Digest32::ZERO;
        assert_eq!(input.digest(), Err(PlannerLeaseError::MissingIdentity));
        assert!(matches!(
            PlannerFinalUseLeaseV1::new(&binding(), Duration::ZERO),
            Err(PlannerLeaseError::InvalidLifetime)
        ));
        assert!(matches!(
            PlannerFinalUseLeaseV1::new(&binding(), Duration::from_secs(2)),
            Err(PlannerLeaseError::InvalidLifetime)
        ));
    }
}
