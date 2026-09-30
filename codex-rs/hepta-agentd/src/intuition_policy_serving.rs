//! Authenticated intuition gate on the canonical Agentd serving path.
//!
//! Production is fail-closed even when both the host and invocation are absent.
//! Compatibility bypass requires an explicit non-production startup profile.
//! The host authenticates V3 evidence and owns the durable signed ledger.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::ProductionDispositionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::intelligence_ingress::AgentdIntuitionProductInvocationV1;
use crate::intelligence_product::AgentdIntelligenceProductOutcomeV1;
use crate::intuition_policy::AgentdIntuitionDecisionReceiptV2;
use crate::state::AgentdState;

const REQUEST_METRIC: &str = "codex.hepta.intuition.policy.request";
const OUTCOME_METRIC: &str = "codex.hepta.intuition.policy.outcome";
const FAILURE_METRIC: &str = "codex.hepta.intuition.policy.failure";
const DURATION_METRIC: &str = "codex.hepta.intuition.policy.duration";
const LEDGER_APPEND_METRIC: &str = "codex.hepta.intuition.policy.ledger_append";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ServingProfile {
    Development,
    Test,
    Production,
}

impl ServingProfile {
    fn parse(value: Option<&str>, test_build: bool) -> Result<Self, &'static str> {
        match value {
            None | Some("production") => Ok(Self::Production),
            Some("development") => Ok(Self::Development),
            Some("test") if test_build => Ok(Self::Test),
            Some("test") => Err("agentd.intuition.profile.test_unavailable_in_product"),
            Some(_) => Err("agentd.intuition.profile.invalid"),
        }
    }

    /// Resolve once while building AgentdState, before opening serving paths.
    /// Runtime requests never re-read environment variables or a global cache.
    pub(crate) fn from_environment() -> Result<Self, AgentdError> {
        let result = match std::env::var("HEPTA_INTUITION_PROFILE") {
            Ok(value) => Self::parse(Some(&value), cfg!(test)),
            Err(std::env::VarError::NotPresent) => Self::parse(None, cfg!(test)),
            Err(std::env::VarError::NotUnicode(_)) => Err("agentd.intuition.profile.invalid"),
        };
        result.map_err(|code| AgentdError::Invalid(code.to_string()))
    }

    pub(crate) fn require_host(self, product_ready: bool) -> Result<(), &'static str> {
        if self == Self::Production && !product_ready {
            Err("agentd.intuition.service.production_product_host_required")
        } else {
            Ok(())
        }
    }

    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Development => "development",
            Self::Test => "test",
            Self::Production => "production",
        }
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn authenticate_canonical_intuition(
    state: &AgentdState,
    product: Option<AgentdIntuitionProductInvocationV1>,
    request: CalibratedDecisionRequestV1,
    episode_id: StableId,
    run_snapshot_digest: Digest32,
    canonical: &AgentdIntelligenceProductOutcomeV1,
    now: u64,
) -> Result<Option<AgentdIntuitionDecisionReceiptV2>, AgentdError> {
    let started = Instant::now();
    let profile = state.intuition_serving_profile;
    record_request(profile.as_str());
    let span = tracing::info_span!(
        "hepta.intuition_policy.authenticate",
        profile = profile.as_str()
    );
    let _entered = span.enter();

    let result: Result<Option<AgentdIntuitionDecisionReceiptV2>, AgentdError> = (|| {
        let host = state.intuition_policy.get();
        state.require_intuition_host_configuration()?;
        let product = match (host.is_some(), product) {
            (false, None) => return Ok(None),
            (true, Some(product)) => product,
            (true, None) => {
                return Err(AgentdError::Invalid(
                    "agentd.intuition.service.authenticated_invocation_required".to_string(),
                ));
            }
            (false, Some(_)) => {
                return Err(AgentdError::Invalid(
                    "agentd.intuition.service.product_host_required".to_string(),
                ));
            }
        };

        let AgentdIntuitionProductInvocationV1 {
            profile,
            scoring,
            assignment,
            completeness_evidence,
            profile_qualification_evidence,
            runtime_evidence,
            expected_ledger_head,
            decision_evidence,
        } = product;
        let policy_prepared = {
            let qualification = IntuitionQualificationEvidenceV2 {
                completeness: &completeness_evidence,
                profile_qualification: &profile_qualification_evidence,
                runtime: &runtime_evidence,
            };
            state
                .prepare_intuition_policy_v3(
                    request,
                    profile,
                    scoring,
                    assignment,
                    qualification,
                    episode_id,
                    run_snapshot_digest,
                    now,
                )
                .map_err(AgentdError::from)?
        };
        require_outcome_parity(
            canonical,
            &policy_prepared.decision().decision.disposition,
            &policy_prepared.decision().decision.propensities,
        )?;

        // Final-use time and current trust are sampled inside the sole
        // LedgerWriter lock; the serving caller cannot extend a prepared lease.
        let committed = state
            .commit_intuition_policy_v4(policy_prepared, expected_ledger_head, decision_evidence)
            .map_err(AgentdError::from)?;
        let final_check = (|| {
            require_outcome_parity(
                canonical,
                &committed.decision.decision.disposition,
                &committed.decision.decision.propensities,
            )?;
            match &committed.decision.decision.disposition {
                ProductionDispositionV1::Selected(_) if committed.learning.is_none() => {
                    Err(AgentdError::Protocol(
                        "agentd.intuition.service.selected_without_durable_decision".to_string(),
                    ))
                }
                ProductionDispositionV1::Abstained(_) | ProductionDispositionV1::SlowPath(_)
                    if committed.learning.is_some() =>
                {
                    Err(AgentdError::Protocol(
                        "agentd.intuition.service.nonselected_with_decision".to_string(),
                    ))
                }
                _ => Ok(()),
            }
        })();
        if let Err(source) = final_check {
            return Err(
                crate::AgentdIntuitionServiceErrorV1::AdmissionFailedAfterPolicy {
                    receipt: committed,
                    source: Box::new(source),
                }
                .into(),
            );
        }
        Ok(Some(committed))
    })();

    record_result(profile, started.elapsed(), &result);
    result
}

fn record_request(profile: &'static str) {
    emit_counter(REQUEST_METRIC, &[("profile", profile)]);
}

fn record_result(
    profile: ServingProfile,
    elapsed: Duration,
    result: &Result<Option<AgentdIntuitionDecisionReceiptV2>, AgentdError>,
) {
    match result {
        Ok(Some(receipt)) => {
            let disposition = disposition_tag(&receipt.decision.decision.disposition);
            let durable_append = if receipt.learning.is_some() {
                "true"
            } else {
                "false"
            };
            emit_counter(
                OUTCOME_METRIC,
                &[
                    ("profile", profile.as_str()),
                    ("status", "succeeded"),
                    ("disposition", disposition),
                    ("durable_append", durable_append),
                ],
            );
            if receipt.learning.is_some() {
                emit_counter(
                    LEDGER_APPEND_METRIC,
                    &[("profile", profile.as_str()), ("status", "committed")],
                );
            }
            emit_duration(
                DURATION_METRIC,
                elapsed,
                &[("profile", profile.as_str()), ("status", "succeeded")],
            );
            tracing::info!(
                profile = profile.as_str(),
                disposition,
                durable_append,
                elapsed_ms = elapsed.as_millis(),
                "intuition policy request completed"
            );
        }
        Ok(None) => {
            emit_counter(
                OUTCOME_METRIC,
                &[
                    ("profile", profile.as_str()),
                    ("status", "bypassed"),
                    ("disposition", "none"),
                    ("durable_append", "false"),
                ],
            );
            emit_duration(
                DURATION_METRIC,
                elapsed,
                &[("profile", profile.as_str()), ("status", "bypassed")],
            );
            tracing::info!(
                profile = profile.as_str(),
                elapsed_ms = elapsed.as_millis(),
                "intuition policy compatibility bypass completed"
            );
        }
        Err(error) => record_failure(profile.as_str(), elapsed, error),
    }
}

fn record_failure(profile: &'static str, elapsed: Duration, error: &AgentdError) {
    let error_class = agentd_error_class(error);
    let reason_code = agentd_error_reason(error);
    emit_counter(
        FAILURE_METRIC,
        &[
            ("profile", profile),
            ("error_class", error_class),
            ("reason_code", reason_code),
        ],
    );
    emit_duration(
        DURATION_METRIC,
        elapsed,
        &[("profile", profile), ("status", "failed")],
    );
    tracing::warn!(
        profile,
        error_class,
        reason_code,
        error = %error,
        elapsed_ms = elapsed.as_millis(),
        "intuition policy request rejected"
    );
}

fn emit_counter(name: &'static str, tags: &[(&str, &str)]) {
    let Some(metrics) = codex_otel::global() else {
        return;
    };
    if let Err(error) = metrics.counter(name, 1, tags) {
        tracing::debug!(metric = name, error = %error, "intuition policy counter emission failed");
    }
}

fn emit_duration(name: &'static str, duration: Duration, tags: &[(&str, &str)]) {
    let Some(metrics) = codex_otel::global() else {
        return;
    };
    if let Err(error) = metrics.record_duration(name, duration, tags) {
        tracing::debug!(metric = name, error = %error, "intuition policy duration emission failed");
    }
}

const fn disposition_tag(disposition: &ProductionDispositionV1) -> &'static str {
    match disposition {
        ProductionDispositionV1::Selected(_) => "selected",
        ProductionDispositionV1::Abstained(_) => "abstained",
        ProductionDispositionV1::SlowPath(_) => "slow_path",
    }
}

const fn agentd_error_class(error: &AgentdError) -> &'static str {
    match error {
        AgentdError::Invalid(_) => "invalid",
        AgentdError::GenerationFenced(_) => "generation_fenced",
        AgentdError::CognitiveWriteRuntimeUnavailable => "runtime_unavailable",
        AgentdError::Protocol(_) => "protocol",
        AgentdError::IntuitionPolicy(_) => "intuition_policy",
        AgentdError::Overloaded { .. } => "overloaded",
        AgentdError::Fleet(_) => "fleet",
        AgentdError::Automation(_) => "automation",
        AgentdError::Io(_) => "io",
        AgentdError::Json(_) => "json",
        AgentdError::ProductionWriter(_) => "production_writer",
        AgentdError::ProductionCognitiveMutation(_) => "production_cognitive_mutation",
        AgentdError::CognitiveStore(_) => "cognitive_store",
    }
}

fn agentd_error_reason(error: &AgentdError) -> &'static str {
    match error {
        AgentdError::IntuitionPolicy(source) => source.code(),
        _ => agentd_error_class(error),
    }
}

fn require_outcome_parity(
    canonical: &AgentdIntelligenceProductOutcomeV1,
    authenticated: &ProductionDispositionV1,
    propensities: &[codex_hepta_intuition::CalibratedCandidatePropensityV1],
) -> Result<(), AgentdError> {
    let matches = match canonical {
        AgentdIntelligenceProductOutcomeV1::Ready(prepared) => require_decision_parity(
            &prepared.envelope.decision.decision,
            authenticated,
            propensities,
        ),
        AgentdIntelligenceProductOutcomeV1::Abstained => {
            matches!(authenticated, ProductionDispositionV1::Abstained(_))
        }
        AgentdIntelligenceProductOutcomeV1::SlowPath => {
            matches!(authenticated, ProductionDispositionV1::SlowPath(_))
        }
    };
    if matches {
        Ok(())
    } else {
        Err(AgentdError::Protocol(
            "agentd.intuition.service.advisory_disposition_mismatch".to_string(),
        ))
    }
}

fn require_decision_parity(
    canonical: &AdvisoryDecisionV1,
    authenticated: &ProductionDispositionV1,
    propensities: &[codex_hepta_intuition::CalibratedCandidatePropensityV1],
) -> bool {
    match (canonical, authenticated) {
        (
            AdvisoryDecisionV1::Selected {
                candidate_id,
                propensity,
            },
            ProductionDispositionV1::Selected(authenticated_id),
        ) if candidate_id == authenticated_id && propensity.raw() > 0 => {
            let mut matching = propensities
                .iter()
                .filter(|row| &row.candidate_id == authenticated_id);
            matching
                .next()
                .is_some_and(|row| row.probability == *propensity)
                && matching.next().is_none()
        }
        (AdvisoryDecisionV1::Abstained, ProductionDispositionV1::Abstained(_)) => true,
        (AdvisoryDecisionV1::SlowPath, ProductionDispositionV1::SlowPath(_)) => true,
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_intuition::CalibratedCandidatePropensityV1;
    use codex_hepta_intuition::ProductionSlowPathReasonV1;
    use codex_hepta_types::ProbabilityQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    #[test]
    fn missing_profile_defaults_to_production_in_all_builds() {
        assert_eq!(
            ServingProfile::parse(None, false),
            Ok(ServingProfile::Production)
        );
        assert_eq!(
            ServingProfile::parse(None, true),
            Ok(ServingProfile::Production)
        );
    }

    #[test]
    fn production_profile_rejects_missing_or_legacy_only_host() {
        assert!(ServingProfile::Production.require_host(false).is_err());
        assert!(ServingProfile::Production.require_host(true).is_ok());
    }

    #[test]
    fn compatibility_profile_must_be_explicit() {
        assert_eq!(
            ServingProfile::parse(Some("development"), false),
            Ok(ServingProfile::Development)
        );
        assert!(ServingProfile::Development.require_host(false).is_ok());
        assert_eq!(
            ServingProfile::parse(Some("test"), true),
            Ok(ServingProfile::Test)
        );
        assert!(ServingProfile::Test.require_host(false).is_ok());
        assert!(ServingProfile::parse(Some("test"), false).is_err());
    }

    #[test]
    fn malformed_profiles_do_not_fall_back() {
        for value in [
            "",
            "Production",
            " production",
            "production ",
            "fixture",
            "prod",
            "unknown",
        ] {
            assert!(ServingProfile::parse(Some(value), true).is_err());
        }
    }

    #[test]
    fn telemetry_dimensions_are_stable_and_low_cardinality() {
        assert_eq!(ServingProfile::Development.as_str(), "development");
        assert_eq!(ServingProfile::Test.as_str(), "test");
        assert_eq!(ServingProfile::Production.as_str(), "production");
        assert_eq!(
            agentd_error_class(&AgentdError::Invalid("request-specific detail".to_string())),
            "invalid"
        );
        assert_eq!(
            agentd_error_class(&AgentdError::Protocol(
                "request-specific detail".to_string()
            )),
            "protocol"
        );
        assert_eq!(
            agentd_error_class(&AgentdError::Overloaded { retry_after_ms: 10 }),
            "overloaded"
        );
    }

    #[test]
    fn telemetry_retains_static_policy_reason_without_request_details() {
        let expiry = AgentdError::from(crate::AgentdIntuitionServiceErrorV1::Policy(
            crate::AgentdIntuitionPolicyError::PreparedEvidenceExpired,
        ));
        assert_eq!(
            agentd_error_reason(&expiry),
            "agentd.intuition.prepared_evidence_expired"
        );
        let arbitrary = AgentdError::Invalid("secret/request/arbitrary text".to_string());
        assert_eq!(agentd_error_reason(&arbitrary), "invalid");
    }

    #[test]
    fn decision_parity_requires_exact_selected_candidate_and_propensity() {
        let candidate = id("candidate:one");
        let canonical = AdvisoryDecisionV1::Selected {
            candidate_id: candidate.clone(),
            propensity: ProbabilityQ32::ONE,
        };
        let rows = vec![CalibratedCandidatePropensityV1 {
            candidate_id: candidate.clone(),
            probability: ProbabilityQ32::ONE,
        }];
        assert!(require_decision_parity(
            &canonical,
            &ProductionDispositionV1::Selected(candidate),
            &rows
        ));
        assert!(!require_decision_parity(
            &canonical,
            &ProductionDispositionV1::Selected(id("candidate:two")),
            &rows
        ));
    }

    #[test]
    fn decision_parity_rejects_zero_missing_duplicate_and_changed_propensity() {
        let candidate = id("candidate:one");
        let selected = ProductionDispositionV1::Selected(candidate.clone());
        let canonical = AdvisoryDecisionV1::Selected {
            candidate_id: candidate.clone(),
            propensity: ProbabilityQ32::ONE,
        };
        let row = CalibratedCandidatePropensityV1 {
            candidate_id: candidate.clone(),
            probability: ProbabilityQ32::ONE,
        };
        assert!(!require_decision_parity(&canonical, &selected, &[]));
        assert!(!require_decision_parity(
            &canonical,
            &selected,
            &[row.clone(), row]
        ));
        let zero_row = CalibratedCandidatePropensityV1 {
            candidate_id: candidate.clone(),
            probability: ProbabilityQ32::ZERO,
        };
        assert!(!require_decision_parity(
            &canonical,
            &selected,
            std::slice::from_ref(&zero_row)
        ));
        let zero_canonical = AdvisoryDecisionV1::Selected {
            candidate_id: candidate,
            propensity: ProbabilityQ32::ZERO,
        };
        assert!(!require_decision_parity(
            &zero_canonical,
            &selected,
            &[zero_row]
        ));
    }

    #[test]
    fn terminal_outcome_parity_preserves_disposition_class() {
        let authenticated =
            ProductionDispositionV1::SlowPath(ProductionSlowPathReasonV1::ProfileRiskRule);
        assert!(
            require_outcome_parity(
                &AgentdIntelligenceProductOutcomeV1::SlowPath,
                &authenticated,
                &[]
            )
            .is_ok()
        );
        assert!(
            require_outcome_parity(
                &AgentdIntelligenceProductOutcomeV1::Abstained,
                &authenticated,
                &[]
            )
            .is_err()
        );
    }
}
