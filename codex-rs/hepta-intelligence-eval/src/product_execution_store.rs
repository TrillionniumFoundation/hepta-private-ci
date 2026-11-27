//! Durable original-owner execution storage contract; no evaluation authority.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::error::Error as StdError;
use std::fmt;

pub const MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationExecutionKeyV1 {
    pub plan_id: StableId,
    pub binding_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductEvaluationExecutionStateV1 {
    Pending,
    Completed(Vec<u8>),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductEvaluationExecutionClaimV1 {
    Claimed,
    Existing(ProductEvaluationExecutionStateV1),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationExecutionStoreErrorV1 {
    Missing,
    Conflict,
    Rejected,
    Unavailable,
    Indeterminate,
    Corrupt,
}

impl fmt::Display for ProductEvaluationExecutionStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvaluationExecutionStoreErrorV1 {}

/// The original host's durable execution journal, separate from holdout authority.
/// Claims are linearizable and flushed before returning `Claimed`. A plan ID is
/// unique within the owner's namespace: a changed binding must return Conflict.
/// Completion is immutable and flushed before acknowledgement. Missing, corrupt,
/// rolled-back or indeterminate storage must never be reported as a fresh claim.
/// Implementations retain an independent recovery minimum; an in-memory test
/// implementation does not establish process recovery or independent custody.
pub trait ProductEvaluationExecutionStoreV1 {
    fn claim(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionClaimV1, ProductEvaluationExecutionStoreErrorV1>;

    fn complete(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
        payload: &[u8],
    ) -> Result<(), ProductEvaluationExecutionStoreErrorV1>;

    fn readback(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionStateV1, ProductEvaluationExecutionStoreErrorV1>;
}
