//! A held Root channel must not depend on progress in the application executor.
use super::*;
use std::thread::JoinHandle;
use tokio::sync::oneshot;

pub(super) struct RootObservationWorker {
    stop: Option<oneshot::Sender<()>>,
    // Dropping a JoinHandle detaches; shutdown is requested without blocking
    // the caller's executor. Authority is already permanently fenced on Drop.
    _thread: JoinHandle<()>,
}

impl RootObservationWorker {
    pub(super) async fn start(
        live: Arc<LiveRoot>,
        stream: RootObservationStream,
        next_refresh_at: tokio::time::Instant,
    ) -> Result<Self, AgentdRootAuthorityError> {
        let transfer = stream.into_transfer().inspect_err(|_| {
            live.cache.fence_at(ObservationFailure {
                stage: "refresh_worker_transfer",
                ..Default::default()
            });
        })?;
        let (stop, stopping) = oneshot::channel();
        let (ready, started) = oneshot::channel();
        let background = Arc::clone(&live);
        let thread = std::thread::Builder::new()
            .name("hepta-root-feed".into())
            .spawn(move || {
                let _fence = FenceOnDrop(Arc::clone(&background));
                let runtime = match tokio::runtime::Builder::new_current_thread()
                    .enable_io()
                    .enable_time()
                    .max_blocking_threads(2)
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(_) => {
                        let _ = ready.send(Err(AgentdRootAuthorityError::Unavailable));
                        return;
                    }
                };
                let stream = {
                    let _entered = runtime.enter();
                    transfer.register()
                };
                let stream = match stream {
                    Ok(stream) => stream,
                    Err(error) => {
                        let _ = ready.send(Err(error));
                        runtime.shutdown_background();
                        return;
                    }
                };
                if ready.send(Ok(())).is_ok() {
                    runtime.block_on(run(background, stream, next_refresh_at, stopping));
                }
                runtime.shutdown_background();
            })
            .map_err(|_| {
                live.cache.fence_at(ObservationFailure {
                    stage: "refresh_worker_spawn",
                    ..Default::default()
                });
                AgentdRootAuthorityError::Unavailable
            })?;
        // This local guard also owns cancellation if the caller abandons the
        // async bootstrap before the dedicated reactor acknowledges readiness.
        let worker = Self {
            stop: Some(stop),
            _thread: thread,
        };
        match started.await {
            Ok(Ok(())) => Ok(worker),
            _ => {
                live.cache.fence_at(ObservationFailure {
                    stage: "refresh_worker_start",
                    ..Default::default()
                });
                Err(AgentdRootAuthorityError::Unavailable)
            }
        }
    }

    pub(super) fn stop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
    }
}

impl Drop for RootObservationWorker {
    fn drop(&mut self) {
        self.stop();
    }
}

async fn run(
    live: Arc<LiveRoot>,
    stream: RootObservationStream,
    mut next_refresh_at: tokio::time::Instant,
    mut stopping: oneshot::Receiver<()>,
) {
    loop {
        live.cache.diagnostics.refresh(RefreshEvent::Sleeping);
        tokio::select! {
            biased;
            _ = &mut stopping => return,
            _ = tokio::time::sleep_until(next_refresh_at) => {},
        }
        // This endpoint remains diagnostic metadata, never authority time.
        live.cache.diagnostics.refresh(RefreshEvent::Woke {
            boottime_ns: boottime_ns().ok(),
        });
        let result = tokio::select! {
            biased;
            _ = &mut stopping => return,
            result = refresh(&live, &stream) => result,
        };
        next_refresh_at = match result {
            Ok(next) => next,
            Err(_) => return,
        };
    }
}
