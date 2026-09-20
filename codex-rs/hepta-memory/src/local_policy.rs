//! Explicit policy boundary for local-development lifecycle writes.
//!
//! The local witness writer is useful for qualification and development, but
//! it must never be mistaken for a production authority transition.  Keeping
//! the policy as a typed, closed-world value gives embedding owners one small
//! positive gate to validate before invoking a writer while making all
//! production capabilities fail closed by construction.

/// Version of the local-development lifecycle policy contract.
pub const LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_SCHEMA_VERSION: u32 = 1;
/// Namespace in which this policy is valid.
pub const LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_NAMESPACE: &str = "local_development_only";

/// A policy error which is safe to expose through host/app-server diagnostics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalDevelopmentLifecyclePolicyError {
    UnsupportedSchema,
    WrongNamespace,
    QualificationRequired,
    CallerMustBeZero,
    WitnessWriterDisabled,
    AutomaticLifecycleRegistrationForbidden,
    ProductionCapabilityEnabled,
}

impl std::fmt::Display for LocalDevelopmentLifecyclePolicyError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::UnsupportedSchema => "unsupported local-development lifecycle policy schema",
            Self::WrongNamespace => "local-development lifecycle policy has the wrong namespace",
            Self::QualificationRequired => {
                "local-development lifecycle policy must be qualification-only"
            }
            Self::CallerMustBeZero => {
                "local-development lifecycle policy must have a caller-zero surface"
            }
            Self::WitnessWriterDisabled => {
                "local-development lifecycle policy must explicitly enable the witness writer"
            }
            Self::AutomaticLifecycleRegistrationForbidden => {
                "local-development lifecycle policy cannot register lifecycle callbacks automatically"
            }
            Self::ProductionCapabilityEnabled => {
                "local-development lifecycle policy enables a production capability"
            }
        })
    }
}

impl std::error::Error for LocalDevelopmentLifecyclePolicyError {}

/// Closed-world policy for the explicit local witness owner.
///
/// The fields are public so an embedding can include the exact policy in a
/// diagnostic/qualification receipt.  `validate` must succeed before the
/// owner invokes a writer.  The canonical constructor is
/// [`Self::qualification_only`]; callers should not hand-build a value from
/// untrusted configuration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LocalDevelopmentLifecyclePolicy {
    pub schema_version: u32,
    pub namespace: &'static str,
    pub qualification_only: bool,
    pub caller_zero: bool,
    pub witness_writer_enabled: bool,
    pub automatic_lifecycle_registration: bool,
    pub production_activation: bool,
    pub external_effects: bool,
    pub provider_effects: bool,
    pub kg_write_authority: bool,
    pub routing_authority: bool,
    pub production_caller: bool,
}

impl LocalDevelopmentLifecyclePolicy {
    /// Return the only policy currently permitted for this local seam.
    pub const fn qualification_only() -> Self {
        Self {
            schema_version: LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_SCHEMA_VERSION,
            namespace: LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_NAMESPACE,
            qualification_only: true,
            caller_zero: true,
            witness_writer_enabled: true,
            automatic_lifecycle_registration: false,
            production_activation: false,
            external_effects: false,
            provider_effects: false,
            kg_write_authority: false,
            routing_authority: false,
            production_caller: false,
        }
    }

    /// Validate the complete policy, not just the positive writer bit.
    pub fn validate(self) -> Result<(), LocalDevelopmentLifecyclePolicyError> {
        if self.schema_version != LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_SCHEMA_VERSION {
            return Err(LocalDevelopmentLifecyclePolicyError::UnsupportedSchema);
        }
        if self.namespace != LOCAL_DEVELOPMENT_LIFECYCLE_POLICY_NAMESPACE {
            return Err(LocalDevelopmentLifecyclePolicyError::WrongNamespace);
        }
        if !self.qualification_only {
            return Err(LocalDevelopmentLifecyclePolicyError::QualificationRequired);
        }
        if !self.caller_zero {
            return Err(LocalDevelopmentLifecyclePolicyError::CallerMustBeZero);
        }
        if !self.witness_writer_enabled {
            return Err(LocalDevelopmentLifecyclePolicyError::WitnessWriterDisabled);
        }
        if self.automatic_lifecycle_registration {
            return Err(
                LocalDevelopmentLifecyclePolicyError::AutomaticLifecycleRegistrationForbidden,
            );
        }
        if self.production_activation
            || self.external_effects
            || self.provider_effects
            || self.kg_write_authority
            || self.routing_authority
            || self.production_caller
        {
            return Err(LocalDevelopmentLifecyclePolicyError::ProductionCapabilityEnabled);
        }
        Ok(())
    }

    /// Whether this policy permits one explicit, host-invoked witness write.
    pub fn permits_explicit_witness_write(self) -> bool {
        self.validate().is_ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_policy_is_positive_but_local_only() {
        let policy = LocalDevelopmentLifecyclePolicy::qualification_only();
        assert!(policy.validate().is_ok());
        assert!(policy.permits_explicit_witness_write());
        assert!(!policy.automatic_lifecycle_registration);
        assert!(!policy.production_activation);
        assert!(!policy.external_effects);
        assert!(!policy.provider_effects);
        assert!(!policy.kg_write_authority);
        assert!(!policy.routing_authority);
        assert!(!policy.production_caller);
    }

    #[test]
    fn every_authority_or_registration_bit_fails_closed() {
        let canonical = LocalDevelopmentLifecyclePolicy::qualification_only();
        for mutate in [
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.qualification_only = false,
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.caller_zero = false,
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.witness_writer_enabled = false,
            |policy: &mut LocalDevelopmentLifecyclePolicy| {
                policy.automatic_lifecycle_registration = true
            },
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.production_activation = true,
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.external_effects = true,
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.provider_effects = true,
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.kg_write_authority = true,
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.routing_authority = true,
            |policy: &mut LocalDevelopmentLifecyclePolicy| policy.production_caller = true,
        ] {
            let mut candidate = canonical;
            mutate(&mut candidate);
            assert!(!candidate.permits_explicit_witness_write());
        }
    }
}
