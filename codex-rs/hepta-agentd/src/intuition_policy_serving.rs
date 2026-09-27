//! Authenticated intuition gate on the canonical Agentd serving path.
//!
//! Production is fail-closed even when both the host and invocation are absent.
//! Compatibility bypass requires an explicit non-production profile. The
//! product host authenticates V3 evidence and owns the durable signed ledger;
//! an advisory result alone never grants production admission.

use std::sync::OnceLock;

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ServingProfile {
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

    fn require_host(self, product_ready: bool) -> Result<(), &'static str> {
        if self == Self::Production && !product_ready {
            Err("agentd.intuition.service.production_product_host_required")
        } else {
            Ok(())
        }
    }
}

fn serving_profile() -> Result<ServingProfile, AgentdError> {
    // Pin the process profile on first access. Runtime environment changes must
    // not demote an already serving production process into compatibility mode.
    static PROFILE: OnceLock<Result<ServingProfile, &'static str>> = OnceLock::new();
    let profile = PROFILE.get_or_init(|| match std::env::var("HEPTA_INTUITION_PROFILE") {
        Ok(value) => ServingProfile::parse(Some(&value), cfg!(test)),
        Err(std::env::VarError::NotPresent) => ServingProfile::parse(None, cfg!(test)),
        Err(std::env::VarError::NotUnicode(_)) => Err("agentd.intuition.profile.invalid"),
    });
    (*profile).map_err(|code| AgentdError::Invalid(code.to_string()))
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
    let host = state.intuition_policy.get();
    serving_profile()?
        .require_host(host.is_some_and(|host| host.is_product_ready()))
        .map_err(|code| AgentdError::Invalid(code.to_string()))?;
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

    // Signature verification and advisory preparation consume time. A lease
    // validated at prepare cannot be extended by replaying its old timestamp.
    let commit_now = crate::authbus_ingress::now_ms()?;
    let committed = state
        .commit_intuition_policy_v3(
            policy_prepared,
            expected_ledger_head,
            decision_evidence,
            commit_now,
        )
        .map_err(AgentdError::from)?;
    require_outcome_parity(
        canonical,
        &committed.decision.decision.disposition,
        &committed.decision.decision.propensities,
    )?;

    match &committed.decision.decision.disposition {
        ProductionDispositionV1::Selected(_) if committed.learning.is_none() => {
            return Err(AgentdError::Protocol(
                "agentd.intuition.service.selected_without_durable_decision".to_string(),
            ));
        }
        ProductionDispositionV1::Abstained(_) | ProductionDispositionV1::SlowPath(_)
            if committed.learning.is_some() =>
        {
            return Err(AgentdError::Protocol(
                "agentd.intuition.service.nonselected_with_decision".to_string(),
            ));
        }
        _ => {}
    }
    Ok(Some(committed))
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
            &rows,
        ));
        assert!(!require_decision_parity(
            &canonical,
            &ProductionDispositionV1::Selected(id("candidate:two")),
            &rows,
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
            &[row.clone(), row],
        ));
        let zero_row = CalibratedCandidatePropensityV1 {
            candidate_id: candidate.clone(),
            probability: ProbabilityQ32::ZERO,
        };
        assert!(!require_decision_parity(
            &canonical,
            &selected,
            std::slice::from_ref(&zero_row),
        ));
        let zero_canonical = AdvisoryDecisionV1::Selected {
            candidate_id: candidate,
            propensity: ProbabilityQ32::ZERO,
        };
        assert!(!require_decision_parity(
            &zero_canonical,
            &selected,
            &[zero_row],
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
                &[],
            )
            .is_ok()
        );
        assert!(
            require_outcome_parity(
                &AgentdIntelligenceProductOutcomeV1::Abstained,
                &authenticated,
                &[],
            )
            .is_err()
        );
    }
}
