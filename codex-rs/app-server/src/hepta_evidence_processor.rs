use std::sync::Arc;

use codex_app_server_protocol::HEPTA_EVIDENCE_SUMMARY_SCHEMA_VERSION;
use codex_app_server_protocol::HeptaEvidenceSummaryReadParams;
use codex_app_server_protocol::HeptaEvidenceSummaryReadResponse;
use codex_app_server_protocol::HeptaGovernanceEvidenceSummary;
use codex_app_server_protocol::HeptaHistoricalEvidenceFamily;
use codex_app_server_protocol::HeptaHistoricalEvidenceReadParams;
use codex_app_server_protocol::HeptaHistoricalEvidenceReadResponse;
use codex_app_server_protocol::HeptaHistoricalEvidenceRecord;
use codex_app_server_protocol::HeptaHistoricalEvidenceState;
use codex_app_server_protocol::HeptaProviderEvidenceSummary;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_hepta_evidence::EvidenceSummary;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::HistoricalEvidenceFamily;
use codex_hepta_evidence::HistoricalEvidenceRecord;
use codex_hepta_evidence::HistoricalEvidenceSelector;
use codex_hepta_evidence::HistoricalEvidenceState;
use codex_rollout::StateDbHandle;

use crate::error_code::internal_error;
use crate::error_code::invalid_params;
use crate::error_code::method_not_found;

pub(crate) struct HeptaEvidenceRequestProcessor {
    enabled: bool,
    state_db: Option<StateDbHandle>,
    evidence: tokio::sync::OnceCell<Result<Arc<HeptaEvidenceStore>, Arc<str>>>,
}

impl HeptaEvidenceRequestProcessor {
    pub(crate) fn new(enabled: bool, state_db: Option<StateDbHandle>) -> Self {
        Self {
            enabled,
            state_db,
            evidence: tokio::sync::OnceCell::new(),
        }
    }

    pub(crate) async fn summary_read(
        &self,
        _params: HeptaEvidenceSummaryReadParams,
    ) -> Result<HeptaEvidenceSummaryReadResponse, JSONRPCErrorError> {
        if !self.enabled {
            return Err(method_not_found("Hepta evidence is not enabled"));
        }
        let evidence = self.evidence().await?;
        let summary = evidence.summary().await.map_err(|error| {
            tracing::error!(detail = %error, "Hepta evidence summary failed");
            internal_error("Hepta evidence summary is unavailable")
        })?;
        Ok(summary_response(summary))
    }

    pub(crate) async fn historical_read(
        &self,
        params: HeptaHistoricalEvidenceReadParams,
    ) -> Result<HeptaHistoricalEvidenceReadResponse, JSONRPCErrorError> {
        if !self.enabled {
            return Err(method_not_found("Hepta evidence is not enabled"));
        }
        let family = historical_family(params.family);
        let selector = HistoricalEvidenceSelector::new(family, params.record_id)
            .map_err(|error| invalid_params(format!("invalid Hepta evidence selector: {error}")))?;
        let evidence = self.evidence().await?;
        let record = evidence
            .historical_record(&selector)
            .await
            .map_err(|error| {
                tracing::error!(detail = %error, "Hepta historical evidence read failed");
                internal_error("Hepta historical evidence is unavailable")
            })?
            .map(|record| project_historical_record(record, &selector))
            .transpose()?;
        Ok(HeptaHistoricalEvidenceReadResponse {
            schema_version: codex_app_server_protocol::HEPTA_HISTORICAL_EVIDENCE_SCHEMA_VERSION,
            record,
        })
    }

    async fn evidence(&self) -> Result<Arc<HeptaEvidenceStore>, JSONRPCErrorError> {
        let evidence = self
            .evidence
            .get_or_init(|| async {
                match self.state_db.as_ref() {
                    Some(state_db) => {
                        { HeptaEvidenceStore::open_existing_read_only(state_db.sqlite()) }
                            .await
                            .map(Arc::new)
                            .map_err(|error| Arc::<str>::from(error.to_string()))
                    }
                    None => Err(Arc::from("Codex state runtime is unavailable")),
                }
            })
            .await;
        evidence.clone().map_err(|detail| {
            tracing::error!(%detail, "Hepta evidence store failed to open");
            internal_error("Hepta evidence store is unavailable")
        })
    }
}

fn historical_family(family: HeptaHistoricalEvidenceFamily) -> HistoricalEvidenceFamily {
    match family {
        HeptaHistoricalEvidenceFamily::GovernanceAction => {
            HistoricalEvidenceFamily::GovernanceAction
        }
        HeptaHistoricalEvidenceFamily::ProviderAttempt => HistoricalEvidenceFamily::ProviderAttempt,
    }
}

fn project_historical_record(
    record: HistoricalEvidenceRecord,
    selector: &HistoricalEvidenceSelector,
) -> Result<HeptaHistoricalEvidenceRecord, JSONRPCErrorError> {
    record.validate().map_err(|error| {
        tracing::error!(detail = %error, "Hepta historical evidence record failed validation");
        internal_error("Hepta historical evidence is unavailable")
    })?;
    if record.schema_version()
        != codex_app_server_protocol::HEPTA_HISTORICAL_EVIDENCE_SCHEMA_VERSION
    {
        tracing::error!(
            schema_version = record.schema_version(),
            "Hepta historical evidence schema is unsupported by the protocol"
        );
        return Err(internal_error("Hepta historical evidence is unavailable"));
    }
    if record.family() != selector.family() || record.record_id() != selector.record_id() {
        tracing::error!("Hepta historical evidence store returned a mismatched selector");
        return Err(internal_error("Hepta historical evidence is unavailable"));
    }
    Ok(HeptaHistoricalEvidenceRecord {
        schema_version: record.schema_version(),
        family: project_historical_family(record.family()),
        record_id: record.record_id().to_string(),
        state: project_historical_state(record.state()),
        evidence_sha256: record.evidence_sha256().as_str().to_string(),
        record_sha256: record.record_sha256().as_str().to_string(),
    })
}

fn project_historical_family(family: HistoricalEvidenceFamily) -> HeptaHistoricalEvidenceFamily {
    match family {
        HistoricalEvidenceFamily::GovernanceAction => {
            HeptaHistoricalEvidenceFamily::GovernanceAction
        }
        HistoricalEvidenceFamily::ProviderAttempt => HeptaHistoricalEvidenceFamily::ProviderAttempt,
    }
}

fn project_historical_state(state: HistoricalEvidenceState) -> HeptaHistoricalEvidenceState {
    match state {
        HistoricalEvidenceState::Pending => HeptaHistoricalEvidenceState::Pending,
        HistoricalEvidenceState::HandlerCompletedSuccess => {
            HeptaHistoricalEvidenceState::HandlerCompletedSuccess
        }
        HistoricalEvidenceState::HandlerCompletedFailure => {
            HeptaHistoricalEvidenceState::HandlerCompletedFailure
        }
        HistoricalEvidenceState::Blocked => HeptaHistoricalEvidenceState::Blocked,
        HistoricalEvidenceState::HandlerFailedBeforeExecution => {
            HeptaHistoricalEvidenceState::HandlerFailedBeforeExecution
        }
        HistoricalEvidenceState::HandlerFailedAfterExecution => {
            HeptaHistoricalEvidenceState::HandlerFailedAfterExecution
        }
        HistoricalEvidenceState::Aborted => HeptaHistoricalEvidenceState::Aborted,
        HistoricalEvidenceState::Completed => HeptaHistoricalEvidenceState::Completed,
        HistoricalEvidenceState::Rejected => HeptaHistoricalEvidenceState::Rejected,
        HistoricalEvidenceState::NotDispatched => HeptaHistoricalEvidenceState::NotDispatched,
        HistoricalEvidenceState::Indeterminate => HeptaHistoricalEvidenceState::Indeterminate,
    }
}

fn summary_response(summary: EvidenceSummary) -> HeptaEvidenceSummaryReadResponse {
    HeptaEvidenceSummaryReadResponse {
        schema_version: HEPTA_EVIDENCE_SUMMARY_SCHEMA_VERSION,
        governance: HeptaGovernanceEvidenceSummary {
            decisions: summary.governance.decisions,
            receipts: summary.governance.receipts,
            pending_actions: summary.governance.pending_actions,
        },
        provider: HeptaProviderEvidenceSummary {
            intents: summary.provider.intents,
            receipts: summary.provider.receipts,
            pending_attempts: summary.provider.pending_attempts,
            indeterminate_attempts: summary.provider.indeterminate_attempts,
        },
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_evidence::HISTORICAL_EVIDENCE_SCHEMA_VERSION;
    use codex_utils_absolute_path::AbsolutePathBuf;

    use crate::error_code::INTERNAL_ERROR_CODE;
    use crate::error_code::METHOD_NOT_FOUND_ERROR_CODE;

    use super::*;

    #[tokio::test]
    async fn disabled_product_does_not_expose_hepta_evidence() {
        let processor = HeptaEvidenceRequestProcessor::new(false, None);
        let error = processor
            .summary_read(HeptaEvidenceSummaryReadParams {})
            .await
            .expect_err("ordinary Codex must not expose Hepta evidence");
        assert_eq!(error.code, METHOD_NOT_FOUND_ERROR_CODE);
    }

    #[tokio::test]
    async fn enabled_product_without_state_runtime_fails_closed() {
        let processor = HeptaEvidenceRequestProcessor::new(true, None);
        let error = processor
            .summary_read(HeptaEvidenceSummaryReadParams {})
            .await
            .expect_err("missing state runtime must fail closed");
        assert_eq!(error.code, INTERNAL_ERROR_CODE);
    }

    #[tokio::test]
    async fn enabled_product_without_existing_evidence_store_fails_closed_without_creating_it() {
        let temp = tempfile::TempDir::new().expect("temporary state home");
        let sqlite = codex_state::SqliteConfig::new_for_testing(
            AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute state home"),
        );
        let state_db = codex_state::StateRuntime::init(sqlite, "test-provider".to_string())
            .await
            .expect("initialize state runtime");
        let evidence_path = temp.path().join("hepta_evidence_2.sqlite");
        assert!(!evidence_path.exists());
        let processor = HeptaEvidenceRequestProcessor::new(true, Some(state_db.clone()));

        let error = processor
            .summary_read(HeptaEvidenceSummaryReadParams {})
            .await
            .expect_err("a diagnostic read must not create the evidence store");
        assert_eq!(error.code, INTERNAL_ERROR_CODE);
        assert!(!evidence_path.exists());

        drop(processor);
        state_db.close().await;
    }

    #[tokio::test]
    async fn enabled_product_reads_an_explicitly_composed_empty_store() {
        let temp = tempfile::TempDir::new().expect("temporary state home");
        let sqlite = codex_state::SqliteConfig::new_for_testing(
            AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute state home"),
        );
        let state_db = codex_state::StateRuntime::init(sqlite, "test-provider".to_string())
            .await
            .expect("initialize state runtime");
        let evidence_store = HeptaEvidenceStore::open(state_db.sqlite())
            .await
            .expect("explicitly compose the evidence store");
        let processor = HeptaEvidenceRequestProcessor::new(true, Some(state_db.clone()));

        let summary = processor
            .summary_read(HeptaEvidenceSummaryReadParams {})
            .await
            .expect("read empty evidence summary");
        assert_eq!(
            summary.schema_version,
            HEPTA_EVIDENCE_SUMMARY_SCHEMA_VERSION
        );
        assert_eq!(summary.governance.decisions, 0);
        assert_eq!(summary.governance.receipts, 0);
        assert_eq!(summary.governance.pending_actions, 0);
        assert_eq!(summary.provider.intents, 0);
        assert_eq!(summary.provider.receipts, 0);
        assert_eq!(summary.provider.pending_attempts, 0);
        assert_eq!(summary.provider.indeterminate_attempts, 0);

        let historical = processor
            .historical_read(HeptaHistoricalEvidenceReadParams {
                family: HeptaHistoricalEvidenceFamily::ProviderAttempt,
                record_id: format!("provider-attempt:v1:{}", "a".repeat(64)),
            })
            .await
            .expect("read missing exact historical record");
        assert_eq!(
            historical.schema_version,
            codex_app_server_protocol::HEPTA_HISTORICAL_EVIDENCE_SCHEMA_VERSION
        );
        assert!(historical.record.is_none());

        drop(processor);
        drop(evidence_store);
        state_db.close().await;
    }

    #[tokio::test]
    async fn disabled_product_does_not_expose_historical_evidence() {
        let processor = HeptaEvidenceRequestProcessor::new(false, None);
        let error = processor
            .historical_read(HeptaHistoricalEvidenceReadParams {
                family: HeptaHistoricalEvidenceFamily::GovernanceAction,
                record_id: format!("tool:v1:{}", "a".repeat(64)),
            })
            .await
            .expect_err("ordinary Codex must not expose historical Hepta evidence");
        assert_eq!(error.code, METHOD_NOT_FOUND_ERROR_CODE);
    }

    #[tokio::test]
    async fn historical_evidence_rejects_malformed_exact_id_before_store_open() {
        let processor = HeptaEvidenceRequestProcessor::new(true, None);
        let error = processor
            .historical_read(HeptaHistoricalEvidenceReadParams {
                family: HeptaHistoricalEvidenceFamily::ProviderAttempt,
                record_id: "not-an-attempt".to_string(),
            })
            .await
            .expect_err("malformed historical selector must fail closed");
        assert_eq!(error.code, crate::error_code::INVALID_PARAMS_ERROR_CODE);
    }

    #[tokio::test]
    async fn historical_evidence_rejects_cross_family_id_before_store_open() {
        let processor = HeptaEvidenceRequestProcessor::new(true, None);
        let error = processor
            .historical_read(HeptaHistoricalEvidenceReadParams {
                family: HeptaHistoricalEvidenceFamily::ProviderAttempt,
                record_id: format!("tool:v1:{}", "a".repeat(64)),
            })
            .await
            .expect_err("cross-family selector must fail before store access");
        assert_eq!(error.code, crate::error_code::INVALID_PARAMS_ERROR_CODE);
    }

    #[tokio::test]
    async fn valid_historical_selector_reaches_store_and_fails_closed_without_runtime() {
        let processor = HeptaEvidenceRequestProcessor::new(true, None);
        let error = processor
            .historical_read(HeptaHistoricalEvidenceReadParams {
                family: HeptaHistoricalEvidenceFamily::GovernanceAction,
                record_id: format!("tool:v1:{}", "a".repeat(64)),
            })
            .await
            .expect_err("valid selector must reach the unavailable store");
        assert_eq!(error.code, INTERNAL_ERROR_CODE);
    }

    #[test]
    fn historical_projection_maps_every_supported_family_and_state() {
        assert_eq!(
            codex_app_server_protocol::HEPTA_HISTORICAL_EVIDENCE_SCHEMA_VERSION,
            HISTORICAL_EVIDENCE_SCHEMA_VERSION
        );
        for (source, expected, wire) in [
            (
                HistoricalEvidenceFamily::GovernanceAction,
                HeptaHistoricalEvidenceFamily::GovernanceAction,
                "governanceAction",
            ),
            (
                HistoricalEvidenceFamily::ProviderAttempt,
                HeptaHistoricalEvidenceFamily::ProviderAttempt,
                "providerAttempt",
            ),
        ] {
            let projected = project_historical_family(source);
            assert_eq!(projected, expected);
            assert_eq!(historical_family(projected), source);
            assert_eq!(
                serde_json::to_value(projected).expect("serialize projected family"),
                serde_json::Value::String(wire.to_string())
            );
        }
        for (source, wire) in [
            (HistoricalEvidenceState::Pending, "pending"),
            (
                HistoricalEvidenceState::HandlerCompletedSuccess,
                "handlerCompletedSuccess",
            ),
            (
                HistoricalEvidenceState::HandlerCompletedFailure,
                "handlerCompletedFailure",
            ),
            (HistoricalEvidenceState::Blocked, "blocked"),
            (
                HistoricalEvidenceState::HandlerFailedBeforeExecution,
                "handlerFailedBeforeExecution",
            ),
            (
                HistoricalEvidenceState::HandlerFailedAfterExecution,
                "handlerFailedAfterExecution",
            ),
            (HistoricalEvidenceState::Aborted, "aborted"),
            (HistoricalEvidenceState::Completed, "completed"),
            (HistoricalEvidenceState::Rejected, "rejected"),
            (HistoricalEvidenceState::NotDispatched, "notDispatched"),
            (HistoricalEvidenceState::Indeterminate, "indeterminate"),
        ] {
            assert_eq!(
                serde_json::to_value(project_historical_state(source))
                    .expect("serialize projected state"),
                serde_json::Value::String(wire.to_string())
            );
        }
    }

    #[test]
    fn evidence_projection_maps_every_authoritative_count() {
        let response = summary_response(EvidenceSummary {
            governance: codex_hepta_evidence::GovernanceEvidenceSummary {
                decisions: 1,
                receipts: 2,
                pending_actions: 3,
            },
            provider: codex_hepta_evidence::ProviderEvidenceSummary {
                intents: 4,
                receipts: 5,
                pending_attempts: 6,
                indeterminate_attempts: 7,
            },
        });

        assert_eq!(response.schema_version, 1);
        assert_eq!(response.governance.decisions, 1);
        assert_eq!(response.governance.receipts, 2);
        assert_eq!(response.governance.pending_actions, 3);
        assert_eq!(response.provider.intents, 4);
        assert_eq!(response.provider.receipts, 5);
        assert_eq!(response.provider.pending_attempts, 6);
        assert_eq!(response.provider.indeterminate_attempts, 7);
    }
}
