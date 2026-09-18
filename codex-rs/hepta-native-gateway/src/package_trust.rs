use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
#[cfg(any(target_os = "macos", target_os = "windows"))]
use std::process::Command;

use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageTrustKind {
    AppleCodeSignAndGatekeeper,
    WindowsAuthenticode,
    ManifestEd25519,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PackageTrustReceipt {
    pub trust_kind: PackageTrustKind,
    pub artifact_digest: Digest32,
    pub observation_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PackageTrustError {
    PathNotAbsolute,
    ArtifactMissing,
    InvalidSignerThumbprint,
    VerificationUnavailable,
    VerificationFailed,
    Command(String),
}

impl fmt::Display for PackageTrustError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PackageTrustError {}

/// Platform package trust verifier used after the repository-owned Ed25519
/// update manifest has bound the exact artifact digest.
///
/// macOS additionally requires `codesign --verify` and Gatekeeper assessment.
/// Windows additionally requires a valid Authenticode signature and can pin a
/// signer certificate thumbprint. Linux relies on the Ed25519 manifest because
/// there is no single OS-wide notarization mechanism for portable binaries.
#[derive(Clone, Debug, Default)]
pub struct SystemPackageTrustVerifier {
    windows_signer_thumbprint: Option<String>,
}

impl SystemPackageTrustVerifier {
    pub fn new(windows_signer_thumbprint: Option<String>) -> Result<Self, PackageTrustError> {
        if let Some(thumbprint) = &windows_signer_thumbprint {
            validate_thumbprint(thumbprint)?;
        }
        Ok(Self {
            windows_signer_thumbprint,
        })
    }

    pub fn verify(
        &self,
        artifact: &Path,
        artifact_digest: Digest32,
    ) -> Result<PackageTrustReceipt, PackageTrustError> {
        if !artifact.is_absolute() {
            return Err(PackageTrustError::PathNotAbsolute);
        }
        if !artifact.is_file() {
            return Err(PackageTrustError::ArtifactMissing);
        }
        if artifact_digest.is_zero() {
            return Err(PackageTrustError::VerificationFailed);
        }
        verify_platform_package(artifact, self.windows_signer_thumbprint.as_deref())?;
        let trust_kind = current_trust_kind()?;
        let mut evidence = b"hepta.ui.native.package-trust.v1\0".to_vec();
        evidence.extend_from_slice(artifact_digest.as_array());
        evidence.extend_from_slice(format!("{trust_kind:?}").as_bytes());
        Ok(PackageTrustReceipt {
            trust_kind,
            artifact_digest,
            observation_digest: Digest32::of_bytes(&evidence),
        })
    }
}

fn validate_thumbprint(value: &str) -> Result<(), PackageTrustError> {
    if value.len() != 40 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(PackageTrustError::InvalidSignerThumbprint);
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn verify_platform_package(
    artifact: &Path,
    _windows_signer_thumbprint: Option<&str>,
) -> Result<(), PackageTrustError> {
    run_checked(
        Command::new("codesign")
            .arg("--verify")
            .arg("--deep")
            .arg("--strict")
            .arg("--verbose=2")
            .arg(artifact),
    )?;
    run_checked(
        Command::new("spctl")
            .arg("--assess")
            .arg("--type")
            .arg("execute")
            .arg(artifact),
    )
}

#[cfg(target_os = "windows")]
fn verify_platform_package(
    artifact: &Path,
    windows_signer_thumbprint: Option<&str>,
) -> Result<(), PackageTrustError> {
    const SCRIPT: &str = r#"
$sig = Get-AuthenticodeSignature -LiteralPath $env:HEPTA_UPDATE_ARTIFACT;
if ($sig.Status -ne 'Valid') { exit 11 }
if ($env:HEPTA_UPDATE_SIGNER -and $sig.SignerCertificate.Thumbprint -ne $env:HEPTA_UPDATE_SIGNER) { exit 12 }
exit 0
"#;
    let mut command = Command::new("powershell.exe");
    command
        .arg("-NoLogo")
        .arg("-NoProfile")
        .arg("-NonInteractive")
        .arg("-Command")
        .arg(SCRIPT)
        .env("HEPTA_UPDATE_ARTIFACT", artifact);
    if let Some(thumbprint) = windows_signer_thumbprint {
        command.env("HEPTA_UPDATE_SIGNER", thumbprint.to_ascii_uppercase());
    }
    run_checked(&mut command)
}

#[cfg(target_os = "linux")]
fn verify_platform_package(
    _artifact: &Path,
    _windows_signer_thumbprint: Option<&str>,
) -> Result<(), PackageTrustError> {
    // The exact bytes are already Ed25519-signed by SignedUpdateVerifier.
    // Linux package-manager/repository provenance is deployment-specific and
    // must be added by the selected distribution channel rather than guessed.
    Ok(())
}

#[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
fn verify_platform_package(
    _artifact: &Path,
    _windows_signer_thumbprint: Option<&str>,
) -> Result<(), PackageTrustError> {
    Err(PackageTrustError::VerificationUnavailable)
}

#[cfg(target_os = "macos")]
fn current_trust_kind() -> Result<PackageTrustKind, PackageTrustError> {
    Ok(PackageTrustKind::AppleCodeSignAndGatekeeper)
}

#[cfg(target_os = "windows")]
fn current_trust_kind() -> Result<PackageTrustKind, PackageTrustError> {
    Ok(PackageTrustKind::WindowsAuthenticode)
}

#[cfg(target_os = "linux")]
fn current_trust_kind() -> Result<PackageTrustKind, PackageTrustError> {
    Ok(PackageTrustKind::ManifestEd25519)
}

#[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
fn current_trust_kind() -> Result<PackageTrustKind, PackageTrustError> {
    Err(PackageTrustError::VerificationUnavailable)
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn run_checked(command: &mut Command) -> Result<(), PackageTrustError> {
    let status = command
        .status()
        .map_err(|error| PackageTrustError::Command(error.to_string()))?;
    if !status.success() {
        return Err(PackageTrustError::VerificationFailed);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_thumbprint_policy_is_strict_even_on_other_platforms() {
        assert!(SystemPackageTrustVerifier::new(Some("a".repeat(40))).is_ok());
        assert!(matches!(
            SystemPackageTrustVerifier::new(Some("not-a-thumbprint".to_string())),
            Err(PackageTrustError::InvalidSignerThumbprint)
        ));
    }
}
