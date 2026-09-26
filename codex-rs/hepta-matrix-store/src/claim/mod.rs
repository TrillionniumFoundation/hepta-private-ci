use std::fmt;

use codex_hepta_contracts::Sha256Digest;

use crate::MatrixEventId;
use crate::MatrixTransactionId;
use crate::OutboxRecord;

const CLAIM_TOKEN_BYTES: usize = 32;
const MAX_GRANT_ID_BYTES: usize = 128;

/// An opaque, non-constructible capability for one exact durable outbox lease.
///
/// The random token is never serialized or exposed. The durable store retains
/// only its SHA-256 digest and every production transition compares that digest,
/// the attempt and the lease epoch in one SQLite writer transaction.
pub struct MatrixFencedOutboxClaim {
    record: OutboxRecord,
    token: [u8; CLAIM_TOKEN_BYTES],
    token_sha256: String,
    lease_epoch: u64,
    claimed_at_ms: u64,
    lease_until_ms: u64,
}

impl fmt::Debug for MatrixFencedOutboxClaim {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("MatrixFencedOutboxClaim")
            .field("stable_txn_id", &self.record.stable_txn_id)
            .field("attempt", &self.record.attempts)
            .field("lease_epoch", &self.lease_epoch)
            .field("claimed_at_ms", &self.claimed_at_ms)
            .field("lease_until_ms", &self.lease_until_ms)
            .field("token", &"[REDACTED]")
            .finish()
    }
}

impl MatrixFencedOutboxClaim {
    pub fn record(&self) -> &OutboxRecord {
        &self.record
    }

    pub const fn lease_epoch(&self) -> u64 {
        self.lease_epoch
    }

    pub const fn claimed_at_ms(&self) -> u64 {
        self.claimed_at_ms
    }

    pub const fn lease_until_ms(&self) -> u64 {
        self.lease_until_ms
    }

    fn identity(&self) -> ClaimIdentity<'_> {
        debug_assert_eq!(
            self.token_sha256,
            Sha256Digest::for_bytes(&self.token).as_str()
        );
        ClaimIdentity {
            stable_txn_id: &self.record.stable_txn_id,
            attempt: self.record.attempts,
            lease_epoch: self.lease_epoch,
            token_sha256: &self.token_sha256,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixOutboxAuthorityWitness {
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub grant_id: String,
    pub verified_use_witness_sha256: String,
    pub revocation_head_sha256: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixAttemptFailureClass {
    Retryable,
    RateLimited,
    Dns,
    Tls,
    ConnectTimeout,
    ConnectFailure,
    ReadTimeout,
    ConnectionReset,
    ResponseLost,
    ServerUnavailable,
    Permanent,
    AuthorityDenied,
}

impl MatrixAttemptFailureClass {
    fn as_str(self) -> &'static str {
        match self {
            Self::Retryable => "retryable",
            Self::RateLimited => "rate_limited",
            Self::Dns => "dns",
            Self::Tls => "tls",
            Self::ConnectTimeout => "connect_timeout",
            Self::ConnectFailure => "connect_failure",
            Self::ReadTimeout => "read_timeout",
            Self::ConnectionReset => "connection_reset",
            Self::ResponseLost => "response_lost",
            Self::ServerUnavailable => "server_unavailable",
            Self::Permanent => "permanent",
            Self::AuthorityDenied => "authority_denied",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "retryable" => Some(Self::Retryable),
            "rate_limited" => Some(Self::RateLimited),
            "dns" => Some(Self::Dns),
            "tls" => Some(Self::Tls),
            "connect_timeout" => Some(Self::ConnectTimeout),
            "connect_failure" => Some(Self::ConnectFailure),
            "read_timeout" => Some(Self::ReadTimeout),
            "connection_reset" => Some(Self::ConnectionReset),
            "response_lost" => Some(Self::ResponseLost),
            "server_unavailable" => Some(Self::ServerUnavailable),
            "permanent" => Some(Self::Permanent),
            "authority_denied" => Some(Self::AuthorityDenied),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixDispatchAttemptEventKind {
    Claimed,
    Prepared,
    Authorized,
    Dispatching,
    TransportAccepted,
    Indeterminate,
    RetryScheduled,
    Confirmed,
    Redacted,
    PermanentlyRejected,
    Revoked,
    Canceled,
    Expired,
}

impl MatrixDispatchAttemptEventKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Claimed => "claimed",
            Self::Prepared => "prepared",
            Self::Authorized => "authorized",
            Self::Dispatching => "dispatching",
            Self::TransportAccepted => "transport_accepted",
            Self::Indeterminate => "indeterminate",
            Self::RetryScheduled => "retry_scheduled",
            Self::Confirmed => "confirmed",
            Self::Redacted => "redacted",
            Self::PermanentlyRejected => "permanently_rejected",
            Self::Revoked => "revoked",
            Self::Canceled => "canceled",
            Self::Expired => "expired",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "claimed" => Some(Self::Claimed),
            "prepared" => Some(Self::Prepared),
            "authorized" => Some(Self::Authorized),
            "dispatching" => Some(Self::Dispatching),
            "transport_accepted" => Some(Self::TransportAccepted),
            "indeterminate" => Some(Self::Indeterminate),
            "retry_scheduled" => Some(Self::RetryScheduled),
            "confirmed" => Some(Self::Confirmed),
            "redacted" => Some(Self::Redacted),
            "permanently_rejected" => Some(Self::PermanentlyRejected),
            "revoked" => Some(Self::Revoked),
            "canceled" => Some(Self::Canceled),
            "expired" => Some(Self::Expired),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchAttemptEvent {
    pub event_seq: u64,
    pub stable_txn_id: MatrixTransactionId,
    pub attempt: u64,
    pub lease_epoch: u64,
    pub event_kind: MatrixDispatchAttemptEventKind,
    pub failure_class: Option<MatrixAttemptFailureClass>,
    pub retry_after_ms: Option<u64>,
    pub event_id: Option<MatrixEventId>,
    pub detail_sha256: Option<String>,
    pub recorded_at_ms: u64,
}

#[derive(Clone, Copy)]
pub(super) struct ClaimIdentity<'a> {
    pub(super) stable_txn_id: &'a MatrixTransactionId,
    pub(super) attempt: u64,
    pub(super) lease_epoch: u64,
    pub(super) token_sha256: &'a str,
}

mod sql;
mod store;
