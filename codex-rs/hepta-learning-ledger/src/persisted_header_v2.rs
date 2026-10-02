//! Proposed new headers as pure codecs. A checksum is not owner authorization.
use crate::LedgerAnchor;
use crate::PersistedCodecErrorV2;
use codex_hepta_types::Digest32;

pub const LEDGER_JOURNAL_MAGIC_V2: &[u8; 8] = b"HEPTLR02";
pub const LEDGER_SEGMENT_MAGIC_V3: &[u8; 8] = b"HEPTLS03";
pub const LEDGER_CONTAINER_HEADER_V2_BYTES: usize = 192;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LedgerContainerKindV2 {
    Journal,
    Segment,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerContainerHeaderV2 {
    pub kind: LedgerContainerKindV2,
    pub binding: Digest32,
    pub owner_generation: u64,
    pub writer_fence: u64,
    pub segment_index: u64,
    pub predecessor: LedgerAnchor,
    /// None denotes a new history. Some identifies an immutable, independently
    /// authorized legacy inventory/codec plan; the digest alone proves none of it.
    pub legacy_manifest_digest: Option<Digest32>,
    pub maximum_records: u64,
    pub maximum_bytes: u64,
}
impl LedgerContainerHeaderV2 {
    pub fn encode(&self) -> Result<Vec<u8>, PersistedCodecErrorV2> {
        if self.binding.is_zero()
            || self.owner_generation == 0
            || self.writer_fence == 0
            || self.segment_index >= crate::MAX_LEDGER_SEGMENTS as u64
            || (self.kind == LedgerContainerKindV2::Journal && self.segment_index != 0)
            || (self.predecessor.sequence == 0) != self.predecessor.chain_digest.is_zero()
            || self.legacy_manifest_digest.is_some_and(Digest32::is_zero)
            || (self.segment_index == 0
                && self.legacy_manifest_digest.is_none()
                && self.predecessor.sequence != 0)
            || !(1..=8192).contains(&self.maximum_records)
            || !(4096..=8 * 1024 * 1024).contains(&self.maximum_bytes)
        {
            return Err(PersistedCodecErrorV2::Header);
        }
        let magic = match self.kind {
            LedgerContainerKindV2::Journal => LEDGER_JOURNAL_MAGIC_V2,
            LedgerContainerKindV2::Segment => LEDGER_SEGMENT_MAGIC_V3,
        };
        let mut bytes = magic.to_vec();
        bytes.extend_from_slice(&2_u16.to_be_bytes()); // header layout version
        bytes.extend_from_slice(&2_u16.to_be_bytes()); // event codec version
        bytes.extend_from_slice(&u32::from(self.legacy_manifest_digest.is_some()).to_be_bytes());
        bytes.extend_from_slice(self.binding.as_array());
        for value in [
            self.owner_generation,
            self.writer_fence,
            self.segment_index,
            self.predecessor.sequence,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(self.predecessor.chain_digest.as_array());
        bytes.extend_from_slice(
            self.legacy_manifest_digest
                .unwrap_or(Digest32::ZERO)
                .as_array(),
        );
        bytes.extend_from_slice(&self.maximum_records.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_bytes.to_be_bytes());
        let checksum = Digest32::of_bytes(&bytes);
        bytes.extend_from_slice(checksum.as_array());
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, PersistedCodecErrorV2> {
        if bytes.len() != LEDGER_CONTAINER_HEADER_V2_BYTES {
            return Err(PersistedCodecErrorV2::Size);
        }
        let kind = if &bytes[..8] == LEDGER_JOURNAL_MAGIC_V2 {
            LedgerContainerKindV2::Journal
        } else if &bytes[..8] == LEDGER_SEGMENT_MAGIC_V3 {
            LedgerContainerKindV2::Segment
        } else {
            return Err(PersistedCodecErrorV2::Version);
        };
        if bytes[8..12] != [0, 2, 0, 2] {
            return Err(PersistedCodecErrorV2::Version);
        }
        let flags = u32::from_be_bytes(
            bytes[12..16]
                .try_into()
                .map_err(|_| PersistedCodecErrorV2::Header)?,
        );
        if flags > 1 || Digest32::of_bytes(&bytes[..160]) != digest(bytes, 160)? {
            return Err(PersistedCodecErrorV2::Header);
        }
        let manifest = digest(bytes, 112)?;
        if (flags == 0) != manifest.is_zero() {
            return Err(PersistedCodecErrorV2::Header);
        }
        let header = Self {
            kind,
            binding: digest(bytes, 16)?,
            owner_generation: number(bytes, 48)?,
            writer_fence: number(bytes, 56)?,
            segment_index: number(bytes, 64)?,
            predecessor: LedgerAnchor {
                sequence: number(bytes, 72)?,
                chain_digest: digest(bytes, 80)?,
            },
            legacy_manifest_digest: if flags == 0 { None } else { Some(manifest) },
            maximum_records: number(bytes, 144)?,
            maximum_bytes: number(bytes, 152)?,
        };
        if header.encode()? != bytes {
            return Err(PersistedCodecErrorV2::Header);
        }
        Ok(header)
    }
}
fn digest(bytes: &[u8], at: usize) -> Result<Digest32, PersistedCodecErrorV2> {
    Ok(Digest32::from_array(
        bytes
            .get(at..at + 32)
            .ok_or(PersistedCodecErrorV2::Header)?
            .try_into()
            .map_err(|_| PersistedCodecErrorV2::Header)?,
    ))
}
fn number(bytes: &[u8], at: usize) -> Result<u64, PersistedCodecErrorV2> {
    Ok(u64::from_be_bytes(
        bytes
            .get(at..at + 8)
            .ok_or(PersistedCodecErrorV2::Header)?
            .try_into()
            .map_err(|_| PersistedCodecErrorV2::Header)?,
    ))
}
