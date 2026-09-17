//! Capability-scoped, authenticated multi-peer federation.
//!
//! V3 closes the source-side federation boundary: every peer attempt consumes a
//! kernel-owned signed final-use grant, uses an immutable enrolled peer snapshot,
//! binds the remote response to the exact query and grant epoch, verifies an
//! Ed25519 peer signature over canonical response bytes, rechecks authority and
//! time after I/O, and only then releases non-authoritative evidence. The module
//! still never enrolls peers, mints authority, writes remote memory, or retries a
//! request implicitly.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use codex_http_client::HttpClientBuilder;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use futures::FutureExt;
use futures::future::BoxFuture;
use futures::stream;
use futures::stream::StreamExt;
use serde::Deserialize;
use serde::Serialize;
use url::Url;

use crate::FederatedCompletenessV2;
use crate::FederatedEvidenceItemV2;
use crate::FederatedValidityV2;
use crate::MAX_FEDERATED_RESULTS_V2;

pub const MAX_FEDERATED_PEERS_V3: usize = 16;
pub const MAX_FEDERATION_CACHE_ENTRIES_V3: usize = 4096;
pub const MAX_FEDERATION_RESPONSE_BYTES_V3: usize = 4 * 1024 * 1024;
pub const MAX_FEDERATION_QUERY_LIFETIME_MS_V3: u64 = 60_000;

const QUERY_DOMAIN_V3: &[u8] = b"hepta.memory-federation.query.v3";
const RESPONSE_PAYLOAD_DOMAIN_V3: &[u8] = b"hepta.memory-federation.response-payload.v3";
const RESPONSE_SIGNATURE_DOMAIN_V3: &[u8] = b"hepta.memory-federation.response-signature.v3";
const PEER_RESULT_DOMAIN_V3: &[u8] = b"hepta.memory-federation.peer-result.v3";
const AGGREGATE_RESULT_DOMAIN_V3: &[u8] = b"hepta.memory-federation.aggregate-result.v3";
const AUTHORITY_RECEIPT_DOMAIN_V3: &[u8] = b"hepta.memory-federation.authority-receipt.v3";
const FEDERATION_QUERY_PATH_V3: &str = "v1/memory/federation/query";

include!("v3/protocol.rs");
include!("v3/transport.rs");
include!("v3/results_cache.rs");
include!("v3/aggregate.rs");
include!("v3/client.rs");
include!("v3/wire_helpers.rs");

#[cfg(all(test, unix))]
#[path = "v3_tests.rs"]
mod tests;
