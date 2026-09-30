//! Explicit type boundary for caller-supplied transient snapshots.
//!
//! A locally consistent [`CognitiveSnapshot`] is not proof of source ownership,
//! caller access, completeness, freshness or revocation state. Product callers
//! must use an owner-acquired cut and perform final-use revalidation. This
//! wrapper makes that limitation visible in the type system while preserving
//! the compatibility projection functions.

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_types::AuthorityPosture;

use crate::Error;
use crate::ReadIdsError;
use crate::ReadIdsRequestV1;
use crate::ReadIdsResultV1;
use crate::read_ids_v1;

#[derive(Clone, Copy, Debug)]
pub struct TransientSnapshotProjectionV1<'a> {
    snapshot: &'a CognitiveSnapshot,
}

impl<'a> TransientSnapshotProjectionV1<'a> {
    pub fn try_new(snapshot: &'a CognitiveSnapshot) -> Result<Self, Error> {
        snapshot
            .validate_integrity()
            .map_err(|_| Error::SnapshotMismatch)?;
        Ok(Self { snapshot })
    }

    #[must_use]
    pub const fn snapshot(&self) -> &'a CognitiveSnapshot {
        self.snapshot
    }

    pub fn read_ids(
        &self,
        request: ReadIdsRequestV1,
    ) -> Result<TransientReadIdsResultV1, ReadIdsError> {
        read_ids_v1(self.snapshot, request).map(TransientReadIdsResultV1)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransientReadIdsResultV1(ReadIdsResultV1);

impl TransientReadIdsResultV1 {
    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    #[must_use]
    pub const fn result(&self) -> &ReadIdsResultV1 {
        &self.0
    }

    #[must_use]
    pub fn into_inner(self) -> ReadIdsResultV1 {
        self.0
    }
}
