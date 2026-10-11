mod binding;

// Registered ahead of the transport caller for the same staged-review reason
// as `binding`; the caller-composition slice removes this allowance.
#[allow(dead_code)]
mod lifecycle;

mod memory;

mod ephemeral_input;

// Registered before the HTTP/WS callsites so cancellation ownership can be
// reviewed and tested independently.
#[allow(dead_code)]
mod attempt_owner;

// Registered before response-stream plumbing so terminal framing remains a
// focused review slice.
#[allow(dead_code)]
mod response_terminal;

// Registered before HTTP/WS caller composition so wire identity can be
// reviewed independently from transport control flow.
#[allow(dead_code)]
mod transport;

pub(crate) use attempt_owner::ProviderAttemptOwner;
pub(crate) use binding::ModelProviderPolicyContext;
#[cfg(test)]
pub(crate) use binding::bytes_sha256;
pub(crate) use binding::canonical_sha256;
pub(crate) use binding::prepare_model_provider_attempt;
pub(crate) use binding::prepare_model_provider_policy;
pub(crate) use ephemeral_input::resolve_ephemeral_model_input;
pub(crate) use lifecycle::ModelProviderPolicyBegin;
pub(crate) use lifecycle::active_model_provider_policies;
pub(crate) use lifecycle::begin_active_model_provider_policy;
pub(crate) use lifecycle::begin_model_provider_policy;
pub(crate) use lifecycle::has_active_model_provider_policy;
pub use memory::MemoryModelProviderPolicyHandle;
pub use memory::MemoryTurnInputSubmission;
pub(crate) use response_terminal::ProviderResponseTerminal;
pub(crate) use transport::ProviderRoutingHint;
pub(crate) use transport::ProviderWireSemantic;
pub(crate) use transport::logical_compaction_request;
pub(crate) use transport::logical_responses_request;
pub(crate) use transport::provider_websocket_wire_payload;
pub(crate) use transport::responses_lite_from_http_header;
pub(crate) use transport::responses_lite_from_ws_metadata;
