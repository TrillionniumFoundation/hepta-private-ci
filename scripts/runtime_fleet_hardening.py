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


def replace_exact_count(path: str, old: str, new: str, expected: int) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        if text.count(new) == expected:
            return
        raise SystemExit(f"{path}: replacement source missing: {old[:120]!r}")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} replacements, found {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new))


def append_once(path: str, marker: str, addition: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    file.write_text(text + addition.lstrip("\n"))


# ---------------------------------------------------------------------------
# 1. Non-rollback frontier before every durable mutation.
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-fleet/src/durable_owner_frontier.rs"
for old, new in [
    (
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self.inner.refresh_capacity(operation_id, observer);""",
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        self.reconcile_latest_frontier(operation_id)?;
        let result = self.inner.refresh_capacity(operation_id, observer);""",
    ),
    (
        """    ) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
        let result = self.inner.issue_with_authority(""",
        """    ) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
        self.reconcile_latest_frontier(operation_id)?;
        let result = self.inner.issue_with_authority(""",
    ),
    (
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self.inner.renew_or_revoke(""",
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        self.reconcile_latest_frontier(operation_id)?;
        let result = self.inner.renew_or_revoke(""",
    ),
    (
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self.inner.reconcile_expired(operation_id);""",
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        self.reconcile_latest_frontier(operation_id)?;
        let result = self.inner.reconcile_expired(operation_id);""",
    ),
    (
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self
            .inner
            .persist_revocation_snapshot(operation_id, snapshot);""",
        """    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        self.reconcile_latest_frontier(operation_id)?;
        let result = self
            .inner
            .persist_revocation_snapshot(operation_id, snapshot);""",
    ),
]:
    replace_once(path, old, new)


# ---------------------------------------------------------------------------
# 2. Durable retired-allocation tombstones survive grant-history compaction.
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-fleet/src/lease_ledger_v2.rs"
replace_once(
    path,
    "pub const MAX_GRANT_HISTORY: usize = 32_768;\n",
    "pub const MAX_GRANT_HISTORY: usize = 32_768;\n"
    "pub const MAX_RETIRED_ALLOCATION_IDS: usize = 1_048_576;\n",
)
replace_once(
    path,
    """    pub history: VecDeque<GrantHistoryRecord>,
    pub compacted_history_records: u64,""",
    """    pub history: VecDeque<GrantHistoryRecord>,
    pub retired_allocation_ids: BTreeSet<String>,
    pub compacted_history_records: u64,""",
)
replace_once(
    path,
    """    GrantCapacityExceeded,
    HostNotFound,""",
    """    GrantCapacityExceeded,
    RetiredGrantCapacityExceeded,
    HostNotFound,""",
)
replace_once(
    path,
    """    history: VecDeque<GrantHistoryRecord>,
    compacted_history_records: u64,""",
    """    history: VecDeque<GrantHistoryRecord>,
    retired_allocation_ids: BTreeSet<String>,
    compacted_history_records: u64,""",
)
replace_once(
    path,
    """            .field("history", &self.history.len())
            .field("compacted_history_records", &self.compacted_history_records)""",
    """            .field("history", &self.history.len())
            .field("retired_allocation_ids", &self.retired_allocation_ids.len())
            .field("compacted_history_records", &self.compacted_history_records)""",
)
replace_once(
    path,
    """            history: VecDeque::new(),
            compacted_history_records: 0,""",
    """            history: VecDeque::new(),
            retired_allocation_ids: BTreeSet::new(),
            compacted_history_records: 0,""",
)
replace_once(
    path,
    """        if snapshot.hosts.len() > MAX_HOSTS
            || snapshot.active_grants.len() > MAX_ACTIVE_GRANTS
            || snapshot.history.len() > MAX_GRANT_HISTORY
        {""",
    """        if snapshot.hosts.len() > MAX_HOSTS
            || snapshot.active_grants.len() > MAX_ACTIVE_GRANTS
            || snapshot.history.len() > MAX_GRANT_HISTORY
            || snapshot.retired_allocation_ids.len() > MAX_RETIRED_ALLOCATION_IDS
        {""",
)
replace_once(
    path,
    """            history: snapshot.history,
            compacted_history_records: snapshot.compacted_history_records,""",
    """            history: snapshot.history,
            retired_allocation_ids: snapshot.retired_allocation_ids,
            compacted_history_records: snapshot.compacted_history_records,""",
)
replace_once(
    path,
    """        validate_history(&ledger.history, &ledger.active_grants)?;
        let grants = ledger.active_grants.values().cloned().collect::<Vec<_>>();""",
    """        validate_history(&ledger.history, &ledger.active_grants)?;
        validate_retired_identities(
            &ledger.retired_allocation_ids,
            &ledger.history,
            &ledger.active_grants,
            ledger.compacted_history_records,
        )?;
        let grants = ledger.active_grants.values().cloned().collect::<Vec<_>>();""",
)
replace_once(
    path,
    """            history: self.history.clone(),
            compacted_history_records: self.compacted_history_records,""",
    """            history: self.history.clone(),
            retired_allocation_ids: self.retired_allocation_ids.clone(),
            compacted_history_records: self.compacted_history_records,""",
)
replace_once(
    path,
    """        if self
            .history
            .iter()
            .any(|record| record.grant.allocation_id == grant.allocation_id)
        {
            return Err(Error::Conflict);
        }""",
    """        if self.retired_allocation_ids.contains(&grant.allocation_id) {
            return Err(Error::Conflict);
        }""",
)
replace_once(
    path,
    """    fn revoke(&mut self, current: AllocationGrant, now_ms: u64) -> Result<LeaseReceipt, Error> {
        let mut grant = self""",
    """    fn revoke(&mut self, current: AllocationGrant, now_ms: u64) -> Result<LeaseReceipt, Error> {
        self.ensure_retirement_capacity(1)?;
        let mut grant = self""",
)
replace_once(
    path,
    """        let deadlines = self
            .expiry_index
            .range(..=now_ms)
            .map(|(deadline, _)| *deadline)
            .collect::<Vec<_>>();
        let mut expired = 0;""",
    """        let deadlines = self
            .expiry_index
            .range(..=now_ms)
            .map(|(deadline, _)| *deadline)
            .collect::<Vec<_>>();
        let retiring = deadlines.iter().try_fold(0_usize, |total, deadline| {
            total
                .checked_add(self.expiry_index.get(deadline).map_or(0, BTreeSet::len))
                .ok_or(Error::ArithmeticOverflow)
        })?;
        self.ensure_retirement_capacity(retiring)?;
        let mut expired = 0;""",
)
replace_once(
    path,
    """            .map(|grant| grant.allocation_id.clone())
            .collect::<Vec<_>>();
        for allocation_id in allocation_ids {""",
    """            .map(|grant| grant.allocation_id.clone())
            .collect::<Vec<_>>();
        self.ensure_retirement_capacity(allocation_ids.len())?;
        for allocation_id in allocation_ids {""",
)
replace_once(
    path,
    """    ) -> Result<(), Error> {
        self.history.push_back(GrantHistoryRecord {
            grant,
            terminal_reason,
            terminal_at_ms,
        });""",
    """    ) -> Result<(), Error> {
        if !self
            .retired_allocation_ids
            .insert(grant.allocation_id.clone())
        {
            return Err(Error::CorruptSnapshot);
        }
        self.history.push_back(GrantHistoryRecord {
            grant,
            terminal_reason,
            terminal_at_ms,
        });""",
)
replace_once(
    path,
    """    fn terminal_lookup_error(&self, allocation_id: &str) -> Error {
        self.history
            .iter()
            .rev()
            .find(|record| record.grant.allocation_id == allocation_id)
            .map_or(Error::AllocationNotFound, |record| {
                match record.terminal_reason {
                    GrantTerminalReason::Revoked => Error::Revoked,
                    GrantTerminalReason::Expired | GrantTerminalReason::HostGenerationReplaced => {
                        Error::StaleLease
                    }
                }
            })
    }""",
    """    fn terminal_lookup_error(&self, allocation_id: &str) -> Error {
        if let Some(record) = self
            .history
            .iter()
            .rev()
            .find(|record| record.grant.allocation_id == allocation_id)
        {
            return match record.terminal_reason {
                GrantTerminalReason::Revoked => Error::Revoked,
                GrantTerminalReason::Expired | GrantTerminalReason::HostGenerationReplaced => {
                    Error::StaleLease
                }
            };
        }
        if self.retired_allocation_ids.contains(allocation_id) {
            Error::StaleLease
        } else {
            Error::AllocationNotFound
        }
    }""",
)
replace_once(
    path,
    """    fn insert_expiry(&mut self, grant: &AllocationGrant) {""",
    """    fn ensure_retirement_capacity(&self, additional: usize) -> Result<(), Error> {
        check_retirement_capacity(self.retired_allocation_ids.len(), additional)
    }

    fn insert_expiry(&mut self, grant: &AllocationGrant) {""",
)
replace_once(
    path,
    """fn validate_history(
    history: &VecDeque<GrantHistoryRecord>,
    active: &BTreeMap<String, AllocationGrant>,
) -> Result<(), Error> {""",
    """fn check_retirement_capacity(current: usize, additional: usize) -> Result<(), Error> {
    let total = current
        .checked_add(additional)
        .ok_or(Error::RetiredGrantCapacityExceeded)?;
    if total > MAX_RETIRED_ALLOCATION_IDS {
        return Err(Error::RetiredGrantCapacityExceeded);
    }
    Ok(())
}

fn validate_retired_identities(
    retired: &BTreeSet<String>,
    history: &VecDeque<GrantHistoryRecord>,
    active: &BTreeMap<String, AllocationGrant>,
    compacted_history_records: u64,
) -> Result<(), Error> {
    if retired.len() > MAX_RETIRED_ALLOCATION_IDS {
        return Err(Error::CorruptSnapshot);
    }
    let retained_history =
        u64::try_from(history.len()).map_err(|_| Error::ArithmeticOverflow)?;
    let retired_count = u64::try_from(retired.len()).map_err(|_| Error::ArithmeticOverflow)?;
    if compacted_history_records
        .checked_add(retained_history)
        .ok_or(Error::ArithmeticOverflow)?
        != retired_count
    {
        return Err(Error::CorruptSnapshot);
    }
    for allocation_id in retired {
        validate_identity(allocation_id, "retired allocation")
            .map_err(|_| Error::CorruptSnapshot)?;
        if active.contains_key(allocation_id) {
            return Err(Error::CorruptSnapshot);
        }
    }
    for (allocation_id, grant) in active {
        if allocation_id != &grant.allocation_id {
            return Err(Error::CorruptSnapshot);
        }
    }
    if history
        .iter()
        .any(|record| !retired.contains(&record.grant.allocation_id))
    {
        return Err(Error::CorruptSnapshot);
    }
    Ok(())
}

fn validate_history(
    history: &VecDeque<GrantHistoryRecord>,
    active: &BTreeMap<String, AllocationGrant>,
) -> Result<(), Error> {""",
)

# Expose the durable tombstone bound through the actual V3/public path.
replace_once(
    "codex-rs/hepta-fleet/src/lease_ledger_v3.rs",
    "pub use core::MAX_HOSTS;\n",
    "pub use core::MAX_HOSTS;\npub use core::MAX_RETIRED_ALLOCATION_IDS;\n",
)
replace_once(
    "codex-rs/hepta-fleet/src/lib.rs",
    "pub use lease_ledger::MAX_HOSTS;\n",
    "pub use lease_ledger::MAX_HOSTS;\npub use lease_ledger::MAX_RETIRED_ALLOCATION_IDS;\n",
)

append_once(
    "codex-rs/hepta-fleet/src/lease_ledger_tests.rs",
    "fn compacted_history_keeps_allocation_identity_retired()",
    r"""
#[test]
fn compacted_history_keeps_allocation_identity_retired() {
    let (clock, mut ledger) = ledger(200);
    let retired = grant("retired", 100, 800);
    ledger.issue(retired.clone()).expect("grant");
    ledger
        .renew_or_revoke(
            "retired",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        )
        .expect("revoke");
    assert_eq!(ledger.compact_history(0).expect("compact"), 1);
    assert!(ledger.snapshot().retired_allocation_ids.contains("retired"));
    assert_eq!(ledger.issue(retired.clone()), Err(Error::Conflict));

    let snapshot = ledger.snapshot();
    let mut reopened = LeaseLedger::from_snapshot(clock, snapshot).expect("restore tombstones");
    assert_eq!(reopened.issue(retired), Err(Error::Conflict));
}

#[test]
fn retired_identity_snapshot_mismatch_is_corruption() {
    let (clock, mut ledger) = ledger(200);
    ledger.issue(grant("retired", 100, 800)).expect("grant");
    ledger
        .renew_or_revoke(
            "retired",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        )
        .expect("revoke");
    let mut snapshot = ledger.snapshot();
    snapshot.retired_allocation_ids.clear();
    assert_eq!(
        LeaseLedger::from_snapshot(clock, snapshot).unwrap_err(),
        Error::CorruptSnapshot
    );
}

#[test]
fn retirement_capacity_fails_closed_before_mutation() {
    assert_eq!(
        check_retirement_capacity(MAX_RETIRED_ALLOCATION_IDS, 1),
        Err(Error::RetiredGrantCapacityExceeded)
    );
    assert_eq!(
        check_retirement_capacity(MAX_RETIRED_ALLOCATION_IDS - 1, 1),
        Ok(())
    );
}
""",
)


# ---------------------------------------------------------------------------
# 3. Durable operation tombstones and commit-bound receipt hashes.
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-fleet/src/durable_owner_core.rs"
replace_once(
    path,
    """pub const DURABLE_FLEET_STATE_SCHEMA_VERSION: u32 = 1;
pub const MAX_DURABLE_OPERATION_RECEIPTS: usize = 16_384;""",
    """pub const DURABLE_FLEET_STATE_SCHEMA_VERSION: u32 = 2;
pub const MAX_DURABLE_OPERATION_RECEIPTS: usize = 16_384;
pub const MAX_COMPACTED_OPERATION_IDS: usize = 1_048_576;""",
)
replace_once(
    path,
    """    pub lease_receipt: Option<LeaseReceipt>,
    pub authority_witness: Option<VerifiedUseTokenWitnessV1>,""",
    """    pub lease_receipt: Option<LeaseReceipt>,
    pub authority_witness: Option<VerifiedUseTokenWitnessV1>,
    pub committed_state_sha256: String,""",
)
replace_once(
    path,
    """    pub fleet_operation_receipts: VecDeque<FleetOperationReceiptV1>,
    pub compacted_operation_receipts: u64,""",
    """    pub fleet_operation_receipts: VecDeque<FleetOperationReceiptV1>,
    pub compacted_operation_index: BTreeMap<String, String>,
    pub compacted_operation_receipts: u64,""",
)
replace_exact_count(
    path,
    """            authority_witness: None,
        };""",
    """            authority_witness: None,
            committed_state_sha256: String::new(),
        };""",
    4,
)
replace_once(
    path,
    """            authority_witness: Some(witness.clone()),
        };""",
    """            authority_witness: Some(witness.clone()),
            committed_state_sha256: String::new(),
        };""",
)
replace_once(
    path,
    """        fleet_operation_receipts: VecDeque::new(),
        compacted_operation_receipts: 0,""",
    """        fleet_operation_receipts: VecDeque::new(),
        compacted_operation_index: BTreeMap::new(),
        compacted_operation_receipts: 0,""",
)
replace_once(
    path,
    """        || state.fleet_operation_receipts.len() > MAX_DURABLE_OPERATION_RECEIPTS
        || !valid_digest(&state.previous_state_sha256)""",
    """        || state.fleet_operation_receipts.len() > MAX_DURABLE_OPERATION_RECEIPTS
        || state.compacted_operation_index.len() > MAX_COMPACTED_OPERATION_IDS
        || !valid_digest(&state.previous_state_sha256)""",
)
replace_once(
    path,
    """        if !valid_digest(&receipt.operation_digest)
            || receipt.committed_generation == 0
            || receipt.committed_generation > state.generation
            || !operation_ids.insert(receipt.operation_id.as_str())""",
    """        if !valid_digest(&receipt.operation_digest)
            || !valid_digest(&receipt.committed_state_sha256)
            || receipt.committed_generation == 0
            || receipt.committed_generation > state.generation
            || state
                .compacted_operation_index
                .contains_key(&receipt.operation_id)
            || !operation_ids.insert(receipt.operation_id.as_str())""",
)
replace_once(
    path,
    """    if let Some(snapshot) = &state.fleet_revocation_frontier {""",
    """    let compacted_count = u64::try_from(state.compacted_operation_index.len())
        .map_err(|_| DurableFleetError::ArithmeticOverflow)?;
    if compacted_count != state.compacted_operation_receipts {
        return Err(DurableFleetError::CorruptState);
    }
    for (operation_id, operation_digest) in &state.compacted_operation_index {
        validate_operation_id(operation_id)?;
        if !valid_digest(operation_digest) || operation_ids.contains(operation_id.as_str()) {
            return Err(DurableFleetError::CorruptState);
        }
    }
    if let Some(snapshot) = &state.fleet_revocation_frontier {""",
)
replace_once(
    path,
    """fn append_operation(
    state: &mut DurableFleetStateV1,
    operation: FleetOperationReceiptV1,
) -> Result<(), DurableFleetError> {
    state.fleet_operation_receipts.push_back(operation);
    while state.fleet_operation_receipts.len() > MAX_DURABLE_OPERATION_RECEIPTS {
        let removed = state
            .fleet_operation_receipts
            .pop_front()
            .ok_or(DurableFleetError::CorruptState)?;
        let encoded = serde_json::to_vec(&removed)?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.fleet.operation-receipt-chain.v1\0");
        digest.update(state.compacted_operation_receipts_sha256.as_bytes());
        digest.update(encoded);
        state.compacted_operation_receipts_sha256 = format!("{:x}", digest.finalize());
        state.compacted_operation_receipts = state
            .compacted_operation_receipts
            .checked_add(1)
            .ok_or(DurableFleetError::ArithmeticOverflow)?;
    }
    Ok(())
}""",
    """fn append_operation(
    state: &mut DurableFleetStateV1,
    operation: FleetOperationReceiptV1,
) -> Result<(), DurableFleetError> {
    if state
        .compacted_operation_index
        .contains_key(&operation.operation_id)
    {
        return Err(DurableFleetError::CorruptState);
    }
    state.fleet_operation_receipts.push_back(operation);
    while state.fleet_operation_receipts.len() > MAX_DURABLE_OPERATION_RECEIPTS {
        let removed = state
            .fleet_operation_receipts
            .pop_front()
            .ok_or(DurableFleetError::CorruptState)?;
        if state.compacted_operation_index.len() >= MAX_COMPACTED_OPERATION_IDS {
            return Err(DurableFleetError::OperationHistoryCapacityExceeded);
        }
        if state
            .compacted_operation_index
            .insert(
                removed.operation_id.clone(),
                removed.operation_digest.clone(),
            )
            .is_some()
        {
            return Err(DurableFleetError::CorruptState);
        }
        let encoded = serde_json::to_vec(&removed)?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.fleet.operation-receipt-chain.v1\0");
        digest.update(state.compacted_operation_receipts_sha256.as_bytes());
        digest.update(encoded);
        state.compacted_operation_receipts_sha256 = format!("{:x}", digest.finalize());
        state.compacted_operation_receipts = state
            .compacted_operation_receipts
            .checked_add(1)
            .ok_or(DurableFleetError::ArithmeticOverflow)?;
    }
    Ok(())
}""",
)
replace_once(
    path,
    """            Some(_) => Err(DurableFleetError::OperationConflict(
                operation_id.to_string(),
            )),
            None => Ok(None),
        }""",
    """            Some(_) => Err(DurableFleetError::OperationConflict(
                operation_id.to_string(),
            )),
            None => match self.state.compacted_operation_index.get(operation_id) {
                Some(compacted_digest) if compacted_digest == operation_digest => {
                    Err(DurableFleetError::OperationReceiptCompacted(
                        operation_id.to_string(),
                    ))
                }
                Some(_) => Err(DurableFleetError::OperationConflict(
                    operation_id.to_string(),
                )),
                None => Ok(None),
            },
        }""",
)
replace_once(
    path,
    """            generation: operation.committed_generation,
            state_sha256: self.state.content_sha256.clone(),
            operation,""",
    """            generation: operation.committed_generation,
            state_sha256: operation.committed_state_sha256.clone(),
            operation,""",
)
replace_once(
    path,
    """        mut candidate: DurableFleetStateV1,
        operation: FleetOperationReceiptV1,""",
    """        mut candidate: DurableFleetStateV1,
        mut operation: FleetOperationReceiptV1,""",
)
replace_once(
    path,
    """        candidate.content_sha256.clear();
        candidate.content_sha256 = state_digest(&candidate)?;
        validate_state(&candidate, Arc::clone(&self.clock))?;""",
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
)
replace_once(
    path,
    """        generation: operation.committed_generation,
        state_sha256: state.content_sha256.clone(),
        lease,""",
    """        generation: operation.committed_generation,
        state_sha256: operation.committed_state_sha256.clone(),
        lease,""",
)
replace_once(
    path,
    """    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;""",
    """    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    for receipt in &mut candidate.fleet_operation_receipts {
        receipt.committed_state_sha256.clear();
    }
    let encoded = serde_json::to_vec(&candidate)?;""",
)
replace_once(
    path,
    """    OperationConflict(String),
    IndeterminateCommit {""",
    """    OperationConflict(String),
    OperationReceiptCompacted(String),
    OperationHistoryCapacityExceeded,
    IndeterminateCommit {""",
)
replace_once(
    path,
    """        candidate.fleet_revocation_frontier = Some(snapshot);""",
    """        snapshot.validate_successor(candidate.fleet_revocation_frontier.as_ref())?;
        candidate.fleet_revocation_frontier = Some(snapshot);""",
)

# The frontier re-hashes the same serialized state and must use identical
# normalization for commit-bound receipt hashes.
replace_once(
    "codex-rs/hepta-fleet/src/durable_owner_frontier.rs",
    """    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;""",
    """    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    for receipt in &mut candidate.fleet_operation_receipts {
        receipt.committed_state_sha256.clear();
    }
    let encoded = serde_json::to_vec(&candidate)?;""",
)
replace_once(
    "codex-rs/hepta-fleet/src/durable_owner_frontier.rs",
    "pub use core::MAX_DURABLE_OPERATION_RECEIPTS;\n",
    "pub use core::MAX_DURABLE_OPERATION_RECEIPTS;\npub use core::MAX_COMPACTED_OPERATION_IDS;\n",
)
replace_once(
    "codex-rs/hepta-fleet/src/lib.rs",
    "pub use durable_owner::MAX_DURABLE_OPERATION_RECEIPTS;\n",
    "pub use durable_owner::MAX_DURABLE_OPERATION_RECEIPTS;\n"
    "pub use durable_owner::MAX_COMPACTED_OPERATION_IDS;\n",
)

# Idempotent convenience functions must not re-run a compacted operation ID.
path = "codex-rs/hepta-fleet/src/durable_command_port.rs"
replace_once(
    path,
    """    owner.metrics()?;
    let Some(operation) = owner""",
    """    owner.metrics()?;
    if owner
        .state()
        .compacted_operation_index
        .contains_key(operation_id)
    {
        return Err(DurableFleetError::OperationReceiptCompacted(
            operation_id.to_string(),
        ));
    }
    let Some(operation) = owner""",
)
replace_once(
    path,
    """        state_sha256: owner.state().content_sha256.clone(),""",
    """        state_sha256: operation.committed_state_sha256.clone(),""",
)

# Existing issue replay must return the hash of its original committed state,
# even after later generations advance the owner.
replace_once(
    "codex-rs/hepta-fleet/src/durable_owner_tests.rs",
    """    let duplicate = reopened
        .issue_with_authority("operation-one", &port, "fleet-issue-one", 1, grant)
        .expect("idempotent duplicate");
    assert_eq!(duplicate.generation, issued.generation);""",
    """    reopened
        .refresh_capacity("capacity-two", &FixedObserver)
        .expect("advance durable generation");
    let duplicate = reopened
        .issue_with_authority("operation-one", &port, "fleet-issue-one", 1, grant)
        .expect("idempotent duplicate");
    assert_eq!(duplicate.generation, issued.generation);
    assert_eq!(duplicate.state_sha256, issued.state_sha256);
    assert_ne!(duplicate.state_sha256, reopened.state().content_sha256);""",
)

append_once(
    "codex-rs/hepta-fleet/src/durable_owner_tests.rs",
    "fn compacted_operation_ids_never_reenter_execution()",
    r"""
#[test]
fn compacted_operation_ids_never_reenter_execution() {
    let mut state = initial_state("1".repeat(64));
    let first_operation_id = "operation-0".to_string();
    let first_digest =
        operation_digest(b"test", &(&first_operation_id, 0_usize)).expect("digest");
    for index in 0..=MAX_DURABLE_OPERATION_RECEIPTS {
        let operation_id = format!("operation-{index}");
        let digest = operation_digest(b"test", &(&operation_id, index)).expect("digest");
        append_operation(
            &mut state,
            FleetOperationReceiptV1 {
                operation_id,
                operation_kind: FleetOperationKindV1::ExpiryReconciliation,
                operation_digest: digest,
                committed_generation: 1,
                committed_at_ms: 1,
                lease_receipt: None,
                authority_witness: None,
                committed_state_sha256: "2".repeat(64),
            },
        )
        .expect("append bounded operation");
    }
    assert_eq!(
        state.compacted_operation_index.get("operation-0"),
        Some(&first_digest)
    );

    let directory = tempfile::tempdir().expect("tempdir");
    let owner = DurableFleetOwner {
        root: directory.path().join("owner"),
        supervisor_state_root: directory.path().join("state"),
        clock: Arc::new(ManualClock::new(1)),
        state,
        counters: RuntimeCounters::default(),
    };
    assert!(matches!(
        owner.existing_operation("operation-0", &first_digest),
        Err(DurableFleetError::OperationReceiptCompacted(operation_id))
            if operation_id == "operation-0"
    ));
    assert!(matches!(
        owner.existing_operation("operation-0", &"3".repeat(64)),
        Err(DurableFleetError::OperationConflict(operation_id))
            if operation_id == "operation-0"
    ));
}
""",
)


# ---------------------------------------------------------------------------
# 4. Monotonic durable revocation evidence and exact final-use rejection.
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-fleet/src/revocation_snapshot.rs"
replace_once(
    path,
    """use codex_hepta_contracts::SignedFinalUseRevocationAck;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;""",
    """use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::MAX_REVOCATION_FEED_LIFETIME_MS;
use codex_hepta_contracts::SignedFinalUseRevocationAck;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;""",
)
replace_once(
    path,
    """use std::fmt;
use std::sync::Arc;""",
    """use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;""",
)
replace_once(
    path,
    """    pub fn validate_shape(&self) -> Result<(), FleetRevocationSnapshotError> {
        if self.schema_version != FLEET_REVOCATION_SNAPSHOT_SCHEMA_VERSION
            || self.convergence_sla_ms == 0
            || self.acknowledgements.len() > MAX_FLEET_REVOCATION_NODES
            || (self.current_update.is_none() && !self.acknowledgements.is_empty())
        {
            return Err(FleetRevocationSnapshotError::InvalidShape);
        }
        Ok(())
    }""",
    """    pub fn validate_shape(&self) -> Result<(), FleetRevocationSnapshotError> {
        if self.schema_version != FLEET_REVOCATION_SNAPSHOT_SCHEMA_VERSION
            || self.convergence_sla_ms == 0
            || self.convergence_sla_ms > MAX_REVOCATION_FEED_LIFETIME_MS
            || self.acknowledgements.len() > MAX_FLEET_REVOCATION_NODES
            || (self.current_update.is_none() && !self.acknowledgements.is_empty())
        {
            return Err(FleetRevocationSnapshotError::InvalidShape);
        }
        let mut node_ids = BTreeSet::new();
        if let Some(update) = &self.current_update {
            let update_sha256 = revocation_update_sha256(&update.update)?;
            for acknowledgement in &self.acknowledgements {
                let ack = &acknowledgement.ack;
                if !node_ids.insert(ack.node_id.as_str())
                    || ack.distributor_id != update.update.distributor_id
                    || ack.authority_epoch != update.update.head.authority_epoch
                    || ack.revision != update.update.head.revision
                    || ack.update_sha256 != update_sha256
                {
                    return Err(FleetRevocationSnapshotError::InvalidShape);
                }
            }
        }
        Ok(())
    }

    pub fn validate_successor(
        &self,
        previous: Option<&Self>,
    ) -> Result<(), FleetRevocationSnapshotError> {
        self.validate_shape()?;
        let Some(previous) = previous else {
            return Ok(());
        };
        previous.validate_shape()?;
        if self.convergence_sla_ms != previous.convergence_sla_ms {
            return Err(FleetRevocationSnapshotError::ConflictingEvidence);
        }
        let (Some(old), Some(new)) = (&previous.current_update, &self.current_update) else {
            return if previous.current_update.is_some() {
                Err(FleetRevocationSnapshotError::Rollback)
            } else {
                Ok(())
            };
        };
        let old_head = &old.update.head;
        let new_head = &new.update.head;
        if new_head.authority_epoch < old_head.authority_epoch
            || (new_head.authority_epoch == old_head.authority_epoch
                && new_head.revision < old_head.revision)
        {
            return Err(FleetRevocationSnapshotError::Rollback);
        }
        if new_head.authority_epoch == old_head.authority_epoch
            && !new_head
                .revoked_grant_ids
                .is_superset(&old_head.revoked_grant_ids)
        {
            return Err(FleetRevocationSnapshotError::Rollback);
        }
        if new_head.authority_epoch == old_head.authority_epoch
            && new_head.revision == old_head.revision
        {
            if new != old {
                return Err(FleetRevocationSnapshotError::ConflictingEvidence);
            }
            let new_acks = self
                .acknowledgements
                .iter()
                .map(|ack| (ack.ack.node_id.as_str(), ack))
                .collect::<BTreeMap<_, _>>();
            for old_ack in &previous.acknowledgements {
                if new_acks.get(old_ack.ack.node_id.as_str()).copied() != Some(old_ack) {
                    return Err(FleetRevocationSnapshotError::Rollback);
                }
            }
        }
        Ok(())
    }""",
)
replace_once(
    path,
    """#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetRevocationSnapshotError {
    InvalidShape,
    Encoding,""",
    """fn revocation_update_sha256(
    update: &FinalUseRevocationUpdate,
) -> Result<[u8; 32], FleetRevocationSnapshotError> {
    let encoded = update
        .signing_bytes()
        .map_err(|_| FleetRevocationSnapshotError::Encoding)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.kernel.authority.revocation-update-digest.v1\0");
    digest.update(encoded);
    Ok(digest.finalize().into())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetRevocationSnapshotError {
    InvalidShape,
    Rollback,
    ConflictingEvidence,
    Encoding,""",
)
append_once(
    path,
    "fn stale_or_weakened_revocation_snapshots_are_rejected()",
    r"""
#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_contracts::FinalUseRevocationAck;
    use codex_hepta_contracts::FinalUseRevocations;

    fn update(
        authority_epoch: u64,
        revision: u64,
        revoked: &[&str],
    ) -> SignedFinalUseRevocationUpdate {
        let update = FinalUseRevocationUpdate::new(
            "distributor".into(),
            FinalUseRevocations {
                authority_epoch,
                revision,
                revoked_grant_ids: revoked.iter().map(|value| (*value).to_string()).collect(),
            },
            1_000,
            10_000,
        );
        SignedFinalUseRevocationUpdate {
            signature: vec![7; 64],
            update,
        }
    }

    fn ack(update: &SignedFinalUseRevocationUpdate) -> SignedFinalUseRevocationAck {
        SignedFinalUseRevocationAck {
            signature: vec![8; 64],
            ack: FinalUseRevocationAck {
                schema_version: 1,
                node_id: "node-a".into(),
                distributor_id: update.update.distributor_id.clone(),
                authority_epoch: update.update.head.authority_epoch,
                revision: update.update.head.revision,
                update_sha256: revocation_update_sha256(&update.update).expect("digest"),
                applied_at_unix_ms: 2_000,
            },
        }
    }

    fn snapshot(update: SignedFinalUseRevocationUpdate, with_ack: bool) -> FleetRevocationSnapshotV1 {
        let acknowledgements = if with_ack {
            vec![ack(&update)]
        } else {
            Vec::new()
        };
        FleetRevocationSnapshotV1 {
            schema_version: FLEET_REVOCATION_SNAPSHOT_SCHEMA_VERSION,
            convergence_sla_ms: 1_000,
            current_update: Some(update),
            acknowledgements,
        }
    }

    #[test]
    fn stale_or_weakened_revocation_snapshots_are_rejected() {
        let previous = snapshot(update(7, 3, &["grant-a", "grant-b"]), true);
        assert_eq!(
            snapshot(update(7, 2, &["grant-a", "grant-b"]), false)
                .validate_successor(Some(&previous)),
            Err(FleetRevocationSnapshotError::Rollback)
        );
        assert_eq!(
            snapshot(update(7, 4, &["grant-a"]), false)
                .validate_successor(Some(&previous)),
            Err(FleetRevocationSnapshotError::Rollback)
        );
    }

    #[test]
    fn same_head_cannot_drop_acknowledgement_evidence() {
        let signed = update(7, 3, &["grant-a"]);
        let previous = snapshot(signed.clone(), true);
        let successor = snapshot(signed, false);
        assert_eq!(
            successor.validate_successor(Some(&previous)),
            Err(FleetRevocationSnapshotError::Rollback)
        );
    }

    #[test]
    fn strictly_newer_monotonic_head_is_accepted() {
        let previous = snapshot(update(7, 3, &["grant-a"]), true);
        let successor = snapshot(update(7, 4, &["grant-a", "grant-b"]), false);
        assert_eq!(successor.validate_successor(Some(&previous)), Ok(()));
    }
}
""",
)

path = "codex-rs/hepta-fleet/src/final_use.rs"
replace_once(
    path,
    """    let grant = owner
        .verify_final_use(""",
    """    let current_update = snapshot
        .current_update
        .as_ref()
        .ok_or(FleetFinalUseError::RevocationUpdateMissing)?;
    let grant = owner
        .verify_final_use(""",
)
replace_once(
    path,
    """        )
        .map_err(FleetFinalUseError::Durable)?;

    // Reopen the owner generation after grant verification.""",
    """        )
        .map_err(FleetFinalUseError::Durable)?;
    validate_grant_revocation_binding(
        &grant,
        status.authority_epoch,
        &current_update.update.head.revoked_grant_ids,
    )?;

    // Reopen the owner generation after grant verification.""",
)
replace_once(
    path,
    """#[derive(Debug)]
pub enum FleetFinalUseError {
    RevocationSnapshotMissing,""",
    """fn validate_grant_revocation_binding(
    grant: &GrantUseWitnessV1,
    revocation_authority_epoch: u64,
    revoked_grant_ids: &std::collections::BTreeSet<String>,
) -> Result<(), FleetFinalUseError> {
    if grant.authority_epoch != revocation_authority_epoch {
        return Err(FleetFinalUseError::AuthorityEpochMismatch {
            grant: grant.authority_epoch,
            revocation: revocation_authority_epoch,
        });
    }
    if revoked_grant_ids.contains(&grant.allocation_id) {
        return Err(FleetFinalUseError::GrantRevoked);
    }
    Ok(())
}

#[derive(Debug)]
pub enum FleetFinalUseError {
    RevocationSnapshotMissing,
    RevocationUpdateMissing,
    GrantRevoked,
    AuthorityEpochMismatch { grant: u64, revocation: u64 },""",
)
append_once(
    path,
    "fn revoked_grant_is_denied_after_authenticated_snapshot_restore()",
    r"""
#[cfg(test)]
mod binding_tests {
    use super::*;
    use std::collections::BTreeSet;

    fn witness(authority_epoch: u64) -> GrantUseWitnessV1 {
        GrantUseWitnessV1 {
            allocation_id: "allocation-one".into(),
            principal_id: "agent-one".into(),
            host_id: "host-one".into(),
            host_generation: 1,
            lease_generation: 1,
            authority_epoch,
            verified_at_ms: 1_000,
            expires_at_ms: 2_000,
            semantic_digest: "1".repeat(64),
            resource_digest: "2".repeat(64),
        }
    }

    #[test]
    fn revoked_grant_is_denied_after_authenticated_snapshot_restore() {
        assert!(matches!(
            validate_grant_revocation_binding(
                &witness(7),
                7,
                &BTreeSet::from(["allocation-one".to_string()]),
            ),
            Err(FleetFinalUseError::GrantRevoked)
        ));
    }

    #[test]
    fn grant_epoch_must_match_current_revocation_epoch() {
        assert!(matches!(
            validate_grant_revocation_binding(&witness(6), 7, &BTreeSet::new()),
            Err(FleetFinalUseError::AuthorityEpochMismatch {
                grant: 6,
                revocation: 7
            })
        ));
    }
}
""",
)

print("runtime.fleet hardening patches applied")
