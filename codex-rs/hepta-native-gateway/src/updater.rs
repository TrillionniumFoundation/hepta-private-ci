use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedUpdateManifestV1 {
    pub package_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub evidence_digest: Digest32,
    pub platform: String,
    pub architecture: String,
    pub backend_protocol_version: u32,
    pub channel: StableId,
    pub selected_by: StableId,
    pub generator_principal: StableId,
    pub signature: [u8; 64],
}

impl SignedUpdateManifestV1 {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.ui.native.update-manifest.v1\0".to_vec();
        bytes.extend_from_slice(self.package_digest.as_array());
        bytes.extend_from_slice(self.predecessor_digest.as_array());
        bytes.extend_from_slice(self.evidence_digest.as_array());
        push_text(&mut bytes, &self.platform);
        push_text(&mut bytes, &self.architecture);
        bytes.extend_from_slice(&self.backend_protocol_version.to_be_bytes());
        push_text(&mut bytes, self.channel.as_str());
        push_text(&mut bytes, self.selected_by.as_str());
        push_text(&mut bytes, self.generator_principal.as_str());
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedUpdate {
    pub package_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub evidence_digest: Digest32,
    pub channel: StableId,
    pub selected_by: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UpdateStatus {
    Succeeded,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateDisposition {
    pub package_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub status: UpdateStatus,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateObservation {
    pub terminal_observed: bool,
    pub restarted: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UpdateError {
    EmptyDigest(&'static str),
    PackageDigestMismatch,
    PlatformMismatch,
    ArchitectureMismatch,
    BackendProtocolMismatch,
    ChannelMismatch,
    GeneratorMismatch,
    SelfSelected,
    InvalidSignature,
    Apply(String),
    Rollback(String),
}

impl fmt::Display for UpdateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for UpdateError {}

pub struct SignedUpdateVerifier {
    verifying_key: VerifyingKey,
    channel: StableId,
    generator_principal: StableId,
}

impl SignedUpdateVerifier {
    pub fn new(
        verifying_key: VerifyingKey,
        channel: StableId,
        generator_principal: StableId,
    ) -> Self {
        Self {
            verifying_key,
            channel,
            generator_principal,
        }
    }

    pub fn verify(
        &self,
        manifest: &SignedUpdateManifestV1,
        package_bytes: &[u8],
        platform: &str,
        architecture: &str,
        backend_protocol_version: u32,
    ) -> Result<VerifiedUpdate, UpdateError> {
        for (name, digest) in [
            ("package", manifest.package_digest),
            ("predecessor", manifest.predecessor_digest),
            ("evidence", manifest.evidence_digest),
        ] {
            if digest.is_zero() {
                return Err(UpdateError::EmptyDigest(name));
            }
        }
        if Digest32::of_bytes(package_bytes) != manifest.package_digest {
            return Err(UpdateError::PackageDigestMismatch);
        }
        if manifest.platform != platform {
            return Err(UpdateError::PlatformMismatch);
        }
        if manifest.architecture != architecture {
            return Err(UpdateError::ArchitectureMismatch);
        }
        if manifest.backend_protocol_version != backend_protocol_version {
            return Err(UpdateError::BackendProtocolMismatch);
        }
        if manifest.channel != self.channel {
            return Err(UpdateError::ChannelMismatch);
        }
        if manifest.generator_principal != self.generator_principal {
            return Err(UpdateError::GeneratorMismatch);
        }
        if manifest.selected_by == manifest.generator_principal {
            return Err(UpdateError::SelfSelected);
        }
        self.verifying_key
            .verify_strict(
                &manifest.signing_bytes(),
                &Signature::from_bytes(&manifest.signature),
            )
            .map_err(|_| UpdateError::InvalidSignature)?;
        Ok(VerifiedUpdate {
            package_digest: manifest.package_digest,
            predecessor_digest: manifest.predecessor_digest,
            evidence_digest: manifest.evidence_digest,
            channel: manifest.channel.clone(),
            selected_by: manifest.selected_by.clone(),
        })
    }
}

pub trait UpdateDriver {
    type Error: StdError;

    fn apply(
        &mut self,
        update: &VerifiedUpdate,
        package_bytes: &[u8],
    ) -> Result<UpdateObservation, Self::Error>;

    fn rollback(&mut self, predecessor_digest: Digest32) -> Result<(), Self::Error>;
}

pub struct NativeUpdateController<D: UpdateDriver> {
    verifier: SignedUpdateVerifier,
    driver: D,
}

impl<D: UpdateDriver> NativeUpdateController<D> {
    pub fn new(verifier: SignedUpdateVerifier, driver: D) -> Self {
        Self { verifier, driver }
    }

    pub fn apply_shell_update(
        &mut self,
        manifest: &SignedUpdateManifestV1,
        package_bytes: &[u8],
        platform: &str,
        architecture: &str,
        backend_protocol_version: u32,
    ) -> Result<UpdateDisposition, UpdateError> {
        let verified = self.verifier.verify(
            manifest,
            package_bytes,
            platform,
            architecture,
            backend_protocol_version,
        )?;
        let observed = match self.driver.apply(&verified, package_bytes) {
            Ok(observed) => observed,
            Err(error) => {
                self.driver
                    .rollback(verified.predecessor_digest)
                    .map_err(|rollback| UpdateError::Rollback(rollback.to_string()))?;
                return Err(UpdateError::Apply(error.to_string()));
            }
        };
        if !observed.terminal_observed || !observed.restarted {
            self.driver
                .rollback(verified.predecessor_digest)
                .map_err(|error| UpdateError::Rollback(error.to_string()))?;
            return Ok(UpdateDisposition {
                package_digest: verified.package_digest,
                predecessor_digest: verified.predecessor_digest,
                status: UpdateStatus::Quarantined,
                terminal_observed: observed.terminal_observed,
            });
        }
        Ok(UpdateDisposition {
            package_digest: verified.package_digest,
            predecessor_digest: verified.predecessor_digest,
            status: UpdateStatus::Succeeded,
            terminal_observed: true,
        })
    }

    pub fn into_driver(self) -> D {
        self.driver
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use std::io;

    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;

    use super::*;

    #[derive(Debug, Default)]
    struct MockDriver {
        observation: Option<UpdateObservation>,
        apply_error: bool,
        rollback_count: usize,
    }

    impl UpdateDriver for MockDriver {
        type Error = io::Error;

        fn apply(
            &mut self,
            _update: &VerifiedUpdate,
            _package_bytes: &[u8],
        ) -> Result<UpdateObservation, Self::Error> {
            if self.apply_error {
                return Err(io::Error::other("apply failed after staging"));
            }
            Ok(self.observation.clone().unwrap_or(UpdateObservation {
                terminal_observed: true,
                restarted: true,
            }))
        }

        fn rollback(&mut self, _predecessor_digest: Digest32) -> Result<(), Self::Error> {
            self.rollback_count += 1;
            Ok(())
        }
    }

    fn stable(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("fixture id: {error}"))
    }

    fn signed_manifest(package: &[u8], key: &SigningKey) -> SignedUpdateManifestV1 {
        let mut manifest = SignedUpdateManifestV1 {
            package_digest: Digest32::of_bytes(package),
            predecessor_digest: Digest32::of_bytes(b"predecessor"),
            evidence_digest: Digest32::of_bytes(b"evidence"),
            platform: "linux".to_string(),
            architecture: "x86_64".to_string(),
            backend_protocol_version: 1,
            channel: stable("stable"),
            selected_by: stable("release.reviewer"),
            generator_principal: stable("release.generator"),
            signature: [0; 64],
        };
        manifest.signature = key.sign(&manifest.signing_bytes()).to_bytes();
        manifest
    }

    fn controller(driver: MockDriver, key: &SigningKey) -> NativeUpdateController<MockDriver> {
        NativeUpdateController::new(
            SignedUpdateVerifier::new(
                key.verifying_key(),
                stable("stable"),
                stable("release.generator"),
            ),
            driver,
        )
    }

    #[test]
    fn signed_compatible_update_requires_observed_restart() {
        let key = SigningKey::from_bytes(&[11_u8; 32]);
        let package = b"signed package bytes";
        let manifest = signed_manifest(package, &key);
        let disposition = controller(MockDriver::default(), &key)
            .apply_shell_update(&manifest, package, "linux", "x86_64", 1)
            .unwrap_or_else(|error| panic!("update: {error}"));
        assert_eq!(disposition.status, UpdateStatus::Succeeded);
    }

    #[test]
    fn failed_or_unobserved_restart_rolls_back_and_quarantines() {
        let key = SigningKey::from_bytes(&[12_u8; 32]);
        let package = b"package";
        let manifest = signed_manifest(package, &key);
        let driver = MockDriver {
            observation: Some(UpdateObservation {
                terminal_observed: false,
                restarted: false,
            }),
            ..MockDriver::default()
        };
        let mut controller = controller(driver, &key);
        let disposition = controller
            .apply_shell_update(&manifest, package, "linux", "x86_64", 1)
            .unwrap_or_else(|error| panic!("update: {error}"));
        assert_eq!(disposition.status, UpdateStatus::Quarantined);
        assert_eq!(controller.into_driver().rollback_count, 1);
    }

    #[test]
    fn apply_exception_still_rolls_back() {
        let key = SigningKey::from_bytes(&[13_u8; 32]);
        let package = b"package";
        let manifest = signed_manifest(package, &key);
        let driver = MockDriver {
            apply_error: true,
            ..MockDriver::default()
        };
        let mut controller = controller(driver, &key);
        assert!(matches!(
            controller.apply_shell_update(&manifest, package, "linux", "x86_64", 1),
            Err(UpdateError::Apply(_))
        ));
        assert_eq!(controller.into_driver().rollback_count, 1);
    }

    #[test]
    fn selector_cannot_be_generator_and_generator_identity_is_trusted() {
        let key = SigningKey::from_bytes(&[14_u8; 32]);
        let package = b"package";
        let mut manifest = signed_manifest(package, &key);
        manifest.selected_by = manifest.generator_principal.clone();
        manifest.signature = key.sign(&manifest.signing_bytes()).to_bytes();
        let mut controller = controller(MockDriver::default(), &key);
        assert_eq!(
            controller.apply_shell_update(&manifest, package, "linux", "x86_64", 1),
            Err(UpdateError::SelfSelected)
        );
    }

    #[test]
    fn unsigned_or_payload_drifted_update_is_rejected() {
        let key = SigningKey::from_bytes(&[15_u8; 32]);
        let package = b"package";
        let manifest = signed_manifest(package, &key);
        let mut controller = controller(MockDriver::default(), &key);
        assert_eq!(
            controller.apply_shell_update(&manifest, b"tampered", "linux", "x86_64", 1),
            Err(UpdateError::PackageDigestMismatch)
        );
    }
}
