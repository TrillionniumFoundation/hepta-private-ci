//! Trusted native Root installation of one existing HOS2 namespace policy.
//! Exact request leases and signing reuse the original Notes effect-admission
//! mechanism; no nonce journal, key, sequence or lease registry is introduced.
use super::writer::WriterRegistrationExt;
use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;

pub(crate) struct RootNativeCpuGrantAdmission {
    registry: Arc<AuthorityLeaseRegistry>,
    writer: HostAuthorityWriterRegistration,
    proof: crate::HostSignedWriterAuthorizationV1,
    policy: DeploymentGrantPolicy,
}
fn denied(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}
impl RootNativeCpuGrantAdmission {
    pub(crate) fn from_registered_namespace(
        issuer: &DeploymentFinalUseIssuer,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        scope: [u8; 32],
        lifetime_ms: u64,
    ) -> io::Result<Self> {
        if unsafe { libc::geteuid() } != 0
            || std::process::id() != 1
            || scope == [0; 32]
            || !(1..=30_000).contains(&lifetime_ms)
        {
            return Err(denied(
                "actual native Root and finite namespace policy required",
            ));
        }
        writer.validate()?;
        let policy = DeploymentGrantPolicy {
            subject_id: writer.registered_agent_id.to_string(),
            destination_id: codex_hepta_memory::HOS2_DESTINATION_V1.into(),
            scope_sha256: scope,
            lifetime_ms,
        };
        let canonical = &issuer
            .lease
            .as_ref()
            .ok_or_else(|| denied("protected canonical issuer required"))?
            .verifier;
        let actual = registry
            .read_lease(&writer.authority_lease.lease_id)
            .map_err(root::lease_error)?
            .ok_or_else(|| denied("registered writer missing"))?;
        if actual.lease != writer.authority_lease {
            return Err(denied("registered writer changed"));
        }
        let token = registry
            .verifier()
            .verify_use(
                &actual.lease.lease_id,
                actual.lease.revision,
                &actual.lease.binding,
            )
            .map_err(root::lease_error)?;
        let proof = canonical
            .with_dispatch_boundary(token, &actual.lease.binding, || {
                let state = issuer.store.load(STATE_OWNER).map_err(io::Error::other)?;
                if state
                    .policies
                    .iter()
                    .filter(|entry| **entry == policy)
                    .count()
                    != 1
                {
                    return Err(denied(
                        "one exact registered native namespace policy required",
                    ));
                }
                issuer.retained_writer_authorization(&writer)
            })
            .map_err(root::lease_error)??;
        Ok(Self {
            registry,
            writer,
            proof,
            policy,
        })
    }
    pub(crate) fn matches_writer(
        &self,
        writer: &HostAuthorityWriterRegistration,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> bool {
        self.writer == *writer && self.proof == *proof
    }
    pub(crate) fn issue(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        binding: &FinalUseBinding,
    ) -> io::Result<Option<SignedFinalUseGrant>> {
        let bytes = serde_json::to_vec(&(
            "runtime.hos2.effect-lease.v1",
            self.proof.sha256()?,
            binding,
        ))?;
        let lease_id = format!(
            "hos2-effect.{}",
            codex_hepta_contracts::Sha256Digest::for_bytes(&bytes)
        );
        super::registered_effect::issue(
            issuer,
            &self.registry,
            &self.writer,
            &self.proof,
            &self.policy,
            lease_id,
            binding,
        )
    }
}
