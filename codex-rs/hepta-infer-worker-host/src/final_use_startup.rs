//! Startup-only physical readiness. No grant, trust frame or local owner is
//! created by waiting; the first trust LOAD may enroll the original frontier.

use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use super::Result;
use super::UnixFinalUseTrustPort;
use super::remaining;
use crate::final_use_authorizer::IssuerProcessGuard;
use crate::final_use_authorizer::validate_connected_issuer_with_attestation;
use crate::final_use_authorizer::validate_issuer_socket;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::MODEL_ISSUER_SCHEMA_VERSION;
use codex_hepta_contracts::MODEL_TRUST_LOAD;
use codex_hepta_contracts::ModelTrustRequest;
use codex_hepta_contracts::ModelTrustResponse;

impl UnixFinalUseTrustPort {
    pub(crate) fn load_startup_snapshot(&self) -> Result<ModelTrustResponse> {
        let deadline = Instant::now()
            .checked_add(self.timeout)
            .ok_or(AuthorityTrustError::Invalid)?;
        loop {
            remaining(deadline)?;
            if let Some((stream, guard)) = self.startup_connection()? {
                return self.exchange_connected(
                    ModelTrustRequest {
                        schema_version: MODEL_ISSUER_SCHEMA_VERSION,
                        operation: MODEL_TRUST_LOAD.into(),
                        signer_id: self.signer_id.clone(),
                        expected: None,
                        next: None,
                    },
                    stream,
                    guard,
                    deadline,
                );
            }
            std::thread::sleep(remaining(deadline)?.min(Duration::from_millis(20)));
        }
    }

    fn startup_connection(&self) -> Result<Option<(UnixStream, IssuerProcessGuard)>> {
        if !protected_publication_ready(&self.issuer_socket, self.issuer_uid)? {
            return Ok(None);
        }
        validate_issuer_socket(&self.issuer_socket, self.issuer_uid)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        let socket = rustix::net::socket_with(
            rustix::net::AddressFamily::UNIX,
            rustix::net::SocketType::STREAM,
            rustix::net::SocketFlags::NONBLOCK | rustix::net::SocketFlags::CLOEXEC,
            /*protocol*/ None,
        )
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        let address = rustix::net::SocketAddrUnix::new(&self.issuer_socket)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        match rustix::net::connect(&socket, &address) {
            Ok(()) => {}
            Err(rustix::io::Errno::NOENT | rustix::io::Errno::CONNREFUSED) => return Ok(None),
            // A full backlog, permissions failure or other error is not a
            // startup publication signal. It remains an immediate failure.
            Err(_) => return Err(AuthorityTrustError::Unavailable),
        }
        let peer = rustix::net::sockopt::socket_peercred(&socket)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if peer.uid.as_raw() != self.issuer_uid {
            return Err(AuthorityTrustError::Invalid);
        }
        if let Some(path) = self.process_attestation.as_deref()
            && !protected_publication_ready(path, /*owner_uid*/ 0)?
        {
            return Ok(None);
        }
        // An existing stale, malformed or mismatched identity never becomes a
        // retryable error. The producer publishes identity before binding.
        let guard = validate_connected_issuer_with_attestation(
            Some(u32::try_from(peer.pid.as_raw_pid()).map_err(|_| AuthorityTrustError::Invalid)?),
            self.process_identity.as_ref(),
            self.process_attestation.as_deref(),
        )
        .map_err(|_| AuthorityTrustError::Invalid)?
        .ok_or(AuthorityTrustError::Invalid)?;
        Ok(Some((UnixStream::from(socket), guard)))
    }
}

fn protected_publication_ready(path: &Path, owner_uid: u32) -> Result<bool> {
    if !path.is_absolute() {
        return Err(AuthorityTrustError::Invalid);
    }
    let mut present = true;
    let mut protected_anchor = false;
    for directory in path
        .parent()
        .ok_or(AuthorityTrustError::Invalid)?
        .ancestors()
    {
        match std::fs::symlink_metadata(directory) {
            Ok(metadata) => {
                let protected = metadata.is_dir()
                    && (metadata.uid() == 0 || metadata.uid() == owner_uid)
                    && metadata.mode() & 0o022 == 0;
                // Root sticky ancestors are safe only above an already present
                // protected directory. Waiting directly in shared /tmp is not.
                let sticky_ancestor = metadata.is_dir()
                    && metadata.uid() == 0
                    && metadata.mode() & 0o1000 != 0
                    && protected_anchor;
                if !protected && !sticky_ancestor {
                    return Err(AuthorityTrustError::Invalid);
                }
                protected_anchor |= protected;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => present = false,
            Err(_) => return Err(AuthorityTrustError::Invalid),
        }
    }
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.uid() != owner_uid
                || (!metadata.file_type().is_socket() && !metadata.is_file())
                || metadata.mode() & 0o022 != 0
                    && (!metadata.file_type().is_socket() || metadata.mode() & 0o007 != 0)
            {
                return Err(AuthorityTrustError::Invalid);
            }
            Ok(present)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err(AuthorityTrustError::Invalid),
    }
}

#[cfg(test)]
#[path = "final_use_startup_tests.rs"]
mod tests;
