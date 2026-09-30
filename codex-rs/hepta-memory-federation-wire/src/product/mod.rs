//! Product bridge from the authenticated wire host to canonical federation V2.
//!
//! The authenticated control frame binds an opaque canonical body. This module
//! verifies that body before durable replay or terminal state is committed and
//! exposes the existing canonical `FederationTransportV2` seam. It deliberately
//! does not open sockets or manufacture transport identity. A selected transport
//! must mint channel evidence through a configured transport-context issuer, and
//! the product bridge verifies that evidence with the corresponding capability.

mod body;
mod bridge;
mod context;
mod error;
mod packet;
mod transport;

pub use body::decode_query_v2;
pub use body::decode_response_v2;
pub use body::encode_query_v2;
pub use body::encode_response_v2;
pub use bridge::AdmittedFederationProductQueryV1;
pub use bridge::FederationProductClientV1;
pub use bridge::FederationProductHostAdmissionV1;
pub use bridge::FederationProductHostV1;
pub use context::FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES;
pub use context::FederationAuthenticatedTransportV1;
pub use context::FederationProductProfileV1;
pub use context::FederationTransportContextIssuerV1;
pub use context::FederationTransportContextVerifierV1;
pub use error::FederationProductErrorV1;
pub use packet::FederationProductPacketV1;
pub use packet::MAX_FEDERATION_PRODUCT_BODY_BYTES;
pub use packet::MAX_FEDERATION_PRODUCT_FRAME_BYTES;
pub use packet::MAX_FEDERATION_PRODUCT_PACKET_BYTES;
pub use transport::FederationProductClockV1;
pub use transport::FederationProductExchangeErrorV1;
pub use transport::FederationProductExchangeFutureV1;
pub use transport::FederationProductExchangeResponseV1;
pub use transport::FederationProductExchangeV1;
pub use transport::FederationWireTransportV2;
pub use transport::SystemFederationProductClockV1;
