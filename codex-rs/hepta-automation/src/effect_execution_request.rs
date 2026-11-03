use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;

use crate::AuthorizedEffectIntent;
use crate::TaskFlowFence;

/// Caller-supplied bytes and claims for one synchronous or asynchronous dispatch.
///
/// This is a request, not a verified capability. Automation still verifies the
/// claimed step, wire digest, exact binding, signed grant and current fence at
/// their existing admission boundaries before contacting the provider.
pub struct AuthorizedEffectDispatchRequest<'a> {
    pub intent: &'a AuthorizedEffectIntent,
    pub wire_payload: &'a [u8],
    pub fence: &'a TaskFlowFence,
    pub signed_grant: &'a SignedFinalUseGrant,
    pub expected_binding: &'a FinalUseBinding,
    pub command_id: &'a str,
    pub now_ms: u64,
}
