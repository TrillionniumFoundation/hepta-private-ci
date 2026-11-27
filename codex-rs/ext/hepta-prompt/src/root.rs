//! Provider-bound prompt runtime facade.
//!
//! The reviewed V1 runtime remains the source/dispatch owner. This facade adds
//! an exact-tokenizer capability and a second physical-send policy guard while
//! preserving the public runtime DTOs used by Agentd and the Codex adapter.

#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod compatibility;

pub use compatibility::PromptRuntimeAttachmentV1;
pub use compatibility::PromptRuntimeDeveloperFragmentV1;
pub use compatibility::PromptRuntimeDispatchFuture;
pub use compatibility::PromptRuntimeDispatchRecordV1;
pub use compatibility::PromptRuntimeError;
pub use compatibility::PromptRuntimeHostError;
pub use compatibility::PromptRuntimePrepareFuture;
pub use compatibility::PromptRuntimePrepareRequest;
pub use compatibility::PromptRuntimeRecordFuture;
pub use compatibility::PromptRuntimeTerminalOutcomeV1;
pub use compatibility::PromptRuntimeTerminalRecordV1;

mod provider_bound;

pub use provider_bound::PromptRuntimeHost;
pub use provider_bound::install_prompt_runtime;
