//! One bounded external signed grant, never an issuer or a second nonce owner.

use std::path::Path;
use std::sync::Arc;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdFinalUseGrantProvider;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::FinalUseProductionOutboxTarget;

pub const MAX_SIGNED_GRANT_FILE_BYTES: usize = 16 * 1024;

/// Immutable courier for one exact operation binding and externally signed
/// grant. No key, dynamic file reload, issuer registry or retry state is owned.
/// Loading this input does not establish production policy/issuer custody or
/// source-lease verification; the configured host still owns those inputs.
pub struct SignedFinalUseGrantCourier {
    signed: SignedFinalUseGrant,
    authority: FinalUseAuthority,
}

impl SignedFinalUseGrantCourier {
    /// Load one protected, singly linked regular file containing exactly one
    /// bounded JSON grant. Symlinks, FIFOs, writable inputs and trailing frames
    /// are refused. The configured UID is an input from the trusted host, not
    /// authority inferred from a pathname or signature supplied by the worker.
    #[cfg(unix)]
    pub fn open(
        path: &Path,
        issuer_uid: u32,
        authority: FinalUseAuthority,
        expected: &FinalUseBinding,
    ) -> Result<Self, AgentdError> {
        use std::io::Read;
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::OpenOptionsExt;

        if !path.is_absolute() {
            return Err(invalid("signed grant courier path must be absolute"));
        }
        let mut file = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .map_err(|_| invalid("signed grant courier input could not be opened"))?;
        let metadata = file
            .metadata()
            .map_err(|_| invalid("signed grant courier metadata is unavailable"))?;
        if !metadata.is_file()
            || metadata.uid() != issuer_uid
            || metadata.mode() & 0o022 != 0
            || metadata.nlink() != 1
            || metadata.len() == 0
            || metadata.len() > MAX_SIGNED_GRANT_FILE_BYTES as u64
        {
            return Err(invalid(
                "signed grant courier input is not protected and bounded",
            ));
        }
        // A fixed buffer also bounds a concurrent growth after metadata read.
        let mut bytes = [0_u8; MAX_SIGNED_GRANT_FILE_BYTES + 1];
        let mut used = 0;
        while used < bytes.len() {
            let read = file
                .read(&mut bytes[used..])
                .map_err(|_| invalid("signed grant courier input read failed"))?;
            if read == 0 {
                break;
            }
            used += read;
        }
        if used == 0 || used > MAX_SIGNED_GRANT_FILE_BYTES {
            return Err(invalid("signed grant courier frame exceeds its bound"));
        }
        let signed: SignedFinalUseGrant = serde_json::from_slice(&bytes[..used])
            .map_err(|_| invalid("signed grant courier requires one complete grant frame"))?;
        authority
            .check_unclaimed_grant(&signed, expected)
            .map_err(|_| invalid("signed grant courier authority rejected input"))?;
        Ok(Self { signed, authority })
    }

    #[cfg(not(unix))]
    pub fn open(
        _path: &Path,
        _issuer_uid: u32,
        _authority: FinalUseAuthority,
        _expected: &FinalUseBinding,
    ) -> Result<Self, AgentdError> {
        Err(invalid(
            "signed grant courier requires a qualified protected Unix input",
        ))
    }

    /// Explicitly attach to the already recovered original Agentd writer and
    /// this courier's same FinalUse owner. Default startup remains unchanged.
    /// This creates no writer, grant, namespace or physical resource owner.
    pub fn attach_to_host(
        self,
        host: AgentdProductionWriterHost,
        target: Arc<dyn FinalUseProductionOutboxTarget>,
    ) -> Result<AgentdProductionWriterHost, AgentdError> {
        if host.production_mutation().is_none()
            || target.destination_id() != self.signed.grant.binding.destination_id
        {
            return Err(invalid(
                "signed grant courier requires the recovered exact destination host",
            ));
        }
        let authority = self.authority.clone();
        host.attach_target(authority, target, Arc::new(self))
    }
}

impl AgentdFinalUseGrantProvider for SignedFinalUseGrantCourier {
    fn signed_grant(&self, expected: &FinalUseBinding) -> Result<SignedFinalUseGrant, AgentdError> {
        // Re-read this same owner's issuer window, current revocation/clock and
        // original nonce state on every request. Actual claim/entry remain the
        // original dispatcher's atomic one-shot and final live checks.
        self.authority
            .check_unclaimed_grant(&self.signed, expected)
            .map_err(|_| invalid("signed grant courier current authority refused delivery"))?;
        Ok(self.signed.clone())
    }
}

fn invalid(message: &'static str) -> AgentdError {
    AgentdError::Protocol(message.to_owned())
}

#[cfg(all(test, unix))]
#[path = "final_use_grant_courier_tests.rs"]
mod tests;
