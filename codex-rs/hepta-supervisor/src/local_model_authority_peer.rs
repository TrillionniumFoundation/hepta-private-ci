//! Reuse the issuer's actual Fleet peer admission without opening a signer.

use super::Config;
use super::ExecutableCache;
use super::Peer;
use super::capture_peer;
use super::protected_directory;
use super::read_protected;
use anyhow::Context;
use codex_hepta_fleet::FleetExecutionVerifier;
use sha2::Digest;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use tokio::net::UnixStream;

/// A read-only Root consumer of the original issuer policy, native executable
/// pins and Fleet process hold. It neither opens signing keys nor initializes
/// a frontier, grant, clock or alternate process registry.
pub struct RootFleetPeerAdmissionV1 {
    policy_path: PathBuf,
    policy_bytes: Vec<u8>,
    policy_sha256: [u8; 32],
    config: Config,
    verifier: FleetExecutionVerifier,
    executables: ExecutableCache,
}

/// Only actual kernel/Fleet admission constructs this process identity.
/// It is a factual identity for the original connection, not an effect grant.
pub struct RootAdmittedFleetPeerV1 {
    policy_sha256: [u8; 32],
    uid: u32,
    peer: Peer,
}

impl RootAdmittedFleetPeerV1 {
    pub fn subject(&self) -> &str {
        &self.peer.subject
    }
    pub fn uid(&self) -> u32 {
        self.uid
    }
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub fn pid(&self) -> u32 {
        self.peer.pid
    }
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub fn start_ticks(&self) -> u64 {
        self.peer.start_ticks
    }
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub fn cgroup(&self) -> &str {
        &self.peer.cgroup
    }
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub fn executable_sha256(&self) -> &str {
        &self.peer.executable_sha256
    }
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub fn policy_sha256(&self) -> [u8; 32] {
        self.policy_sha256
    }
}

impl RootFleetPeerAdmissionV1 {
    /// Reuse the original bounded, no-follow Root source reader. Reading a
    /// factual source does not open an issuer, signing key or owner frontier.
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub fn read_protected_source(
        path: &Path,
        maximum: usize,
        private: bool,
    ) -> anyhow::Result<Vec<u8>> {
        anyhow::ensure!(
            rustix::process::geteuid().as_raw() == 0 && (1..=1024 * 1024).contains(&maximum),
            "bounded protected source reading requires the actual Root owner"
        );
        read_protected(path, maximum, private)
    }

    pub async fn open(policy_path: &Path) -> anyhow::Result<Self> {
        anyhow::ensure!(
            rustix::process::geteuid().as_raw() == 0,
            "Fleet peer admission requires the actual Root owner"
        );
        let policy_bytes = read_protected(policy_path, 64 * 1024, true)?;
        let config: Config = serde_json::from_slice(&policy_bytes)?;
        config.validate()?;
        let executables = ExecutableCache::prewarm(
            &config.allowed_executable_paths,
            &config.allowed_executable_sha256,
        )?;
        protected_directory(&config.cgroup_root)?;
        let verifier = FleetExecutionVerifier::open(&config.fleet_database).await?;
        Ok(Self {
            policy_path: policy_path.to_owned(),
            policy_sha256: sha2::Sha256::digest(&policy_bytes).into(),
            policy_bytes,
            config,
            verifier,
            executables,
        })
    }

    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub async fn admit(&self, stream: &UnixStream) -> anyhow::Result<RootAdmittedFleetPeerV1> {
        let peer = self.capture(stream).await?;
        Ok(RootAdmittedFleetPeerV1 {
            policy_sha256: self.policy_sha256,
            uid: stream.peer_cred()?.uid(),
            peer,
        })
    }

    /// Validate an independently Root-custodied historical model observation
    /// against the original enrollment. This does not assert its old PID is
    /// alive or substitute it for authentication of the current held socket.
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub fn validate_historical_model_scope(
        &self,
        current: &RootAdmittedFleetPeerV1,
        subject: &str,
        cgroup: &str,
        executable_sha256: &str,
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            current.policy_sha256 == self.policy_sha256
                && read_protected(&self.policy_path, 64 * 1024, /*private*/ true)?
                    == self.policy_bytes
                && current.subject() == subject
                && self.config.admitted_subject(current.uid(), cgroup)? == subject
                && self
                    .config
                    .allowed_executable_sha256
                    .contains(executable_sha256),
            "historical native observation differs from original model enrollment"
        );
        Ok(())
    }

    /// The same held socket must still resolve to the original policy and
    /// exact PID/start/executable/cgroup/current Fleet hold before effects.
    #[cfg_attr(
        all(test, not(feature = "local-model-authority")),
        expect(
            dead_code,
            reason = "Off-feature tests only exercise peer gate open refusal."
        )
    )]
    pub async fn revalidate(
        &self,
        stream: &UnixStream,
        original: &RootAdmittedFleetPeerV1,
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            original.policy_sha256 == self.policy_sha256
                && original.uid == stream.peer_cred()?.uid()
                && original.peer == self.capture(stream).await?,
            "original admitted Fleet peer changed"
        );
        Ok(())
    }

    async fn capture(&self, stream: &UnixStream) -> anyhow::Result<Peer> {
        anyhow::ensure!(
            rustix::process::geteuid().as_raw() == 0
                && read_protected(&self.policy_path, 64 * 1024, true)? == self.policy_bytes,
            "original Root Fleet peer policy changed"
        );
        let observed = u64::try_from(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_millis(),
        )?;
        self.verifier.verify_owner_clock_floor(observed).await?;
        tokio::time::timeout(
            Duration::from_millis(self.config.request_timeout_ms),
            capture_peer(&self.config, &self.verifier, &self.executables, stream),
        )
        .await
        .context("original Fleet peer admission deadline elapsed")?
    }
}

#[cfg(test)]
#[path = "local_model_authority_peer_tests.rs"]
mod tests;
