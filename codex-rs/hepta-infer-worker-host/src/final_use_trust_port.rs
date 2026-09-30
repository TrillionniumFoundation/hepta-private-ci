//! Protected root-side time and nonce-frontier oracle for the local verifier.

use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::MODEL_ISSUER_MAX_REQUEST_BYTES;
use codex_hepta_contracts::MODEL_ISSUER_MAX_RESPONSE_BYTES;
use codex_hepta_contracts::MODEL_ISSUER_SCHEMA_VERSION;
use codex_hepta_contracts::MODEL_TRUST_CAS;
use codex_hepta_contracts::MODEL_TRUST_LOAD;
use codex_hepta_contracts::ModelTrustRequest;
use codex_hepta_contracts::ModelTrustResponse;

use crate::final_use_authorizer::FinalUseAuthorizerConfig;
use crate::final_use_authorizer::IssuerProcessIdentityConfig;

type Result<T> = std::result::Result<T, AuthorityTrustError>;

/// Both trust interfaces use the independently operated root issuer. Neither
/// local wall time nor a missing/uncertain response can manufacture a frontier.
pub(crate) struct UnixFinalUseTrustPort {
    issuer_socket: PathBuf,
    issuer_uid: u32,
    signer_id: String,
    timeout: Duration,
    process_identity: Option<IssuerProcessIdentityConfig>,
    process_attestation: Option<PathBuf>,
}

impl UnixFinalUseTrustPort {
    pub(crate) fn for_production(config: &FinalUseAuthorizerConfig) -> Result<Self> {
        if !cfg!(target_os = "linux")
            || config.issuer_uid != 0
            || !config.issuer_socket.is_absolute()
            || config.signer_id.is_empty()
            || config.signer_id.len() > 256
            || !(1..=30_000).contains(&config.issuer_timeout_ms)
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let process_attestation = config
            .issuer_process_attestation
            .clone()
            .filter(|path| path.is_absolute())
            .ok_or(AuthorityTrustError::Invalid)?;
        Ok(Self {
            issuer_socket: config.issuer_socket.clone(),
            issuer_uid: config.issuer_uid,
            signer_id: config.signer_id.clone(),
            timeout: Duration::from_millis(config.issuer_timeout_ms),
            process_identity: config.issuer_process_identity.clone(),
            process_attestation: Some(process_attestation),
        })
    }

    pub(crate) fn load_snapshot(&self) -> Result<ModelTrustResponse> {
        self.exchange(ModelTrustRequest {
            schema_version: MODEL_ISSUER_SCHEMA_VERSION,
            operation: MODEL_TRUST_LOAD.into(),
            signer_id: self.signer_id.clone(),
            expected: None,
            next: None,
        })
    }

    #[cfg(target_os = "linux")]
    fn exchange(&self, request: ModelTrustRequest) -> Result<ModelTrustResponse> {
        use std::io::Write;
        use std::os::unix::net::UnixStream;
        use std::time::Instant;

        use crate::final_use_authorizer::validate_connected_issuer_with_attestation;
        use crate::final_use_authorizer::validate_issuer_socket;

        let deadline = Instant::now()
            .checked_add(self.timeout)
            .ok_or(AuthorityTrustError::Invalid)?;
        validate_issuer_socket(&self.issuer_socket, self.issuer_uid)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        let bytes = serde_json::to_vec(&request).map_err(|_| AuthorityTrustError::Invalid)?;
        if bytes.is_empty() || bytes.len() > MODEL_ISSUER_MAX_REQUEST_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let socket = rustix::net::socket_with(
            rustix::net::AddressFamily::UNIX,
            rustix::net::SocketType::STREAM,
            rustix::net::SocketFlags::NONBLOCK | rustix::net::SocketFlags::CLOEXEC,
            /*protocol*/ None,
        )
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        let address = rustix::net::SocketAddrUnix::new(&self.issuer_socket)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        // A full local backlog fails closed immediately; connect cannot block
        // beyond the caller's trust deadline waiting for a malicious listener.
        rustix::net::connect(&socket, &address).map_err(|_| AuthorityTrustError::Unavailable)?;
        let peer = rustix::net::sockopt::socket_peercred(&socket)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if peer.uid.as_raw() != self.issuer_uid {
            return Err(AuthorityTrustError::Invalid);
        }
        let guard = validate_connected_issuer_with_attestation(
            Some(u32::try_from(peer.pid.as_raw_pid()).map_err(|_| AuthorityTrustError::Invalid)?),
            self.process_identity.as_ref(),
            self.process_attestation.as_deref(),
        )
        .map_err(|_| AuthorityTrustError::Invalid)?
        .ok_or(AuthorityTrustError::Invalid)?;
        let mut stream = UnixStream::from(socket);
        stream
            .set_nonblocking(false)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let mut frame = u32::try_from(bytes.len())
            .map_err(|_| AuthorityTrustError::Invalid)?
            .to_be_bytes()
            .to_vec();
        frame.extend_from_slice(&bytes);
        while !frame.is_empty() {
            stream
                .set_write_timeout(Some(remaining(deadline)?))
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            match stream.write(&frame) {
                Ok(0) => return Err(AuthorityTrustError::Unavailable),
                Ok(count) => {
                    frame.drain(..count);
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => return Err(AuthorityTrustError::Unavailable),
            }
        }
        let mut header = [0_u8; 4];
        read_before(&mut stream, &mut header, deadline)?;
        let length = usize::try_from(u32::from_be_bytes(header))
            .map_err(|_| AuthorityTrustError::Invalid)?;
        if !(1..=MODEL_ISSUER_MAX_RESPONSE_BYTES).contains(&length) {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut response = vec![0_u8; length];
        read_before(&mut stream, &mut response, deadline)?;
        guard
            .revalidate()
            .map_err(|_| AuthorityTrustError::Invalid)?;
        remaining(deadline)?;
        let response =
            serde_json::from_slice(&response).map_err(|_| AuthorityTrustError::Invalid)?;
        validate_response(&response)?;
        Ok(response)
    }

    #[cfg(not(target_os = "linux"))]
    fn exchange(&self, _request: ModelTrustRequest) -> Result<ModelTrustResponse> {
        Err(AuthorityTrustError::Unavailable)
    }
}

impl AuthorityClock for UnixFinalUseTrustPort {
    fn now_unix_ms(&self) -> Result<u64> {
        let response = self.load_snapshot()?;
        Ok(response.now_unix_ms)
    }
}

impl AuthorityFrontierStore<FinalUseFrontier> for UnixFinalUseTrustPort {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier> {
        if owner_id != self.signer_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let response = self.load_snapshot()?;
        Ok(response.frontier)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<()> {
        if owner_id != self.signer_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let response = self.exchange(ModelTrustRequest {
            schema_version: MODEL_ISSUER_SCHEMA_VERSION,
            operation: MODEL_TRUST_CAS.into(),
            signer_id: owner_id.into(),
            expected: Some(*expected),
            next: Some(*next),
        })?;
        if response.frontier != *next {
            return Err(AuthorityTrustError::Conflict);
        }
        Ok(())
    }
}

fn validate_response(response: &ModelTrustResponse) -> Result<()> {
    if response.schema_version != MODEL_ISSUER_SCHEMA_VERSION
        || response.now_unix_ms == 0
        || response.frontier.authority_epoch == 0
        || response.frontier.revocation_revision == 0
        || response.frontier.state_sha256 == [0; 32]
        || response.revocations.authority_epoch != response.frontier.authority_epoch
        || response.revocations.revision != response.frontier.revocation_revision
    {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn remaining(deadline: std::time::Instant) -> Result<Duration> {
    deadline
        .checked_duration_since(std::time::Instant::now())
        .filter(|remaining| !remaining.is_zero())
        .ok_or(AuthorityTrustError::Unavailable)
}

#[cfg(target_os = "linux")]
fn read_before(
    stream: &mut std::os::unix::net::UnixStream,
    mut output: &mut [u8],
    deadline: std::time::Instant,
) -> Result<()> {
    use std::io::Read;

    while !output.is_empty() {
        stream
            .set_read_timeout(Some(remaining(deadline)?))
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        match stream.read(output) {
            Ok(0) => return Err(AuthorityTrustError::Unavailable),
            Ok(count) => output = &mut output[count..],
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(AuthorityTrustError::Unavailable),
        }
    }
    Ok(())
}

#[cfg(all(test, target_os = "linux"))]
#[path = "final_use_trust_port_tests.rs"]
mod tests;
