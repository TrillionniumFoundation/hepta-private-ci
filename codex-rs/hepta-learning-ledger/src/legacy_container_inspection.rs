//! Bounded byte inspection, not durable recovery or witnessed admission.
use crate::InspectedLegacyEventV1;
use crate::LedgerAnchor;
use crate::LegacyInspectionError;
use crate::LegacyLedgerProfileV1;
use codex_hepta_types::Digest32;

const MAX_BYTES: usize = 8 * 1024 * 1024;
const MAX_RECORDS: u64 = 8192;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegacyContainerObservationV1 {
    pub caller_selected_profile: LegacyLedgerProfileV1,
    pub binding: Digest32,
    pub segment_index: Option<u64>,
    pub predecessor: LedgerAnchor,
    pub last: LedgerAnchor,
    pub records: u64,
    pub sealed: bool,
    pub original_bytes_digest: Digest32,
}

/// Inspect one complete journal or segment. Never truncates an incomplete tail,
/// opens a file, authenticates a witness, or infers a legacy grammar from bytes.
/// Cross-segment causal replay and independent provenance remain owner duties.
pub fn inspect_legacy_container_v1(
    bytes: &[u8],
    profile: Option<LegacyLedgerProfileV1>,
    expected_binding: Digest32,
) -> Result<LegacyContainerObservationV1, LegacyInspectionError> {
    let profile = profile.ok_or(LegacyInspectionError::ProfileRequired)?;
    if bytes.len() > MAX_BYTES {
        return Err(LegacyInspectionError::Size);
    }
    let magic = bytes.get(..8).ok_or(LegacyInspectionError::Incomplete)?;
    let (header, segment, prior, maximum_records, maximum_bytes) = match magic {
        b"HEPTLR01" => (
            72,
            None,
            LedgerAnchor {
                sequence: 0,
                chain_digest: Digest32::ZERO,
            },
            MAX_RECORDS,
            MAX_BYTES as u64,
        ),
        b"HEPTLS02" => {
            if bytes.len() < 136 {
                return Err(LegacyInspectionError::Incomplete);
            }
            if number(bytes, 40)? >= crate::MAX_LEDGER_SEGMENTS as u64 {
                return Err(LegacyInspectionError::Size);
            }
            let records = number(bytes, 88)?;
            let maximum_bytes = number(bytes, 96)?;
            if !(1..=MAX_RECORDS).contains(&records)
                || !(4096..=MAX_BYTES as u64).contains(&maximum_bytes)
            {
                return Err(LegacyInspectionError::Size);
            }
            (
                136,
                Some(number(bytes, 40)?),
                LedgerAnchor {
                    sequence: number(bytes, 48)?,
                    chain_digest: digest(bytes, 56)?,
                },
                records,
                maximum_bytes,
            )
        }
        _ => return Err(LegacyInspectionError::Encoding),
    };
    if bytes.len() < header {
        return Err(LegacyInspectionError::Incomplete);
    }
    if bytes.len() as u64 > maximum_bytes {
        return Err(LegacyInspectionError::Size);
    }
    let binding = digest(bytes, 8)?;
    if binding.is_zero() || binding != expected_binding {
        return Err(LegacyInspectionError::Binding);
    }
    if Digest32::of_bytes(&bytes[..header - 32]) != digest(bytes, header - 32)? {
        return Err(LegacyInspectionError::Digest);
    }
    if (prior.sequence == 0) != prior.chain_digest.is_zero() {
        return Err(LegacyInspectionError::Sequence);
    }
    let mut result = LegacyContainerObservationV1 {
        caller_selected_profile: profile,
        binding,
        segment_index: segment,
        predecessor: prior,
        last: prior,
        records: 0,
        sealed: false,
        original_bytes_digest: Digest32::of_bytes(bytes),
    };
    let mut cursor = header;
    while cursor < bytes.len() {
        let prefix = bytes
            .get(cursor..cursor + 8)
            .ok_or(LegacyInspectionError::Incomplete)?;
        let size = u32::from_be_bytes(
            prefix[..4]
                .try_into()
                .map_err(|_| LegacyInspectionError::Encoding)?,
        );
        let complement = u32::from_be_bytes(
            prefix[4..]
                .try_into()
                .map_err(|_| LegacyInspectionError::Encoding)?,
        );
        if size != !complement {
            return Err(LegacyInspectionError::Encoding);
        }
        if size == 0 {
            let index = segment.ok_or(LegacyInspectionError::Encoding)?;
            if bytes.len() - cursor != 80 {
                return Err(LegacyInspectionError::Incomplete);
            }
            let footer = &bytes[cursor..];
            if number(footer, 8)? != result.last.sequence
                || digest(footer, 16)? != result.last.chain_digest
            {
                return Err(LegacyInspectionError::Sequence);
            }
            let expected = Digest32::of_parts(&[
                b"hepta.learning-ledger.segment-seal.v2\0",
                binding.as_array(),
                &index.to_be_bytes(),
                &footer[..48],
            ]);
            if digest(footer, 48)? != expected {
                return Err(LegacyInspectionError::Digest);
            }
            result.sealed = true;
            break;
        }
        if size as usize > crate::durable_codec::MAX_EVENT || result.records >= maximum_records {
            return Err(LegacyInspectionError::Size);
        }
        let total = size as usize + crate::durable_codec::FRAME_OVERHEAD;
        let frame = bytes
            .get(cursor..cursor + total)
            .ok_or(LegacyInspectionError::Incomplete)?;
        let sequence = number(frame, 8)?;
        if sequence
            != result
                .last
                .sequence
                .checked_add(1)
                .ok_or(LegacyInspectionError::Sequence)?
            || digest(frame, 16)? != result.last.chain_digest
        {
            return Err(LegacyInspectionError::Sequence);
        }
        if Digest32::of_bytes(&frame[..total - 32]) != digest(frame, total - 32)? {
            return Err(LegacyInspectionError::Digest);
        }
        let event = InspectedLegacyEventV1::inspect(&frame[48..48 + size as usize], Some(profile))?;
        let chain = Digest32::of_parts(&[
            b"hepta.learning-ledger.chain.v1",
            result.last.chain_digest.as_array(),
            &sequence.to_be_bytes(),
            event.original_digest().as_array(),
        ]);
        if digest(frame, 48 + size as usize)? != chain {
            return Err(LegacyInspectionError::Digest);
        }
        result.last = LedgerAnchor {
            sequence,
            chain_digest: chain,
        };
        result.records += 1;
        cursor += total;
    }
    Ok(result)
}

fn digest(bytes: &[u8], offset: usize) -> Result<Digest32, LegacyInspectionError> {
    let raw = bytes
        .get(offset..offset + 32)
        .ok_or(LegacyInspectionError::Incomplete)?;
    Ok(Digest32::from_array(
        raw.try_into()
            .map_err(|_| LegacyInspectionError::Encoding)?,
    ))
}
fn number(bytes: &[u8], offset: usize) -> Result<u64, LegacyInspectionError> {
    let raw = bytes
        .get(offset..offset + 8)
        .ok_or(LegacyInspectionError::Incomplete)?;
    Ok(u64::from_be_bytes(
        raw.try_into()
            .map_err(|_| LegacyInspectionError::Encoding)?,
    ))
}
