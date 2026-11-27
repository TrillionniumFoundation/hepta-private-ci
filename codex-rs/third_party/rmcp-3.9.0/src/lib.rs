#![cfg_attr(docsrs, feature(doc_cfg))]
#![cfg_attr(docsrs, allow(unused_attributes))]
#![doc = include_str!("../README.md")]

mod error;
mod time;
pub use error::ErrorData;
pub use error::RmcpError;

/// Basic data types in MCP specification
pub mod model;
#[cfg(any(feature = "client", feature = "server"))]
pub mod service;
#[cfg(feature = "client")]
pub use handler::client::ClientHandler;
#[cfg(feature = "server")]
pub use handler::server::ServerHandler;
#[cfg(feature = "server")]
pub use handler::server::wrapper::Json;
#[cfg(feature = "client")]
pub use service::ClientCacheConfig;
#[cfg(feature = "client")]
pub use service::ClientLifecycleMode;
#[cfg(feature = "client")]
pub use service::ClientServiceExt;
#[cfg(feature = "client")]
pub use service::MAX_CLIENT_CACHE_TTL;
#[cfg(any(feature = "client", feature = "server"))]
pub use service::Peer;
#[cfg(feature = "client")]
pub use service::RoleClient;
#[cfg(feature = "server")]
pub use service::RoleServer;
#[cfg(any(feature = "client", feature = "server"))]
pub use service::Service;
#[cfg(any(feature = "client", feature = "server"))]
pub use service::ServiceError;
#[cfg(any(feature = "client", feature = "server"))]
pub use service::ServiceExt;
#[cfg(feature = "client")]
pub use service::select_protocol_version;
#[cfg(feature = "client")]
pub use service::serve_client;
#[cfg(feature = "client")]
pub use service::serve_client_with_lifecycle;
#[cfg(feature = "server")]
pub use service::serve_server;

pub mod handler;
#[cfg(feature = "server")]
pub mod task_manager;
#[cfg(any(feature = "client", feature = "server"))]
pub mod transport;

// re-export
#[cfg(all(feature = "macros", feature = "server"))]
pub use pastey::paste;
#[cfg(all(feature = "macros", feature = "server"))]
pub use rmcp_macros::*;
#[cfg(feature = "schemars")]
pub use schemars;
#[cfg(feature = "macros")]
pub use serde;
#[cfg(feature = "macros")]
pub use serde_json;
