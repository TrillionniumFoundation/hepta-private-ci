//! Finite-horizon, scalar, zero-noise recursive utility. Not a learned FBSDE.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use crate::mul_q32_ties_even;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UtilityEvent {
    pub sequence: u64,
    pub event_digest: Digest32,
    pub preference_digest: Digest32,
    pub instant: FixedQ32,
    pub discount: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecursiveUtilityPath {
    pub objective_digest: Digest32,
    pub episode_digest: Digest32,
    pub coefficient_digest: Digest32,
    pub units_digest: Digest32,
    pub terminal_outcome_digest: Digest32,
    pub terminal: FixedQ32,
    pub lower: FixedQ32,
    pub upper: FixedQ32,
    pub events: Vec<UtilityEvent>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecursiveUtilityReceipt {
    /// U[0] through U[n], including the independently supplied terminal utility.
    pub values: Vec<FixedQ32>,
    pub projection_count: u32,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecursiveUtilityError {
    MissingDigest,
    InvalidBounds,
    Horizon,
    Sequence,
    DuplicateEvent,
    InvalidDiscount,
    Arithmetic,
}

impl fmt::Display for RecursiveUtilityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for RecursiveUtilityError {}

/// U[k] = project(instant[k] + discount[k] * U[k+1]).
///
/// Upstream must authenticate provenance, legal actions and the outcome observer.
/// Byte digests supplied to this pure function do not prove those external facts.
/// No current preference, outcome, selected artifact or objective is mutated.
pub fn evaluate_recursive_utility(
    path: &RecursiveUtilityPath,
) -> Result<RecursiveUtilityReceipt, RecursiveUtilityError> {
    if path.events.is_empty() || path.events.len() > 512 {
        return Err(RecursiveUtilityError::Horizon);
    }
    if path.lower >= path.upper || path.terminal < path.lower || path.terminal > path.upper {
        return Err(RecursiveUtilityError::InvalidBounds);
    }
    let context = [
        path.objective_digest,
        path.episode_digest,
        path.coefficient_digest,
        path.units_digest,
        path.terminal_outcome_digest,
    ];
    if context.iter().any(|digest| digest.is_zero()) {
        return Err(RecursiveUtilityError::MissingDigest);
    }
    let mut seen = BTreeSet::new();
    let mut bytes = b"hepta.ndu.recursive-utility.scalar.q32.v1".to_vec();
    for digest in context {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [path.terminal, path.lower, path.upper] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&(path.events.len() as u64).to_be_bytes());
    for (index, event) in path.events.iter().enumerate() {
        if event.sequence != index as u64 + 1 {
            return Err(RecursiveUtilityError::Sequence);
        }
        if event.event_digest.is_zero() || event.preference_digest.is_zero() {
            return Err(RecursiveUtilityError::MissingDigest);
        }
        if !seen.insert(*event.event_digest.as_array()) {
            return Err(RecursiveUtilityError::DuplicateEvent);
        }
        if event.discount < FixedQ32::ZERO || event.discount > FixedQ32::ONE {
            return Err(RecursiveUtilityError::InvalidDiscount);
        }
        if event.instant < path.lower || event.instant > path.upper {
            return Err(RecursiveUtilityError::InvalidBounds);
        }
        bytes.extend_from_slice(&event.sequence.to_be_bytes());
        bytes.extend_from_slice(event.event_digest.as_array());
        bytes.extend_from_slice(event.preference_digest.as_array());
        bytes.extend_from_slice(&event.instant.raw().to_be_bytes());
        bytes.extend_from_slice(&event.discount.raw().to_be_bytes());
    }
    let mut values = vec![FixedQ32::ZERO; path.events.len() + 1];
    values[path.events.len()] = path.terminal;
    let mut projection_count = 0_u32;
    for (index, event) in path.events.iter().enumerate().rev() {
        let continuation = mul_q32_ties_even(event.discount, values[index + 1])
            .map_err(|_| RecursiveUtilityError::Arithmetic)?;
        let raw = i128::from(event.instant.raw()) + i128::from(continuation.raw());
        let projected = raw.clamp(i128::from(path.lower.raw()), i128::from(path.upper.raw()));
        projection_count += u32::from(raw != projected);
        let value = i64::try_from(projected).map_err(|_| RecursiveUtilityError::Arithmetic)?;
        values[index] = FixedQ32::from_raw(value);
    }
    for value in &values {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&projection_count.to_be_bytes());
    Ok(RecursiveUtilityReceipt {
        values,
        projection_count,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "recursive_tests.rs"]
mod tests;
