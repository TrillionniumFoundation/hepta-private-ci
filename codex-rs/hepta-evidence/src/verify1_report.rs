//! Typed VERIFY-1 claims. Parsing and evidence support never grant effect authority.
//!
//! The inner raw JSON is hashed without Rust float reserialization: Python's
//! canonical number spellings are not assumed to equal serde's spellings.

use std::collections::BTreeSet;
use std::fmt::Write;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

const ENCODING: &str = "verify1-python-canonical-json-v1";
const PAYLOAD_TYPE: &str = "hepta.verify1.report";
const MAX_PAYLOAD_BYTES: usize = 32 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Verify1Scope {
    pub task_id: String,
    pub attempt_id: String,
    pub subject_sha256: String,
    pub state_version: u64,
    pub domain: String,
    pub event: String,
    pub horizon_start: u64,
    pub horizon_end: u64,
}

impl Verify1Scope {
    pub fn validate(&self) -> Result<(), String> {
        for value in [&self.task_id, &self.attempt_id, &self.domain, &self.event] {
            text(value)?;
        }
        digest(&self.subject_sha256)?;
        require(
            self.horizon_start <= self.horizon_end,
            "reversed VERIFY-1 horizon",
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Verify1ModelIdentity {
    pub base_sha256: String,
    #[serde(deserialize_with = "required_nullable_digest")]
    pub adapter_sha256: Option<String>,
    pub policy_sha256: String,
}

impl Verify1ModelIdentity {
    fn validate(&self) -> Result<(), String> {
        digest(&self.base_sha256)?;
        digest(&self.policy_sha256)?;
        if let Some(adapter) = &self.adapter_sha256 {
            digest(adapter)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Verify1RiskPrediction {
    pub scope: Verify1Scope,
    pub model: Verify1ModelIdentity,
    pub probability: f64,
    pub observed_step: u64,
    pub evidence_sha256: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Verify1CalibrationReport {
    pub scope: Verify1Scope,
    pub model: Verify1ModelIdentity,
    pub training_source_groups: Vec<String>,
    pub calibration_source_groups: Vec<String>,
    pub confirmation_source_groups: Vec<String>,
    pub data_sha256: String,
    pub metric: String,
    pub metric_kind: String,
    pub metric_value: f64,
    pub sample_count: u64,
    pub drift: String,
    pub assumptions: Vec<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Verify1Verdict {
    Proved,
    Refuted,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Verify1VerificationReceipt {
    pub scope: Verify1Scope,
    pub property: String,
    pub assumptions: Vec<String>,
    pub checker_id: String,
    pub checker_version: String,
    pub evidence_sha256: String,
    pub checked_step: u64,
    pub verdict: Verify1Verdict,
    pub reason: String,
    pub residual_obligations: Vec<String>,
}

impl Verify1VerificationReceipt {
    pub fn validate(&self) -> Result<(), String> {
        self.scope.validate()?;
        for value in [
            &self.property,
            &self.checker_id,
            &self.checker_version,
            &self.reason,
        ] {
            text(value)?;
        }
        digest(&self.evidence_sha256)?;
        strings(&self.assumptions)?;
        strings(&self.residual_obligations)?;
        require(
            self.checked_step >= self.scope.horizon_start,
            "receipt predates its scope",
        )?;
        match self.verdict {
            Verify1Verdict::Proved => require(
                self.residual_obligations.is_empty(),
                "proved has unresolved obligations",
            ),
            Verify1Verdict::Unknown => require(
                !self.residual_obligations.is_empty(),
                "unknown needs unresolved obligations",
            ),
            Verify1Verdict::Refuted => Ok(()),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Verify1Record {
    RiskPrediction(Verify1RiskPrediction),
    CalibrationReport(Verify1CalibrationReport),
    VerificationReceipt(Verify1VerificationReceipt),
}

// Deserialize concrete wire records directly. Serde's internally-tagged enum
// buffering turns arbitrary-precision JSON numbers into private maps; accepting
// those maps as numbers would also weaken the JSON type boundary.
macro_rules! wire_record {
    ($wire:ident => $record:ident { $($field:ident: $kind:ty),* $(,)? }) => {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct $wire {
            #[serde(rename = "type")]
            tag: String,
            $($field: $kind,)*
        }
        impl $wire {
            fn typed(self, expected_tag: &str) -> Result<$record, String> {
                require(self.tag == expected_tag, "VERIFY-1 record type mismatch")?;
                Ok($record { $($field: self.$field,)* })
            }
        }
    };
}

wire_record!(RiskWire => Verify1RiskPrediction {
    scope: Verify1Scope, model: Verify1ModelIdentity, probability: f64,
    observed_step: u64, evidence_sha256: String,
});
wire_record!(CalibrationWire => Verify1CalibrationReport {
    scope: Verify1Scope, model: Verify1ModelIdentity,
    training_source_groups: Vec<String>, calibration_source_groups: Vec<String>, confirmation_source_groups: Vec<String>,
    data_sha256: String, metric: String, metric_kind: String, metric_value: f64,
    sample_count: u64, drift: String, assumptions: Vec<String>,
});
wire_record!(VerificationWire => Verify1VerificationReceipt {
    scope: Verify1Scope, property: String, assumptions: Vec<String>, checker_id: String, checker_version: String,
    evidence_sha256: String, checked_step: u64, verdict: Verify1Verdict, reason: String, residual_obligations: Vec<String>,
});

impl Verify1Record {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::RiskPrediction(_) => "risk_prediction",
            Self::CalibrationReport(_) => "calibration_report",
            Self::VerificationReceipt(_) => "verification_receipt",
        }
    }

    pub fn scope(&self) -> &Verify1Scope {
        match self {
            Self::RiskPrediction(record) => &record.scope,
            Self::CalibrationReport(record) => &record.scope,
            Self::VerificationReceipt(record) => &record.scope,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        self.scope().validate()?;
        match self {
            Self::RiskPrediction(record) => {
                record.model.validate()?;
                probability(record.probability)?;
                digest(&record.evidence_sha256)?;
                require(
                    record.observed_step <= record.scope.horizon_start,
                    "retrospective risk prediction",
                )
            }
            Self::CalibrationReport(record) => {
                record.model.validate()?;
                probability(record.metric_value)?;
                digest(&record.data_sha256)?;
                let mut groups = BTreeSet::new();
                for partition in [
                    &record.training_source_groups,
                    &record.calibration_source_groups,
                    &record.confirmation_source_groups,
                ] {
                    strings(partition)?;
                    for group in partition {
                        require(
                            groups.insert(group),
                            "source groups overlap across partitions",
                        )?;
                    }
                }
                require(
                    !record.calibration_source_groups.is_empty()
                        && !record.confirmation_source_groups.is_empty(),
                    "calibration and confirmation partitions required",
                )?;
                require(record.sample_count > 0, "calibration needs observations")?;
                strings(&record.assumptions)?;
                require(
                    !record.assumptions.is_empty(),
                    "calibration assumptions required",
                )?;
                require(
                    matches!(
                        record.drift.as_str(),
                        "not_detected" | "detected" | "unknown"
                    ),
                    "invalid drift state",
                )?;
                require(
                    matches!(
                        (record.metric.as_str(), record.metric_kind.as_str()),
                        ("brier", "proper_scoring_rule")
                            | ("ece", "calibration_diagnostic")
                            | ("score_miscoverage", "score_event_frequency")
                            | ("accepted_trajectory_error_rate", "outcome_event_frequency")
                    ),
                    "metric kind mismatch",
                )
            }
            Self::VerificationReceipt(record) => record.validate(),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Payload {
    schema_version: u32,
    payload_type: String,
    record_type: String,
    record_encoding: String,
    record_sha256: String,
    record_json: String,
}

/// Validate a claimed report, including its original bytes; this is not authentication.
pub fn parse_verify1_payload(payload: &Value) -> Result<Verify1Record, String> {
    require(
        serde_json::to_vec(payload)
            .map_err(|error| error.to_string())?
            .len()
            <= MAX_PAYLOAD_BYTES,
        "VERIFY-1 payload exceeds 32 KiB",
    )?;
    let payload: Payload =
        serde_json::from_value(payload.clone()).map_err(|error| error.to_string())?;
    require(
        payload.schema_version == 1
            && payload.payload_type == PAYLOAD_TYPE
            && payload.record_encoding == ENCODING,
        "unsupported VERIFY-1 payload profile",
    )?;
    digest(&payload.record_sha256)?;
    require(
        Sha256Digest::for_bytes(payload.record_json.as_bytes()).as_str() == payload.record_sha256,
        "VERIFY-1 raw record digest mismatch",
    )?;
    let record = match payload.record_type.as_str() {
        "risk_prediction" => Verify1Record::RiskPrediction(
            serde_json::from_str::<RiskWire>(&payload.record_json)
                .map_err(|error| error.to_string())?
                .typed(&payload.record_type)?,
        ),
        "calibration_report" => Verify1Record::CalibrationReport(
            serde_json::from_str::<CalibrationWire>(&payload.record_json)
                .map_err(|error| error.to_string())?
                .typed(&payload.record_type)?,
        ),
        "verification_receipt" => Verify1Record::VerificationReceipt(
            serde_json::from_str::<VerificationWire>(&payload.record_json)
                .map_err(|error| error.to_string())?
                .typed(&payload.record_type)?,
        ),
        _ => return Err("unsupported VERIFY-1 record type".to_string()),
    };
    record.validate()?;
    Ok(record)
}

/// Encode an integer-only checker receipt in the existing Python wire profile.
/// Other record producers must retain and hash their original JSON encoding.
pub fn verify1_receipt_payload(receipt: &Verify1VerificationReceipt) -> Result<Value, String> {
    receipt.validate()?;
    let record = Verify1Record::VerificationReceipt(receipt.clone());
    let raw = python_integer_json(&record)?;
    let payload = serde_json::json!({
        "schema_version": 1, "payload_type": PAYLOAD_TYPE,
        "record_type": record.kind(), "record_encoding": ENCODING,
        "record_sha256": Sha256Digest::for_bytes(&raw).as_str(),
        "record_json": String::from_utf8(raw).map_err(|error| error.to_string())?,
    });
    parse_verify1_payload(&payload)?;
    Ok(payload)
}

pub(crate) fn python_integer_json(value: &impl Serialize) -> Result<Vec<u8>, String> {
    let value = serde_json::to_value(value).map_err(|error| error.to_string())?;
    let mut pending = vec![&value];
    while let Some(item) = pending.pop() {
        match item {
            Value::Number(number) => require(
                !number.is_f64(),
                "integer-only encoding cannot reformat floats",
            )?,
            Value::Array(items) => pending.extend(items),
            Value::Object(items) => pending.extend(items.values()),
            Value::Null | Value::Bool(_) | Value::String(_) => {}
        }
    }
    let raw = crate::canonical::canonical_json(&value).map_err(|error| error.to_string())?;
    let raw = String::from_utf8(raw).map_err(|error| error.to_string())?;
    let mut ascii = String::with_capacity(raw.len());
    for character in raw.chars() {
        if character <= '\u{7e}' {
            ascii.push(character);
        } else {
            for unit in character.encode_utf16(&mut [0; 2]) {
                write!(ascii, "\\u{unit:04x}").map_err(|error| error.to_string())?;
            }
        }
    }
    Ok(ascii.into_bytes())
}

fn require(condition: bool, message: &str) -> Result<(), String> {
    if condition {
        Ok(())
    } else {
        Err(message.to_string())
    }
}

fn text(value: &str) -> Result<(), String> {
    require(
        !value.is_empty() && value == value.trim(),
        "VERIFY-1 text must be nonempty and unpadded",
    )
}

fn digest(value: &str) -> Result<(), String> {
    Sha256Digest::parse(value).map(|_| ())
}

fn required_nullable_digest<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<String>, D::Error> {
    Option::<String>::deserialize(deserializer)
}

fn probability(value: f64) -> Result<(), String> {
    require(
        value.is_finite() && (0.0..=1.0).contains(&value),
        "VERIFY-1 probability or metric is outside [0,1]",
    )
}

fn strings(values: &[String]) -> Result<(), String> {
    let mut seen = BTreeSet::new();
    for value in values {
        text(value)?;
        require(seen.insert(value), "duplicate VERIFY-1 text entry")?;
    }
    Ok(())
}
