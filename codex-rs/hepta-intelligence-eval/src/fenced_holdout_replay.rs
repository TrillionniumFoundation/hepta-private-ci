//! Canonical transitions shared by live CAS admission and incremental replay.
//! Replay retains one semantic journal instead of reconstructing every prefix.
use super::*;

pub(super) fn transition_payload(
    current: Option<&FinalHoldoutCasRecordV1>,
    next: &FinalHoldoutCasRecordV1,
) -> Result<Vec<u8>, LockedFileCasErrorV1> {
    match current {
        None => {
            if !next.journal.records.is_empty() {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            encode_fence(&next.fence)
        }
        Some(current) if next.journal == current.journal => {
            if next.fence == current.fence {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            if next.fence.generation <= current.fence.generation {
                return Err(LockedFileCasErrorV1::Rollback);
            }
            encode_fence(&next.fence)
        }
        Some(current) => {
            if next.fence != current.fence
                || next.journal.records.len() != current.journal.records.len() + 1
                || next.journal.records[..current.journal.records.len()]
                    != current.journal.records[..]
            {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            let record = next
                .journal
                .records
                .last()
                .ok_or(LockedFileCasErrorV1::Corrupt)?;
            let encoded =
                encode_holdout_plan(&record.plan).map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            let mut payload = vec![EVENT_PLAN];
            payload.extend_from_slice(&encoded);
            Ok(payload)
        }
    }
}

pub(super) fn replay_event(
    binding: Digest32,
    current: Option<&FinalHoldoutCasRecordV1>,
    journal: &mut FinalHoldoutJournalV1,
    payload: &[u8],
) -> Result<FinalHoldoutCasRecordV1, LockedFileCasErrorV1> {
    let tag = *payload.first().ok_or(LockedFileCasErrorV1::Corrupt)?;
    match tag {
        EVENT_FENCE => {
            let fence = decode_fence(payload)?;
            if current.is_some_and(|record| fence.generation <= record.fence.generation) {
                return Err(LockedFileCasErrorV1::Rollback);
            }
            FinalHoldoutCasRecordV1::new(binding, fence, journal.snapshot())
                .map_err(|_| LockedFileCasErrorV1::Corrupt)
        }
        EVENT_PLAN => {
            let current = current.ok_or(LockedFileCasErrorV1::Corrupt)?;
            let plan =
                decode_holdout_plan(&payload[1..]).map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            let receipt = journal
                .consume(journal.head_digest(), &plan)
                .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            if receipt.disposition != crate::HoldoutUseDispositionV1::Recorded {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            FinalHoldoutCasRecordV1::new(binding, current.fence.clone(), journal.snapshot())
                .map_err(|_| LockedFileCasErrorV1::Corrupt)
        }
        _ => Err(LockedFileCasErrorV1::Corrupt),
    }
}

fn encode_fence(fence: &HoldoutWriterFenceV1) -> Result<Vec<u8>, LockedFileCasErrorV1> {
    if fence.generation == 0 || fence.lease_digest.is_zero() {
        return Err(LockedFileCasErrorV1::Binding);
    }
    let owner = fence.owner_id.as_str().as_bytes();
    let owner_len = u16::try_from(owner.len()).map_err(|_| LockedFileCasErrorV1::Capacity)?;
    let mut payload = vec![EVENT_FENCE];
    payload.extend_from_slice(&owner_len.to_be_bytes());
    payload.extend_from_slice(owner);
    payload.extend_from_slice(&fence.generation.to_be_bytes());
    payload.extend_from_slice(fence.lease_digest.as_array());
    Ok(payload)
}

fn decode_fence(payload: &[u8]) -> Result<HoldoutWriterFenceV1, LockedFileCasErrorV1> {
    if payload.first().copied() != Some(EVENT_FENCE) || payload.len() < 1 + 2 + 8 + 32 {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    let owner_len = u16::from_be_bytes([payload[1], payload[2]]) as usize;
    let owner_start = 3;
    let owner_end = owner_start + owner_len;
    let generation_end = owner_end + 8;
    let lease_end = generation_end + 32;
    if lease_end != payload.len() {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    let owner = std::str::from_utf8(
        payload
            .get(owner_start..owner_end)
            .ok_or(LockedFileCasErrorV1::Corrupt)?,
    )
    .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
    let generation_bytes = payload
        .get(owner_end..generation_end)
        .ok_or(LockedFileCasErrorV1::Corrupt)?;
    let generation = u64::from_be_bytes(
        generation_bytes
            .try_into()
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?,
    );
    let lease = payload
        .get(generation_end..lease_end)
        .ok_or(LockedFileCasErrorV1::Corrupt)?;
    let lease_digest = Digest32::from_array(
        lease
            .try_into()
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?,
    );
    let owner_id = StableId::new(owner).map_err(|_| LockedFileCasErrorV1::Corrupt)?;
    if generation == 0 || lease_digest.is_zero() {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    Ok(HoldoutWriterFenceV1 {
        owner_id,
        generation,
        lease_digest,
    })
}
