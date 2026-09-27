//! Closed-world verification policies. A caller selects a named question, not
//! an arbitrary role subset. Gate consumers must require their expected profile;
//! support for one profile is not support for another or release authority.

use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceError;
use crate::EvidenceIssuerRoleV1;
use crate::VerifyChainRequestV1;

macro_rules! profiles {
    ($($name:ident => ($wire:literal, $claim:ident, [$($role:ident),+])),+ $(,)?) => {
        #[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
        #[serde(rename_all = "snake_case")]
        pub enum EvidenceVerificationProfileV1 { $($name),+ }

        impl EvidenceVerificationProfileV1 {
            pub const ALL: &'static [Self] = &[$(Self::$name),+];

            pub fn as_str(self) -> &'static str {
                match self { $(Self::$name => $wire),+ }
            }

            pub fn parse(value: &str) -> Result<Self, String> {
                match value {
                    $($wire => Ok(Self::$name)),+,
                    _ => Err("unknown owner-controlled evidence verification profile".to_string()),
                }
            }

            pub fn claim_class(self) -> EvidenceClaimClassV1 {
                match self { $(Self::$name => EvidenceClaimClassV1::$claim),+ }
            }

            pub fn required_roles(self) -> &'static [EvidenceIssuerRoleV1] {
                match self { $(Self::$name => &[$(EvidenceIssuerRoleV1::$role),+]),+ }
            }
        }
    };
}

profiles! {
    ExactSourceArchitecture => ("exact_source_architecture", ExactSource, [Architecture]),
    SyntheticMergeArchitecture => ("synthetic_merge_architecture", SyntheticMerge, [Architecture]),
    MandatoryTestsGeneratorEvaluator => ("mandatory_tests_generator_evaluator", MandatoryTests, [Generator, Evaluator]),
    MandatoryTestsReviewed => ("mandatory_tests_reviewed", MandatoryTests, [Generator, Evaluator, Reviewer]),
    FixtureEvaluator => ("fixture_evaluator", Fixture, [Evaluator]),
    HardwareEvaluator => ("hardware_evaluator", Hardware, [Evaluator]),
    CausalEvaluator => ("causal_evaluator", Causal, [Evaluator]),
    LongitudinalEvaluator => ("longitudinal_evaluator", Longitudinal, [Evaluator]),
    SecurityResourceSecurity => ("security_resource_security", SecurityResource, [Security]),
    ProviderEffectTerminalObserver => ("provider_effect_terminal_observer", ProviderEffect, [TerminalObserver]),
    IndependentArchitecture => ("independent_architecture", IndependentDecision, [Architecture]),
    IndependentArchitectureSecurity => ("independent_architecture_security", IndependentDecision, [Architecture, Security]),
    IndependentDurability => ("independent_durability", IndependentDecision, [Durability]),
    IndependentLearning => ("independent_learning", IndependentDecision, [Learning]),
    IndependentSecurity => ("independent_security", IndependentDecision, [Security]),
    IndependentOperator => ("independent_operator", IndependentDecision, [Operator]),
    IndependentDocumentation => ("independent_documentation", IndependentDecision, [Documentation]),
    ConformanceReviewer => ("conformance_reviewer", Conformance, [Reviewer]),
    AlgorithmFaultReviewer => ("algorithm_fault_reviewer", AlgorithmFault, [Reviewer]),
    RuntimeTerminalObserver => ("runtime_terminal_observer", Runtime, [TerminalObserver]),
    OutboxTerminalObserver => ("outbox_terminal_observer", Outbox, [TerminalObserver]),
    ReconciliationTerminalObserver => ("reconciliation_terminal_observer", Reconciliation, [TerminalObserver]),
    UnlearningReviewer => ("unlearning_reviewer", Unlearning, [Reviewer]),
    OperatorAcceptanceOperator => ("operator_acceptance_operator", OperatorAcceptance, [Operator]),
    RegistrySnapshotReviewer => ("registry_snapshot_reviewer", RegistrySnapshot, [Reviewer]),
}

impl EvidenceVerificationProfileV1 {
    /// Bounded V1 wire compatibility, NOT an ad-hoc policy constructor. Only an
    /// exact registered claim/role set is representable. Empty, duplicate,
    /// unknown, subset and mixed-policy combinations fail closed.
    pub fn from_legacy_roles(
        claim: EvidenceClaimClassV1,
        roles: &[EvidenceIssuerRoleV1],
    ) -> Result<Self, EvidenceError> {
        if roles.is_empty() || roles.len() > 32 {
            return Err(invalid("verification requires a non-empty registered role policy"));
        }
        let requested: BTreeSet<_> = roles.iter().copied().collect();
        if requested.len() != roles.len() {
            return Err(invalid("verification role policy contains duplicate roles"));
        }
        Self::ALL.iter().copied().find(|profile| {
            profile.claim_class() == claim
                && profile.required_roles().iter().copied().collect::<BTreeSet<_>>() == requested
        }).ok_or_else(|| invalid("claim and roles do not name a registered verification profile"))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfiledVerifyChainRequestV1 {
    candidate: EvidenceCandidateV1,
    profile: EvidenceVerificationProfileV1,
    now_unix_ms: u64,
}

impl ProfiledVerifyChainRequestV1 {
    pub fn new(
        candidate: EvidenceCandidateV1,
        profile: EvidenceVerificationProfileV1,
        now_unix_ms: u64,
    ) -> Result<Self, EvidenceError> {
        candidate.validate().map_err(EvidenceError::InvalidRecord)?;
        Ok(Self { candidate, profile, now_unix_ms })
    }

    pub fn candidate(&self) -> &EvidenceCandidateV1 { &self.candidate }
    pub fn profile(&self) -> EvidenceVerificationProfileV1 { self.profile }
    pub fn now_unix_ms(&self) -> u64 { self.now_unix_ms }
}

mod sealed {
    pub trait Sealed {}
}

/// Product builds accept only the typed profile request. Legacy raw role arrays
/// remain test fixtures, not an implementable external capability.
///
/// ```compile_fail
/// use codex_hepta_evidence::{EvidenceVerificationRequest, VerifyChainRequestV1};
/// fn accepts<T: EvidenceVerificationRequest>(_: &T) {}
/// fn cannot_lower(request: &VerifyChainRequestV1) { accepts(request); }
/// ```
pub trait EvidenceVerificationRequest: sealed::Sealed {
    #[doc(hidden)]
    fn as_verification_request(&self) -> VerifyChainRequestV1;
}

impl sealed::Sealed for ProfiledVerifyChainRequestV1 {}
impl EvidenceVerificationRequest for ProfiledVerifyChainRequestV1 {
    fn as_verification_request(&self) -> VerifyChainRequestV1 {
        VerifyChainRequestV1 {
            candidate: self.candidate.clone(),
            claim_class: self.profile.claim_class(),
            required_roles: self.profile.required_roles().to_vec(),
            now_unix_ms: self.now_unix_ms,
        }
    }
}

#[cfg(test)]
impl sealed::Sealed for VerifyChainRequestV1 {}
#[cfg(test)]
impl EvidenceVerificationRequest for VerifyChainRequestV1 {
    fn as_verification_request(&self) -> VerifyChainRequestV1 { self.clone() }
}

fn invalid(message: &str) -> EvidenceError {
    EvidenceError::InvalidRecord(message.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_profiles_have_nonempty_unique_fixed_role_sets() {
        let mut names = BTreeSet::new();
        for profile in EvidenceVerificationProfileV1::ALL {
            assert!(names.insert(profile.as_str()));
            assert!(!profile.required_roles().is_empty());
            assert_eq!(
                profile.required_roles().iter().collect::<BTreeSet<_>>().len(),
                profile.required_roles().len()
            );
            assert_eq!(EvidenceVerificationProfileV1::parse(profile.as_str()), Ok(*profile));
            assert_eq!(
                EvidenceVerificationProfileV1::from_legacy_roles(
                    profile.claim_class(), profile.required_roles()
                ).expect("registered policy"),
                *profile
            );
        }
    }

    #[test]
    fn empty_duplicate_and_weakened_legacy_requests_are_rejected() {
        use EvidenceClaimClassV1::MandatoryTests;
        use EvidenceIssuerRoleV1::Evaluator;
        use EvidenceIssuerRoleV1::Generator;
        for roles in [vec![], vec![Generator], vec![Evaluator], vec![Generator, Generator]] {
            assert!(EvidenceVerificationProfileV1::from_legacy_roles(MandatoryTests, &roles).is_err());
        }
        assert!(EvidenceVerificationProfileV1::parse("").is_err());
        assert!(EvidenceVerificationProfileV1::parse("all_checks_passed").is_err());
    }
}
