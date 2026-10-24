//! Continued custody from the original kernel factory. The Supervisor remains
//! the only lifecycle/generation owner; this source retains actual child guards
//! and at most the kernel's one pending immutable launch receipt.

use super::*;
use std::collections::VecDeque;
use std::os::fd::BorrowedFd;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KernelSuccessorRole {
    Manager,
    Recovery,
    HistoryOnly,
}

/// One actual final image named by the authenticated kernel launch receipt.
/// Private fields prevent the activation callback from choosing another PID.
#[derive(Clone, Debug)]
pub struct KernelSuccessorImage {
    launch: KernelLaunchReceipt,
    role: KernelSuccessorRole,
    pid: u32,
}
impl KernelSuccessorImage {
    pub fn launch(&self) -> &KernelLaunchReceipt {
        &self.launch
    }
    pub fn role(&self) -> KernelSuccessorRole {
        self.role
    }
    pub fn pid(&self) -> u32 {
        self.pid
    }
}

type Activation = Box<
    dyn for<'fd> FnMut(
        &SpawnSpec,
        &KernelSuccessorImage,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
>;

pub(super) struct KernelSuccessorSource {
    launcher: Arc<RootKernelLauncher>,
    observations: Arc<codex_hepta_contracts::RootAuthorityDirectory>,
    current: KernelLaunchReceipt,
    pending: Option<KernelLaunchReceipt>,
    to_capture: VecDeque<KernelSuccessorImage>,
    children: VecDeque<(KernelSuccessorImage, KernelInitialChild)>,
    activate: Activation,
}

impl KernelSuccessorSource {
    pub(super) fn new<G>(
        bootstrap: &[u8],
        launcher: Arc<RootKernelLauncher>,
        observations: Arc<codex_hepta_contracts::RootAuthorityDirectory>,
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
        let current = launcher.query()?;
        if current.boot_id().as_slice() != &bootstrap[96..112]
            || (current.generation() == 0
                && (current.history_spaces()[0].as_slice() != &bootstrap[112..128]
                    || current.history_spaces()[1].as_slice() != &bootstrap[128..144]))
        {
            return Err(ProcessDriverError::new(
                "kernel factory does not match original Root bootstrap",
            ));
        }
        // Query may observe an already-published launch after a Root service
        // restart. Saving and ACKing those same bytes precedes any adoption;
        // it never allocates another process or resets an owner generation.
        let pending = (current.generation() != 0).then(|| current.clone());
        Ok(Self {
            launcher,
            observations,
            current,
            pending,
            to_capture: VecDeque::new(),
            children: VecDeque::new(),
            activate: Box::new(activate),
        })
    }

    fn capture_published(&mut self) -> Result<(), ProcessDriverError> {
        if let Some(launch) = self.pending.as_ref() {
            let retirement = self.launcher.read_retirement(launch)?;
            // Root administration saves independently of Host startup. A failed
            // save/ACK retains this same pending receipt for exact retry. No
            // child is released and no further Advance is attempted here.
            self.launcher
                .save_and_acknowledge(&self.observations, launch, &retirement)?;
            let mut images = VecDeque::new();
            for (role, pid) in [
                (KernelSuccessorRole::Manager, launch.manager_pid()),
                (KernelSuccessorRole::Recovery, launch.recovery_pid()),
                (KernelSuccessorRole::HistoryOnly, launch.history_pid()),
            ] {
                if let Some(pid) = pid {
                    images.push_back(KernelSuccessorImage {
                        launch: launch.clone(),
                        role,
                        pid,
                    });
                }
            }
            self.current = launch.clone();
            self.to_capture = images;
            self.pending = None;
        }
        while let Some(image) = self.to_capture.front() {
            // A partial failure retains earlier guards and this unresolved
            // slot. Recapture never creates two guards for the same child.
            let child = KernelInitialChild::capture_if_present(image.pid)?;
            let image = self
                .to_capture
                .pop_front()
                .ok_or_else(|| ProcessDriverError::new("kernel image custody disappeared"))?;
            if let Some(child) = child {
                self.children.push_back((image, child));
            }
        }
        Ok(())
    }

    pub(super) fn take_next(
        &mut self,
    ) -> Result<(KernelSuccessorImage, KernelInitialChild), ProcessDriverError> {
        if self.children.is_empty() && self.to_capture.is_empty() && self.pending.is_none() {
            // The kernel independently requires all former privileged children
            // actually reaped. The original Supervisor performs that reaping.
            self.pending = Some(self.launcher.advance(&self.current)?);
        }
        self.capture_published()?;
        self.children
            .pop_front()
            .ok_or_else(|| ProcessDriverError::new("published kernel successor images are absent"))
    }

    pub(super) fn activate(
        &mut self,
        spec: &SpawnSpec,
        image: &KernelSuccessorImage,
        pidfd: BorrowedFd<'_>,
    ) -> Result<(), ProcessDriverError> {
        (self.activate)(spec, image, pidfd)
    }

    pub(super) fn adopt(
        &mut self,
        spec: &AdoptSpec,
    ) -> Result<Adoption<UnixManagedProcess>, ProcessDriverError> {
        // Adoption does not call Advance. Only the current authenticated
        // receipt and actual unreaped child custody can name the process.
        self.capture_published()?;
        if ![
            self.current.manager_pid(),
            self.current.recovery_pid(),
            self.current.history_pid(),
        ]
        .into_iter()
        .flatten()
        .any(|pid| u64::from(pid) == spec.identity.system_id())
        {
            return Ok(Adoption::Rejected);
        }
        let Some(index) = self
            .children
            .iter()
            .position(|(_, child)| u64::from(child.pid()) == spec.identity.system_id())
        else {
            return Ok(Adoption::Missing);
        };
        let child = &self.children[index].1;
        if spec.identity != process_identity(child, spec.spawn_generation)? {
            return Ok(Adoption::Rejected);
        }
        if !child.is_alive()? {
            self.children.remove(index);
            return Ok(Adoption::Missing);
        }
        if !crate::unix::prove_kernel_initial_adoption(spec, child.pid()) {
            return Ok(Adoption::Rejected);
        }
        for (_, previous) in self.children.iter().take(index) {
            if previous.is_alive()? {
                return Ok(Adoption::Rejected);
            }
        }
        // Never revisit an earlier image after adopting its actual successor.
        drop(self.children.drain(..index));
        let (_, child) = self
            .children
            .pop_front()
            .ok_or_else(|| ProcessDriverError::new("kernel successor adoption lost custody"))?;
        Ok(Adoption::Adopted(
            UnixManagedProcess::from_kernel_initial_adoption(spec, child)?,
        ))
    }
}
