//! Physical-send input resolution composition.
//!
//! Context final-use is resolved before any attempt-local ephemeral input. The
//! context resolver cannot add or mutate request content; it only obtains the
//! construction-closed proof for context already assembled into the request.

use codex_extension_api::ModelProviderPolicyError;

use super::binding::ModelProviderAttemptEnvelope;
use super::binding::ModelProviderPolicyContext;
use super::lifecycle::ActiveModelProviderPolicies;

#[path = "ephemeral_input_legacy.rs"]
mod legacy;
pub(crate) use legacy::EphemeralModelInputBinding;
pub(crate) use legacy::PreparedEphemeralModelInput;

pub(crate) async fn resolve_ephemeral_model_input(
    context: &ModelProviderPolicyContext<'_>,
    attempt: &ModelProviderAttemptEnvelope,
    active_policies: &ActiveModelProviderPolicies,
    model_context_window: Option<i64>,
) -> Result<Option<PreparedEphemeralModelInput>, ModelProviderPolicyError> {
    // A returned binding is intentionally not folded into ephemeral-input
    // semantics. The final-use contributor retains the construction-closed
    // proof for this exact attempt and the provider policy consumes it before
    // transport. Multiple claimants and scope drift fail here.
    let _context_binding =
        super::context_input::resolve_model_provider_context(context, attempt).await?;
    legacy::resolve_ephemeral_model_input(
        context,
        attempt,
        active_policies,
        model_context_window,
    )
    .await
}
