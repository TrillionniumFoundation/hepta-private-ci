//! Deterministic V15 migration transition kernel; no I/O and no authority grant.
//!
//! Control must call this under its authoritative transaction after signature,
//! source freshness, component-byte and request-binding verification. A returned
//! state is a proposal; it cannot authorize effects until that transaction commits.
//! Full V15 publication, reshape, durable deduplication and recovery are external.

use std::collections::BTreeMap;

pub type Identity = [u8; 32];
pub type Digest = [u8; 32];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellPhase {
    Active,
    Prepared,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TransferPhase {
    Prepared,
    Ready,
    Committed,
    Aborted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Sources {
    Current,
    Stale,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Cell {
    pub id: String,
    pub owner: Identity,
    pub epoch: u64,
    pub bundle: Digest,
    pub phase: CellPhase,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Transfer {
    pub cell: String,
    pub source: Identity,
    pub target: Identity,
    pub epoch: u64,
    pub bundle: Digest,
    pub phase: TransferPhase,
    pub recovery_controller: Option<Identity>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct State {
    pub admin: Identity,
    pub cell: Cell,
    pub transfers: BTreeMap<String, Transfer>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Operation {
    Prepare { target: Identity },
    RecoverPrepare { target: Identity },
    Ready { verified_bundle: Digest },
    Commit,
    Abort,
}

#[derive(Clone, Debug)]
pub struct Request {
    pub cell: String,
    pub transfer: String,
    pub actor: Identity,
    pub expected_epoch: u64,
    pub expected_bundle: Digest,
    pub operation: Operation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Rejection {
    InvalidIdentifier,
    WrongActor,
    StaleCell,
    StaleTransfer,
    WrongPhase,
    StaleSources,
    SameOwner,
    DuplicateTransfer,
    UnknownTransfer,
    WrongBundle,
    EpochExhausted,
}

// V15 persists signed integers in SQLite. Never wrap or let SQLite promote a
// saturated counter to REAL; a native transition must remain representable.
const MAX_EPOCH: u64 = i64::MAX as u64;

fn next_epoch(epoch: u64) -> Result<u64, Rejection> {
    if epoch == 0 || epoch >= MAX_EPOCH {
        Err(Rejection::EpochExhausted)
    } else {
        Ok(epoch + 1)
    }
}

/// Validate one transition against a complete current cut without modifying it.
/// The caller persists both returned cell and transfer rows in one transaction.
pub fn transition(state: &State, request: &Request, sources: Sources) -> Result<State, Rejection> {
    if request.cell.is_empty() || request.transfer.is_empty() || request.transfer.len() > 128 {
        return Err(Rejection::InvalidIdentifier);
    }
    if request.cell != state.cell.id {
        return Err(Rejection::StaleCell);
    }
    let cell = &state.cell;
    let mut proposed = state.clone();
    match request.operation {
        Operation::Prepare { target } | Operation::RecoverPrepare { target } => {
            let recovery = matches!(request.operation, Operation::RecoverPrepare { .. });
            let authorizer = if recovery { state.admin } else { cell.owner };
            if request.actor != authorizer {
                return Err(Rejection::WrongActor);
            }
            if (request.expected_epoch, request.expected_bundle) != (cell.epoch, cell.bundle) {
                return Err(Rejection::StaleCell);
            }
            if cell.phase != CellPhase::Active {
                return Err(Rejection::WrongPhase);
            }
            if sources != Sources::Current {
                return Err(Rejection::StaleSources);
            }
            if target == cell.owner {
                return Err(Rejection::SameOwner);
            }
            if state.transfers.contains_key(&request.transfer) {
                return Err(Rejection::DuplicateTransfer);
            }
            let epoch = next_epoch(cell.epoch)?;
            next_epoch(epoch)?; // Reserve a terminal commit/abort increment.
            proposed.cell.epoch = epoch;
            proposed.cell.phase = CellPhase::Prepared;
            proposed.transfers.insert(
                request.transfer.clone(),
                Transfer {
                    cell: cell.id.clone(),
                    source: cell.owner,
                    target,
                    epoch,
                    bundle: cell.bundle,
                    phase: TransferPhase::Prepared,
                    recovery_controller: recovery.then_some(state.admin),
                },
            );
        }
        Operation::Ready { .. } | Operation::Commit | Operation::Abort => {
            let transfer = state
                .transfers
                .get(&request.transfer)
                .ok_or(Rejection::UnknownTransfer)?;
            if (
                request.cell.as_str(),
                request.expected_epoch,
                request.expected_bundle,
            ) != (transfer.cell.as_str(), transfer.epoch, transfer.bundle)
            {
                return Err(Rejection::StaleTransfer);
            }
            if (cell.epoch, cell.bundle, cell.phase, cell.owner)
                != (
                    transfer.epoch,
                    transfer.bundle,
                    CellPhase::Prepared,
                    transfer.source,
                )
            {
                return Err(Rejection::StaleCell);
            }
            match request.operation {
                Operation::Abort => {
                    let permitted = match transfer.recovery_controller {
                        Some(controller) => request.actor == controller,
                        None => request.actor == transfer.source || request.actor == state.admin,
                    };
                    if !permitted {
                        return Err(Rejection::WrongActor);
                    }
                    if !matches!(
                        transfer.phase,
                        TransferPhase::Prepared | TransferPhase::Ready
                    ) {
                        return Err(Rejection::WrongPhase);
                    }
                    proposed.cell.epoch = next_epoch(cell.epoch)?;
                    proposed.cell.phase = CellPhase::Active;
                    proposed
                        .transfers
                        .get_mut(&request.transfer)
                        .expect("existing transfer")
                        .phase = TransferPhase::Aborted;
                }
                Operation::Ready { verified_bundle } => {
                    if request.actor != transfer.target {
                        return Err(Rejection::WrongActor);
                    }
                    if transfer.phase != TransferPhase::Prepared {
                        return Err(Rejection::WrongPhase);
                    }
                    if sources != Sources::Current {
                        return Err(Rejection::StaleSources);
                    }
                    if verified_bundle != transfer.bundle {
                        return Err(Rejection::WrongBundle);
                    }
                    proposed
                        .transfers
                        .get_mut(&request.transfer)
                        .expect("existing transfer")
                        .phase = TransferPhase::Ready;
                }
                Operation::Commit => {
                    if request.actor != transfer.target {
                        return Err(Rejection::WrongActor);
                    }
                    if transfer.phase != TransferPhase::Ready {
                        return Err(Rejection::WrongPhase);
                    }
                    if sources != Sources::Current {
                        return Err(Rejection::StaleSources);
                    }
                    proposed.cell.epoch = next_epoch(cell.epoch)?;
                    proposed.cell.owner = transfer.target;
                    proposed.cell.phase = CellPhase::Active;
                    proposed
                        .transfers
                        .get_mut(&request.transfer)
                        .expect("existing transfer")
                        .phase = TransferPhase::Committed;
                }
                Operation::Prepare { .. } | Operation::RecoverPrepare { .. } => unreachable!(),
            }
        }
    }
    Ok(proposed)
}
