//! One bounded historical transport failure. Never execution or Ready authority.

use std::io;
use std::ops::Deref;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use serde::Serialize;
use serde::Serializer;

use crate::model_worker::WorkerRequest;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DiagnosticText<const N: usize> {
    bytes: [u8; N],
    len: usize,
}

impl<const N: usize> DiagnosticText<N> {
    fn prefix(value: &str) -> Self {
        let mut len = value.len().min(N);
        while !value.is_char_boundary(len) {
            len -= 1;
        }
        let mut text = Self { bytes: [0; N], len };
        text.bytes[..len].copy_from_slice(&value.as_bytes()[..len]);
        text
    }
}

impl<const N: usize> Serialize for DiagnosticText<N> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let value =
            std::str::from_utf8(&self.bytes[..self.len]).map_err(serde::ser::Error::custom)?;
        serializer.serialize_str(value)
    }
}

/// Passive fixed-size copy of the original first failure, including closed ports.
/// Missing ID values mean unavailable, never a shortened substitute identifier.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct SmolLmFirstExchangeFailureV1 {
    stage: &'static str,
    io_kind: Option<DiagnosticText<64>>,
    raw_os_error: Option<i32>,
    request_id: Option<DiagnosticText<64>>,
    request_id_bytes: usize,
    #[serde(serialize_with = "serialize_digest")]
    request_id_sha256: Digest32,
    reservation_id: Option<DiagnosticText<64>>,
    reservation_id_bytes: usize,
    #[serde(serialize_with = "serialize_digest")]
    reservation_id_sha256: Digest32,
    admitted_deadline_ms: u64,
    original_error_prefix: DiagnosticText<256>,
    original_error_bytes: usize,
    #[serde(serialize_with = "serialize_digest")]
    original_error_sha256: Digest32,
    original_error_truncated: bool,
    operation_before: FailureClockV1,
    failure_after: FailureClockV1,
}

fn serialize_digest<S: Serializer>(digest: &Digest32, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&digest.to_string())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
struct FailureClockV1 {
    since_exchange_entry_ns: Option<u64>,
    unix_ns: Option<u64>,
    execution_remaining_ns: Option<i64>,
    io_remaining_ns: Option<i64>,
}

#[derive(Clone, Copy)]
pub(super) struct Attempt {
    stage: &'static str,
    instant: Instant,
    unix_ns: Option<u64>,
}

impl Attempt {
    pub(super) fn new(stage: &'static str) -> Self {
        Self {
            stage,
            instant: Instant::now(),
            unix_ns: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .ok()
                .and_then(|value| u64::try_from(value.as_nanos()).ok()),
        }
    }
    fn sample(self) -> (Instant, Option<u64>) {
        (self.instant, self.unix_ns)
    }
    pub(super) fn stage(self, stage: &'static str) -> Self {
        Self { stage, ..self }
    }
    pub(super) fn message(self, original: impl Into<String>) -> ExchangeFailure {
        ExchangeFailure {
            original: original.into(),
            before: self,
            after: Self::new(self.stage).sample(),
            io: None,
        }
    }
    pub(super) fn io(self, error: io::Error) -> ExchangeFailure {
        let after = Self::new(self.stage).sample();
        ExchangeFailure {
            original: error.to_string(),
            before: self,
            after,
            io: Some((error.kind(), error.raw_os_error())),
        }
    }
}

#[derive(Debug)]
pub(super) struct ExchangeFailure {
    original: String,
    before: Attempt,
    after: (Instant, Option<u64>),
    io: Option<(io::ErrorKind, Option<i32>)>,
}

impl std::fmt::Debug for Attempt {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Attempt")
            .field("stage", &self.stage)
            .finish_non_exhaustive()
    }
}

impl Deref for ExchangeFailure {
    type Target = str;
    fn deref(&self) -> &str {
        &self.original
    }
}

impl ExchangeFailure {
    pub(super) fn into_original(self) -> String {
        self.original
    }
}

pub(super) struct FailureRecorder<'a> {
    slot: &'a mut Option<SmolLmFirstExchangeFailureV1>,
    request: &'a WorkerRequest,
    entry: Instant,
    execution_deadline: Instant,
    io_deadline: Option<Instant>,
}

fn remaining(deadline: Instant, observed: Instant) -> Option<i64> {
    if deadline >= observed {
        i64::try_from(deadline.duration_since(observed).as_nanos()).ok()
    } else {
        i64::try_from(observed.duration_since(deadline).as_nanos())
            .ok()?
            .checked_neg()
    }
}

impl<'a> FailureRecorder<'a> {
    pub(super) fn new(
        slot: &'a mut Option<SmolLmFirstExchangeFailureV1>,
        request: &'a WorkerRequest,
        execution_deadline: Instant,
    ) -> Self {
        Self {
            slot,
            request,
            entry: Instant::now(),
            execution_deadline,
            io_deadline: None,
        }
    }
    pub(super) fn io_deadline(&mut self, deadline: Instant) {
        self.io_deadline = Some(deadline);
    }
    pub(super) fn retain(&mut self, failure: ExchangeFailure) -> String {
        if self.slot.is_none() {
            let clock = |(instant, unix_ns): (Instant, Option<u64>)| FailureClockV1 {
                since_exchange_entry_ns: instant
                    .checked_duration_since(self.entry)
                    .and_then(|value| u64::try_from(value.as_nanos()).ok()),
                unix_ns,
                execution_remaining_ns: remaining(self.execution_deadline, instant),
                io_remaining_ns: self
                    .io_deadline
                    .and_then(|deadline| remaining(deadline, instant)),
            };
            *self.slot = Some(SmolLmFirstExchangeFailureV1 {
                stage: failure.before.stage,
                io_kind: failure
                    .io
                    .map(|value| DiagnosticText::prefix(&format!("{:?}", value.0))),
                raw_os_error: failure.io.and_then(|value| value.1),
                request_id: (self.request.request_id.len() <= 64)
                    .then(|| DiagnosticText::prefix(&self.request.request_id)),
                request_id_bytes: self.request.request_id.len(),
                request_id_sha256: Digest32::of_bytes(self.request.request_id.as_bytes()),
                reservation_id: (self.request.reservation_id.len() <= 64)
                    .then(|| DiagnosticText::prefix(&self.request.reservation_id)),
                reservation_id_bytes: self.request.reservation_id.len(),
                reservation_id_sha256: Digest32::of_bytes(self.request.reservation_id.as_bytes()),
                admitted_deadline_ms: self.request.deadline_ms,
                original_error_prefix: DiagnosticText::prefix(&failure.original),
                original_error_bytes: failure.original.len(),
                original_error_sha256: Digest32::of_bytes(failure.original.as_bytes()),
                original_error_truncated: failure.original.len() > 256,
                operation_before: clock(failure.before.sample()),
                failure_after: clock(failure.after),
            });
        }
        failure.into_original()
    }
}

#[cfg(test)]
#[path = "smollm_neural_failure_tests.rs"]
mod tests;
