#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if new in text and old not in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1))


ledger = "codex-rs/hepta-fleet/src/lease_ledger_v2.rs"

# Reserve a durable tombstone slot when a grant is issued. Active grants are
# already part of the permanent identity budget, so terminal transitions add no
# new identity and must not double-count the retiring grants.
replace_once(
    ledger,
    """        if self.active_grants.len() >= MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        let committed = self""",
    """        if self.active_grants.len() >= MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        self.ensure_retirement_capacity(1)?;
        let committed = self""",
)
replace_once(
    ledger,
    """    fn revoke(&mut self, current: AllocationGrant, now_ms: u64) -> Result<LeaseReceipt, Error> {
        self.ensure_retirement_capacity(1)?;""",
    """    fn revoke(&mut self, current: AllocationGrant, now_ms: u64) -> Result<LeaseReceipt, Error> {
        self.ensure_retirement_capacity(0)?;""",
)
replace_once(
    ledger,
    """        let retiring = deadlines.iter().try_fold(0_usize, |total, deadline| {
            total
                .checked_add(self.expiry_index.get(deadline).map_or(0, BTreeSet::len))
                .ok_or(Error::ArithmeticOverflow)
        })?;
        self.ensure_retirement_capacity(retiring)?;
        let mut expired = 0;""",
    """        self.ensure_retirement_capacity(0)?;
        let mut expired = 0;""",
)
replace_once(
    ledger,
    """        self.ensure_retirement_capacity(allocation_ids.len())?;
        for allocation_id in allocation_ids {""",
    """        self.ensure_retirement_capacity(0)?;
        for allocation_id in allocation_ids {""",
)
replace_once(
    ledger,
    """    fn ensure_retirement_capacity(&self, additional: usize) -> Result<(), Error> {
        check_retirement_capacity(self.retired_allocation_ids.len(), additional)
    }""",
    """    fn ensure_retirement_capacity(&self, additional: usize) -> Result<(), Error> {
        let live_and_retired = self
            .retired_allocation_ids
            .len()
            .checked_add(self.active_grants.len())
            .ok_or(Error::RetiredGrantCapacityExceeded)?;
        check_retirement_capacity(live_and_retired, additional)
    }""",
)
replace_once(
    ledger,
    """    if retired.len() > MAX_RETIRED_ALLOCATION_IDS {
        return Err(Error::CorruptSnapshot);
    }
    let retained_history =""",
    """    if retired
        .len()
        .checked_add(active.len())
        .is_none_or(|total| total > MAX_RETIRED_ALLOCATION_IDS)
    {
        return Err(Error::CorruptSnapshot);
    }
    let retained_history =""",
)

core = "codex-rs/hepta-fleet/src/durable_owner_core.rs"
frontier = "codex-rs/hepta-fleet/src/durable_owner_frontier.rs"

# The final state hash covers the operation commitment. The operation
# commitment excludes only its own self-referential field, not every historical
# receipt field. This preserves both stable replay identity and state integrity.
replace_once(
    core,
    """        candidate.content_sha256.clear();
        candidate.content_sha256 = state_digest(&candidate)?;
        operation.committed_state_sha256 = candidate.content_sha256.clone();
        let stored_operation = candidate
            .fleet_operation_receipts
            .iter_mut()
            .find(|receipt| receipt.operation_id == operation.operation_id)
            .ok_or(DurableFleetError::CorruptState)?;
        stored_operation.committed_state_sha256 = candidate.content_sha256.clone();
        validate_state(&candidate, Arc::clone(&self.clock))?;""",
    """        candidate.content_sha256.clear();
        let operation_commitment =
            operation_state_commitment_digest(&candidate, &operation.operation_id)?;
        operation.committed_state_sha256 = operation_commitment.clone();
        let stored_operation = candidate
            .fleet_operation_receipts
            .iter_mut()
            .find(|receipt| receipt.operation_id == operation.operation_id)
            .ok_or(DurableFleetError::CorruptState)?;
        stored_operation.committed_state_sha256 = operation_commitment;
        candidate.content_sha256 = state_digest(&candidate)?;
        validate_state(&candidate, Arc::clone(&self.clock))?;""",
)
replace_once(
    core,
    """fn issue_receipt_from_operation(
    state: &DurableFleetStateV1,
    operation: FleetOperationReceiptV1,""",
    """fn issue_receipt_from_operation(
    _state: &DurableFleetStateV1,
    operation: FleetOperationReceiptV1,""",
)
replace_once(
    core,
    """fn state_digest(state: &DurableFleetStateV1) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    for receipt in &mut candidate.fleet_operation_receipts {
        receipt.committed_state_sha256.clear();
    }
    let encoded = serde_json::to_vec(&candidate)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.durable-state.v1\\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}""",
    """fn operation_state_commitment_digest(
    state: &DurableFleetStateV1,
    operation_id: &str,
) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    let operation = candidate
        .fleet_operation_receipts
        .iter_mut()
        .find(|receipt| receipt.operation_id == operation_id)
        .ok_or(DurableFleetError::CorruptState)?;
    operation.committed_state_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.operation-state-commitment.v1\\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn state_digest(state: &DurableFleetStateV1) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.durable-state.v1\\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}""",
)
replace_once(
    frontier,
    """fn state_digest(state: &DurableFleetStateV1) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    for receipt in &mut candidate.fleet_operation_receipts {
        receipt.committed_state_sha256.clear();
    }
    let encoded = serde_json::to_vec(&candidate)?;""",
    """fn state_digest(state: &DurableFleetStateV1) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;""",
)

print("runtime.fleet commitment and capacity fixups applied")
