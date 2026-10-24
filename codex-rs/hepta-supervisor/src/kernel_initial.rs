//! Process custody for original G2 images and its restricted kernel factory.
//!
//! The original Supervisor owns lifecycle transitions, generations and its
//! durable process lease. The driver releases already-created final images;
//! optional successors come only from the same authenticated kernel factory.
//! It never executes a caller-selected program or creates a native grant.

use std::os::fd::AsFd;
use std::os::fd::BorrowedFd;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessIdentity;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::UnixManagedProcess;

#[path = "kernel_initial_child.rs"]
mod child;
pub(crate) use child::KernelInitialChild;

#[path = "kernel_launcher.rs"]
mod launcher;
pub use launcher::KernelLaunchMode;
pub use launcher::KernelLaunchReceipt;
pub use launcher::KernelPolicyRetirement;
pub use launcher::RootKernelLauncher;

#[path = "kernel_initial_successor.rs"]
mod successor;
pub use successor::KernelSuccessorImage;
pub use successor::KernelSuccessorRole;
use successor::KernelSuccessorSource;

/// One of the two already-loaded management images in the G2 transaction.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KernelInitialRole {
    Manager,
    Recovery,
}

/// Bounded activation of the kernel-created final images, with original
/// Supervisor generation allocation and process-lease persistence.
///
/// `activate` is installed by the trusted Root composition. It must validate
/// the real child peer and deliver its finite configuration within a deadline;
/// it receives the original `SpawnSpec`, role and an already-held actual pidfd.
/// It must not fork/exec, rewrite lifecycle state or manufacture authority.
/// Root remains the exclusive child reaper for the driver's entire lifetime.
pub struct KernelInitialProcessDriver<F> {
    children: [Option<KernelInitialChild>; 2],
    command: AgentCommand,
    activate: F,
    previous: Option<(codex_hepta_contracts::AgentId, u64)>,
    successors: Option<KernelSuccessorSource>,
}

impl<F> KernelInitialProcessDriver<F>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    /// Takes custody only as the actual Root PID 1 of a G2 v3 transaction.
    /// Discovery values alone grant nothing: each slot is independently bound
    /// to an actual unreaped child, held pidfd, boot identity and start time.
    pub fn new(
        bootstrap: &[u8],
        command: AgentCommand,
        activate: F,
    ) -> Result<Self, ProcessDriverError> {
        validate_root(bootstrap)?;
        let manager = KernelInitialChild::capture_if_present(/*pid*/ 2)?;
        let recovery = KernelInitialChild::capture_if_present(/*pid*/ 4)?;
        Ok(Self {
            children: [manager, recovery],
            command,
            activate,
            previous: None,
            successors: None,
        })
    }

    /// Continue through the original kernel factory after the initial slots.
    /// The Root observation directory is the existing protected administration
    /// namespace. Every actual launch is saved and ACKed before activation,
    /// independently of whether a new Host ever reaches Ready.
    pub fn with_successors<G>(
        mut self,
        bootstrap: &[u8],
        launcher: std::sync::Arc<RootKernelLauncher>,
        observations: std::sync::Arc<codex_hepta_contracts::RootAuthorityDirectory>,
        activate: G,
    ) -> Result<Self, ProcessDriverError>
    where
        G: for<'fd> FnMut(
                &SpawnSpec,
                &KernelSuccessorImage,
                BorrowedFd<'fd>,
            ) -> Result<(), ProcessDriverError>
            + 'static,
    {
        validate_root(bootstrap)?;
        if self.previous.is_some() || self.successors.is_some() {
            return Err(ProcessDriverError::new(
                "kernel successor source must be installed before lifecycle use",
            ));
        }
        self.successors = Some(KernelSuccessorSource::new(
            bootstrap,
            launcher,
            observations,
            activate,
        )?);
        Ok(self)
    }
}

impl<F> ProcessDriver for KernelInitialProcessDriver<F>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    type Process = UnixManagedProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        if spec.generation == 0
            || spec.command != self.command
            || self.previous.as_ref().is_some_and(|(agent, generation)| {
                agent != &spec.agent_id || spec.generation <= *generation
            })
        {
            return Err(ProcessDriverError::new(
                "kernel-initial spawn differs from its fixed release or generation fence",
            ));
        }
        if self.children.iter().all(Option::is_none) {
            let source = self.successors.as_mut().ok_or_else(|| {
                ProcessDriverError::new("kernel-initial management images are exhausted")
            })?;
            let (image, child) = source.take_next()?;
            child.check_alive()?;
            let identity = process_identity(&child, spec.generation)?;
            self.previous = Some((spec.agent_id.clone(), spec.generation));
            source.activate(spec, &image, child.as_fd())?;
            child.check_alive()?;
            let process = UnixManagedProcess::from_kernel_initial_spawn(spec, child)?;
            return Ok(SpawnedProcess { identity, process });
        }
        let (index, role) = if self.children[0].is_some() {
            (0, KernelInitialRole::Manager)
        } else {
            (1, KernelInitialRole::Recovery)
        };
        let child = self.children[index].take().ok_or_else(|| {
            ProcessDriverError::new("kernel-initial management images are exhausted")
        })?;
        child.check_alive()?;
        let identity = process_identity(&child, spec.generation)?;
        // From this point failure consumes the slot and the guard terminates
        // and reaps exactly this child; a partial activation is never replayed.
        self.previous = Some((spec.agent_id.clone(), spec.generation));
        (self.activate)(spec, role, child.as_fd())?;
        child.check_alive()?;
        let process = UnixManagedProcess::from_kernel_initial_spawn(spec, child)?;
        Ok(SpawnedProcess { identity, process })
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        let index = match spec.identity.system_id() {
            2 => 0,
            4 => 1,
            _ => {
                if spec.spawn_generation == 0
                    || spec.registry_generation < spec.spawn_generation
                    || self.previous.as_ref().is_some_and(|(agent, generation)| {
                        agent != &spec.agent_id || spec.spawn_generation <= *generation
                    })
                {
                    return Ok(Adoption::Rejected);
                }
                let Some(source) = self.successors.as_mut() else {
                    return Ok(Adoption::Rejected);
                };
                let adopted = source.adopt(spec)?;
                if matches!(&adopted, Adoption::Adopted(_)) {
                    self.previous = Some((spec.agent_id.clone(), spec.spawn_generation));
                }
                return Ok(adopted);
            }
        };
        let Some(child) = self.children[index].as_ref() else {
            return Ok(Adoption::Missing);
        };
        if spec.spawn_generation == 0
            || spec.registry_generation < spec.spawn_generation
            || spec.identity != process_identity(child, spec.spawn_generation)?
            || self.previous.as_ref().is_some_and(|(agent, generation)| {
                agent != &spec.agent_id || spec.spawn_generation <= *generation
            })
        {
            return Ok(Adoption::Rejected);
        }
        if !child.is_alive()? {
            self.children[index].take();
            return Ok(Adoption::Missing);
        }
        // A persisted lease does not replace the original exact Agentd UDS
        // health identity proof. Rejection never signals an unproved PID.
        if !crate::unix::prove_kernel_initial_adoption(spec, child.pid()) {
            return Ok(Adoption::Rejected);
        }
        if index == 1 {
            if let Some(manager) = self.children[0].as_ref()
                && manager.is_alive()?
            {
                return Ok(Adoption::Rejected);
            }
            // Recovery is the successor slot, never permission to revisit an
            // earlier image. Only a definite retired manager is reaped here.
            self.children[0].take();
        }
        let child = self.children[index]
            .take()
            .ok_or_else(|| ProcessDriverError::new("kernel-initial adoption lost custody"))?;
        self.previous = Some((spec.agent_id.clone(), spec.spawn_generation));
        Ok(Adoption::Adopted(
            UnixManagedProcess::from_kernel_initial_adoption(spec, child)?,
        ))
    }
}

fn process_identity(
    child: &KernelInitialChild,
    generation: u64,
) -> Result<ProcessIdentity, ProcessDriverError> {
    ProcessIdentity::new(
        u64::from(child.pid()),
        format!(
            "g2-{}-{}-{generation}",
            child.boot_id(),
            child.start_ticks()
        ),
    )
    .map_err(|error| ProcessDriverError::new(error.to_string()))
}

fn validate_root(bootstrap: &[u8]) -> Result<(), ProcessDriverError> {
    let word = |offset: usize| -> Option<u64> {
        Some(u64::from_le_bytes(
            bootstrap.get(offset..offset + 8)?.try_into().ok()?,
        ))
    };
    // SAFETY: these process/credential queries take no pointer arguments.
    let actual_root = unsafe {
        std::process::id() == 1
            && libc::getuid() == 0
            && libc::geteuid() == 0
            && libc::getgid() == 0
            && libc::getegid() == 0
    };
    if !actual_root
        || !matches!(bootstrap.len(), 200 | 4096)
        || bootstrap.get(..8) != Some(b"HOS2BOOT".as_slice())
        || word(8) != Some(3)
        || word(16) != Some(4)
        || word(24) != Some(200)
        || word(144) != Some(2)
        || word(152) != Some(3)
        || word(160) != Some(4)
        || word(192) != Some(1)
        || bootstrap[32..96].iter().any(|byte| *byte != 0)
        || bootstrap[200..].iter().any(|byte| *byte != 0)
    {
        return Err(ProcessDriverError::new(
            "actual G2 kernel-initial Root transaction required",
        ));
    }
    // SIGCHLD auto-reaping would make numeric child custody unverifiable.
    let mut disposition = unsafe { std::mem::zeroed::<libc::sigaction>() };
    if unsafe { libc::sigaction(libc::SIGCHLD, std::ptr::null(), &mut disposition) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    if disposition.sa_sigaction != libc::SIG_DFL || disposition.sa_flags & libc::SA_NOCLDWAIT != 0 {
        return Err(ProcessDriverError::new(
            "kernel-initial Root must exclusively reap its actual children",
        ));
    }
    Ok(())
}
