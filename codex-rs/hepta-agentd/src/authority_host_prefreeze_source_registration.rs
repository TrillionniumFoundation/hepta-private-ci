//! One explicit disclosure selected by the protected Root supervisor. The
//! Generator signature authenticates its request; it does not select the task,
//! trust, read scope or recipient that this private registration authorizes.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use codex_hepta_learning_ledger::{ActivatedLearningTrustV1, SignedLearningEvidenceV1};
use crate::{AgentdError, OriginalCircuitPrefreezeSourceRequestV1};

/// Opaque, non-Clone, one-use registration. Only the Root loader which has read
/// its protected fixed disclosure contract may construct this value. Neither
/// the request signature nor a remote frame can construct one.
pub struct OriginalRootPrefreezeSourceRegistrationV1 {
    pub(super) request: OriginalCircuitPrefreezeSourceRequestV1,
    pub(super) trust: ActivatedLearningTrustV1,
    pub(super) evidence: SignedLearningEvidenceV1,
    pub(super) original_consumer_pidfd: OwnedFd,
    pub(super) stream: UnixStream,
    pub(super) startup_end: Instant,
}

impl OriginalRootPrefreezeSourceRegistrationV1 {
    /// The supplied startup_end is the existing task assembly's common startup
    /// deadline, never a newly granted wait after A. Root clamps it again to the
    /// same session end. Missing explicit disclosure authority must refuse here
    /// at the loader; evidence-role membership alone is insufficient.
    pub(crate) fn from_original_supervisor(
        request: OriginalCircuitPrefreezeSourceRequestV1,
        trust: ActivatedLearningTrustV1,
        evidence: SignedLearningEvidenceV1,
        original_consumer_pidfd: OwnedFd,
        stream: UnixStream,
        startup_end: Instant,
    ) -> Result<Self, AgentdError> {
        let now = Instant::now();
        if rustix::process::getuid().as_raw() != 0 || rustix::process::geteuid().as_raw() != 0
            || request.consumer.pid == std::process::id()
            || startup_end <= now || startup_end > now + Duration::from_secs(30)
        { return Err(super::protocol("original pre-freeze supervisor scope differs")); }
        let at = SystemTime::now().duration_since(UNIX_EPOCH).map_err(super::protocol)?.as_secs();
        request.require_evidence(trust.verifier(), trust.distribution_digest(),
            trust.generation(), &evidence, at).map_err(super::protocol)?;
        Ok(Self { request, trust, evidence, original_consumer_pidfd, stream, startup_end })
    }
}
