//! Explicit G2 history successor; no management or current-usage capability.
//! The original writer still owns K/D recovery and the retirement permit.

use super::AgentdHos2Device;
use super::ControlTransport;
use super::FileTransport;
use super::ProcessIdentity;
use super::read16;
use super::read64;
use codex_hepta_memory::HOS2_CPU_PERIOD_NS;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::Hos2DeliveryObservation;
use codex_hepta_memory::Hos2Device;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::Hos2InstallContradiction;
use codex_hepta_memory::Hos2InstallOutcome;
use codex_hepta_memory::Hos2RetirementObservation;
use codex_hepta_memory::Hos2RetirementPermit;
use std::fs::File;

// The retained original G2 request profile, not a grant to this successor.
const ORIGINAL_MANAGE_SLOT: u64 = 2;
const ORIGINAL_MANAGE_GENERATION: u64 = 1;
const ORIGINAL_MAXIMUM_CAP_NS: u64 = 50_000_000;

/// A role-5 successor can query the two retained old namespaces and acknowledge
/// only a prefix proved by the original durable writer. It cannot construct an
/// install request, read current CPU usage or execute any InstallBudget call.
/// The private inner device shares only the original framing and history code;
/// callers cannot recover it as a management adapter.
pub struct AgentdHos2HistoryDevice {
    device: AgentdHos2Device,
}

impl AgentdHos2HistoryDevice {
    /// Attach only the actual v4 role-5 child of Root PID 1. This file must have
    /// been opened by this same final process image; copying discovery bytes or
    /// receiving another image's file does not transfer kernel capabilities.
    /// QueryAbi must report this successor's local space, not either old D space.
    /// No writer, issuer, FinalUse owner, grant or terminal state is created.
    pub fn from_g2_successor_bootstrap(file: File, bootstrap: &[u8]) -> Result<Self, String> {
        Self::attach(
            Box::new(FileTransport { file }),
            bootstrap,
            ProcessIdentity::current(),
        )
    }

    fn attach(
        transport: Box<dyn ControlTransport>,
        bootstrap: &[u8],
        process: ProcessIdentity,
    ) -> Result<Self, String> {
        if bootstrap.len() < 240
            || bootstrap.len() > 4096
            || &bootstrap[..8] != b"HOS2BOOT"
            || read64(bootstrap, /*offset*/ 8)? != 4
            || read64(bootstrap, /*offset*/ 16)? != 5
            || read64(bootstrap, /*offset*/ 24)? != 240
            || bootstrap[232..].iter().any(|byte| *byte != 0)
            || read64(bootstrap, /*offset*/ 144)? != 0
            || read64(bootstrap, /*offset*/ 160)? != 0
            || read64(bootstrap, /*offset*/ 168)? != 0
            || read64(bootstrap, /*offset*/ 176)? != HOS2_CPU_PERIOD_NS
            || read64(bootstrap, /*offset*/ 184)? != 0
            || read64(bootstrap, /*offset*/ 192)? != 1
            || read64(bootstrap, /*offset*/ 200)? != u64::from(process.pid)
            || read64(bootstrap, /*offset*/ 224)? == 0
            || process.parent_pid != 1
            || !(2..=i32::MAX as u32).contains(&process.pid)
        {
            return Err("invalid G2 history-only successor discovery".to_string());
        }
        let workload = read64(bootstrap, /*offset*/ 152)?;
        if !(2..=i32::MAX as u64).contains(&workload) || workload == u64::from(process.pid) {
            return Err("G2 history successor aliases the workload process".to_string());
        }
        for (index, expected) in [0, 0, 0, 0, 3, 1, 4, 1].into_iter().enumerate() {
            if read64(bootstrap, 32 + index * 8)? != expected {
                return Err("G2 history successor has different capability slots".to_string());
            }
        }
        let boot_id = read16(bootstrap, /*offset*/ 96)?;
        let manager_space = read16(bootstrap, /*offset*/ 112)?;
        let recovery_space = read16(bootstrap, /*offset*/ 128)?;
        let local_space = read16(bootstrap, /*offset*/ 208)?;
        if [boot_id, manager_space, recovery_space, local_space].contains(&[0; 16])
            || manager_space == recovery_space
            || local_space == manager_space
            || local_space == recovery_space
        {
            return Err(
                "G2 history successor local and retained spaces are invalid or aliased".to_string(),
            );
        }
        let device = AgentdHos2Device {
            transport,
            boot_id,
            local_space,
            manager_space,
            recovery_space,
            observe_slot: 0,
            observe_generation: 0,
            manage_slot: 0,
            manage_generation: 0,
            manager_history: (3, 1),
            recovery_history: (4, 1),
            maximum_cap_ns: 0,
        };
        device.check_query_abi()?;
        Ok(Self { device })
    }
}

impl Hos2Device for AgentdHos2HistoryDevice {
    fn install(&self, _request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        // Even an exact old K/D must never be replayed through this image.
        // No ioctl, asynchronous task or effect fallback is reachable here.
        Err("G2 history-only successor cannot execute InstallBudget".to_string())
    }

    fn observe(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        request.to_json()?;
        self.device.history_slot(&request.delivery)?;
        // These constants validate the immutable request's ORIGINAL G2 profile.
        // The current page correctly contains no management slot, cap or lease.
        // Do not compare an old effect with this successor's zero authority.
        if request.manage_slot != ORIGINAL_MANAGE_SLOT
            || request.manage_generation != ORIGINAL_MANAGE_GENERATION
        {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::RequestBindingMismatch,
            ));
        }
        if request.cap_ns > ORIGINAL_MAXIMUM_CAP_NS {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::BudgetExceedsGrant {
                    maximum_cap_ns: ORIGINAL_MAXIMUM_CAP_NS,
                },
            ));
        }
        self.device
            .query(&request.delivery)
            .map(Hos2InstallOutcome::Observed)
    }

    fn query(&self, delivery: &Hos2DeliveryId) -> Result<Hos2DeliveryObservation, String> {
        self.device.query(delivery)
    }

    fn retire(&self, permit: &Hos2RetirementPermit) -> Result<Hos2RetirementObservation, String> {
        // The only public proof type has no caller constructor or deserializer.
        // Its original writer rechecks its live authority after SQLite awaits.
        self.device.retire(permit)
    }
}

#[cfg(test)]
#[path = "hos2_history_tests.rs"]
mod tests;
