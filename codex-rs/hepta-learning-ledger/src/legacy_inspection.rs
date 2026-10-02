//! Read-only, explicitly profiled inspection of the two colliding legacy codecs.
//!
//! A caller-selected profile is not authenticated deployment provenance. These
//! structural results do not authorize recovery, repair, append or migration.
//! Original event bytes/digests are retained; no trial-decoder selection occurs.

use crate::durable_codec::MAX_EVENT;
use crate::durable_codec::Reader;
use crate::durable_codec::decode_assignment_body;
use crate::durable_codec::decode_event;
use codex_hepta_types::Digest32;
use std::error::Error;
use std::fmt;

pub(crate) const LEGACY_EVENT_DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LegacyLedgerProfileV1 {
    IntegrationPreparation,
    OperatorPublication,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LegacyLedgerEventKindV1 {
    Common(u8),
    RetrievalPrepared,
    RetrievalAssignmentIntent,
    RetrievalPublicationConfirmed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InspectedLegacyEventV1 {
    profile: LegacyLedgerProfileV1,
    kind: LegacyLedgerEventKindV1,
    original: Vec<u8>,
    digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LegacyInspectionError {
    ProfileRequired,
    Size,
    Encoding,
    ProfileMismatch,
    Binding,
    Sequence,
    Digest,
    Incomplete,
}
impl fmt::Display for LegacyInspectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for LegacyInspectionError {}

impl InspectedLegacyEventV1 {
    pub fn inspect(
        bytes: &[u8],
        profile: Option<LegacyLedgerProfileV1>,
    ) -> Result<Self, LegacyInspectionError> {
        let profile = profile.ok_or(LegacyInspectionError::ProfileRequired)?;
        if bytes.len() > MAX_EVENT {
            return Err(LegacyInspectionError::Size);
        }
        let (tag, body) = bytes
            .strip_prefix(LEGACY_EVENT_DOMAIN)
            .and_then(|rest| rest.split_first())
            .ok_or(LegacyInspectionError::Encoding)?;
        let kind = match (profile, *tag) {
            (LegacyLedgerProfileV1::IntegrationPreparation, 10) => {
                let mut reader = Reader(body);
                let assignment = decode_assignment_body(&mut reader)
                    .map_err(|_| LegacyInspectionError::Encoding)?;
                // Exact integration-reader shape check, before interpreting its
                // exposure-shaped fields as preparation rather than publication.
                if !reader.0.is_empty()
                    || assignment.context_exposed
                        == assignment.delivered_candidate_indices.is_empty()
                    || assignment.context_exposed != assignment.published_context_digest.is_some()
                {
                    return Err(LegacyInspectionError::Encoding);
                }
                LegacyLedgerEventKindV1::RetrievalPrepared
            }
            (LegacyLedgerProfileV1::IntegrationPreparation, 11..) => {
                return Err(LegacyInspectionError::ProfileMismatch);
            }
            (LegacyLedgerProfileV1::OperatorPublication, 10) => {
                decode_event(bytes).map_err(|_| LegacyInspectionError::Encoding)?;
                LegacyLedgerEventKindV1::RetrievalAssignmentIntent
            }
            (LegacyLedgerProfileV1::OperatorPublication, 11) => {
                decode_event(bytes).map_err(|_| LegacyInspectionError::Encoding)?;
                LegacyLedgerEventKindV1::RetrievalPublicationConfirmed
            }
            (_, 0..=9) => {
                decode_event(bytes).map_err(|_| LegacyInspectionError::Encoding)?;
                LegacyLedgerEventKindV1::Common(*tag)
            }
            _ => return Err(LegacyInspectionError::ProfileMismatch),
        };
        Ok(Self {
            profile,
            kind,
            original: bytes.to_vec(),
            digest: Digest32::of_bytes(bytes),
        })
    }
    pub const fn caller_selected_profile(&self) -> LegacyLedgerProfileV1 {
        self.profile
    }
    pub const fn kind(&self) -> LegacyLedgerEventKindV1 {
        self.kind
    }
    pub fn original_bytes(&self) -> &[u8] {
        &self.original
    }
    pub const fn original_digest(&self) -> Digest32 {
        self.digest
    }
}

#[cfg(test)]
#[path = "legacy_inspection_tests.rs"]
mod tests;
