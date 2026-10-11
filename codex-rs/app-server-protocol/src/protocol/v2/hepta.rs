use crate::JsonSchema;
use crate::TS;
use serde::Deserialize;
use serde::Serialize;

pub const HEPTA_EVIDENCE_SUMMARY_SCHEMA_VERSION: u32 = 1;
pub const HEPTA_HISTORICAL_EVIDENCE_SCHEMA_VERSION: u32 = 1;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, Default, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HeptaEvidenceSummaryReadParams {}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HeptaGovernanceEvidenceSummary {
    pub decisions: u64,
    pub receipts: u64,
    pub pending_actions: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HeptaProviderEvidenceSummary {
    pub intents: u64,
    pub receipts: u64,
    pub pending_attempts: u64,
    pub indeterminate_attempts: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HeptaEvidenceSummaryReadResponse {
    pub schema_version: u32,
    pub governance: HeptaGovernanceEvidenceSummary,
    pub provider: HeptaProviderEvidenceSummary,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum HeptaHistoricalEvidenceFamily {
    GovernanceAction,
    ProviderAttempt,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum HeptaHistoricalEvidenceState {
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

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HeptaHistoricalEvidenceReadParams {
    pub family: HeptaHistoricalEvidenceFamily,
    pub record_id: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HeptaHistoricalEvidenceRecord {
    pub schema_version: u32,
    pub family: HeptaHistoricalEvidenceFamily,
    pub record_id: String,
    pub state: HeptaHistoricalEvidenceState,
    pub evidence_sha256: String,
    pub record_sha256: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HeptaHistoricalEvidenceReadResponse {
    pub schema_version: u32,
    pub record: Option<HeptaHistoricalEvidenceRecord>,
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn evidence_summary_exposes_only_composed_families() {
        assert_eq!(
            serde_json::to_value(HeptaEvidenceSummaryReadParams::default())
                .expect("serialize empty evidence summary params"),
            json!({})
        );
        let response = HeptaEvidenceSummaryReadResponse {
            schema_version: HEPTA_EVIDENCE_SUMMARY_SCHEMA_VERSION,
            governance: HeptaGovernanceEvidenceSummary {
                decisions: 2,
                receipts: 1,
                pending_actions: 0,
            },
            provider: HeptaProviderEvidenceSummary {
                intents: 3,
                receipts: 2,
                pending_attempts: 1,
                indeterminate_attempts: 1,
            },
        };
        assert_eq!(
            serde_json::to_value(response).expect("serialize evidence summary"),
            json!({
                "schemaVersion": 1,
                "governance": {"decisions": 2, "receipts": 1, "pendingActions": 0},
                "provider": {
                    "intents": 3,
                    "receipts": 2,
                    "pendingAttempts": 1,
                    "indeterminateAttempts": 1
                }
            })
        );
    }

    #[test]
    fn historical_evidence_uses_exact_typed_ids_and_authoritative_digests() {
        let params = HeptaHistoricalEvidenceReadParams {
            family: HeptaHistoricalEvidenceFamily::GovernanceAction,
            record_id: format!("tool:v1:{}", "a".repeat(64)),
        };
        assert_eq!(
            serde_json::to_value(params).expect("serialize historical evidence params"),
            json!({
                "family": "governanceAction",
                "recordId": format!("tool:v1:{}", "a".repeat(64))
            })
        );

        let response = HeptaHistoricalEvidenceReadResponse {
            schema_version: HEPTA_HISTORICAL_EVIDENCE_SCHEMA_VERSION,
            record: Some(HeptaHistoricalEvidenceRecord {
                schema_version: HEPTA_HISTORICAL_EVIDENCE_SCHEMA_VERSION,
                family: HeptaHistoricalEvidenceFamily::ProviderAttempt,
                record_id: format!("provider-attempt:v1:{}", "b".repeat(64)),
                state: HeptaHistoricalEvidenceState::NotDispatched,
                evidence_sha256: "c".repeat(64),
                record_sha256: "d".repeat(64),
            }),
        };
        assert_eq!(
            serde_json::to_value(response).expect("serialize historical evidence response"),
            json!({
                "schemaVersion": 1,
                "record": {
                    "schemaVersion": 1,
                    "family": "providerAttempt",
                    "recordId": format!("provider-attempt:v1:{}", "b".repeat(64)),
                    "state": "notDispatched",
                    "evidenceSha256": "c".repeat(64),
                    "recordSha256": "d".repeat(64)
                }
            })
        );
        assert!(
            serde_json::from_value::<HeptaHistoricalEvidenceFamily>(json!("channelIngress"))
                .is_err()
        );
        for forbidden in ["accepted", "acknowledged", "notDelivered"] {
            assert!(
                serde_json::from_value::<HeptaHistoricalEvidenceState>(json!(forbidden)).is_err(),
                "unsupported historical state must stay outside the wire contract: {forbidden}"
            );
        }
    }
}
