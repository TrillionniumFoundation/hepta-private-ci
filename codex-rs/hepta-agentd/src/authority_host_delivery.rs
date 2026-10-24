//! Permanent launch cancellation and the original lanes' response boundary.
use super::*;
use std::net::Shutdown;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[derive(Default)]
pub(super) struct ServiceDelivery {
    failed: AtomicBool,
    publication: Mutex<()>,
    streams: Mutex<Vec<Weak<UnixStream>>>,
}

impl ServiceDelivery {
    pub(super) fn require_open(&self) -> Result<(), HostIssuerTransportError> {
        if self.failed.load(Ordering::Acquire) {
            return Err(HostIssuerTransportError::Closed);
        }
        Ok(())
    }

    pub(super) fn register(&self, stream: &UnixStream) -> Result<Arc<UnixStream>, HostIssuerTransportError> {
        let pin = Arc::new(stream.try_clone().map_err(unavailable)?);
        {
            let mut streams = self.streams.lock().map_err(|_| HostIssuerTransportError::Unavailable)?;
            streams.retain(|stream| stream.strong_count() > 0);
            streams.push(Arc::downgrade(&pin));
        }
        // A registration racing close either appears in its snapshot or fails
        // here before any handler is entered. No reconnect resets this state.
        self.require_open()?;
        Ok(pin)
    }

    pub(super) fn response_guard(&self) -> Result<MutexGuard<'_, ()>, HostIssuerTransportError> {
        let guard = self.publication.lock().map_err(|_| HostIssuerTransportError::Unavailable)?;
        self.require_open()?;
        Ok(guard)
    }

    pub(super) fn close(&self) {
        self.failed.store(true, Ordering::Release);
        // Shutdown before waiting for an in-progress bounded write. Handler
        // durability holds neither lock, and can finish only as Unknown.
        let mut streams = self.streams.lock().unwrap_or_else(|error| error.into_inner());
        for stream in streams.drain(..).filter_map(|stream| stream.upgrade()) {
            let _ = stream.shutdown(Shutdown::Both);
        }
        drop(streams);
        // On return, every previously admitted actual response write ended.
        // No registry/issuer/checkpoint lock is acquired under this gate.
        drop(self.publication.lock().unwrap_or_else(|error| error.into_inner()));
    }
}

impl HostAuthorityService {
    pub(super) fn fail_material_startup(&self) {
        self.delivery.close();
        if let Some(startup) = &self.material_startup { startup.fail(); }
        if let Some(checkpoint) = &self.checkpoint { checkpoint.backend.close(); }
    }
}

#[cfg(test)]
#[path = "authority_host_delivery_tests.rs"]
mod tests;
