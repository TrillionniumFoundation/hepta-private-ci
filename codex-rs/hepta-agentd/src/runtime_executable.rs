//! Process-local executable observation used by built-in module registration.
//!
//! A manifest hash is NOT an implementation identity. Hash the executable once,
//! with bounded memory, and bind that observation to each module's manifest.
//! This neither authenticates build provenance nor grants selection/activation.
//! Linux observes the kernel's loaded-image handle, including an unlinked image.
//! Other targets report the weaker executable-path observation explicitly.

use std::fs::File;
use std::io;
use std::sync::OnceLock;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;

const MAX_EXECUTABLE_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const IMPLEMENTATION_DOMAIN: &[u8] = b"hepta.runtime-module-executable.v1\0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeExecutableOrigin {
    LinuxLoadedImage,
    ExecutablePath,
}

/// An observation of bytes, not a signed release or an independent assessment.
/// Fields are private so source manifests cannot masquerade as observations.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeExecutableIdentity {
    origin: RuntimeExecutableOrigin,
    artifact_digest: Digest32,
    bytes: u64,
}

impl RuntimeExecutableIdentity {
    /// Cache only within this process. Failure remains a startup error; neither
    /// an environment variable nor a registry string is a fallback identity.
    pub fn observe_current() -> Result<&'static Self, AgentdError> {
        static OBSERVED: OnceLock<Result<RuntimeExecutableIdentity, io::ErrorKind>> =
            OnceLock::new();
        observe_cached(&OBSERVED, observe_current_image)
    }

    pub fn origin(&self) -> RuntimeExecutableOrigin {
        self.origin
    }

    pub fn artifact_digest(&self) -> Digest32 {
        self.artifact_digest
    }

    pub fn bytes(&self) -> u64 {
        self.bytes
    }

    /// The implementation binds real artifact bytes AND module semantics. The
    /// module's generation is deliberately absent: a rollback uses the same
    /// predecessor content under a NEW generation, never revives an old epoch.
    pub fn implementation_digest(&self, module: &StableId, manifest: Digest32) -> Digest32 {
        let origin = match self.origin {
            RuntimeExecutableOrigin::LinuxLoadedImage => 1_u8,
            RuntimeExecutableOrigin::ExecutablePath => 2_u8,
        };
        let name = module.as_str().as_bytes();
        Digest32::of_parts(&[
            IMPLEMENTATION_DOMAIN,
            &[origin],
            &(name.len() as u64).to_be_bytes(),
            name,
            self.artifact_digest.as_array(),
            manifest.as_array(),
        ])
    }
}

fn observe_cached<F>(
    cache: &OnceLock<Result<RuntimeExecutableIdentity, io::ErrorKind>>,
    observe: F,
) -> Result<&RuntimeExecutableIdentity, AgentdError>
where
    F: FnOnce() -> io::Result<RuntimeExecutableIdentity>,
{
    cache
        .get_or_init(|| observe().map_err(|error| error.kind()))
        .as_ref()
        .map_err(|kind| {
            AgentdError::Io(io::Error::new(
                *kind,
                "runtime executable observation failed",
            ))
        })
}

fn observe_current_image() -> io::Result<RuntimeExecutableIdentity> {
    #[cfg(target_os = "linux")]
    let (file, origin) = (
        File::open("/proc/self/exe")?,
        RuntimeExecutableOrigin::LinuxLoadedImage,
    );
    #[cfg(not(target_os = "linux"))]
    let (file, origin) = (
        File::open(std::env::current_exe()?)?,
        RuntimeExecutableOrigin::ExecutablePath,
    );
    observe_file(file, origin, MAX_EXECUTABLE_BYTES)
}

fn observe_file(
    mut file: File,
    origin: RuntimeExecutableOrigin,
    maximum: u64,
) -> io::Result<RuntimeExecutableIdentity> {
    let before = file.metadata()?;
    if !before.is_file() || before.len() == 0 || before.len() > maximum {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid executable size or type",
        ));
    }
    let artifact_digest = Digest32::of_reader(&mut file, before.len())?;
    let after = file.metadata()?;
    if before.len() != after.len() || before.modified()? != after.modified()? {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "executable changed during observation",
        ));
    }
    Ok(RuntimeExecutableIdentity {
        origin,
        artifact_digest,
        bytes: before.len(),
    })
}

#[cfg(test)]
#[path = "runtime_executable_tests.rs"]
mod tests;
