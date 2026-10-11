use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::HandlerOutcome;
use codex_hepta_contracts::ProviderAttemptId;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::provider_store::load_provider_attempt_in_transaction;
use crate::schema_validation::classify_sqlx_error;
use crate::store::load_action_evidence_in_transaction;

pub const HISTORICAL_EVIDENCE_SCHEMA_VERSION: u32 = 1;
pub const HISTORICAL_EVIDENCE_DIGEST_DOMAIN: &str = "hepta.authoritative-historical-evidence.v1";
pub const HISTORICAL_EVIDENCE_RECORD_DIGEST_DOMAIN: &str =
    "hepta.authoritative-historical-record.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HistoricalEvidenceFamily {
    GovernanceAction,
    ProviderAttempt,
}

impl HistoricalEvidenceFamily {
    pub const fn as_wire_str(self) -> &'static str {
        match self {
            Self::GovernanceAction => "governanceAction",
            Self::ProviderAttempt => "providerAttempt",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HistoricalEvidenceState {
    Pending,
    HandlerCompletedSuccess,
    HandlerCompletedFailure,
    Blocked,
    HandlerFailedBeforeExecution,
    HandlerFailedAfterExecution,
    Aborted,
    Completed,
    Rejected,
    NotDispatched,
    Indeterminate,
}

impl HistoricalEvidenceState {
    pub const fn as_wire_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::HandlerCompletedSuccess => "handlerCompletedSuccess",
            Self::HandlerCompletedFailure => "handlerCompletedFailure",
            Self::Blocked => "blocked",
            Self::HandlerFailedBeforeExecution => "handlerFailedBeforeExecution",
            Self::HandlerFailedAfterExecution => "handlerFailedAfterExecution",
            Self::Aborted => "aborted",
            Self::Completed => "completed",
            Self::Rejected => "rejected",
            Self::NotDispatched => "notDispatched",
            Self::Indeterminate => "indeterminate",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HistoricalEvidenceSelector {
    family: HistoricalEvidenceFamily,
    record_id: String,
}

impl HistoricalEvidenceSelector {
    pub fn new(
        family: HistoricalEvidenceFamily,
        record_id: impl Into<String>,
    ) -> Result<Self, String> {
        let record_id = canonical_record_id(family, record_id.into())?;
        Ok(Self { family, record_id })
    }

    pub const fn family(&self) -> HistoricalEvidenceFamily {
        self.family
    }

    pub fn record_id(&self) -> &str {
        &self.record_id
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HistoricalEvidenceRecord {
    schema_version: u32,
    family: HistoricalEvidenceFamily,
    record_id: String,
    state: HistoricalEvidenceState,
    evidence_sha256: Sha256Digest,
    record_sha256: Sha256Digest,
}

impl HistoricalEvidenceRecord {
    pub const fn schema_version(&self) -> u32 {
        self.schema_version
    }

    pub const fn family(&self) -> HistoricalEvidenceFamily {
        self.family
    }

    pub fn record_id(&self) -> &str {
        &self.record_id
    }

    pub const fn state(&self) -> HistoricalEvidenceState {
        self.state
    }

    pub const fn evidence_sha256(&self) -> &Sha256Digest {
        &self.evidence_sha256
    }

    pub const fn record_sha256(&self) -> &Sha256Digest {
        &self.record_sha256
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != HISTORICAL_EVIDENCE_SCHEMA_VERSION {
            return Err("unsupported historical evidence schema version".to_string());
        }
        let canonical = canonical_record_id(self.family, self.record_id.clone())?;
        if canonical != self.record_id {
            return Err("historical record id is not canonical".to_string());
        }
        if !state_belongs_to_family(self.family, self.state) {
            return Err("historical state does not belong to its evidence family".to_string());
        }
        let expected = historical_record_sha256(
            self.schema_version,
            self.family,
            &self.record_id,
            self.state,
            &self.evidence_sha256,
        )
        .map_err(|error| error.to_string())?;
        if expected != self.record_sha256 {
            return Err("historical record digest mismatch".to_string());
        }
        Ok(())
    }
}

impl HeptaEvidenceStore {
    /// Projects one exact authoritative record from a single SQLite read
    /// transaction. The projection is diagnostic and does not confer authority.
    pub async fn historical_record(
        &self,
        selector: &HistoricalEvidenceSelector,
    ) -> Result<Option<HistoricalEvidenceRecord>, EvidenceError> {
        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let projected = match selector.family {
            HistoricalEvidenceFamily::GovernanceAction => {
                let action_id = ActionId::parse(selector.record_id.clone())
                    .map_err(EvidenceError::InvalidRecord)?;
                let evidence =
                    load_action_evidence_in_transaction(&mut transaction, &action_id).await?;
                if evidence.admission.is_none()
                    && evidence.authorization.is_none()
                    && evidence.receipt.is_none()
                {
                    None
                } else {
                    let receipt = evidence.receipt.as_ref().map(|stored| &stored.receipt);
                    let state = receipt.map_or(HistoricalEvidenceState::Pending, |receipt| {
                        match receipt.outcome {
                            HandlerOutcome::HandlerCompleted {
                                reported_success: true,
                            } => HistoricalEvidenceState::HandlerCompletedSuccess,
                            HandlerOutcome::HandlerCompleted {
                                reported_success: false,
                            } => HistoricalEvidenceState::HandlerCompletedFailure,
                            HandlerOutcome::Blocked => HistoricalEvidenceState::Blocked,
                            HandlerOutcome::HandlerFailed {
                                handler_executed: false,
                            } => HistoricalEvidenceState::HandlerFailedBeforeExecution,
                            HandlerOutcome::HandlerFailed {
                                handler_executed: true,
                            } => HistoricalEvidenceState::HandlerFailedAfterExecution,
                            HandlerOutcome::Aborted => HistoricalEvidenceState::Aborted,
                            HandlerOutcome::Indeterminate { .. } => {
                                HistoricalEvidenceState::Indeterminate
                            }
                        }
                    });
                    let material = (
                        evidence.admission.as_ref(),
                        evidence.authorization.as_ref(),
                        receipt,
                    );
                    let digest = evidence_digest(selector, &material)?;
                    Some(project_record(selector, state, digest)?)
                }
            }
            HistoricalEvidenceFamily::ProviderAttempt => {
                let attempt_id = ProviderAttemptId::parse(selector.record_id.clone())
                    .map_err(EvidenceError::InvalidRecord)?;
                let Some(evidence) =
                    load_provider_attempt_in_transaction(&mut transaction, &attempt_id).await?
                else {
                    transaction.commit().await.map_err(classify_sqlx_error)?;
                    return Ok(None);
                };
                let receipt = evidence.receipt.as_ref().map(|stored| &stored.receipt);
                let state =
                    receipt.map_or(HistoricalEvidenceState::Pending, |receipt| {
                        match receipt.terminal {
                            ProviderTerminal::Completed { .. }
                            | ProviderTerminal::CompletedUnary { .. } => {
                                HistoricalEvidenceState::Completed
                            }
                            ProviderTerminal::Rejected { .. } => HistoricalEvidenceState::Rejected,
                            ProviderTerminal::NotDispatched { .. } => {
                                HistoricalEvidenceState::NotDispatched
                            }
                            ProviderTerminal::Indeterminate { .. } => {
                                HistoricalEvidenceState::Indeterminate
                            }
                        }
                    });
                let material = (&evidence.intent.intent, receipt);
                let digest = evidence_digest(selector, &material)?;
                Some(project_record(selector, state, digest)?)
            }
        };
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(projected)
    }
}

fn canonical_record_id(
    family: HistoricalEvidenceFamily,
    record_id: String,
) -> Result<String, String> {
    match family {
        HistoricalEvidenceFamily::GovernanceAction => {
            ActionId::parse(record_id).map(|id| id.as_str().to_string())
        }
        HistoricalEvidenceFamily::ProviderAttempt => {
            ProviderAttemptId::parse(record_id).map(|id| id.as_str().to_string())
        }
    }
}

const fn state_belongs_to_family(
    family: HistoricalEvidenceFamily,
    state: HistoricalEvidenceState,
) -> bool {
    match family {
        HistoricalEvidenceFamily::GovernanceAction => matches!(
            state,
            HistoricalEvidenceState::Pending
                | HistoricalEvidenceState::HandlerCompletedSuccess
                | HistoricalEvidenceState::HandlerCompletedFailure
                | HistoricalEvidenceState::Blocked
                | HistoricalEvidenceState::HandlerFailedBeforeExecution
                | HistoricalEvidenceState::HandlerFailedAfterExecution
                | HistoricalEvidenceState::Aborted
                | HistoricalEvidenceState::Indeterminate
        ),
        HistoricalEvidenceFamily::ProviderAttempt => matches!(
            state,
            HistoricalEvidenceState::Pending
                | HistoricalEvidenceState::Completed
                | HistoricalEvidenceState::Rejected
                | HistoricalEvidenceState::NotDispatched
                | HistoricalEvidenceState::Indeterminate
        ),
    }
}

fn project_record(
    selector: &HistoricalEvidenceSelector,
    state: HistoricalEvidenceState,
    evidence_sha256: Sha256Digest,
) -> Result<HistoricalEvidenceRecord, EvidenceError> {
    if !state_belongs_to_family(selector.family, state) {
        return Err(EvidenceError::Corrupt(
            "historical state does not belong to its evidence family".to_string(),
        ));
    }
    let record_sha256 = historical_record_sha256(
        HISTORICAL_EVIDENCE_SCHEMA_VERSION,
        selector.family,
        &selector.record_id,
        state,
        &evidence_sha256,
    )?;
    Ok(HistoricalEvidenceRecord {
        schema_version: HISTORICAL_EVIDENCE_SCHEMA_VERSION,
        family: selector.family,
        record_id: selector.record_id.clone(),
        state,
        evidence_sha256,
        record_sha256,
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct HistoricalEvidenceRecordDigest<'a> {
    domain: &'static str,
    schema_version: u32,
    family: &'static str,
    record_id: &'a str,
    state: &'static str,
    evidence_sha256: &'a Sha256Digest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct HistoricalEvidenceDigest<'a, T> {
    domain: &'static str,
    schema_version: u32,
    family: &'static str,
    record_id: &'a str,
    material: &'a T,
}

fn evidence_digest<T: Serialize>(
    selector: &HistoricalEvidenceSelector,
    material: &T,
) -> Result<Sha256Digest, EvidenceError> {
    canonical_digest(&HistoricalEvidenceDigest {
        domain: HISTORICAL_EVIDENCE_DIGEST_DOMAIN,
        schema_version: HISTORICAL_EVIDENCE_SCHEMA_VERSION,
        family: selector.family.as_wire_str(),
        record_id: &selector.record_id,
        material,
    })
}

/// Recomputes the canonical digest of one historical projection.
///
/// The digest provides record self-consistency only; it is not a keyed
/// authority, external anchor, or anti-rollback root.
pub fn historical_record_sha256(
    schema_version: u32,
    family: HistoricalEvidenceFamily,
    record_id: &str,
    state: HistoricalEvidenceState,
    evidence_sha256: &Sha256Digest,
) -> Result<Sha256Digest, EvidenceError> {
    canonical_digest(&HistoricalEvidenceRecordDigest {
        domain: HISTORICAL_EVIDENCE_RECORD_DIGEST_DOMAIN,
        schema_version,
        family: family.as_wire_str(),
        record_id,
        state: state.as_wire_str(),
        evidence_sha256,
    })
}

fn canonical_digest<T: Serialize>(value: &T) -> Result<Sha256Digest, EvidenceError> {
    canonical_json(value).map(|bytes| Sha256Digest::for_bytes(&bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(prefix: &str, byte: char) -> String {
        format!("{prefix}{}", byte.to_string().repeat(64))
    }

    #[test]
    fn selectors_are_strictly_family_typed() {
        let fixtures = [
            (
                HistoricalEvidenceFamily::GovernanceAction,
                id("tool:v1:", 'a'),
            ),
            (
                HistoricalEvidenceFamily::ProviderAttempt,
                id("provider-attempt:v1:", 'b'),
            ),
        ];
        for (family, record_id) in &fixtures {
            let selector = HistoricalEvidenceSelector::new(*family, record_id)
                .expect("matching typed selector");
            assert_eq!(selector.family(), *family);
            assert_eq!(selector.record_id(), record_id);
        }
        for (family, _) in &fixtures {
            for (_, record_id) in &fixtures {
                let matches = HistoricalEvidenceSelector::new(*family, record_id).is_ok();
                assert_eq!(
                    matches,
                    match family {
                        HistoricalEvidenceFamily::GovernanceAction => {
                            record_id.starts_with("tool:v1:")
                        }
                        HistoricalEvidenceFamily::ProviderAttempt => {
                            record_id.starts_with("provider-attempt:v1:")
                        }
                    }
                );
            }
        }
        for malformed in [
            "",
            "tool:v1:short",
            "tool:v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "action:v1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ] {
            assert!(
                HistoricalEvidenceSelector::new(
                    HistoricalEvidenceFamily::GovernanceAction,
                    malformed,
                )
                .is_err()
            );
        }
    }

    #[test]
    fn record_digest_has_fixed_family_oracles_and_binds_every_field() {
        let evidence = Sha256Digest::for_bytes(b"evidence");
        let fixtures = [
            (
                HistoricalEvidenceFamily::GovernanceAction,
                id("tool:v1:", 'a'),
                HistoricalEvidenceState::Blocked,
                "b538dd0125355927786a2081877e28f099a11deda1b735544a7c9a4eab83a1a1",
            ),
            (
                HistoricalEvidenceFamily::ProviderAttempt,
                id("provider-attempt:v1:", 'a'),
                HistoricalEvidenceState::Completed,
                "410889741964b4ca348e232caa12c34fc1beb94df1172fc40ecc9a1b6720c45b",
            ),
        ];
        for (family, record_id, state, expected) in fixtures {
            assert_eq!(
                historical_record_sha256(1, family, &record_id, state, &evidence)
                    .expect("record digest"),
                Sha256Digest::parse(expected.to_string()).expect("fixture digest")
            );
        }

        let baseline = historical_record_sha256(
            1,
            HistoricalEvidenceFamily::ProviderAttempt,
            &id("provider-attempt:v1:", 'a'),
            HistoricalEvidenceState::Completed,
            &evidence,
        )
        .expect("baseline");
        for changed in [
            historical_record_sha256(
                2,
                HistoricalEvidenceFamily::ProviderAttempt,
                &id("provider-attempt:v1:", 'a'),
                HistoricalEvidenceState::Completed,
                &evidence,
            ),
            historical_record_sha256(
                1,
                HistoricalEvidenceFamily::GovernanceAction,
                &id("provider-attempt:v1:", 'a'),
                HistoricalEvidenceState::Completed,
                &evidence,
            ),
            historical_record_sha256(
                1,
                HistoricalEvidenceFamily::ProviderAttempt,
                &id("provider-attempt:v1:", 'b'),
                HistoricalEvidenceState::Completed,
                &evidence,
            ),
            historical_record_sha256(
                1,
                HistoricalEvidenceFamily::ProviderAttempt,
                &id("provider-attempt:v1:", 'a'),
                HistoricalEvidenceState::Rejected,
                &evidence,
            ),
            historical_record_sha256(
                1,
                HistoricalEvidenceFamily::ProviderAttempt,
                &id("provider-attempt:v1:", 'a'),
                HistoricalEvidenceState::Completed,
                &Sha256Digest::for_bytes(b"changed"),
            ),
        ] {
            assert_ne!(changed.expect("changed digest"), baseline);
        }
    }

    #[test]
    fn impossible_family_state_pairs_are_rejected() {
        assert!(state_belongs_to_family(
            HistoricalEvidenceFamily::GovernanceAction,
            HistoricalEvidenceState::Blocked
        ));
        assert!(!state_belongs_to_family(
            HistoricalEvidenceFamily::GovernanceAction,
            HistoricalEvidenceState::Completed
        ));
        assert!(!state_belongs_to_family(
            HistoricalEvidenceFamily::ProviderAttempt,
            HistoricalEvidenceState::HandlerCompletedSuccess
        ));
    }
}
