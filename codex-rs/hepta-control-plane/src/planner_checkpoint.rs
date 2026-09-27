//! A checkpoint signature authenticates bytes, not freshness. The selected
//! anchor owner must maintain a durable monotonic CAS outside the planner's
//! backup domain. The planner never creates that owner's signing key.

use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlannerCheckpointV1 {
    pub store_id: Digest32,
    pub sequence: u64,
    pub head_digest: Digest32,
    pub retired: bool,
}

impl PlannerCheckpointV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.control.planner-checkpoint.v1\0".to_vec();
        bytes.extend_from_slice(self.store_id.as_array());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(self.head_digest.as_array());
        bytes.push(u8::from(self.retired));
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedPlannerCheckpointV1 {
    pub checkpoint: PlannerCheckpointV1,
    pub signature: [u8; 64],
}

impl SignedPlannerCheckpointV1 {
    pub fn verify(&self, pinned_key: &VerifyingKey) -> bool {
        !self.checkpoint.store_id.is_zero()
            && !self.checkpoint.head_digest.is_zero()
            && pinned_key
                .verify_strict(
                    &self.checkpoint.signing_bytes(),
                    &Signature::from_bytes(&self.signature),
                )
                .is_ok()
    }
}

/// Authenticated owner port, not a caller-provided claim. Implementations must
/// survive planner process death and old-backup restoration. `compare_exchange`
/// is linearizable, durable before acknowledgement, and idempotent for the
/// exact same predecessor/successor. Errors are indeterminate to the planner.
///
/// An in-memory implementation is appropriate only for unit fixtures. Selecting
/// a real anchor service/key and qualifying its rollback domain is a host gate.
pub trait PlannerCheckpointAnchorV1: Send {
    fn load(
        &mut self,
        store_id: Digest32,
    ) -> Result<Option<SignedPlannerCheckpointV1>, String>;

    fn compare_exchange(
        &mut self,
        expected: Option<PlannerCheckpointV1>,
        next: PlannerCheckpointV1,
    ) -> Result<SignedPlannerCheckpointV1, String>;
}
