//! Pure V2 frame/chain encoding. No append, fsync, repair or activation authority.
use crate::DiscriminatedLedgerEventV2;
use crate::MAX_LEDGER_EVENT_V2_BYTES;
use crate::PersistedCodecErrorV2;
use codex_hepta_types::Digest32;

pub const LEDGER_CHAIN_DOMAIN_V2: &[u8] = b"hepta.learning-ledger.chain.v2";
pub const LEDGER_FRAME_V2_OVERHEAD: usize = 112;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DiscriminatedLedgerFrameV2 {
    sequence: u64,
    predecessor: Digest32,
    chain_digest: Digest32,
    event: DiscriminatedLedgerEventV2,
    encoded: Vec<u8>,
}
impl DiscriminatedLedgerFrameV2 {
    pub fn new(
        sequence: u64,
        predecessor: Digest32,
        event: DiscriminatedLedgerEventV2,
    ) -> Result<Self, PersistedCodecErrorV2> {
        if sequence == 0 || (sequence == 1) != predecessor.is_zero() {
            return Err(PersistedCodecErrorV2::Frame);
        }
        let payload = event.encoded_bytes();
        let size = u32::try_from(payload.len()).map_err(|_| PersistedCodecErrorV2::Size)?;
        let chain_digest = Digest32::of_parts(&[
            LEDGER_CHAIN_DOMAIN_V2,
            predecessor.as_array(),
            &sequence.to_be_bytes(),
            event.event_digest().as_array(),
        ]);
        let mut encoded = Vec::with_capacity(payload.len() + LEDGER_FRAME_V2_OVERHEAD);
        encoded.extend_from_slice(&size.to_be_bytes());
        encoded.extend_from_slice(&(!size).to_be_bytes());
        encoded.extend_from_slice(&sequence.to_be_bytes());
        encoded.extend_from_slice(predecessor.as_array());
        encoded.extend_from_slice(payload);
        encoded.extend_from_slice(chain_digest.as_array());
        let checksum = Digest32::of_bytes(&encoded);
        encoded.extend_from_slice(checksum.as_array());
        Ok(Self {
            sequence,
            predecessor,
            chain_digest,
            event,
            encoded,
        })
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, PersistedCodecErrorV2> {
        if bytes.len() < LEDGER_FRAME_V2_OVERHEAD
            || bytes.len() > MAX_LEDGER_EVENT_V2_BYTES + LEDGER_FRAME_V2_OVERHEAD
        {
            return Err(PersistedCodecErrorV2::Size);
        }
        let size = u32::from_be_bytes(
            bytes[..4]
                .try_into()
                .map_err(|_| PersistedCodecErrorV2::Frame)?,
        ) as usize;
        let complement = u32::from_be_bytes(
            bytes[4..8]
                .try_into()
                .map_err(|_| PersistedCodecErrorV2::Frame)?,
        );
        if size == 0
            || size > MAX_LEDGER_EVENT_V2_BYTES
            || size + LEDGER_FRAME_V2_OVERHEAD != bytes.len()
            || complement != !(size as u32)
        {
            return Err(PersistedCodecErrorV2::Size);
        }
        let sequence = u64::from_be_bytes(
            bytes[8..16]
                .try_into()
                .map_err(|_| PersistedCodecErrorV2::Frame)?,
        );
        let predecessor = Digest32::from_array(
            bytes[16..48]
                .try_into()
                .map_err(|_| PersistedCodecErrorV2::Frame)?,
        );
        let event = DiscriminatedLedgerEventV2::decode(&bytes[48..48 + size])?;
        let frame = Self::new(sequence, predecessor, event)?;
        if frame.encoded != bytes {
            return Err(PersistedCodecErrorV2::Frame);
        }
        Ok(frame)
    }
    pub const fn sequence(&self) -> u64 {
        self.sequence
    }
    pub const fn predecessor(&self) -> Digest32 {
        self.predecessor
    }
    pub const fn chain_digest(&self) -> Digest32 {
        self.chain_digest
    }
    pub fn event(&self) -> &DiscriminatedLedgerEventV2 {
        &self.event
    }
    pub fn encoded_bytes(&self) -> &[u8] {
        &self.encoded
    }
}

#[cfg(test)]
#[path = "persisted_frame_v2_tests.rs"]
mod tests;
