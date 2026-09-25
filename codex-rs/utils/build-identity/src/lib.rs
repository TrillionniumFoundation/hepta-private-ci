use std::fmt;

pub const RELEASE_SOURCE_SHA_ENV: &str = "CODEX_RELEASE_SOURCE_SHA";
pub const BUILD_SOURCE_DIRTY_ENV: &str = "CODEX_BUILD_SOURCE_DIRTY";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceBinding {
    Unbound,
    Exact,
}

impl SourceBinding {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Unbound => "unbound",
            Self::Exact => "exact",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceDirty {
    Unknown,
    Clean,
    Dirty,
}

impl SourceDirty {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Clean => "clean",
            Self::Dirty => "dirty",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BuildIdentity {
    pub binding: SourceBinding,
    pub source_sha: Option<String>,
    pub source_dirty: SourceDirty,
}

impl BuildIdentity {
    /// Resolve build identity exclusively from explicit build inputs.
    ///
    /// This deliberately does not inspect Git. An ordinary local build is
    /// always unbound, even when a checkout happens to have a discoverable
    /// `HEAD`. Release automation may opt into exact binding by supplying a
    /// validated 40- or 64-character hexadecimal source SHA.
    pub fn resolve(
        release_source_sha: Option<&str>,
        source_dirty: Option<&str>,
    ) -> Result<Self, BuildIdentityError> {
        let source_dirty = parse_dirty(source_dirty)?;
        let Some(source_sha) = release_source_sha else {
            return Ok(Self {
                binding: SourceBinding::Unbound,
                source_sha: None,
                source_dirty,
            });
        };
        let source_sha = normalize_exact_sha(source_sha)?;
        if source_dirty != SourceDirty::Clean {
            return Err(BuildIdentityError::ExactSourceNotVerifiedClean(
                source_dirty,
            ));
        }
        Ok(Self {
            binding: SourceBinding::Exact,
            source_sha: Some(source_sha),
            source_dirty,
        })
    }

    pub fn summary(&self) -> String {
        format!(
            "source={};sha={};dirty={}",
            self.binding.as_str(),
            self.source_sha.as_deref().unwrap_or("none"),
            self.source_dirty.as_str()
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BuildIdentityError {
    InvalidExactSourceSha,
    InvalidDirtyValue(String),
    ExactSourceNotVerifiedClean(SourceDirty),
}

impl fmt::Display for BuildIdentityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidExactSourceSha => formatter.write_str(
                "release source SHA must contain exactly 40 or 64 ASCII hexadecimal characters",
            ),
            Self::InvalidDirtyValue(value) => write!(
                formatter,
                "build source dirty marker must be `true` or `false`, got {value:?}"
            ),
            Self::ExactSourceNotVerifiedClean(dirty) => write!(
                formatter,
                "an exact release source requires `{BUILD_SOURCE_DIRTY_ENV}=false`; resolved dirty state was {}",
                dirty.as_str()
            ),
        }
    }
}

impl std::error::Error for BuildIdentityError {}

fn normalize_exact_sha(value: &str) -> Result<String, BuildIdentityError> {
    if !matches!(value.len(), 40 | 64) || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(BuildIdentityError::InvalidExactSourceSha);
    }
    Ok(value.to_ascii_lowercase())
}

fn parse_dirty(value: Option<&str>) -> Result<SourceDirty, BuildIdentityError> {
    match value {
        None => Ok(SourceDirty::Unknown),
        Some("false") => Ok(SourceDirty::Clean),
        Some("true") => Ok(SourceDirty::Dirty),
        Some(value) => Err(BuildIdentityError::InvalidDirtyValue(value.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ordinary_build_is_explicitly_unbound() {
        assert_eq!(
            BuildIdentity::resolve(None, None).expect("resolve local build"),
            BuildIdentity {
                binding: SourceBinding::Unbound,
                source_sha: None,
                source_dirty: SourceDirty::Unknown,
            }
        );
    }

    #[test]
    fn local_dirty_marker_never_creates_an_exact_binding() {
        let identity = BuildIdentity::resolve(None, Some("true")).expect("resolve dirty build");
        assert_eq!(identity.binding, SourceBinding::Unbound);
        assert_eq!(identity.source_dirty, SourceDirty::Dirty);
        assert_eq!(identity.summary(), "source=unbound;sha=none;dirty=dirty");
    }

    #[test]
    fn exact_binding_accepts_and_normalizes_sha1() {
        let identity = BuildIdentity::resolve(
            Some("ABCDEF0123456789ABCDEF0123456789ABCDEF01"),
            Some("false"),
        )
        .expect("resolve exact SHA-1");
        assert_eq!(identity.binding, SourceBinding::Exact);
        assert_eq!(
            identity.source_sha.as_deref(),
            Some("abcdef0123456789abcdef0123456789abcdef01")
        );
        assert_eq!(identity.source_dirty, SourceDirty::Clean);
    }

    #[test]
    fn exact_binding_accepts_sha256() {
        let sha = "a".repeat(64);
        let identity =
            BuildIdentity::resolve(Some(&sha), Some("false")).expect("resolve exact SHA-256");
        assert_eq!(identity.binding, SourceBinding::Exact);
        assert_eq!(identity.source_sha.as_deref(), Some(sha.as_str()));
    }

    #[test]
    fn malformed_or_dirty_exact_binding_is_rejected() {
        assert_eq!(
            BuildIdentity::resolve(Some("abc123"), None),
            Err(BuildIdentityError::InvalidExactSourceSha)
        );
        assert_eq!(
            BuildIdentity::resolve(Some(&"a".repeat(40)), Some("true")),
            Err(BuildIdentityError::ExactSourceNotVerifiedClean(
                SourceDirty::Dirty
            ))
        );
        assert_eq!(
            BuildIdentity::resolve(Some(&"a".repeat(40)), None),
            Err(BuildIdentityError::ExactSourceNotVerifiedClean(
                SourceDirty::Unknown
            ))
        );
        assert_eq!(
            BuildIdentity::resolve(None, Some("yes")),
            Err(BuildIdentityError::InvalidDirtyValue("yes".to_string()))
        );
    }
}
