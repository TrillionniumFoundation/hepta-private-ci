//! Live effective-token continuity only, without namespace or owner admission.

use crate::security::CurrentUser;
use crate::security::ValidationError;
use crate::security::open_effective_token;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::SecurityDelegation as SECURITY_DELEGATION;
use windows_sys::Win32::Security::SecurityImpersonation as SECURITY_IMPERSONATION;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenImpersonation as TOKEN_IMPERSONATION;
use windows_sys::Win32::Security::TokenPrimary as TOKEN_PRIMARY;
use windows_sys::Win32::Security::TokenStatistics;

#[derive(Eq, PartialEq)]
enum Kind {
    Primary,
    Impersonation(i32),
}

#[derive(Eq, PartialEq)]
struct Identity {
    token: (u32, i32),
    modified: (u32, i32),
    authentication: (u32, i32),
    kind: Kind,
}

impl Identity {
    fn read(token: &OwnedHandle) -> Result<Self, ValidationError> {
        // TOKEN_STATISTICS is fixed-size; no caller-provided bytes are accepted.
        let mut value: TOKEN_STATISTICS = unsafe { std::mem::zeroed() };
        let mut returned = 0;
        // SAFETY: the initialized structure and length output remain live while
        // querying the same owned token with its original TOKEN_QUERY access.
        if unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenStatistics,
                (&mut value as *mut TOKEN_STATISTICS).cast(),
                size_of::<TOKEN_STATISTICS>() as u32,
                &mut returned,
            )
        } == 0
        {
            return Err(io::Error::last_os_error().into());
        }
        if returned as usize != size_of::<TOKEN_STATISTICS>() {
            return Err(ValidationError::MalformedDescriptor);
        }
        let kind = match value.TokenType {
            TOKEN_PRIMARY => Kind::Primary,
            TOKEN_IMPERSONATION => match value.ImpersonationLevel {
                SECURITY_IMPERSONATION | SECURITY_DELEGATION => {
                    Kind::Impersonation(value.ImpersonationLevel)
                }
                _ => return Err(ValidationError::PrincipalChanged),
            },
            _ => return Err(ValidationError::MalformedDescriptor),
        };
        Ok(Self {
            token: (value.TokenId.LowPart, value.TokenId.HighPart),
            modified: (value.ModifiedId.LowPart, value.ModifiedId.HighPart),
            authentication: (
                value.AuthenticationId.LowPart,
                value.AuthenticationId.HighPart,
            ),
            kind,
        })
    }
}

#[derive(Eq, PartialEq)]
struct Snapshot {
    identity: Identity,
    user: CurrentUser,
}

impl Snapshot {
    fn read(token: &OwnedHandle) -> Result<Self, ValidationError> {
        let identity = Identity::read(token)?;
        let user = CurrentUser::from_token(token)?;
        if identity != Identity::read(token)? {
            return Err(ValidationError::PrincipalChanged);
        }
        Ok(Self { identity, user })
    }
}

enum Continuity {
    Live,
    Refused,
}

/// Holds the original effective token and its bounded, kernel-read identity.
///
/// This is neither a private-owner proof nor a promise about future operations.
/// It exposes no token handle, supplied-identity constructor, Clone or Serde.
pub struct CapturedPrincipal {
    token: OwnedHandle,
    original: Snapshot,
    continuity: Continuity,
}

impl CapturedPrincipal {
    pub(crate) fn primary_owner_user(&mut self) -> Result<CurrentUser, ValidationError> {
        self.revalidate_effective()?;
        self.continuity = Continuity::Refused;
        if self.original.identity.kind != Kind::Primary {
            return Err(ValidationError::PrincipalChanged);
        }
        crate::primary_owner::validate_primary(&self.token)?;
        let user = CurrentUser::from_token(&self.token)?;
        self.continuity = Continuity::Live;
        self.revalidate_effective()?;
        Ok(user)
    }

    /// Capture the thread token, falling back only on ERROR_NO_TOKEN.
    ///
    /// Only TOKEN_QUERY is requested. Identification/anonymous impersonation
    /// cannot serve as a resource-owning principal and is refused.
    pub fn capture_effective() -> Result<Self, ValidationError> {
        let token = open_effective_token()?;
        let original = Snapshot::read(&token)?;
        let mut captured = Self {
            token,
            original,
            continuity: Continuity::Live,
        };
        captured.revalidate_effective()?;
        Ok(captured)
    }

    /// Compare both the held token and the current effective token to capture.
    ///
    /// Any query error or identity drift permanently refuses this observation;
    /// restoring a former thread token cannot revive it. A caller must check
    /// again immediately before each operation that depends on this context.
    pub fn revalidate_effective(&mut self) -> Result<(), ValidationError> {
        if let Continuity::Refused = self.continuity {
            return Err(ValidationError::PrincipalChanged);
        }
        self.continuity = Continuity::Refused;
        let current = open_effective_token()?;
        if Snapshot::read(&self.token)? != self.original
            || Snapshot::read(&current)? != self.original
            || Snapshot::read(&self.token)? != self.original
        {
            return Err(ValidationError::PrincipalChanged);
        }
        self.continuity = Continuity::Live;
        Ok(())
    }
}
