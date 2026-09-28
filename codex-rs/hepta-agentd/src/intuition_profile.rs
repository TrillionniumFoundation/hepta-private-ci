//! Immutable startup-selected intuition serving profile. No request-time environment reads.

use crate::AgentdError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntuitionServingProfileV1 {
    Development,
    Test,
    Production,
}

impl IntuitionServingProfileV1 {
    pub(crate) fn parse(value: Option<&str>, test_build: bool) -> Result<Self, &'static str> {
        match value {
            None | Some("production") => Ok(Self::Production),
            Some("development") => Ok(Self::Development),
            Some("test") if test_build => Ok(Self::Test),
            Some("test") => Err("agentd.intuition.profile.test_unavailable_in_product"),
            Some(_) => Err("agentd.intuition.profile.invalid"),
        }
    }

    pub(crate) fn from_process_environment() -> Result<Self, AgentdError> {
        let value = std::env::var_os("HEPTA_INTUITION_PROFILE");
        let value = value.as_ref().map(|value| value.to_str().ok_or_else(|| {
            AgentdError::Invalid("agentd.intuition.profile.invalid".to_string())
        })).transpose()?;
        Self::parse(value, cfg!(test)).map_err(|code| AgentdError::Invalid(code.to_string()))
    }

    pub(crate) fn validate_build(self) -> Result<(), AgentdError> {
        if self == Self::Test && !cfg!(test) {
            return Err(AgentdError::Invalid(
                "agentd.intuition.profile.test_unavailable_in_product".to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) fn require_host(self, product_ready: bool) -> Result<(), &'static str> {
        if self == Self::Production && !product_ready {
            Err("agentd.intuition.service.production_product_host_required")
        } else { Ok(()) }
    }

    pub(crate) const fn as_str(self) -> &'static str {
        match self { Self::Development => "development", Self::Test => "test", Self::Production => "production" }
    }
}

#[cfg(test)]
mod tests {
    use super::IntuitionServingProfileV1 as Profile;
    #[test]
    fn default_is_production_and_compatibility_is_explicit() {
        assert_eq!(Profile::parse(None, false), Ok(Profile::Production));
        assert_eq!(Profile::parse(None, true), Ok(Profile::Production));
        assert_eq!(Profile::parse(Some("development"), false), Ok(Profile::Development));
        assert!(Profile::parse(Some("test"), false).is_err());
        assert_eq!(Profile::parse(Some("test"), true), Ok(Profile::Test));
        for invalid in ["", " production", "production ", "Production", "unknown"] {
            assert!(Profile::parse(Some(invalid), true).is_err());
        }
    }
    #[test]
    fn missing_components_never_demote_production() {
        assert!(Profile::Production.require_host(false).is_err());
        assert!(Profile::Development.require_host(false).is_ok());
    }
}
