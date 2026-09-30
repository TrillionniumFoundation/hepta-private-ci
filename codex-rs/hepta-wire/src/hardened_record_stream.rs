//! Bounded authenticated framing for the final bound production owner.
//!
//! A completed record is not delivered as a raw envelope. The stream first
//! verifies the HPTM prefix, session identity, sequence and MAC, then performs
//! frozen-registry admission, exact codec binding, typed decode and canonical
//! re-encoding through `HardenedManagedWireSession`. Only `C::Value` crosses the
//! production boundary.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::BoundPayloadCodec;
use crate::DecodeFeed;
use crate::HardenedManagedSessionError;
use crate::HardenedManagedWireSession;
use crate::MAX_AUTHENTICATED_RECORD_BYTES;
use crate::MAX_WIRE_FRAME_BYTES;
use crate::RecordStreamLimits;
use crate::SessionLifecycleState;
use crate::WIRE_HEADER_BYTES;

const PREFIX_BYTES: usize = 4 + 2 + 32 + 8 + 4;
const TAG_BYTES: usize = 32;

include!("hardened_record_stream/types.rs");
include!("hardened_record_stream/impl.rs");
#[cfg(test)]
include!("hardened_record_stream/tests.rs");
