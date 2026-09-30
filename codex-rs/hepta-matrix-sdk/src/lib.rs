//! Per-agent Matrix SDK transport for the Hepta Cognitive Fleet.
//!
//! Matrix is a chat transport only. This crate can persist allowlisted room
//! messages and deliver durable outbox records, but it intentionally exposes
//! no tool-approval, turn-cancel, file, or supervisor authority.
//!
//! The final-use permit is deliberately not part of the public API.
//!
//! ```compile_fail,E0432
//! use codex_hepta_matrix_sdk::MatrixSendPermit;
//! # fn main() {}
//! ```
//!
//! Safe downstream code cannot forge the raw transport seal.
//!
//! ```compile_fail,E0451
//! use codex_hepta_matrix_sdk::MatrixRawSendSeal;
//! # fn main() {
//! let _forged = MatrixRawSendSeal { _private: () };
//! # }
//! ```
//!
//! The public transport trait has no overridable authorized-send bypass.
//!
//! ```compile_fail,E0599
//! use codex_hepta_matrix_sdk::MatrixOutboundTransport;
//! fn bypass<T: MatrixOutboundTransport>(transport: &T) {
//!     let _ = transport.send_authorized();
//! }
//! # fn main() {}
//! ```
//!
//! The authenticated SDK facade does not expose the underlying raw client.
//!
//! ```compile_fail,E0599
//! use codex_hepta_matrix_sdk::MatrixSdkClient;
//! fn raw_client(client: &MatrixSdkClient) {
//!     let _ = client.client();
//! }
//! # fn main() {}
//! ```

#![forbid(unsafe_code)]

mod authority;
mod config;
mod content;
#[cfg(test)]
mod gap_fill;
mod ingress;
mod outbound_v2;
#[cfg(feature = "qualification-failpoints")]
mod qualification;
mod sdk;
mod sync;

pub use authority::MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION;
pub use authority::MatrixAuthorityError;
pub use authority::MatrixFinalUseRequest;
pub use authority::MatrixGrantFuture;
pub use authority::MatrixOutboundAuthorizer;
pub use authority::MatrixOutboundIdentity;
pub use authority::build_matrix_final_use_request;
pub use config::MatrixSdkPaths;
pub use config::MatrixSidecarConfig;
pub use config::MatrixSidecarConfigError;
pub use ingress::IngressDisposition;
pub use ingress::IngressIgnoredReason;
pub use ingress::IngressMetrics;
pub use ingress::MatrixIngress;
pub use ingress::MatrixIngressError;
pub use ingress::MatrixTimelineEvent;
pub use matrix_sdk::SessionMeta;
pub use matrix_sdk::SessionTokens;
pub use matrix_sdk::authentication::matrix::MatrixSession;
pub use outbound_v2::MatrixOutboundTransport;
pub use outbound_v2::MatrixRawSendSeal;
pub use outbound_v2::MatrixSendFuture;
pub use outbound_v2::MatrixTransportError;
pub use outbound_v2::OutboxDispatchConfig;
pub use outbound_v2::OutboxDispatchError;
pub use outbound_v2::OutboxDispatchStats;
pub use outbound_v2::dispatch_outbox_once;
pub use outbound_v2::run_outbox_sender;
#[cfg(feature = "qualification-failpoints")]
pub use qualification::arm_post_send_pre_mark_ack_drop_once;
#[cfg(feature = "qualification-failpoints")]
pub use qualification::post_send_pre_mark_ack_drop_receipt_path;
pub use sdk::MatrixSdkClient;
pub use sdk::MatrixSdkError;
pub use sdk::MatrixSyncExit;
