//! Additive discriminated event framing; no writer/recovery path is switched.
//! Body parsing establishes bounded syntax only. Causal validity, signatures,
//! independent provenance and writer authority still belong to the ledger owner.
use crate::InspectedLegacyEventV1;
use crate::LegacyLedgerProfileV1;
use crate::legacy_inspection::LEGACY_EVENT_DOMAIN;
use codex_hepta_types::Digest32;
use std::error::Error;
use std::fmt;

pub const LEDGER_EVENT_DOMAIN_V2: &[u8] = b"hepta.learning-ledger.event.v2";
pub const MAX_LEDGER_EVENT_V2_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PersistedLedgerEventKindV2 {
    Common(u8),
    LegacyRetrievalAssignment,
    RetrievalPrepared,
    RetrievalAssignmentIntent,
    RetrievalPublicationConfirmed,
}
impl PersistedLedgerEventKindV2 {
    fn code(self) -> Result<u16, PersistedCodecErrorV2> {
        match self {
            Self::Common(tag @ 0..=8) => Ok(u16::from(tag)),
            Self::LegacyRetrievalAssignment => Ok(9),
            Self::RetrievalPrepared => Ok(0x100),
            Self::RetrievalAssignmentIntent => Ok(0x101),
            Self::RetrievalPublicationConfirmed => Ok(0x102),
            Self::Common(_) => Err(PersistedCodecErrorV2::Kind),
        }
    }
    fn from_code(code: u16) -> Result<Self, PersistedCodecErrorV2> {
        match code {
            0..=8 => Ok(Self::Common(code as u8)),
            9 => Ok(Self::LegacyRetrievalAssignment),
            0x100 => Ok(Self::RetrievalPrepared),
            0x101 => Ok(Self::RetrievalAssignmentIntent),
            0x102 => Ok(Self::RetrievalPublicationConfirmed),
            _ => Err(PersistedCodecErrorV2::Kind),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PersistedCodecErrorV2 {
    Size,
    Version,
    Kind,
    Body,
    Header,
}
impl fmt::Display for PersistedCodecErrorV2 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for PersistedCodecErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DiscriminatedLedgerEventV2 {
    kind: PersistedLedgerEventKindV2,
    encoded: Vec<u8>,
    digest: Digest32,
}
impl DiscriminatedLedgerEventV2 {
    /// Deterministically encode an explicitly selected kind and bounded body.
    /// This does not authorize rewriting/importing an existing historical row.
    pub fn from_body(
        kind: PersistedLedgerEventKindV2,
        body: &[u8],
    ) -> Result<Self, PersistedCodecErrorV2> {
        let code = kind.code()?;
        if body.len() > MAX_LEDGER_EVENT_V2_BYTES - LEDGER_EVENT_DOMAIN_V2.len() - 6 {
            return Err(PersistedCodecErrorV2::Size);
        }
        // Reuse the exact already bounded body parsers. This dispatch is fixed
        // by the new explicit semantic kind, never by trial decoding or a guess.
        let (profile, tag) = match kind {
            PersistedLedgerEventKindV2::Common(tag) => {
                (LegacyLedgerProfileV1::OperatorPublication, tag)
            }
            PersistedLedgerEventKindV2::LegacyRetrievalAssignment => {
                (LegacyLedgerProfileV1::OperatorPublication, 9)
            }
            PersistedLedgerEventKindV2::RetrievalPrepared => {
                (LegacyLedgerProfileV1::IntegrationPreparation, 10)
            }
            PersistedLedgerEventKindV2::RetrievalAssignmentIntent => {
                (LegacyLedgerProfileV1::OperatorPublication, 10)
            }
            PersistedLedgerEventKindV2::RetrievalPublicationConfirmed => {
                (LegacyLedgerProfileV1::OperatorPublication, 11)
            }
        };
        let mut parsing_input = LEGACY_EVENT_DOMAIN.to_vec();
        parsing_input.push(tag);
        parsing_input.extend_from_slice(body);
        InspectedLegacyEventV1::inspect(&parsing_input, Some(profile))
            .map_err(|_| PersistedCodecErrorV2::Body)?;
        let mut encoded = LEDGER_EVENT_DOMAIN_V2.to_vec();
        encoded.extend_from_slice(&code.to_be_bytes());
        encoded.extend_from_slice(&(body.len() as u32).to_be_bytes());
        encoded.extend_from_slice(body);
        let digest = Digest32::of_bytes(&encoded);
        Ok(Self {
            kind,
            encoded,
            digest,
        })
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, PersistedCodecErrorV2> {
        if bytes.len() > MAX_LEDGER_EVENT_V2_BYTES {
            return Err(PersistedCodecErrorV2::Size);
        }
        let rest = bytes
            .strip_prefix(LEDGER_EVENT_DOMAIN_V2)
            .ok_or(PersistedCodecErrorV2::Version)?;
        let prefix = rest.get(..6).ok_or(PersistedCodecErrorV2::Body)?;
        let code = u16::from_be_bytes(
            prefix[..2]
                .try_into()
                .map_err(|_| PersistedCodecErrorV2::Body)?,
        );
        let length = u32::from_be_bytes(
            prefix[2..]
                .try_into()
                .map_err(|_| PersistedCodecErrorV2::Body)?,
        ) as usize;
        if length != rest.len() - 6 {
            return Err(PersistedCodecErrorV2::Size);
        }
        Self::from_body(PersistedLedgerEventKindV2::from_code(code)?, &rest[6..])
    }
    pub const fn kind(&self) -> PersistedLedgerEventKindV2 {
        self.kind
    }
    pub fn encoded_bytes(&self) -> &[u8] {
        &self.encoded
    }
    pub fn body(&self) -> &[u8] {
        &self.encoded[LEDGER_EVENT_DOMAIN_V2.len() + 6..]
    }
    pub const fn event_digest(&self) -> Digest32 {
        self.digest
    }
}

#[cfg(test)]
#[path = "persisted_codec_v2_tests.rs"]
mod tests;
