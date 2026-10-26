//! One Root-owned bounded worker. A timed-out caller retains the occupied
//! capacity until the original job ends; no alternate queue, retry or grant.

use super::*;
use std::sync::mpsc;

pub(crate) enum SourceCustody {
    FreshRoot,
    RegisteredPublisher,
}

enum Command {
    Capture {
        source: SourceCustody,
        publisher: RetainedCheckpointPublisher,
    },
    Verify,
    Rebind(CognitiveCheckpointReceipt),
    Install,
    ReopenInstallation,
}

struct Job {
    candidate: CognitiveCheckpointReceipt,
    command: Command,
    response: mpsc::SyncSender<Result<Outcome, AuthorityTrustError>>,
}

enum Outcome {
    Verified,
    Installed(codex_hepta_memory::InstalledRootCheckpointImage),
}

pub(crate) struct RootCheckpointMaterial {
    sender: mpsc::SyncSender<Job>,
    peer: codex_hepta_memory::CognitiveCheckpointPeerLifetime,
    deadline: Duration,
    occupied: Arc<AtomicBool>,
}

impl RootCheckpointMaterial {
    pub(crate) fn open(
        profile: RootMaterialProfile,
        peer: codex_hepta_memory::CognitiveCheckpointPeerLifetime,
    ) -> Result<Self, AuthorityTrustError> {
        if profile.deadline.is_zero() || profile.deadline > Duration::from_secs(5) {
            return Err(AuthorityTrustError::Invalid);
        }
        let area = MaterialArea::open(&profile)?;
        let (sender, receiver) = mpsc::sync_channel::<Job>(1);
        let occupied = Arc::new(AtomicBool::new(false));
        let worker_occupied = Arc::clone(&occupied);
        let peer_uid = peer.uid;
        std::thread::Builder::new()
            .name("root-current-material".into())
            .spawn(move || {
                let runtime = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(_) => return,
                };
                while let Ok(job) = receiver.recv() {
                    let result = runtime.block_on(async {
                        match job.command {
                            Command::Capture { source, publisher } => {
                                publisher.require_alive()?;
                                let uid = match source {
                                    SourceCustody::FreshRoot => 0,
                                    SourceCustody::RegisteredPublisher => peer_uid,
                                };
                                let captured = area.prepare(&job.candidate, uid).await?;
                                publisher.require_alive()?;
                                let _ = captured;
                                Ok(Outcome::Verified)
                            }
                            Command::Verify => {
                                area.verify(&job.candidate).await.map(|_| Outcome::Verified)
                            }
                            Command::Rebind(previous) => area
                                .rebind(&previous, &job.candidate)
                                .await
                                .map(|_| Outcome::Verified),
                            Command::Install => {
                                area.install(&job.candidate).await.map(Outcome::Installed)
                            }
                            Command::ReopenInstallation => area
                                .reopen_installation(&job.candidate)
                                .await
                                .map(Outcome::Installed),
                        }
                    });
                    worker_occupied.store(false, Ordering::Release);
                    let _ = job.response.send(result);
                }
            })
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        Ok(Self {
            sender,
            peer,
            deadline: profile.deadline,
            occupied,
        })
    }

    pub(crate) fn prepare(
        &self,
        candidate: CognitiveCheckpointReceipt,
        source: SourceCustody,
    ) -> Result<(), AuthorityTrustError> {
        let publisher = RetainedCheckpointPublisher::capture(self.peer.clone())?;
        self.call(candidate, Command::Capture { source, publisher })
            .map(|_| ())
    }

    pub(crate) fn verify(
        &self,
        candidate: CognitiveCheckpointReceipt,
    ) -> Result<(), AuthorityTrustError> {
        self.call(candidate, Command::Verify).map(|_| ())
    }

    pub(crate) fn rebind(
        &self,
        previous: CognitiveCheckpointReceipt,
        candidate: CognitiveCheckpointReceipt,
    ) -> Result<(), AuthorityTrustError> {
        self.call(candidate, Command::Rebind(previous)).map(|_| ())
    }

    pub(crate) fn install(
        &self,
        previous: CognitiveCheckpointReceipt,
    ) -> Result<codex_hepta_memory::InstalledRootCheckpointImage, AuthorityTrustError> {
        match self.call(previous, Command::Install)? {
            Outcome::Installed(image) => Ok(image),
            Outcome::Verified => Err(AuthorityTrustError::Invalid),
        }
    }

    pub(crate) fn reopen_installation(
        &self,
        current: CognitiveCheckpointReceipt,
    ) -> Result<codex_hepta_memory::InstalledRootCheckpointImage, AuthorityTrustError> {
        match self.call(current, Command::ReopenInstallation)? {
            Outcome::Installed(image) => Ok(image),
            Outcome::Verified => Err(AuthorityTrustError::Invalid),
        }
    }

    fn call(
        &self,
        candidate: CognitiveCheckpointReceipt,
        command: Command,
    ) -> Result<Outcome, AuthorityTrustError> {
        let (response, receiver) = mpsc::sync_channel(1);
        if self
            .occupied
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(AuthorityTrustError::Conflict);
        }
        if self
            .sender
            .try_send(Job {
                candidate,
                command,
                response,
            })
            .is_err()
        {
            self.occupied.store(false, Ordering::Release);
            return Err(AuthorityTrustError::Unavailable);
        }
        receiver
            .recv_timeout(self.deadline)
            .map_err(|_| AuthorityTrustError::Unavailable)?
    }
}
