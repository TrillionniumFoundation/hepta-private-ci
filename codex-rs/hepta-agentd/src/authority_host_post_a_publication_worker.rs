//! Join the one original material registration attempt inside the existing
//! Root learning serve scope. Cancellation closes the same one-shot session.

use std::io;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::super::super::generation_publication::deployment::post_a::OriginalPostAPublicationDeployment;
use super::CLOSED;
use super::InstallationGate;

pub(super) fn serve_original_material(
    deployment: Option<OriginalPostAPublicationDeployment>,
    gate: &InstallationGate,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(deployment) = deployment else {
        return original();
    };
    let stopping = AtomicBool::new(false);
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            let result = OriginalPostAPublicationDeployment::wait_and_register_original_material(
                deployment, &stopping,
            );
            if result.is_err() {
                gate.phase.store(CLOSED, Ordering::Release);
            }
            result.map(|_| ())
        });
        let result = original();
        stopping.store(true, Ordering::Release);
        let registered = worker
            .join()
            .map_err(|_| io::Error::other("original publication material worker panicked"))?;
        result.and(registered)
    })
}
