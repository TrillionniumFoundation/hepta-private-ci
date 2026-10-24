//! Original Root reopens the same canonical owner with a new finite lease.
//! New Process roles come solely from the existing kernel factory receipt.

use super::*;

#[derive(Clone, Debug)]
pub(super) struct OwnerImage {
    pub(super) role: u64,
    pub(super) pid: u32,
    pub(super) kernel: Option<KernelSuccessorImage>,
}
impl OwnerImage {
    pub(super) fn initial(role: KernelInitialRole) -> Self {
        let (role, pid) = match role {
            KernelInitialRole::Manager => (1, 2),
            KernelInitialRole::Recovery => (3, 4),
        };
        Self {
            role,
            pid,
            kernel: None,
        }
    }
    pub(super) fn successor(image: KernelSuccessorImage) -> Self {
        let role = match image.role() {
            KernelSuccessorRole::Manager => 1,
            KernelSuccessorRole::Recovery => 3,
            KernelSuccessorRole::HistoryOnly => 5,
        };
        Self {
            role,
            pid: image.pid(),
            kernel: Some(image),
        }
    }
    pub(super) fn generation(&self) -> u64 {
        self.kernel
            .as_ref()
            .map_or(0, |image| image.launch().generation())
    }
    pub(super) fn runtime_name(&self) -> io::Result<String> {
        owner_runtime_name(self.generation(), self.pid, self.role)
    }
    pub(super) fn label(&self) -> &'static str {
        match self.role {
            1 => "manager",
            3 => "recovery",
            _ => "history_only",
        }
    }
}

impl Installation {
    pub(super) fn refresh_canonical_root_lease(&mut self, spec: &SpawnSpec) -> io::Result<()> {
        if self.recovery.as_ref().is_none_or(|previous| {
            spec.agent_id != previous.writer.registered_agent_id
                || spec.generation <= previous.writer.spawn_generation
        }) {
            return Err(invalid(
                "canonical Root session rotation requires original retired owner material",
            ));
        }
        let mut old = self
            .leases
            .read_lease(&self.config.lease_id)
            .map_err(error)?
            .ok_or_else(|| invalid("original Root lease missing before session rotation"))?
            .lease;
        // The retained installation pin may name an already revoked session.
        // Reconstruct only its original issued revision; the helper verifies
        // the complete original record and actual revocation before reuse as
        // a template. It does not treat that template as live authority.
        old.revision = self.config.lease_revision;
        let now = self.clock.now_unix_ms().map_err(error)?;
        let mut next = old.clone();
        next.lease_id = cold_open::lease_id("root", spec)?;
        next.revision = 1;
        next.issued_at_unix_ms = now;
        next.expires_at_unix_ms = now
            .checked_add(LIFETIME.as_millis() as u64)
            .ok_or_else(|| invalid("new canonical Root lease overflow"))?;
        // The old finite lease is permanently retired, never extended. The
        // fresh original lease has another ID and keeps its actual authority
        // epoch and observation-only binding in the same registry.
        let reason: [u8; 32] = Sha256::digest(
            serde_json::to_vec(&(
                "native-cpu-root-session-retirement.v1",
                &old,
                &next.lease_id,
                &self.recovery.as_ref().unwrap().previous.token,
            ))
            .map_err(error)?,
        )
        .into();
        cold_open::retire_lease_for_handoff(&self.leases, &self.clock, &old, reason)?;
        self.leases.put_lease(next.clone(), 0).map_err(error)?;
        // Open, never create: the original canonical key, head, counter,
        // writer proof and policies remain in their existing protected store.
        let issuer = Arc::new(crate::DeploymentFinalUseIssuer::open_protected(
            &self.config.state_dir.join("issuer"),
            self.clock.clone(),
            self.leases.verifier(),
            next.lease_id.clone(),
            next.revision,
        )?);
        let key = issuer.trust_key()?;
        if key.key_id != self.config.signer_id
            || key.verifying_key != self.config.expected_verifying_key
        {
            return Err(invalid(
                "canonical issuer identity changed while opening the new finite Root session",
            ));
        }
        self.issuer = issuer;
        self.config.lease_id = next.lease_id;
        self.config.lease_revision = next.revision;
        Ok(())
    }
}
