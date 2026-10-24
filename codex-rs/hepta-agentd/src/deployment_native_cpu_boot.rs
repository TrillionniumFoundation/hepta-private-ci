//! Explicit original Root policy change after an independently observed boot.
//! No old watchdog receipt or old delivery result is inferred from this cut.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_supervisor::KernelLaunchMode;
use codex_hepta_supervisor::RootKernelLauncher;

impl DeploymentFinalUseIssuer {
    /// Replace the two exact original namespace policies for the actual new
    /// boot's initial pair. This is Root policy administration, separate from
    /// the same-boot kernel policy-retirement transaction. The former boot's
    /// pending K/D remains unresolved and receives no replacement capability.
    pub(crate) fn replace_native_cpu_namespaces_after_boot(
        &self,
        registration: &HostAuthorityWriterRegistration,
        launcher: &RootKernelLauncher,
        previous: &CognitiveCheckpointReceipt,
        retired: &crate::RetiredCheckpointPublisher,
        expected_scopes: [[u8; 32]; 2],
    ) -> io::Result<[[u8; 32]; 2]> {
        if unsafe { libc::geteuid() } != 0 || std::process::id() != 1 {
            return Err(denied("actual native Root required for new-boot policy"));
        }
        let root = retired
            .prior_boot_root_for_namespace(previous)
            .map_err(io::Error::other)?;
        let launch = launcher.query()?;
        let boot = launch.boot_id();
        let mut canonical_boot = String::with_capacity(36);
        for (index, byte) in boot.iter().enumerate() {
            if matches!(index, 4 | 6 | 8 | 10) {
                canonical_boot.push('-');
            }
            canonical_boot.push_str(&format!("{byte:02x}"));
        }
        if root.pid != 1
            || root.boot_id != canonical_boot
            || previous.head.peer_lifetime.boot_id == root.boot_id
            || registration.registered_agent_id != previous.head.owner_agent_id
            || launch.generation() != 0
            || launch.previous_generation() != 0
            || launch.mode() != KernelLaunchMode::ManagerRecovery
            || launch.root_pid() != 1
            || launch.workload_pid() != 3
            || launch.manager_pid() != Some(2)
            || launch.recovery_pid() != Some(4)
            || launch.history_pid().is_some()
            || expected_scopes[0] == expected_scopes[1]
            || expected_scopes.contains(&[0; 32])
        {
            return Err(denied(
                "new-boot policy differs from original Root and initial kernel pair",
            ));
        }
        let one = |space| -> io::Result<[u8; 32]> {
            let request = codex_hepta_memory::Hos2InstallBudgetV1 {
                schema_version: 1,
                delivery: codex_hepta_memory::Hos2DeliveryId::new(boot, space, 1)
                    .map_err(io::Error::other)?,
                manage_slot: 2,
                manage_generation: 1,
                expected_revision: 1,
                period_ns: codex_hepta_memory::HOS2_CPU_PERIOD_NS,
                cap_ns: 50_000_000,
            };
            Ok(request.scope_digest().into_array())
        };
        let spaces = launch.history_spaces();
        let next_scopes = [one(spaces[0])?, one(spaces[1])?];
        if next_scopes[0] == next_scopes[1]
            || (expected_scopes != next_scopes
                && next_scopes
                    .iter()
                    .any(|scope| expected_scopes.contains(scope)))
        {
            return Err(denied(
                "actual new boot reused an old exact CPU policy scope",
            ));
        }
        // A failed first activation can leave the exact new policies already
        // committed. The original full-token prior-boot and actual initial
        // kernel pair checks above still apply. Equal expectations below are
        // pure original retained-state verification, never a new policy grant.
        let result =
            self.replace_native_cpu_exact_scopes(registration, expected_scopes, next_scopes)?;
        if retired
            .prior_boot_root_for_namespace(previous)
            .map_err(io::Error::other)?
            != root
            || launcher.query()? != launch
        {
            return Err(io::Error::other(
                "new-boot Root/kernel observation changed after policy CAS",
            ));
        }
        Ok(result)
    }
}
