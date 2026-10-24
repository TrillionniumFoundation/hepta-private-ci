//! Original unused issuer administration across an interrupted installation.
//! This path cannot rotate a used writer, issue a grant or reset a sequence.

use super::*;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use codex_hepta_supervisor::KernelLaunchMode;
use codex_hepta_supervisor::RootKernelLauncher;

fn require_unused(state: &IssuerState) -> io::Result<()> {
    if state.sequence != 0
        || state.writer_authorization.is_some()
        || state.head.authority_epoch != 1
        || state.head.revision != 1
        || !state.head.revoked_grant_ids.is_empty()
    {
        return Err(denied("original issuer is not its unused genesis"));
    }
    Ok(())
}

impl DeploymentFinalUseIssuer {
    pub(crate) fn with_original_unused_genesis_for_root<R>(
        &self,
        inspect: impl FnOnce(&str, [u8; 32], &[DeploymentGrantPolicy]) -> io::Result<R>,
    ) -> io::Result<R> {
        if unsafe { libc::geteuid() } != 0 || self.lease.is_none() {
            return Err(denied("actual Root and original protected issuer required"));
        }
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        require_unused(&state)?;
        let result = inspect(
            &state.signer_id,
            self.key.verifying_key().to_bytes(),
            &state.policies,
        );
        if self.store.load(STATE_OWNER).map_err(io::Error::other)? != state {
            return Err(io::Error::other(
                "original unused issuer changed during administration",
            ));
        }
        result
    }

    /// A new actual kernel boot can replace the original unused installation's
    /// two policies. The full existing issuer remains at sequence zero, under
    /// one original request lock from exact-state check through policy CAS.
    /// This is not the PriorBoot checkpoint/Current path.
    pub(crate) fn replace_unused_native_cpu_namespaces_for_root(
        &self,
        launcher: &RootKernelLauncher,
        genesis: &crate::authority_host_checkpoint::RetainedCheckpointGenesis,
        material: &VerifiedCognitiveMaterial,
    ) -> io::Result<[[u8; 32]; 2]> {
        let root = crate::HostAuthorityService::current_root_lifetime_for_admin()?;
        if root.pid != 1 || self.lease.is_none() {
            return Err(denied("actual native Root required"));
        }
        let launch = launcher.query()?;
        let boot = launch.boot_id();
        let mut canonical_boot = String::with_capacity(36);
        for (index, byte) in boot.iter().enumerate() {
            if matches!(index, 4 | 6 | 8 | 10) {
                canonical_boot.push('-');
            }
            canonical_boot.push_str(&format!("{byte:02x}"));
        }
        if root.boot_id != canonical_boot
            || launch.generation() != 0
            || launch.previous_generation() != 0
            || launch.mode() != KernelLaunchMode::ManagerRecovery
            || launch.root_pid() != 1
            || launch.workload_pid() != 3
            || launch.manager_pid() != Some(2)
            || launch.recovery_pid() != Some(4)
            || launch.history_pid().is_some()
        {
            return Err(denied(
                "unused policy requires the actual initial final-image pair",
            ));
        }
        let one = |space| -> io::Result<[u8; 32]> {
            Ok(codex_hepta_memory::Hos2InstallBudgetV1 {
                schema_version: 1,
                delivery: codex_hepta_memory::Hos2DeliveryId::new(boot, space, 1)
                    .map_err(io::Error::other)?,
                manage_slot: 2,
                manage_generation: 1,
                expected_revision: 1,
                period_ns: codex_hepta_memory::HOS2_CPU_PERIOD_NS,
                cap_ns: 50_000_000,
            }
            .scope_digest()
            .into_array())
        };
        let spaces = launch.history_spaces();
        let scopes = [one(spaces[0])?, one(spaces[1])?];
        if scopes[0] == scopes[1] {
            return Err(denied("native policy scopes are not distinct"));
        }
        genesis
            .with_no_checkpoint(material, || {
                let _guard = self
                    .request_lock
                    .lock()
                    .map_err(|_| io::Error::other("issuer fenced"))?;
                let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
                require_unused(&state)?;
                genesis
                    .require_issuer(&state.signer_id, self.key.verifying_key().to_bytes())
                    .map_err(io::Error::other)?;
                if state.policies.len() != 2
                    || state.policies.iter().any(|policy| {
                        policy.subject_id != genesis.cut().owner_agent_id.as_str()
                            || policy.destination_id != codex_hepta_memory::HOS2_DESTINATION_V1
                            || policy.lifetime_ms != 5_000
                            || policy.scope_sha256 == [0; 32]
                    })
                    || state.policies[0].scope_sha256 == state.policies[1].scope_sha256
                    || genesis.initial_policies().len() != 2
                {
                    return Err(denied(
                        "original unused native policy is not the fixed finite pair",
                    ));
                }
                let mut next = state.clone();
                for (policy, scope) in next.policies.iter_mut().zip(scopes) {
                    policy.scope_sha256 = scope;
                }
                if next != state {
                    if root.boot_id == genesis.initial_root().boot_id {
                        return Err(denied(
                            "same initial boot cannot change its untouched namespace policy",
                        ));
                    }
                    self.store
                        .compare_and_set(STATE_OWNER, &state, &next)
                        .map_err(io::Error::other)?;
                }
                if self.store.load(STATE_OWNER).map_err(io::Error::other)? != next
                    || launcher.query()? != launch
                    || crate::HostAuthorityService::current_root_lifetime_for_admin()? != root
                {
                    return Err(io::Error::other(
                        "unused native policy observation changed after original CAS",
                    ));
                }
                Ok(scopes)
            })
            .map_err(io::Error::other)?
    }
}
