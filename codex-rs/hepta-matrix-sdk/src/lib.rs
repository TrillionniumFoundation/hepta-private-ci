//! Per-agent Matrix SDK transport for the Hepta Cognitive Fleet.
//!
//! Matrix is a chat transport only. This crate can persist allowlisted room
//! messages and deliver durable outbox records, but it intentionally exposes
//! no tool-approval, turn-cancel, file, or supervisor authority.

#![forbid(unsafe_code)]

mod config;
#[cfg(test)]
mod gap_fill;
mod ingress;
mod outbound;
#[cfg(feature = "qualification-failpoints")]
mod qualification;
mod sdk;
mod sync;

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
pub use outbound::MatrixOutboundTransport;
pub use outbound::MatrixSendFuture;
pub use outbound::MatrixTransportError;
pub use outbound::OutboxDispatchConfig;
pub use outbound::OutboxDispatchError;
pub use outbound::OutboxDispatchStats;
pub use outbound::dispatch_outbox_once;
pub use outbound::run_outbox_sender;
#[cfg(feature = "qualification-failpoints")]
pub use qualification::arm_post_send_pre_mark_ack_drop_once;
#[cfg(feature = "qualification-failpoints")]
pub use qualification::post_send_pre_mark_ack_drop_receipt_path;
pub use sdk::MatrixSdkClient;
pub use sdk::MatrixSdkError;
pub use sdk::MatrixSyncExit;
