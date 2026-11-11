//! Test-only scheduling at a real retained registration's consumer request.
//! No clock, signer, verifier, lease, process identity or response is injected.

use crate::worker_root_registration::WorkerRootRegistrationV1;
use std::collections::BTreeMap;
use std::io;
use std::sync::Mutex;
use std::sync::mpsc;
use std::time::Duration;

struct Pending {
    entered: mpsc::Sender<()>,
    resume: mpsc::Receiver<()>,
}

static PENDING: Mutex<BTreeMap<[u8; 32], Pending>> = Mutex::new(BTreeMap::new());

pub(super) struct Pause {
    nonce: [u8; 32],
    entered: mpsc::Receiver<()>,
    resume: mpsc::Sender<()>,
}

impl Pause {
    pub(super) fn wait_entered(&self) -> io::Result<()> {
        self.entered
            .recv_timeout(Duration::from_secs(5))
            .map_err(io::Error::other)
    }
}

impl Drop for Pause {
    fn drop(&mut self) {
        // Release the actual server before an assertion can join its thread.
        let _ = self.resume.send(());
        if let Ok(mut pending) = PENDING.lock() {
            pending.remove(&self.nonce);
        }
    }
}

pub(super) fn arm(registration: &WorkerRootRegistrationV1) -> io::Result<Pause> {
    registration.validate()?;
    let (entered, observed) = mpsc::channel();
    let (resume, resumed) = mpsc::channel();
    let mut pending = PENDING
        .lock()
        .map_err(|_| io::Error::other("qualification pause poisoned"))?;
    if pending.contains_key(&registration.registration_nonce) {
        return Err(io::Error::other(
            "this real registration already has a pending pause",
        ));
    }
    pending.insert(
        registration.registration_nonce,
        Pending {
            entered,
            resume: resumed,
        },
    );
    Ok(Pause {
        nonce: registration.registration_nonce,
        entered: observed,
        resume,
    })
}

pub(super) fn at_consumer_request(registration: &WorkerRootRegistrationV1) -> io::Result<()> {
    let pending = PENDING
        .lock()
        .map_err(|_| io::Error::other("qualification pause poisoned"))?
        .remove(&registration.registration_nonce);
    if let Some(pending) = pending {
        // The map mutex is released before any wait. The unchanged native
        // runner and original lane lifetime still bound the whole fixture.
        pending.entered.send(()).map_err(io::Error::other)?;
        pending
            .resume
            .recv_timeout(Duration::from_secs(5))
            .map_err(io::Error::other)?;
    }
    Ok(())
}
