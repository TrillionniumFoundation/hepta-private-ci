//! Pure, qualification-only H7 policy-feedback and replay oracle.
//!
//! This module deliberately stops at an in-memory typed evidence surface. It
//! does not open a database, call a provider, write the KG, publish an
//! outbox event, or grant production authority.  Callers provide an already
//! materialized action and its causal witness; the module validates the
//! witness, appends idempotently, maintains a conservation-checked credit
//! ledger, and computes a deterministic fixed-point off-policy estimate.
//!
//! The attempt/lease scope is part of every action digest.  An oracle binds
//! its first append to that scope and rejects later records from another
//! attempt, lease, owner epoch, generation, or fencing token.  This is a
//! local replay fence, not a replacement for the durable H7 trajectory store
//! (and in particular does not relax migrations 0008/0009).

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::framing::frame_part;

/// Schema identity for this pure qualification surface.
pub const H7_FEEDBACK_SCHEMA_VERSION: u32 = 1;
/// Namespace is intentionally not a production namespace.
pub const H7_FEEDBACK_NAMESPACE: &str = "local_qualification_only";
/// All authority/effect flags are compile-time false by contract.
pub const H7_FEEDBACK_EXTERNAL_EFFECTS: bool = false;
pub const H7_FEEDBACK_KG_WRITE_AUTHORITY: bool = false;
pub const H7_FEEDBACK_PRODUCTION_CALLER: bool = false;
pub const H7_FEEDBACK_PRODUCTION_AUTHORITY: bool = false;
pub const H7_FEEDBACK_REPLAY_ONLY: bool = true;

/// Fixed-point scale used for probabilities and importance weights.
pub const H7_FEEDBACK_SCALE: u64 = 1_000_000;
/// Reward values are expressed in basis points.
pub const H7_FEEDBACK_BPS_SCALE: i64 = 10_000;
pub const H7_FEEDBACK_DEFAULT_WEIGHT_CAP_SCALED: u64 = 10 * H7_FEEDBACK_SCALE;
pub const H7_FEEDBACK_MAX_WEIGHT_CAP_SCALED: u64 = 100 * H7_FEEDBACK_SCALE;
pub const H7_FEEDBACK_MAX_RECORDS: usize = 1_024;
pub const H7_FEEDBACK_MAX_TEXT_BYTES: usize = 256;
pub const H7_FEEDBACK_MAX_CREDIT_UNITS: i64 = 1_000_000_000_000;

const BINDING_DOMAIN: &[u8] = b"hepta-memory:h7-feedback-binding:v1";
const SCOPE_DOMAIN: &[u8] = b"hepta-memory:h7-feedback-attempt-scope:v1";
const ACTION_DOMAIN: &[u8] = b"hepta-memory:h7-feedback-action:v1";
const RECORD_DOMAIN: &[u8] = b"hepta-memory:h7-feedback-record:v1";
const LEDGER_DOMAIN: &[u8] = b"hepta-memory:h7-feedback-credit-ledger:v1";
const ORACLE_DOMAIN: &[u8] = b"hepta-memory:h7-feedback-oracle:v1";
const EVALUATION_DOMAIN: &[u8] = b"hepta-memory:h7-feedback-evaluation:v1";

/// Errors are intentionally typed so callers can distinguish stale/conflict
/// replay from malformed evidence without consulting a database.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum H7FeedbackError {
    #[error("invalid H7 feedback: {0}")]
    Invalid(String),
    #[error("H7 feedback schema mismatch")]
    SchemaMismatch,
    #[error("{0} digest mismatch")]
    DigestMismatch(&'static str),
    #[error("H7 feedback binding mismatch: {0}")]
    BindingMismatch(&'static str),
    #[error("H7 feedback conflict for key {0}")]
    Conflict(String),
    #[error("H7 feedback record is outside the declared support")]
    OutOfSupport,
    #[error("H7 feedback has zero replay weight")]
    ZeroWeight,
    #[error("H7 feedback contains an external effect")]
    ExternalEffect,
    #[error("H7 feedback requests KG-write authority")]
    KgWriteAuthority,
    #[error("H7 feedback was produced by a production caller")]
    ProductionCaller,
    #[error("H7 feedback is not replay-only")]
    NotReplayOnly,
    #[error("H7 feedback credit total overflowed")]
    CreditOverflow,
    #[error("H7 feedback importance weight overflowed")]
    WeightOverflow,
    #[error("H7 feedback ledger is empty")]
    EmptyLedger,
    #[error("H7 feedback record count exceeds {0}")]
    TooManyRecords(usize),
    #[error("H7 feedback sequence is not contiguous (expected {expected}, got {actual})")]
    NonContiguousSequence { expected: u32, actual: u32 },
}

/// Attempt-scoped lease and compact fencing witness.  These values are
/// compared exactly by [`H7FeedbackOracle`] for every record in one replay
/// stream.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7AttemptLeaseScope {
    pub attempt_id: String,
    pub lease_id: String,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fence_sha256: Sha256Digest,
}

impl H7AttemptLeaseScope {
    pub fn new(
        attempt_id: impl Into<String>,
        lease_id: impl Into<String>,
        owner_epoch: u64,
        generation: u64,
        fence_sha256: Sha256Digest,
    ) -> Result<Self, H7FeedbackError> {
        let scope = Self {
            attempt_id: attempt_id.into(),
            lease_id: lease_id.into(),
            owner_epoch,
            generation,
            fence_sha256,
        };
        scope.validate()?;
        Ok(scope)
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        validate_text(&self.attempt_id, "attempt id")?;
        validate_text(&self.lease_id, "lease id")?;
        if self.owner_epoch == 0 || self.generation == 0 {
            return Err(H7FeedbackError::Invalid(
                "owner epoch and generation must be non-zero".to_string(),
            ));
        }
        validate_digest(&self.fence_sha256, "fencing token")
    }

    fn digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, SCOPE_DOMAIN);
        frame_part(&mut hasher, self.attempt_id.as_bytes());
        frame_part(&mut hasher, self.lease_id.as_bytes());
        frame_part(&mut hasher, &self.owner_epoch.to_be_bytes());
        frame_part(&mut hasher, &self.generation.to_be_bytes());
        frame_part(&mut hasher, self.fence_sha256.as_str().as_bytes());
        Sha256Digest::from_sha256_output(hasher.finalize())
    }
}

/// Immutable causal and digest binding carried by a policy action.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7FeedbackBinding {
    pub trajectory_id: String,
    pub turn_id: String,
    pub scope: H7AttemptLeaseScope,
    pub state_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub model_receipt_digest: Sha256Digest,
}

impl H7FeedbackBinding {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        trajectory_id: impl Into<String>,
        turn_id: impl Into<String>,
        scope: H7AttemptLeaseScope,
        state_digest: Sha256Digest,
        policy_digest: Sha256Digest,
        model_receipt_digest: Sha256Digest,
    ) -> Result<Self, H7FeedbackError> {
        let binding = Self {
            trajectory_id: trajectory_id.into(),
            turn_id: turn_id.into(),
            scope,
            state_digest,
            policy_digest,
            model_receipt_digest,
        };
        binding.validate()?;
        Ok(binding)
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        validate_text(&self.trajectory_id, "trajectory id")?;
        validate_text(&self.turn_id, "turn id")?;
        self.scope.validate()?;
        validate_digest(&self.state_digest, "state")?;
        validate_digest(&self.policy_digest, "policy")?;
        validate_digest(&self.model_receipt_digest, "model receipt")
    }

    fn digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, BINDING_DOMAIN);
        frame_part(&mut hasher, self.trajectory_id.as_bytes());
        frame_part(&mut hasher, self.turn_id.as_bytes());
        frame_part(&mut hasher, self.scope.digest().as_str().as_bytes());
        frame_part(&mut hasher, self.state_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.policy_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.model_receipt_digest.as_str().as_bytes());
        Sha256Digest::from_sha256_output(hasher.finalize())
    }
}

/// A policy action whose digest commits to the exact attempt/lease witness.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7PolicyAction {
    pub action_id: String,
    pub binding: H7FeedbackBinding,
    pub action_digest: Sha256Digest,
    pub external_effect_executed: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
}

impl H7PolicyAction {
    pub fn new(
        action_id: impl Into<String>,
        binding: H7FeedbackBinding,
    ) -> Result<Self, H7FeedbackError> {
        let action = Self {
            action_id: action_id.into(),
            binding,
            action_digest: Sha256Digest::for_bytes(b"uncomputed"),
            external_effect_executed: H7_FEEDBACK_EXTERNAL_EFFECTS,
            kg_write_authority: H7_FEEDBACK_KG_WRITE_AUTHORITY,
            production_caller: H7_FEEDBACK_PRODUCTION_CALLER,
        };
        let action = Self {
            action_digest: action.compute_digest(),
            ..action
        };
        action.validate()?;
        Ok(action)
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        validate_text(&self.action_id, "action id")?;
        self.binding.validate()?;
        authority_flags(
            self.external_effect_executed,
            self.kg_write_authority,
            self.production_caller,
        )?;
        if self.action_digest != self.compute_digest() {
            return Err(H7FeedbackError::DigestMismatch("action"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, H7FeedbackError> {
        self.validate()?;
        Ok(self.action_digest.clone())
    }

    fn compute_digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, ACTION_DOMAIN);
        frame_part(&mut hasher, self.action_id.as_bytes());
        frame_part(&mut hasher, self.binding.digest().as_str().as_bytes());
        frame_part(&mut hasher, &[u8::from(self.external_effect_executed)]);
        frame_part(&mut hasher, &[u8::from(self.kg_write_authority)]);
        frame_part(&mut hasher, &[u8::from(self.production_caller)]);
        Sha256Digest::from_sha256_output(hasher.finalize())
    }
}

/// Fixed-point behavior and target policy propensities.  Values are in
/// `0..=H7_FEEDBACK_SCALE`; no floating point is accepted anywhere in this
/// module.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7Propensity {
    pub behavior_scaled: u64,
    pub target_scaled: u64,
}

impl H7Propensity {
    pub fn new(behavior_scaled: u64, target_scaled: u64) -> Result<Self, H7FeedbackError> {
        let propensity = Self {
            behavior_scaled,
            target_scaled,
        };
        propensity.validate()?;
        Ok(propensity)
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        if self.behavior_scaled == 0 || self.behavior_scaled > H7_FEEDBACK_SCALE {
            return Err(H7FeedbackError::Invalid(format!(
                "behavior propensity must be in 1..={H7_FEEDBACK_SCALE}"
            )));
        }
        if self.target_scaled > H7_FEEDBACK_SCALE {
            return Err(H7FeedbackError::Invalid(format!(
                "target propensity must be in 0..={H7_FEEDBACK_SCALE}"
            )));
        }
        Ok(())
    }

    /// Returns `target / behavior` in the same fixed-point scale, rounded
    /// down deterministically.
    pub fn weight_scaled(&self) -> Result<u64, H7FeedbackError> {
        self.validate()?;
        self.target_scaled
            .checked_mul(H7_FEEDBACK_SCALE)
            .ok_or(H7FeedbackError::WeightOverflow)
            .map(|numerator| numerator / self.behavior_scaled)
    }
}

/// Support-set witness for the selected action.  An unsupported observation
/// may be retained for audit, but offline evaluation rejects it closed.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7Support {
    pub in_support: bool,
    pub support_digest: Sha256Digest,
}

impl H7Support {
    pub fn new(in_support: bool, support_digest: Sha256Digest) -> Result<Self, H7FeedbackError> {
        let support = Self {
            in_support,
            support_digest,
        };
        support.validate()?;
        Ok(support)
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        validate_digest(&self.support_digest, "support")
    }
}

/// Stable replay key for a feedback event.
#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(into = "String", try_from = "String")]
pub struct H7FeedbackKey {
    pub trajectory_id: String,
    pub event_seq: u32,
    pub event_id: String,
}

impl H7FeedbackKey {
    pub fn as_string(&self) -> String {
        format!(
            "{}:{}:{}",
            self.trajectory_id, self.event_seq, self.event_id
        )
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        validate_text(&self.trajectory_id, "feedback key trajectory id")?;
        validate_text(&self.event_id, "feedback key event id")?;
        if self.event_seq == 0 {
            return Err(H7FeedbackError::Invalid(
                "feedback key event sequence must be non-zero".to_string(),
            ));
        }
        Ok(())
    }
}

// JSON object keys must be strings.  Encoding the tuple as one JSON string
// keeps all delimiters in trajectory/event ids unambiguous while preserving a
// stable wire form for snapshots.
impl From<H7FeedbackKey> for String {
    fn from(key: H7FeedbackKey) -> Self {
        serde_json::json!([key.trajectory_id, key.event_seq, key.event_id]).to_string()
    }
}

impl TryFrom<String> for H7FeedbackKey {
    type Error = String;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        let (trajectory_id, event_seq, event_id): (String, u32, String) =
            serde_json::from_str(&value).map_err(|error| error.to_string())?;
        let key = Self {
            trajectory_id,
            event_seq,
            event_id,
        };
        key.validate().map_err(|error| error.to_string())?;
        Ok(key)
    }
}

/// One typed feedback observation.  It is immutable after construction; the
/// digest commits to action identity, causal parent, propensity/support, and
/// credit attribution.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7FeedbackRecord {
    pub trajectory_id: String,
    pub turn_id: String,
    pub event_seq: u32,
    pub event_id: String,
    pub causal_parent_seq: u32,
    pub causal_parent_sha256: Sha256Digest,
    pub action: H7PolicyAction,
    pub propensity: H7Propensity,
    pub support: H7Support,
    pub reward_bps: i32,
    pub credit_units: i64,
    pub safety_ok: bool,
    pub terminal: bool,
    pub external_effect_executed: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub feedback_digest: Sha256Digest,
}

impl H7FeedbackRecord {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        event_seq: u32,
        event_id: impl Into<String>,
        causal_parent_seq: u32,
        causal_parent_sha256: Sha256Digest,
        action: H7PolicyAction,
        propensity: H7Propensity,
        support: H7Support,
        reward_bps: i32,
        credit_units: i64,
        safety_ok: bool,
        terminal: bool,
    ) -> Result<Self, H7FeedbackError> {
        let record = Self {
            trajectory_id: action.binding.trajectory_id.clone(),
            turn_id: action.binding.turn_id.clone(),
            event_seq,
            event_id: event_id.into(),
            causal_parent_seq,
            causal_parent_sha256,
            action,
            propensity,
            support,
            reward_bps,
            credit_units,
            safety_ok,
            terminal,
            external_effect_executed: H7_FEEDBACK_EXTERNAL_EFFECTS,
            kg_write_authority: H7_FEEDBACK_KG_WRITE_AUTHORITY,
            production_caller: H7_FEEDBACK_PRODUCTION_CALLER,
            feedback_digest: Sha256Digest::for_bytes(b"uncomputed"),
        };
        let record = Self {
            feedback_digest: record.compute_digest(),
            ..record
        };
        record.validate()?;
        Ok(record)
    }

    pub fn key(&self) -> H7FeedbackKey {
        H7FeedbackKey {
            trajectory_id: self.trajectory_id.clone(),
            event_seq: self.event_seq,
            event_id: self.event_id.clone(),
        }
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        validate_text(&self.trajectory_id, "feedback trajectory id")?;
        validate_text(&self.turn_id, "feedback turn id")?;
        validate_text(&self.event_id, "feedback event id")?;
        if self.event_seq == 0 || self.causal_parent_seq == 0 {
            return Err(H7FeedbackError::Invalid(
                "feedback and causal-parent sequence must be non-zero".to_string(),
            ));
        }
        if self.causal_parent_seq >= self.event_seq {
            return Err(H7FeedbackError::Invalid(
                "causal parent must precede feedback event".to_string(),
            ));
        }
        validate_digest(&self.causal_parent_sha256, "causal parent")?;
        self.action.validate()?;
        if self.action.binding.trajectory_id != self.trajectory_id {
            return Err(H7FeedbackError::BindingMismatch("trajectory"));
        }
        if self.action.binding.turn_id != self.turn_id {
            return Err(H7FeedbackError::BindingMismatch("turn"));
        }
        self.propensity.validate()?;
        self.support.validate()?;
        if !(-H7_FEEDBACK_BPS_SCALE..=H7_FEEDBACK_BPS_SCALE).contains(&(self.reward_bps as i64)) {
            return Err(H7FeedbackError::Invalid(
                "reward must be within -10000..=10000 bps".to_string(),
            ));
        }
        if self.credit_units.unsigned_abs() > H7_FEEDBACK_MAX_CREDIT_UNITS as u64 {
            return Err(H7FeedbackError::Invalid(
                "credit units exceed the bounded qualification range".to_string(),
            ));
        }
        authority_flags(
            self.external_effect_executed,
            self.kg_write_authority,
            self.production_caller,
        )?;
        if self.feedback_digest != self.compute_digest() {
            return Err(H7FeedbackError::DigestMismatch("feedback"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, H7FeedbackError> {
        self.validate()?;
        Ok(self.feedback_digest.clone())
    }

    fn compute_digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, RECORD_DOMAIN);
        frame_part(&mut hasher, self.trajectory_id.as_bytes());
        frame_part(&mut hasher, self.turn_id.as_bytes());
        frame_part(&mut hasher, &self.event_seq.to_be_bytes());
        frame_part(&mut hasher, self.event_id.as_bytes());
        frame_part(&mut hasher, &self.causal_parent_seq.to_be_bytes());
        frame_part(&mut hasher, self.causal_parent_sha256.as_str().as_bytes());
        frame_part(&mut hasher, self.action.action_digest.as_str().as_bytes());
        frame_part(&mut hasher, &self.propensity.behavior_scaled.to_be_bytes());
        frame_part(&mut hasher, &self.propensity.target_scaled.to_be_bytes());
        frame_part(&mut hasher, &[u8::from(self.support.in_support)]);
        frame_part(&mut hasher, self.support.support_digest.as_str().as_bytes());
        frame_part(&mut hasher, &self.reward_bps.to_be_bytes());
        frame_part(&mut hasher, &self.credit_units.to_be_bytes());
        frame_part(&mut hasher, &[u8::from(self.safety_ok)]);
        frame_part(&mut hasher, &[u8::from(self.terminal)]);
        frame_part(&mut hasher, &[u8::from(self.external_effect_executed)]);
        frame_part(&mut hasher, &[u8::from(self.kg_write_authority)]);
        frame_part(&mut hasher, &[u8::from(self.production_caller)]);
        Sha256Digest::from_sha256_output(hasher.finalize())
    }
}

/// Conservation ledger for feedback credits.  Every key has exactly one
/// credit entry and the total is recomputed on every append/validation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7CreditLedger {
    pub schema_version: u32,
    pub namespace: String,
    pub trajectory_id: String,
    pub entries: BTreeMap<H7FeedbackKey, i64>,
    pub total_credit_units: i64,
    pub ledger_digest: Sha256Digest,
    pub replay_only: bool,
    pub production_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
}

impl H7CreditLedger {
    pub fn new(trajectory_id: impl Into<String>) -> Result<Self, H7FeedbackError> {
        let mut ledger = Self {
            schema_version: H7_FEEDBACK_SCHEMA_VERSION,
            namespace: H7_FEEDBACK_NAMESPACE.to_string(),
            trajectory_id: trajectory_id.into(),
            entries: BTreeMap::new(),
            total_credit_units: 0,
            ledger_digest: Sha256Digest::for_bytes(b"uncomputed"),
            replay_only: H7_FEEDBACK_REPLAY_ONLY,
            production_effects: H7_FEEDBACK_EXTERNAL_EFFECTS,
            kg_write_authority: H7_FEEDBACK_KG_WRITE_AUTHORITY,
            production_caller: H7_FEEDBACK_PRODUCTION_CALLER,
        };
        ledger.ledger_digest = ledger.compute_digest();
        ledger.validate()?;
        Ok(ledger)
    }

    pub fn append(&mut self, key: H7FeedbackKey, credit_units: i64) -> Result<(), H7FeedbackError> {
        // Keep direct ledger users fail-closed and atomic as well as the
        // higher-level oracle.  A pre-existing tamper cannot be repaired by a
        // seemingly harmless append.
        self.validate()?;
        key.validate()?;
        if key.trajectory_id != self.trajectory_id {
            return Err(H7FeedbackError::BindingMismatch("ledger trajectory"));
        }
        if credit_units.unsigned_abs() > H7_FEEDBACK_MAX_CREDIT_UNITS as u64 {
            return Err(H7FeedbackError::Invalid(
                "credit units exceed the bounded qualification range".to_string(),
            ));
        }
        if let Some(existing) = self.entries.get(&key) {
            if *existing == credit_units {
                return Ok(());
            }
            return Err(H7FeedbackError::Conflict(key.as_string()));
        }
        let total = self
            .total_credit_units
            .checked_add(credit_units)
            .ok_or(H7FeedbackError::CreditOverflow)?;
        let mut next = self.clone();
        next.entries.insert(key, credit_units);
        next.total_credit_units = total;
        next.ledger_digest = next.compute_digest();
        next.validate()?;
        *self = next;
        Ok(())
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        if self.schema_version != H7_FEEDBACK_SCHEMA_VERSION
            || self.namespace != H7_FEEDBACK_NAMESPACE
        {
            return Err(H7FeedbackError::SchemaMismatch);
        }
        validate_text(&self.trajectory_id, "ledger trajectory id")?;
        if self.entries.len() > H7_FEEDBACK_MAX_RECORDS {
            return Err(H7FeedbackError::TooManyRecords(H7_FEEDBACK_MAX_RECORDS));
        }
        if !self.replay_only {
            return Err(H7FeedbackError::NotReplayOnly);
        }
        authority_flags(
            self.production_effects,
            self.kg_write_authority,
            self.production_caller,
        )?;
        let mut total = 0_i64;
        for (key, credit) in &self.entries {
            key.validate()?;
            if key.trajectory_id != self.trajectory_id {
                return Err(H7FeedbackError::BindingMismatch("ledger key trajectory"));
            }
            if credit.unsigned_abs() > H7_FEEDBACK_MAX_CREDIT_UNITS as u64 {
                return Err(H7FeedbackError::Invalid(
                    "credit units exceed the bounded qualification range".to_string(),
                ));
            }
            total = total
                .checked_add(*credit)
                .ok_or(H7FeedbackError::CreditOverflow)?;
        }
        if total != self.total_credit_units {
            return Err(H7FeedbackError::BindingMismatch("credit conservation"));
        }
        if self.ledger_digest != self.compute_digest() {
            return Err(H7FeedbackError::DigestMismatch("credit ledger"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, H7FeedbackError> {
        self.validate()?;
        Ok(self.ledger_digest.clone())
    }

    fn compute_digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, LEDGER_DOMAIN);
        frame_part(&mut hasher, &self.schema_version.to_be_bytes());
        frame_part(&mut hasher, self.namespace.as_bytes());
        frame_part(&mut hasher, self.trajectory_id.as_bytes());
        frame_part(&mut hasher, &[u8::from(self.replay_only)]);
        frame_part(&mut hasher, &[u8::from(self.production_effects)]);
        frame_part(&mut hasher, &[u8::from(self.kg_write_authority)]);
        frame_part(&mut hasher, &[u8::from(self.production_caller)]);
        frame_part(&mut hasher, &self.total_credit_units.to_be_bytes());
        frame_part(
            &mut hasher,
            &u64::try_from(self.entries.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for (key, credit) in &self.entries {
            frame_part(&mut hasher, key.trajectory_id.as_bytes());
            frame_part(&mut hasher, &key.event_seq.to_be_bytes());
            frame_part(&mut hasher, key.event_id.as_bytes());
            frame_part(&mut hasher, &credit.to_be_bytes());
        }
        Sha256Digest::from_sha256_output(hasher.finalize())
    }
}

/// Result of an idempotent append.  `Replay` is returned only for a byte-for-
/// byte equal record with the same stable key and digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "result")]
pub enum H7FeedbackAppend {
    Inserted {
        feedback_digest: Sha256Digest,
        ledger_digest: Sha256Digest,
        oracle_digest: Sha256Digest,
    },
    Replay {
        feedback_digest: Sha256Digest,
        ledger_digest: Sha256Digest,
        oracle_digest: Sha256Digest,
    },
}

impl H7FeedbackAppend {
    pub const fn is_replay(&self) -> bool {
        matches!(self, Self::Replay { .. })
    }
}

/// Pure in-memory feedback oracle and credit ledger.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7FeedbackOracle {
    pub schema_version: u32,
    pub namespace: String,
    pub trajectory_id: String,
    pub scope: Option<H7AttemptLeaseScope>,
    pub records: BTreeMap<H7FeedbackKey, H7FeedbackRecord>,
    pub ledger: H7CreditLedger,
    pub replay_only: bool,
    pub production_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub oracle_digest: Sha256Digest,
}

impl H7FeedbackOracle {
    pub fn new(trajectory_id: impl Into<String>) -> Result<Self, H7FeedbackError> {
        let trajectory_id = trajectory_id.into();
        validate_text(&trajectory_id, "oracle trajectory id")?;
        let mut oracle = Self {
            schema_version: H7_FEEDBACK_SCHEMA_VERSION,
            namespace: H7_FEEDBACK_NAMESPACE.to_string(),
            trajectory_id: trajectory_id.clone(),
            scope: None,
            records: BTreeMap::new(),
            ledger: H7CreditLedger::new(trajectory_id)?,
            replay_only: H7_FEEDBACK_REPLAY_ONLY,
            production_effects: H7_FEEDBACK_EXTERNAL_EFFECTS,
            kg_write_authority: H7_FEEDBACK_KG_WRITE_AUTHORITY,
            production_caller: H7_FEEDBACK_PRODUCTION_CALLER,
            oracle_digest: Sha256Digest::for_bytes(b"uncomputed"),
        };
        oracle.oracle_digest = oracle.compute_digest();
        oracle.validate()?;
        Ok(oracle)
    }

    /// Appends a record or returns a deterministic replay result.  A key
    /// collision with different content is always a conflict; no overwrite is
    /// possible.
    pub fn append(
        &mut self,
        record: H7FeedbackRecord,
    ) -> Result<H7FeedbackAppend, H7FeedbackError> {
        // Do not let a replay path mask a pre-existing tampered oracle.
        self.validate()?;
        record.validate()?;
        if record.trajectory_id != self.trajectory_id {
            return Err(H7FeedbackError::BindingMismatch("oracle trajectory"));
        }
        if self.records.len() >= H7_FEEDBACK_MAX_RECORDS
            && !self.records.contains_key(&record.key())
        {
            return Err(H7FeedbackError::TooManyRecords(H7_FEEDBACK_MAX_RECORDS));
        }
        if let Some(scope) = &self.scope
            && scope != &record.action.binding.scope
        {
            return Err(H7FeedbackError::BindingMismatch("attempt/lease scope"));
        }
        let key = record.key();
        if let Some(existing) = self.records.get(&key) {
            if existing == &record {
                return Ok(H7FeedbackAppend::Replay {
                    feedback_digest: existing.feedback_digest.clone(),
                    ledger_digest: self.ledger.ledger_digest.clone(),
                    oracle_digest: self.oracle_digest.clone(),
                });
            }
            return Err(H7FeedbackError::Conflict(key.as_string()));
        }
        // Event sequence is a causal position, so a second event id at the
        // same sequence cannot be accepted even though the stable key differs.
        if self
            .records
            .keys()
            .any(|existing| existing.event_seq == key.event_seq)
        {
            return Err(H7FeedbackError::Conflict(format!(
                "{}:{}",
                self.trajectory_id, key.event_seq
            )));
        }

        // Feedback records are an append-only causal stream.  The first
        // record may start after a durable turn-start row that lives outside
        // this in-memory oracle, but every subsequent record must occupy the
        // next sequence.  Without this check a forged gap could make its
        // missing causal parent look like an intentionally external witness.
        if let Some(last_seq) = self.records.keys().map(|key| key.event_seq).max() {
            let expected = last_seq.checked_add(1).ok_or_else(|| {
                H7FeedbackError::Invalid("feedback sequence overflow".to_string())
            })?;
            if key.event_seq != expected {
                return Err(H7FeedbackError::NonContiguousSequence {
                    expected,
                    actual: key.event_seq,
                });
            }

            // Once this in-memory stream has a record, the causal witness for
            // the next record must be the exact immutable predecessor.  A
            // contiguous sequence number alone is not sufficient: accepting
            // an older/external parent would leave a gap in the authenticated
            // chain while still looking like a valid replay.  The first
            // record remains allowed to point at the durable turn-start row
            // that is intentionally outside this pure oracle.
            let previous = self
                .records
                .values()
                .find(|candidate| candidate.event_seq == last_seq)
                .ok_or(H7FeedbackError::BindingMismatch(
                    "missing causal predecessor",
                ))?;
            if record.causal_parent_seq != previous.event_seq {
                return Err(H7FeedbackError::BindingMismatch("causal parent sequence"));
            }
            if record.causal_parent_sha256 != previous.feedback_digest {
                return Err(H7FeedbackError::BindingMismatch("causal parent digest"));
            }
        }

        // Stage the complete state and validate it before publishing.  This
        // keeps append atomic even if a newly added invariant rejects the
        // candidate: callers never observe a half-updated records/ledger/
        // scope triple.
        let mut next = self.clone();
        next.ledger.append(key.clone(), record.credit_units)?;
        next.records.insert(key, record.clone());
        if next.scope.is_none() {
            next.scope = Some(record.action.binding.scope.clone());
        }
        next.oracle_digest = next.compute_digest();
        next.validate()?;
        let ledger_digest = next.ledger.ledger_digest.clone();
        let oracle_digest = next.oracle_digest.clone();
        *self = next;
        Ok(H7FeedbackAppend::Inserted {
            feedback_digest: record.feedback_digest,
            ledger_digest,
            oracle_digest,
        })
    }

    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        self.validate_authority()?;
        validate_text(&self.trajectory_id, "oracle trajectory id")?;
        self.ledger.validate()?;
        if self.ledger.trajectory_id != self.trajectory_id {
            return Err(H7FeedbackError::BindingMismatch("oracle ledger trajectory"));
        }
        if self.records.len() > H7_FEEDBACK_MAX_RECORDS {
            return Err(H7FeedbackError::TooManyRecords(H7_FEEDBACK_MAX_RECORDS));
        }
        if self.ledger.entries.len() > H7_FEEDBACK_MAX_RECORDS {
            return Err(H7FeedbackError::TooManyRecords(H7_FEEDBACK_MAX_RECORDS));
        }
        if self.ledger.entries.len() != self.records.len() {
            return Err(H7FeedbackError::BindingMismatch(
                "oracle ledger cardinality",
            ));
        }
        let mut observed_scope: Option<&H7AttemptLeaseScope> = None;
        let mut previous_seq: Option<u32> = None;
        let mut previous_record: Option<&H7FeedbackRecord> = None;
        for (key, record) in &self.records {
            record.validate()?;
            if key != &record.key() || record.trajectory_id != self.trajectory_id {
                return Err(H7FeedbackError::BindingMismatch("oracle record key"));
            }
            if let Some(previous) = previous_seq {
                let expected = previous.checked_add(1).ok_or_else(|| {
                    H7FeedbackError::Invalid("feedback sequence overflow".to_string())
                })?;
                if key.event_seq != expected {
                    return Err(H7FeedbackError::NonContiguousSequence {
                        expected,
                        actual: key.event_seq,
                    });
                }
            }
            previous_seq = Some(key.event_seq);
            if self.ledger.entries.get(key) != Some(&record.credit_units) {
                return Err(H7FeedbackError::BindingMismatch("oracle credit entry"));
            }
            // The first parent may be a durable H7 turn-start row outside
            // this in-memory feedback slice.  Every later record must point
            // to the immediately preceding immutable record, by both
            // sequence and digest; merely finding any older sequence would
            // permit a forged causal gap.
            if let Some(previous) = previous_record {
                if record.causal_parent_seq != previous.event_seq {
                    return Err(H7FeedbackError::BindingMismatch("causal parent sequence"));
                }
                if previous.feedback_digest != record.causal_parent_sha256 {
                    return Err(H7FeedbackError::BindingMismatch("causal parent digest"));
                }
            }
            if let Some(scope) = observed_scope {
                if scope != &record.action.binding.scope {
                    return Err(H7FeedbackError::BindingMismatch(
                        "record attempt/lease scope",
                    ));
                }
            } else {
                observed_scope = Some(&record.action.binding.scope);
            }
            previous_record = Some(record);
        }
        match (&self.scope, observed_scope) {
            (Some(expected), Some(observed)) if expected != observed => {
                return Err(H7FeedbackError::BindingMismatch(
                    "oracle attempt/lease scope",
                ));
            }
            (Some(_), None) => {
                return Err(H7FeedbackError::BindingMismatch("unbound empty oracle"));
            }
            (None, Some(_)) => {
                return Err(H7FeedbackError::BindingMismatch("missing oracle scope"));
            }
            _ => {}
        }
        if self.oracle_digest != self.compute_digest() {
            return Err(H7FeedbackError::DigestMismatch("feedback oracle"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, H7FeedbackError> {
        self.validate()?;
        Ok(self.oracle_digest.clone())
    }

    pub fn evaluate(&self, weight_cap_scaled: u64) -> Result<H7OfflineEvaluation, H7FeedbackError> {
        self.validate()?;
        if self.records.is_empty() {
            return Err(H7FeedbackError::EmptyLedger);
        }
        if weight_cap_scaled == 0 || weight_cap_scaled > H7_FEEDBACK_MAX_WEIGHT_CAP_SCALED {
            return Err(H7FeedbackError::Invalid(format!(
                "weight cap must be in 1..={H7_FEEDBACK_MAX_WEIGHT_CAP_SCALED}"
            )));
        }
        let sample_count = u32::try_from(self.records.len())
            .map_err(|_| H7FeedbackError::TooManyRecords(H7_FEEDBACK_MAX_RECORDS))?;
        let mut total_weight_scaled = 0_u64;
        let mut weighted_reward_sum = 0_i64;
        let mut direct_reward_sum = 0_i64;
        let mut clipped_count = 0_u32;
        for record in self.records.values() {
            if !record.support.in_support {
                return Err(H7FeedbackError::OutOfSupport);
            }
            let raw_weight = record.propensity.weight_scaled()?;
            let weight = raw_weight.min(weight_cap_scaled);
            if weight != raw_weight {
                clipped_count = clipped_count
                    .checked_add(1)
                    .ok_or(H7FeedbackError::WeightOverflow)?;
            }
            total_weight_scaled = total_weight_scaled
                .checked_add(weight)
                .ok_or(H7FeedbackError::WeightOverflow)?;
            let contribution = i64::try_from(weight)
                .map_err(|_| H7FeedbackError::WeightOverflow)?
                .checked_mul(i64::from(record.reward_bps))
                .ok_or(H7FeedbackError::WeightOverflow)?;
            weighted_reward_sum = weighted_reward_sum
                .checked_add(contribution)
                .ok_or(H7FeedbackError::WeightOverflow)?;
            direct_reward_sum = direct_reward_sum
                .checked_add(i64::from(record.reward_bps))
                .ok_or(H7FeedbackError::WeightOverflow)?;
        }
        if total_weight_scaled == 0 {
            return Err(H7FeedbackError::ZeroWeight);
        }
        let estimate_reward_bps = i32::try_from(
            weighted_reward_sum / i64::try_from(total_weight_scaled).unwrap_or(i64::MAX),
        )
        .map_err(|_| H7FeedbackError::WeightOverflow)?;
        let direct_reward_bps = i32::try_from(direct_reward_sum / i64::from(sample_count))
            .map_err(|_| H7FeedbackError::WeightOverflow)?;
        let coverage_bps = u16::try_from(
            u64::from(sample_count)
                .checked_mul(10_000)
                .ok_or(H7FeedbackError::WeightOverflow)?
                / u64::from(sample_count),
        )
        .map_err(|_| H7FeedbackError::WeightOverflow)?;
        let mut evaluation = H7OfflineEvaluation {
            schema_version: H7_FEEDBACK_SCHEMA_VERSION,
            namespace: H7_FEEDBACK_NAMESPACE.to_string(),
            trajectory_id: self.trajectory_id.clone(),
            input_digest: self.oracle_digest.clone(),
            ledger_digest: self.ledger.ledger_digest.clone(),
            sample_count,
            supported_count: sample_count,
            coverage_bps,
            total_weight_scaled,
            weighted_reward_sum,
            estimate_reward_bps,
            direct_reward_bps,
            clipped_count,
            weight_cap_scaled,
            replay_only: H7_FEEDBACK_REPLAY_ONLY,
            production_effects: H7_FEEDBACK_EXTERNAL_EFFECTS,
            kg_write_authority: H7_FEEDBACK_KG_WRITE_AUTHORITY,
            production_caller: H7_FEEDBACK_PRODUCTION_CALLER,
            evaluation_digest: Sha256Digest::for_bytes(b"uncomputed"),
        };
        evaluation.evaluation_digest = evaluation.compute_digest();
        evaluation.validate()?;
        Ok(evaluation)
    }

    pub fn records(&self) -> &BTreeMap<H7FeedbackKey, H7FeedbackRecord> {
        &self.records
    }

    pub fn ledger(&self) -> &H7CreditLedger {
        &self.ledger
    }

    fn validate_authority(&self) -> Result<(), H7FeedbackError> {
        if self.schema_version != H7_FEEDBACK_SCHEMA_VERSION
            || self.namespace != H7_FEEDBACK_NAMESPACE
        {
            return Err(H7FeedbackError::SchemaMismatch);
        }
        if !self.replay_only {
            return Err(H7FeedbackError::NotReplayOnly);
        }
        authority_flags(
            self.production_effects,
            self.kg_write_authority,
            self.production_caller,
        )
    }

    fn compute_digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, ORACLE_DOMAIN);
        frame_part(&mut hasher, &self.schema_version.to_be_bytes());
        frame_part(&mut hasher, self.namespace.as_bytes());
        frame_part(&mut hasher, self.trajectory_id.as_bytes());
        frame_part(&mut hasher, &[u8::from(self.replay_only)]);
        frame_part(&mut hasher, &[u8::from(self.production_effects)]);
        frame_part(&mut hasher, &[u8::from(self.kg_write_authority)]);
        frame_part(&mut hasher, &[u8::from(self.production_caller)]);
        match &self.scope {
            Some(scope) => {
                frame_part(&mut hasher, &[1]);
                frame_part(&mut hasher, scope.digest().as_str().as_bytes());
            }
            None => frame_part(&mut hasher, &[0]),
        }
        frame_part(
            &mut hasher,
            &u64::try_from(self.records.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for (key, record) in &self.records {
            frame_part(&mut hasher, key.trajectory_id.as_bytes());
            frame_part(&mut hasher, &key.event_seq.to_be_bytes());
            frame_part(&mut hasher, key.event_id.as_bytes());
            frame_part(&mut hasher, record.feedback_digest.as_str().as_bytes());
        }
        frame_part(&mut hasher, self.ledger.ledger_digest.as_str().as_bytes());
        Sha256Digest::from_sha256_output(hasher.finalize())
    }
}

/// Deterministic fixed-point off-policy evaluation result.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7OfflineEvaluation {
    pub schema_version: u32,
    pub namespace: String,
    pub trajectory_id: String,
    pub input_digest: Sha256Digest,
    pub ledger_digest: Sha256Digest,
    pub sample_count: u32,
    pub supported_count: u32,
    pub coverage_bps: u16,
    pub total_weight_scaled: u64,
    pub weighted_reward_sum: i64,
    pub estimate_reward_bps: i32,
    pub direct_reward_bps: i32,
    pub clipped_count: u32,
    pub weight_cap_scaled: u64,
    pub replay_only: bool,
    pub production_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub evaluation_digest: Sha256Digest,
}

impl H7OfflineEvaluation {
    pub fn validate(&self) -> Result<(), H7FeedbackError> {
        if self.schema_version != H7_FEEDBACK_SCHEMA_VERSION
            || self.namespace != H7_FEEDBACK_NAMESPACE
        {
            return Err(H7FeedbackError::SchemaMismatch);
        }
        validate_text(&self.trajectory_id, "evaluation trajectory id")?;
        validate_digest(&self.input_digest, "evaluation input")?;
        validate_digest(&self.ledger_digest, "evaluation ledger")?;
        if self.sample_count == 0 || self.supported_count > self.sample_count {
            return Err(H7FeedbackError::Invalid(
                "evaluation sample counts are inconsistent".to_string(),
            ));
        }
        if self.coverage_bps > 10_000 {
            return Err(H7FeedbackError::Invalid(
                "evaluation coverage exceeds 10000 bps".to_string(),
            ));
        }
        if self.weight_cap_scaled == 0 || self.weight_cap_scaled > H7_FEEDBACK_MAX_WEIGHT_CAP_SCALED
        {
            return Err(H7FeedbackError::Invalid(
                "evaluation weight cap is outside the bounded range".to_string(),
            ));
        }
        if self.total_weight_scaled == 0 {
            return Err(H7FeedbackError::ZeroWeight);
        }
        if !self.replay_only {
            return Err(H7FeedbackError::NotReplayOnly);
        }
        authority_flags(
            self.production_effects,
            self.kg_write_authority,
            self.production_caller,
        )?;
        if self.evaluation_digest != self.compute_digest() {
            return Err(H7FeedbackError::DigestMismatch("offline evaluation"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, H7FeedbackError> {
        self.validate()?;
        Ok(self.evaluation_digest.clone())
    }

    /// Alias useful to callers that use IPS terminology.
    pub const fn ips_reward_bps(&self) -> i32 {
        self.estimate_reward_bps
    }

    fn compute_digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, EVALUATION_DOMAIN);
        frame_part(&mut hasher, &self.schema_version.to_be_bytes());
        frame_part(&mut hasher, self.namespace.as_bytes());
        frame_part(&mut hasher, self.trajectory_id.as_bytes());
        frame_part(&mut hasher, self.input_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.ledger_digest.as_str().as_bytes());
        frame_part(&mut hasher, &self.sample_count.to_be_bytes());
        frame_part(&mut hasher, &self.supported_count.to_be_bytes());
        frame_part(&mut hasher, &self.coverage_bps.to_be_bytes());
        frame_part(&mut hasher, &self.total_weight_scaled.to_be_bytes());
        frame_part(&mut hasher, &self.weighted_reward_sum.to_be_bytes());
        frame_part(&mut hasher, &self.estimate_reward_bps.to_be_bytes());
        frame_part(&mut hasher, &self.direct_reward_bps.to_be_bytes());
        frame_part(&mut hasher, &self.clipped_count.to_be_bytes());
        frame_part(&mut hasher, &self.weight_cap_scaled.to_be_bytes());
        frame_part(&mut hasher, &[u8::from(self.replay_only)]);
        frame_part(&mut hasher, &[u8::from(self.production_effects)]);
        frame_part(&mut hasher, &[u8::from(self.kg_write_authority)]);
        frame_part(&mut hasher, &[u8::from(self.production_caller)]);
        Sha256Digest::from_sha256_output(hasher.finalize())
    }
}

fn authority_flags(
    external_effects: bool,
    kg_write_authority: bool,
    production_caller: bool,
) -> Result<(), H7FeedbackError> {
    if external_effects {
        return Err(H7FeedbackError::ExternalEffect);
    }
    if kg_write_authority {
        return Err(H7FeedbackError::KgWriteAuthority);
    }
    if production_caller {
        return Err(H7FeedbackError::ProductionCaller);
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, label: &'static str) -> Result<(), H7FeedbackError> {
    if Sha256Digest::parse(digest.as_str().to_string()).is_err() {
        return Err(H7FeedbackError::Invalid(format!(
            "{label} must be a lowercase SHA-256 digest"
        )));
    }
    Ok(())
}

fn validate_text(value: &str, label: &'static str) -> Result<(), H7FeedbackError> {
    if value.trim().is_empty()
        || value.len() > H7_FEEDBACK_MAX_TEXT_BYTES
        || value.as_bytes().contains(&0)
        || value.chars().any(char::is_control)
    {
        return Err(H7FeedbackError::Invalid(format!(
            "{label} must contain 1..={H7_FEEDBACK_MAX_TEXT_BYTES} non-control bytes"
        )));
    }
    Ok(())
}
